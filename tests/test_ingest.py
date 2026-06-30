"""
Integration test: ingest one FOMC event fixture then recall against the
loom_market_events dataset. Verifies the pipeline builds a searchable graph.

We use a single event to stay within the 5 RPM free-tier limit on
gemini-2.5-flash — the full 20-event corpus is loaded via:
    python -m ingest.loader
"""

import json
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import cognee
from ingest.loader import DATA_FILE, DATASET_NAME, ingest


@pytest.mark.asyncio
async def test_ingest_and_recall_fed_markets():
    # ── clean slate ──────────────────────────────────────────────────────
    await cognee.prune.prune_data()
    await cognee.prune.prune_system(metadata=True)

    # ── ingest one FOMC event ────────────────────────────────────────────
    all_events = json.loads(DATA_FILE.read_text())
    # FM-001: Sep-2024 50bp cut — clear Fed/FOMC entity density
    event = next(e for e in all_events if e["market_id"] == "FM-001")

    summary = await ingest([event])

    assert summary["events_ingested"] == 1
    assert summary["status"] in (
        "completed",
        "DATASET_PROCESSING_COMPLETED",
    ), f"Unexpected status: {summary['status']}"

    print(
        f"\n[ingest] status={summary['status']} | "
        f"elapsed={summary['elapsed_seconds']}s | "
        f"dataset_id={summary['dataset_id']}"
    )

    # ── recall ───────────────────────────────────────────────────────────
    results = await cognee.recall(
        "Tell me about Fed rate decision markets",
        datasets=[DATASET_NAME],
    )

    assert results, "recall() returned no results"

    print(f"\n[recall] {len(results)} result(s)")
    print("\n=== recall() raw output ===")
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r}\n")

    full_text = str(results).lower()
    fed_keywords = {"fed", "fomc", "federal reserve", "rate", "fm-001"}
    matched = [kw for kw in fed_keywords if kw in full_text]
    assert matched, (
        f"No Fed-related content in recall results "
        f"(checked: {fed_keywords})\n\nraw: {results}"
    )
    print(f"\n✓ Fed keywords found: {matched}")
