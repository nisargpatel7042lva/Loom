"""
Forgetting / pruning layer using Cognee's real deletion API.

ENTRY POINT:
    cognee.forget(data_id=<uuid>, dataset_id=<uuid>)
    → internally calls _forget_data_item() → datasets.delete_data()
    → internally calls delete_data_nodes_and_edges()

This is the correct API. The alternatives below do NOT exist in Cognee 1.2.1:
    cognee.datasets.delete_data(...)    exists but is the LOW-LEVEL call; we use
                                        cognee.forget() to get the unified span + telemetry
    SearchType.FEEDBACK                 does NOT exist
    cognee.prune()                      does NOT exist
    cognee.datasets.prune()             does NOT exist

DELETION GRANULARITY (verified from delete_data_nodes_and_edges.py):
    ✓  Data record (SQLite relational row)          — deleted
    ✓  Nodes UNIQUE to this data item              — deleted from graph + vector
    ✓  Edges UNIQUE to this data item              — deleted from graph + vector
    ✗  Nodes SHARED with other surviving data items — NOT deleted; only their
       belongs_to_set tag for this dataset is removed.

    Example: if FM-001 ("Fed rate cut") and FM-002 ("Fed holds") both produced
    a "Federal Reserve" entity node, deleting FM-001 removes its contribution
    to that node's belongs_to_set annotation but leaves the node itself intact
    because FM-002 still references it. The graph stays coherent for shared structure.

STALE TRIGGER CONDITION:
    An event is a stale false-positive precedent when:
      - It has been surfaced as an analogy in ≥ MIN_FEEDBACKS recall interactions
      - Its average feedback_score across those interactions is ≤ MAX_STALE_SCORE
    These events kept misleading recall (wrong direction predicted) and should be
    pruned so they stop appearing as analogies.

MATCHING EVENT → DATA RECORD:
    When cognee.remember() ingests a text string, it creates a Data record with:
        Data.name         = "text_<md5_hex>.txt"
        Data.content_hash = md5_hex
    where md5_hex = hashlib.md5(text.encode("utf-8")).hexdigest().
    We recompute this hash from event_to_text(event) to find the exact data_id.

CLI:
    python -m memory.forget --dry-run                 # show candidates, no deletion
    python -m memory.forget --commit                  # delete stale events
    python -m memory.forget --dry-run --min-score 3   # lower threshold
    python -m memory.forget --dry-run --min-feedbacks 1
"""

import asyncio
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import cognee

from ingest.loader import DATA_FILE, DATASET_NAME, event_to_text

_FEEDBACK_LOG  = Path(__file__).parent.parent / "data" / "feedback_log.jsonl"
_PRUNE_LOG     = Path(__file__).parent.parent / "data" / "prune_log.jsonl"

MIN_FEEDBACKS_DEFAULT  = 2   # minimum number of feedback entries before an event is prune-eligible
MAX_STALE_SCORE_DEFAULT = 2  # avg feedback_score at or below this → stale


# ── stale detection ───────────────────────────────────────────────────────────

def _load_feedback_log() -> list[dict]:
    if not _FEEDBACK_LOG.exists():
        return []
    entries = []
    for line in _FEEDBACK_LOG.read_text().strip().splitlines():
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    return entries


def find_stale_candidates(
    *,
    min_feedbacks: int = MIN_FEEDBACKS_DEFAULT,
    max_score: int = MAX_STALE_SCORE_DEFAULT,
) -> list[dict]:
    """
    Return events whose feedback history marks them as chronic false positives.

    A stale candidate is a market_id where:
      - ≥ min_feedbacks recall interactions were recorded in feedback_log.jsonl
      - The average feedback_score is ≤ max_score (1=completely wrong, 5=perfect)

    These are events that keep getting surfaced by GRAPH_COMPLETION as precedents
    but consistently mislead the prediction. Pruning them removes the data record
    and their UNIQUE graph nodes/edges; shared nodes (entities referenced by other
    surviving events) are detagged but not removed from the graph.
    """
    entries = _load_feedback_log()
    if not entries:
        return []

    by_market: dict[str, list[int]] = defaultdict(list)
    for entry in entries:
        mid = entry.get("market_id")
        score = entry.get("score")
        if mid and score is not None:
            by_market[mid].append(int(score))

    candidates = []
    for market_id, scores in by_market.items():
        if len(scores) < min_feedbacks:
            continue
        avg = sum(scores) / len(scores)
        if avg <= max_score:
            candidates.append({
                "market_id": market_id,
                "avg_score": round(avg, 2),
                "feedback_count": len(scores),
                "scores": scores,
                "reason": (
                    f"avg_score={avg:.2f} ≤ {max_score} across "
                    f"{len(scores)} resolved markets → chronic false-positive precedent"
                ),
            })

    candidates.sort(key=lambda c: c["avg_score"])
    return candidates


