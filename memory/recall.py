"""
Recall layer: finds analogous past market events via Cognee's graph-aware retrieval.

Two retrieval modes are combined per call:

  GRAPH_COMPLETION   Full graph traversal + LLM synthesis. Follows entity edges
                     (e.g. Federal Reserve → FOMC → rate decision) so the answer
                     reflects actual graph structure, not just embedding proximity.
                     Requires a working LLM API key.

  TRIPLET_COMPLETION Triplet-level graph retrieval (subject→predicate→object).
                     No LLM call — purely vector/graph index. Works only if cognify
                     built the triplet index; silently returns None otherwise.

NOTE — save_interaction=True:
  This parameter does NOT exist in Cognee 1.2.1. Every search() call is already
  logged automatically: log_query() writes the query text + type to the 'queries'
  table in SQLite, log_result() writes the answer to 'results'. session_id groups
  related queries for later review via get_queries(user_id, limit).
  For Phase 3 feedback, retrieve the most recent query by session:
      from cognee.modules.search.operations.get_queries import get_queries
      from cognee.modules.users.methods import get_default_user
      user = await get_default_user()
      recent = await get_queries(user.id, limit=1)
      query_id = recent[0].id if recent else None

CLI:
    python -m memory.recall FM-001
    python -m memory.recall FM-003 --search-type graph
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import cognee
from cognee.api.v1.search.search import SearchType

from ingest.loader import DATA_FILE, DATASET_NAME

_INTERACTIONS_FILE = Path(__file__).parent.parent / "data" / "recall_interactions.json"

LOOM_SESSION_ID = "loom_live"

# Error types from LanceDB / Cognee when an index hasn't been built yet
_MISSING_INDEX_ERRORS = (
    "CollectionNotFoundError",
    "NoDataError",
    "IndexNotFoundError",
)


def _build_query(event: dict[str, Any]) -> str:
    """
    Construct a focused, entity-dense query from the new event's key fields.
    Emphasis on category + trigger (causal context) + narrative keywords so the
    graph traversal follows the right entity paths.
    """
    parts: list[str] = []

    category = event.get("category", "")
    question = event.get("market_question", "")
    trigger = event.get("trigger", "")
    narrative = event.get("narrative", "")

    parts.append(f"Find prediction market precedents analogous to: {question}")

    if category:
        parts.append(f"Category: {category}.")
    if trigger:
        parts.append(f"This was triggered by: {trigger}.")
    if narrative:
        # Truncate long narratives to keep the query tight
        parts.append(f"Context: {narrative[:300]}")

    parts.append(
        "What previous markets in the knowledge graph had similar triggers, "
        "category, or odds movement patterns? Explain the analogy."
    )

    return " ".join(parts)


async def _safe_search(
    query: str,
    search_type: SearchType,
    top_k: int = 10,
) -> list | None:
    """
    Run a single search, returning None (not raising) on index-not-found errors.
    All other exceptions propagate normally.
    """
    try:
        return await cognee.search(
            query_text=query,
            query_type=search_type,
            datasets=[DATASET_NAME],
            session_id=LOOM_SESSION_ID,
            top_k=top_k,
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        exc_str = str(exc)
        # Gracefully handle missing vector/triplet index (not built yet in cognify)
        if exc_name in _MISSING_INDEX_ERRORS or any(
            m in exc_str for m in _MISSING_INDEX_ERRORS
        ):
            return None
        raise


def _append_interaction(market_id: str, qa_id: str, answer_preview: str) -> None:
    """Save a qa_id mapping to data/recall_interactions.json."""
    interactions: dict = {}
    if _INTERACTIONS_FILE.exists():
        try:
            interactions = json.loads(_INTERACTIONS_FILE.read_text())
        except Exception:
            pass

    if market_id not in interactions:
        interactions[market_id] = []

    interactions[market_id].append({
        "qa_id": qa_id,
        "session_id": LOOM_SESSION_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "answer_preview": answer_preview[:200],
    })

    _INTERACTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _INTERACTIONS_FILE.write_text(json.dumps(interactions, indent=2))


async def _save_qa_interaction(
    market_id: str,
    query: str,
    graph_results: list | None,
) -> str | None:
    """
    Manually save a QA entry to Cognee's session manager after a GRAPH_COMPLETION search.

    Returns the qa_id for later feedback attachment, or None if unavailable.

    WHY this exists: cognee.search() with GRAPH_COMPLETION does NOT call session_manager.add_qa()
    automatically — only AGENTIC_COMPLETION does (agentic_retriever.py:452). Without a qa_id we
    cannot attach feedback via add_feedback() in memory/improve.py.

    LIMITATION: used_graph_element_ids (node/edge UUIDs that GRAPH_COMPLETION traversed) are not
    surfaced in the search response. Without them, apply_feedback_weights() will record the feedback
    in SQLite but return skipped=1 — no graph edge weights are actually updated.
    Switch to SearchType.AGENTIC_COMPLETION to get a fully feedback-trainable system.
    """
    try:
        from cognee.infrastructure.session.get_session_manager import get_session_manager
        from cognee.modules.users.methods import get_default_user

        user = await get_default_user()
        session_manager = get_session_manager()

        answer_text = ""
        if isinstance(graph_results, list) and graph_results:
            answer_text = str(graph_results[0])

        qa_id = await session_manager.add_qa(
            user_id=str(user.id),
            question=query,
            context=f"Loom market event recall — {market_id}",
            answer=answer_text,
            session_id=LOOM_SESSION_ID,
        )

        if qa_id:
            _append_interaction(market_id, qa_id, answer_text)

        return qa_id
    except Exception:
        return None


async def find_analogous_events(new_event: dict[str, Any]) -> dict[str, Any]:
    """
    Find past market events analogous to new_event using graph-aware retrieval.

    Args:
        new_event: A single event dict (fixture schema or Jupiter-mapped schema).

    Returns:
        {
            "query":              str   — the query sent to both retrievers
            "session_id":         str   — session ID for history lookup
            "graph_completion":   list  — GRAPH_COMPLETION answer (LLM + graph traversal)
            "triplet_completion": list | None — TRIPLET_COMPLETION answer, None if
                                               triplet index wasn't built during cognify
            "explanation":        str   — formatted explanation of the analogy
        }
    """
    market_id = new_event.get("market_id", "unknown")
    query = _build_query(new_event)

    # ── primary retrieval: graph traversal + LLM synthesis ───────────────────
    graph_results = await _safe_search(query, SearchType.GRAPH_COMPLETION, top_k=10)

    # ── secondary retrieval: triplet index (no LLM) ──────────────────────────
    # TRIPLET_COMPLETION requires cognify to have built the triplet embedding
    # index. If the pipeline didn't include that stage (e.g. the default Cognee
    # pipeline doesn't always run it), this returns None.
    triplet_results = await _safe_search(query, SearchType.TRIPLET_COMPLETION, top_k=5)

    # ── save QA entry to session manager for Phase 4 feedback ────────────────
    # GRAPH_COMPLETION doesn't auto-save qa_ids (only AGENTIC_COMPLETION does).
    # We call add_qa() manually here so improve.py can attach feedback later.
    qa_id = await _save_qa_interaction(market_id, query, graph_results)

    explanation = _build_explanation(new_event, graph_results, triplet_results)

    return {
        "query": query,
        "session_id": LOOM_SESSION_ID,
        "graph_completion": graph_results,
        "triplet_completion": triplet_results,
        "explanation": explanation,
        "qa_id": qa_id,
    }


def _build_explanation(
    new_event: dict[str, Any],
    graph_results: list | None,
    triplet_results: list | None,
) -> str:
    """
    Compose a concise explanation of the analogy.

    GRAPH_COMPLETION already produces an LLM-reasoned answer that references
    specific graph entities and their relationships. We structure it here rather
    than making a redundant second LLM call. TRIPLET_COMPLETION adds edge-level
    corroboration when the index exists.
    """
    lines: list[str] = []
    lines.append(
        f"=== Analogous events for: {new_event.get('market_question', 'unknown')} ==="
    )
    lines.append(f"Category: {new_event.get('category', 'n/a')}  |  "
                 f"Trigger: {new_event.get('trigger', 'n/a')}")
    lines.append("")

    if graph_results:
        lines.append("── Graph-traversal answer (GRAPH_COMPLETION) ──")
        if isinstance(graph_results, list):
            for item in graph_results:
                lines.append(str(item))
        else:
            lines.append(str(graph_results))
    else:
        lines.append("── GRAPH_COMPLETION: no results (graph may be empty or LLM API unavailable)")

    lines.append("")

    if triplet_results is None:
        lines.append(
            "── TRIPLET_COMPLETION: index not available "
            "(triplet embeddings not built by cognify pipeline)"
        )
    elif triplet_results:
        lines.append("── Triplet-level cross-check (TRIPLET_COMPLETION) ──")
        if isinstance(triplet_results, list):
            for item in triplet_results[:3]:
                lines.append(str(item))
        else:
            lines.append(str(triplet_results))
    else:
        lines.append("── TRIPLET_COMPLETION: returned empty")

    return "\n".join(lines)


async def get_last_query_id() -> str | None:
    """
    Return the UUID of the most recently logged search query in this process.
    Useful for Phase 3 feedback attachment.
    """
    try:
        from cognee.modules.search.operations.get_queries import get_queries
        from cognee.modules.users.methods import get_default_user

        user = await get_default_user()
        recent = await get_queries(user.id, limit=1)
        if recent:
            return str(recent[0].id)
        return None
    except Exception:
        return None


# ── CLI ──────────────────────────────────────────────────────────────────────

def _load_fixture_event(market_id: str) -> dict[str, Any]:
    events = json.loads(DATA_FILE.read_text())
    for e in events:
        if e["market_id"] == market_id:
            return e
    ids = [e["market_id"] for e in events]
    raise SystemExit(
        f"Market ID {market_id!r} not found in fixtures.\nAvailable: {ids}"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Find analogous past market events for a given fixture event."
    )
    parser.add_argument("market_id", help="Market ID from sample_events.json, e.g. FM-003")
    parser.add_argument(
        "--search-type",
        choices=["graph", "triplet", "both"],
        default="both",
        help="Which retrieval mode to run (default: both)",
    )
    args = parser.parse_args()

    event = _load_fixture_event(args.market_id)

    async def _main() -> None:
        print(f"\nLooking up analogues for {args.market_id}: {event['market_question']!r}")
        print(f"Dataset: {DATASET_NAME}  |  Session: {LOOM_SESSION_ID}\n")

        result = await find_analogous_events(event)

        print(result["explanation"])
        print()

        query_id = await get_last_query_id()
        if query_id:
            print(f"[logged] query_id={query_id}  (attach Phase 3 feedback to this ID)")

    asyncio.run(_main())
