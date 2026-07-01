"""
Ingestion pipeline: loads market events into Cognee vector memory.

Uses cognee.add() (not remember/cognify) so ingest requires ZERO LLM calls —
only local FastEmbed vectorization. This lets us ingest thousands of live Jupiter
events without touching the daily Gemini API quota.

The LLM is reserved for analysis-time synthesis (exactly 1 call per analyze).

Usage:
    python -m ingest.loader                           # fixtures, all events
    python -m ingest.loader --source live             # all live categories
    python -m ingest.loader --source live --category crypto
    python -m ingest.loader --source fixtures --category crypto
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import cognee

from memory.vector_store import upsert as vs_upsert

DATA_FILE     = Path(__file__).parent.parent / "data" / "sample_events.json"
INGESTED_FILE = Path(__file__).parent.parent / "data" / "ingested_events.json"
DATASET_NAME  = "loom_market_events"

# Jupiter category strings → Loom category strings (for fixture filtering)
_JUPITER_TO_LOOM_CATEGORY = {
    "crypto": "crypto",
    "economics": "macro",
    "politics": "elections",
    "sports": "sports",
}


def event_to_text(event: dict[str, Any]) -> str:
    """Render one structured event as entity-dense NL prose for vector embedding.

    Handles None values for fields absent in live (Jupiter) events.
    """
    parts: list[str] = []

    parts.append(
        f"Prediction market {event['market_id']} asks: \"{event['market_question']}\"."
    )
    parts.append(f"This market belongs to the {event['category']} category.")

    trigger = event.get("trigger")
    timestamp = event.get("timestamp")
    if trigger and timestamp:
        parts.append(f"The market was triggered by {trigger} on {timestamp}.")
    elif timestamp:
        parts.append(f"The market was opened on {timestamp}.")

    odds_before = event.get("odds_before")
    odds_after = event.get("odds_after")
    odds_move = event.get("odds_move_pct")
    if odds_before is not None and odds_after is not None and odds_move is not None:
        parts.append(
            f"Odds moved from {odds_before} to {odds_after} (a {odds_move:+.1f}% change)."
        )
    elif odds_after is not None:
        parts.append(f"Current implied probability: {odds_after:.1%}.")

    outcome = event.get("outcome", "pending")
    outcome_date = event.get("outcome_date")
    if outcome == "pending":
        parts.append("The market outcome is currently pending.")
    elif outcome_date:
        parts.append(f"The market resolved {outcome} on {outcome_date}.")
    else:
        parts.append(f"The market resolved {outcome}.")

    narrative = event.get("narrative")
    if narrative:
        parts.append(narrative)

    return " ".join(parts)


async def ingest(
    events: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Ingest market events into Cognee vector memory using cognee.add() only.

    Zero LLM calls — uses FastEmbed (local) for vectorization. Events are
    searchable immediately via SearchType.CHUNKS after this call.

    Args:
        events: List of event dicts. Reads DATA_FILE when None.

    Returns:
        Dict with events_ingested, dataset_name, status, elapsed_seconds.
    """
    if events is None:
        events = json.loads(DATA_FILE.read_text())

    t0 = time.monotonic()
    ingested = 0

    for i, event in enumerate(events):
        text = event_to_text(event)
        mid = event.get("market_id", f"event-{i+1}")
        print(f"  [{i+1}/{len(events)}] Adding {mid}…", end=" ", flush=True)

        try:
            await cognee.add(data=[text], dataset_name=DATASET_NAME)
            vs_upsert(mid, text)   # local FastEmbed vector store (0 LLM calls)
            ingested += 1
            print("✓")
        except Exception as e:
            print(f"✗ {type(e).__name__}: {str(e)[:60]}")

    elapsed = round(time.monotonic() - t0, 2)

    # Persist ingested events so the UI can list them without re-fetching Jupiter
    _save_ingested_events(events)

    return {
        "events_ingested": ingested,
        "dataset_name": DATASET_NAME,
        "status": "COMPLETED" if ingested == len(events) else "PARTIAL",
        "elapsed_seconds": elapsed,
    }


def _save_ingested_events(new_events: list[dict]) -> None:
    """Merge new_events into ingested_events.json (deduplicate by market_id)."""
    existing: list[dict] = []
    if INGESTED_FILE.exists():
        try:
            existing = json.loads(INGESTED_FILE.read_text())
        except Exception:
            existing = []
    seen = {e["market_id"] for e in existing}
    to_add = [e for e in new_events if e["market_id"] not in seen]
    existing.extend(to_add)
    INGESTED_FILE.parent.mkdir(parents=True, exist_ok=True)
    INGESTED_FILE.write_text(json.dumps(existing, indent=2))


def _load_ingested_events(category: str | None = None) -> list[dict]:
    """Return events previously ingested via Remember."""
    if not INGESTED_FILE.exists():
        return []
    try:
        all_events: list[dict] = json.loads(INGESTED_FILE.read_text())
    except Exception:
        return []
    if not category:
        return all_events
    loom_cat = _JUPITER_TO_LOOM_CATEGORY.get(category, category)
    return [e for e in all_events if e.get("category") == loom_cat]


def _load_fixture_events(category: str | None) -> list[dict]:
    all_events: list[dict] = json.loads(DATA_FILE.read_text())
    if not category:
        return all_events
    loom_cat = _JUPITER_TO_LOOM_CATEGORY.get(category, category)
    return [e for e in all_events if e.get("category") == loom_cat]


def _load_live_events(category: str | None) -> list[dict]:
    from ingest.jupiter_client import get_events
    from ingest.jupiter_adapter import jupiter_event_to_loom_event

    raw = get_events(category=category, include_markets=True)
    if not raw:
        return []
    return [jupiter_event_to_loom_event(e) for e in raw]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest prediction market events into Cognee.")
    parser.add_argument(
        "--source",
        choices=["fixtures", "live"],
        default="fixtures",
        help="fixtures = sample_events.json  |  live = Jupiter Prediction API",
    )
    parser.add_argument(
        "--category",
        default=None,
        help=(
            "Filter by category. "
            "For live: crypto | economics | politics | sports. "
            "For fixtures: crypto | macro | elections | sports."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Cap the number of events ingested.",
    )
    args = parser.parse_args()

    async def _main() -> None:
        if args.source == "live":
            print(f"Fetching live events from Jupiter API (category={args.category or 'all'}) ...")
            events = _load_live_events(args.category)
            if not events:
                print(
                    "\nWARNING: Jupiter API returned zero events "
                    f"(category={args.category or 'all'}).\n"
                    "Run with --source fixtures to use the local sample data instead.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"  → {len(events)} events fetched and mapped.\n")
        else:
            events = _load_fixture_events(args.category)
            print(
                f"Loading fixtures (category={args.category or 'all'}): "
                f"{len(events)} events from {DATA_FILE.name} ..."
            )

        if args.limit is not None and args.limit < len(events):
            print(f"  → capping to {args.limit} events (--limit {args.limit})")
            events = events[: args.limit]

        summary = await ingest(events)
        print(
            f"\n✓ {summary['events_ingested']} events ingested"
            f"\n  dataset    : {summary['dataset_name']}"
            f"\n  status     : {summary['status']}"
            f"\n  elapsed    : {summary['elapsed_seconds']}s"
            f"\n  llm_calls  : 0  (FastEmbed local vectorization only)"
        )

    asyncio.run(_main())