# ── dataset / data lookup ─────────────────────────────────────────────────────

async def _resolve_dataset_id(user: Any) -> UUID | None:
    """Find the loom_market_events dataset_id for the current user."""
    all_datasets = await cognee.datasets.list_datasets(user=user)
    for ds in (all_datasets or []):
        if getattr(ds, "name", None) == DATASET_NAME:
            return ds.id
    return None


def _content_hash(event: dict) -> str:
    """Compute the MD5 content_hash Cognee assigned to this event's Data record.

    TextData.get_metadata() sets content_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    and name = "text_<hash>.txt". We recompute the same hash to find the data_id.
    """
    text = event_to_text(event)
    return hashlib.md5(text.encode("utf-8")).hexdigest()


async def _find_data_record(dataset_id: UUID, event: dict, user: Any) -> Any | None:
    """
    Look up the Data record for a specific event in the dataset.

    Matches on Data.content_hash (= MD5 of event_to_text(event)).
    Returns the Data ORM object, or None if not found (event was never ingested
    or was already deleted).
    """
    try:
        data_items = await cognee.datasets.list_data(dataset_id, user=user)
    except Exception as exc:
        print(f"  [WARN] list_data failed: {exc}")
        return None

    target_hash = _content_hash(event)
    for item in (data_items or []):
        if getattr(item, "content_hash", None) == target_hash:
            return item
    return None


# ── core API ──────────────────────────────────────────────────────────────────

async def prune_stale_events(
    reason: str = "false_positive_precedent",
    *,
    dry_run: bool = True,
    min_feedbacks: int = MIN_FEEDBACKS_DEFAULT,
    max_score: int = MAX_STALE_SCORE_DEFAULT,
) -> dict[str, Any]:
    """
    Find and optionally delete stale false-positive events from the knowledge graph.

    Args:
        reason:        Label written to the prune log (why this event was pruned).
        dry_run:       If True (default), report candidates without deleting.
        min_feedbacks: Minimum feedback entries before an event qualifies.
        max_score:     Average score threshold; events at or below this qualify.

    Returns:
        {
            "candidates":       list of stale candidate dicts,
            "dataset_id":       str | None,
            "pruned":           list of pruned market_ids (empty on dry_run),
            "not_found":        list of candidates with no data record in dataset,
            "dry_run":          bool,
        }

    Deletion granularity (honest):
        - Data record (SQLite)          → removed
        - Unique graph nodes/edges      → removed from graph + vector
        - Shared entity nodes           → detagged (belongs_to_set updated),
                                          NOT removed (other events still reference them)
        This means: a "Federal Reserve" node shared by FM-001 and FM-002 survives
        deletion of FM-001. Only FM-001's UNIQUE nodes (e.g. its specific narrative
        chunk nodes) are actually removed from the graph.
    """
    from cognee.modules.users.methods import get_default_user
    from cognee.low_level import setup

    await setup()
    user = await get_default_user()

    # ── Step 1: find stale candidates from feedback log ───────────────────────
    candidates = find_stale_candidates(min_feedbacks=min_feedbacks, max_score=max_score)

    if not candidates:
        msg = "No stale candidates found."
        if not _FEEDBACK_LOG.exists():
            msg += (
                f" (feedback_log.jsonl does not exist — run "
                f"`python -m memory.recall <id>` then `python -m memory.improve --batch` first)"
            )
        elif _load_feedback_log():
            msg += (
                f" All events have avg_score > {max_score} "
                f"or fewer than {min_feedbacks} feedback entries."
            )
        else:
            msg += " feedback_log.jsonl is empty."
        print(f"  {msg}")
        return {
            "candidates": [],
            "dataset_id": None,
            "pruned": [],
            "not_found": [],
            "dry_run": dry_run,
        }

    # ── Step 2: resolve dataset ───────────────────────────────────────────────
    dataset_id = await _resolve_dataset_id(user)
    if dataset_id is None:
        print(
            f"  [WARN] Dataset '{DATASET_NAME}' not found for this user. "
            "Has ingest.loader been run yet?"
        )
        return {
            "candidates": candidates,
            "dataset_id": None,
            "pruned": [],
            "not_found": [c["market_id"] for c in candidates],
            "dry_run": dry_run,
        }

    # ── Step 3: load all fixture events for hash matching ────────────────────
    all_events = json.loads(DATA_FILE.read_text())
    event_by_id = {e["market_id"]: e for e in all_events}

    pruned = []
    not_found = []

    for candidate in candidates:
        mid = candidate["market_id"]
        event = event_by_id.get(mid)

        if not event:
            print(f"  [{mid}] not in fixtures — skipping")
            not_found.append(mid)
            continue

        data_record = await _find_data_record(dataset_id, event, user)

        if data_record is None:
            print(
                f"  [{mid}] no data record found in '{DATASET_NAME}' "
                f"(content_hash={_content_hash(event)[:12]}…) — event was never ingested "
                "or was already deleted"
            )
            not_found.append(mid)
            continue

        data_id = data_record.id
        data_name = getattr(data_record, "name", str(data_id))

        print(f"\n  [{mid}] avg_score={candidate['avg_score']}  {candidate['reason']}")
        print(f"    data_id  : {data_id}")
        print(f"    data_name: {data_name}")

        if dry_run:
            print(f"    → DRY RUN: would call cognee.forget(data_id={data_id}, dataset_id={dataset_id})")
            print(f"    → Deletion scope: Data record + unique graph nodes/edges")
            print(f"    → Shared entity nodes (referenced by other events) are detagged but NOT removed")
            pruned.append({"market_id": mid, "data_id": str(data_id), "dry_run": True})
        else:
            print(f"    → Calling cognee.forget(data_id=..., dataset_id=...)")
            try:
                result = await cognee.forget(
                    data_id=data_id,
                    dataset_id=dataset_id,
                    user=user,
                )
                print(f"    → cognee.forget returned: {result}")
                pruned.append({
                    "market_id": mid,
                    "data_id": str(data_id),
                    "forget_result": result,
                    "dry_run": False,
                })
                _log_prune({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "market_id": mid,
                    "data_id": str(data_id),
                    "dataset_id": str(dataset_id),
                    "data_name": data_name,
                    "avg_score": candidate["avg_score"],
                    "feedback_count": candidate["feedback_count"],
                    "reason": reason,
                    "forget_result": result,
                })
            except Exception as exc:
                print(f"    → ERROR: cognee.forget raised: {exc}")
                pruned.append({
                    "market_id": mid,
                    "data_id": str(data_id),
                    "error": str(exc),
                    "dry_run": False,
                })

    return {
        "candidates": candidates,
        "dataset_id": str(dataset_id),
        "pruned": pruned,
        "not_found": not_found,
        "dry_run": dry_run,
    }


