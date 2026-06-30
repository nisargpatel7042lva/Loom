"""
Ingestion pipeline: loads market events into Cognee as permanent graph memory.

Two sources:
    --source fixtures  (default) reads data/sample_events.json
    --source live      fetches real events from Jupiter Prediction API

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

# Jupiter category strings → Loom category strings (for fixture filtering)
_JUPITER_TO_LOOM_CATEGORY = {
    "crypto": "crypto",
    "economics": "macro",
    "politics": "elections",
    "sports": "sports",
}


def event_to_text(event: dict[str, Any]) -> str:
    """Render one structured event as entity-dense NL prose for graph extraction.

    Handles None values for fields absent in live (Jupiter) events — trigger,
    narrative, odds_before, odds_move_pct are not available from the API and
    are omitted rather than fabricated.
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
        events: List of event dicts (fixture or mapped Jupiter). Reads
                DATA_FILE when None.

    Returns:
        Dict with events_ingested, dataset_name, dataset_id, status,
        elapsed_seconds.
    """
    if events is None:
        events = json.loads(DATA_FILE.read_text())

    texts = [event_to_text(e) for e in events]

    t0 = time.monotonic()

    result = await cognee.remember(
        data=texts,
        dataset_name=DATASET_NAME,
        # no session_id → permanent graph memory
    )

    final_status = result.status
    if result.dataset_id:
        try:
            final_status = await _wait_for_completion(UUID(result.dataset_id))
        except Exception:
            pass

    elapsed = round(time.monotonic() - t0, 2)

    return {
        "events_ingested": len(events),
        "dataset_name": DATASET_NAME,
        "dataset_id": result.dataset_id,
        "status": final_status,
        "elapsed_seconds": elapsed,
    }


def _load_fixture_events(category: str | None) -> list[dict]:
    all_events: list[dict] = json.loads(DATA_FILE.read_text())
    if not category:
        return all_events
    # Accept either Jupiter category name or Loom category name
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
    args = parser.parse_args()

    async def _main() -> None:
        if args.source == "live":
            print(f"Fetching live events from Jupiter API (category={args.category or 'all'}) ...")
            events = _load_live_events(args.category)
            if not events:
                print(
                    "\nWARNING: Jupiter API returned zero events "
                    f"(category={args.category or 'all'}).\n"
                    "This may mean the API is down, rate-limiting, or the category is empty.\n"
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

        summary = await ingest(events)
        print(
            f"\n✓ {summary['events_ingested']} events ingested"
            f"\n  dataset_id : {summary['dataset_id']}"
            f"\n  status     : {summary['status']}"
            f"\n  elapsed    : {summary['elapsed_seconds']}s"
        )

    asyncio.run(_main())
