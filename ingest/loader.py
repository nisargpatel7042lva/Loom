"""
Ingestion pipeline: loads market events from data/sample_events.json
into Cognee as permanent graph memory (no session_id).

Each event is rendered as explicit relationship-rich prose so Cognee's
LLM-driven graph extractor creates typed entity nodes and traversable
edges rather than isolated text blobs.

All events are passed as a single list to remember() so the cognify
pipeline processes the full corpus in one pass — this lets the extractor
see cross-event entity overlap (five FOMC events share "Federal Reserve",
"FOMC", "rate decision") and wire them into a real connected graph.

Usage:
    python -m ingest.loader
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import cognee
from cognee.modules.pipelines.models import PipelineRunStatus

DATA_FILE = Path(__file__).parent.parent / "data" / "sample_events.json"
DATASET_NAME = "loom_market_events"

_TERMINAL = {
    PipelineRunStatus.DATASET_PROCESSING_COMPLETED,
    PipelineRunStatus.DATASET_PROCESSING_ERRORED,
}


def event_to_text(event: dict[str, Any]) -> str:
    """Render one structured event as explicit NL prose.

    Entity density is intentional: every named actor, numeric value, and
    causal relationship is spelled out so Cognee's extractor creates rich
    typed nodes (market, category, trigger, outcome) and edges between them.
    """
    if event["outcome"] == "pending":
        resolution = "The market outcome is currently pending."
    elif event.get("outcome_date"):
        resolution = f"The market resolved {event['outcome']} on {event['outcome_date']}."
    else:
        resolution = f"The market resolved {event['outcome']}."

    return (
        f"Prediction market {event['market_id']} asks: \"{event['market_question']}\". "
        f"This market belongs to the {event['category']} category. "
        f"The market was triggered by {event['trigger']} on {event['timestamp']}. "
        f"Odds moved from {event['odds_before']} to {event['odds_after']} "
        f"(a {event['odds_move_pct']:+.1f}% change). "
        f"{resolution} "
        f"{event['narrative']}"
    )


async def _wait_for_completion(dataset_id: UUID, poll_interval: float = 3.0) -> str:
    """Poll datasets.get_status() until pipeline reaches a terminal state."""
    while True:
        status_map = await cognee.datasets.get_status([dataset_id])
        status = next(iter(status_map.values()), None)
        if status in _TERMINAL:
            return status.value
        await asyncio.sleep(poll_interval)


async def ingest(events: list[dict] | None = None) -> dict[str, Any]:
    """
    Ingest market events into permanent Cognee graph memory.

    Args:
        events: List of event dicts. Reads DATA_FILE when None.

    Returns:
        Dict with events_ingested, dataset_name, dataset_id, status,
        elapsed_seconds.
    """
    if events is None:
        events = json.loads(DATA_FILE.read_text())

    texts = [event_to_text(e) for e in events]

    t0 = time.monotonic()

    # Single remember() call with all texts — one cognify pipeline pass
    # over the entire corpus produces better cross-event graph edges than
    # N separate calls.
    result = await cognee.remember(
        data=texts,
        dataset_name=DATASET_NAME,
        # no session_id → permanent graph memory
    )

    # remember() with run_in_background=False (default) blocks until
    # cognify completes. We do one poll round as a hard verification.
    final_status = result.status
    if result.dataset_id:
        try:
            final_status = await _wait_for_completion(UUID(result.dataset_id))
        except Exception:
            pass  # RememberResult.status is sufficient fallback

    elapsed = round(time.monotonic() - t0, 2)

    return {
        "events_ingested": len(events),
        "dataset_name": DATASET_NAME,
        "dataset_id": result.dataset_id,
        "status": final_status,
        "elapsed_seconds": elapsed,
    }


if __name__ == "__main__":
    async def _main() -> None:
        events = json.loads(DATA_FILE.read_text())
        print(f"Ingesting {len(events)} market events → dataset '{DATASET_NAME}' ...")
        summary = await ingest(events)
        print(
            f"\n✓ {summary['events_ingested']} events ingested"
            f"\n  dataset_id : {summary['dataset_id']}"
            f"\n  status     : {summary['status']}"
            f"\n  elapsed    : {summary['elapsed_seconds']}s"
        )

    asyncio.run(_main())