def _log_prune(entry: dict) -> None:
    _PRUNE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_PRUNE_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── post-deletion verification ────────────────────────────────────────────────

async def verify_deletion(market_id: str, dataset_id_str: str) -> dict[str, Any]:
    """
    After committing a deletion, verify the data_id is gone and recall returns no result.

    Returns:
        {
            "data_record_gone":   bool  — True if data_id absent from list_data()
            "recall_empty":       bool  — True if GRAPH_COMPLETION returns nothing
            "recall_note":        str   — explanation (empty graph → always True regardless)
        }

    HONEST NOTE: If the graph was never populated (cognify never completed due to
    quota exhaustion), recall_empty will be True for ALL events — the deletion cannot
    be confirmed to have changed recall behaviour. Only a populated graph lets you
    confirm the precedent is truly gone from retrieval.
    """
    from cognee.modules.users.methods import get_default_user
    from cognee.low_level import setup

    await setup()
    user = await get_default_user()

    dataset_id = UUID(dataset_id_str)

    # ── check 1: data record is gone ─────────────────────────────────────────
    all_events = json.loads(DATA_FILE.read_text())
    event = next((e for e in all_events if e["market_id"] == market_id), None)
    data_record_gone = True  # default: if we can't find the event, assume gone

    if event:
        data_record = await _find_data_record(dataset_id, event, user)
        data_record_gone = (data_record is None)

    # ── check 2: recall no longer surfaces it ────────────────────────────────
    recall_empty = False
    recall_note = ""
    try:
        from cognee.api.v1.search.search import SearchType
        results = await cognee.search(
            query_text=f"prediction market {market_id}",
            query_type=SearchType.GRAPH_COMPLETION,
            datasets=[DATASET_NAME],
            top_k=5,
        )
        if not results:
            recall_empty = True
            recall_note = (
                "GRAPH_COMPLETION returned empty. "
                "This is expected if the graph was never populated (cognify never completed). "
                "Cannot attribute absence of this event to deletion without a prior populated graph."
            )
        else:
            result_text = " ".join(str(r) for r in results).lower()
            if market_id.lower() not in result_text:
                recall_empty = True
                recall_note = (
                    f"{market_id} is not mentioned in the GRAPH_COMPLETION answer. "
                    "Consistent with deletion, but also possible without it."
                )
            else:
                recall_note = (
                    f"WARNING: {market_id} still appears in recall results — "
                    "either deletion didn't propagate or another event references similar content."
                )
    except Exception as exc:
        recall_note = f"recall check failed: {exc}"

    return {
        "data_record_gone": data_record_gone,
        "recall_empty": recall_empty,
        "recall_note": recall_note,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Prune stale false-positive prediction market events from Cognee's knowledge graph.\n\n"
            "Stale = avg feedback_score ≤ MAX_SCORE across ≥ MIN_FEEDBACKS recall interactions.\n"
            "Uses cognee.forget(data_id=..., dataset_id=...) for item-level deletion."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Show stale candidates without deleting anything",
    )
    mode.add_argument(
        "--commit",
        action="store_true",
        help="Actually delete stale events via cognee.forget()",
    )

    parser.add_argument(
        "--min-score",
        type=int,
        default=MAX_STALE_SCORE_DEFAULT,
        metavar="N",
        help=f"Avg score at or below this qualifies as stale (default: {MAX_STALE_SCORE_DEFAULT})",
    )
    parser.add_argument(
        "--min-feedbacks",
        type=int,
        default=MIN_FEEDBACKS_DEFAULT,
        metavar="N",
        help=f"Minimum feedback entries required (default: {MIN_FEEDBACKS_DEFAULT})",
    )
    parser.add_argument(
        "--verify",
        metavar="MARKET_ID:DATASET_ID",
        help=(
            "After --commit, verify a specific deletion: "
            "checks list_data() and recall(). "
            "Format: FM-001:<dataset-uuid>"
        ),
    )

    args = parser.parse_args()

    async def _main() -> None:
        dry = args.dry_run

        print(f"\nLoom forget — {'DRY RUN' if dry else 'COMMIT MODE'}")
        print(f"  dataset:      {DATASET_NAME}")
        print(f"  stale if:     avg_score ≤ {args.min_score} across ≥ {args.min_feedbacks} feedbacks")
        print(f"  feedback_log: {_FEEDBACK_LOG}")
        print(f"  prune_log:    {_PRUNE_LOG}")
        print(f"  deletion API: cognee.forget(data_id=..., dataset_id=...)")
        print(f"  scope:        item-level — unique graph nodes/edges only")
        print(f"  shared nodes: detagged, not removed")
        print()

        result = await prune_stale_events(
            dry_run=dry,
            min_feedbacks=args.min_feedbacks,
            max_score=args.min_score,
        )

        print(f"\n{'='*60}")
        print(f"Summary:")
        print(f"  Stale candidates found:  {len(result['candidates'])}")
        print(f"  Dataset ID:              {result['dataset_id'] or 'not found'}")
        print(f"  Events acted on:         {len(result['pruned'])}")
        print(f"  Not found in dataset:    {len(result['not_found'])}")
        print(f"  Mode:                    {'DRY RUN (no changes)' if dry else 'COMMITTED'}")

        if dry and result["pruned"]:
            print(f"\n  Run with --commit to execute these deletions.")

        if not dry and result["pruned"]:
            print(f"\n  Prune log: {_PRUNE_LOG}")
            print(f"\n  To verify a deletion:")
            for p in result["pruned"]:
                if "error" not in p:
                    print(
                        f"    python -m memory.forget --dry-run "
                        f"--verify {p['market_id']}:{result['dataset_id']}"
                    )

        if args.verify:
            try:
                mid, did = args.verify.split(":", 1)
            except ValueError:
                print("\n[ERROR] --verify format: MARKET_ID:DATASET_UUID", file=sys.stderr)
                sys.exit(1)
            print(f"\n{'='*60}")
            print(f"Verifying deletion of {mid} from dataset {did[:8]}…")
            v = await verify_deletion(mid, did)
            print(f"  data_record_gone: {v['data_record_gone']}")
            print(f"  recall_empty:     {v['recall_empty']}")
            print(f"  recall_note:      {v['recall_note']}")

    asyncio.run(_main())
