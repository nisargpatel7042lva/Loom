"""
Recall layer: finds analogous past market events via Cognee vector retrieval.

Uses SearchType.CHUNKS — pure FastEmbed vector similarity search over the text
stored by cognee.add(). Zero LLM calls. Returns raw text chunks ranked by
cosine similarity to the query.

The LLM synthesis step (1 call) happens in agent/core.py using the chunks
returned here as grounding context.

CLI:
    python -m memory.recall FM-001
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
from memory.vector_store import search as vs_search, count as vs_count

_INTERACTIONS_FILE = Path(__file__).parent.parent / "data" / "recall_interactions.json"

LOOM_SESSION_ID = "loom_live"

_MISSING_INDEX_ERRORS = (
    "CollectionNotFoundError",
    "NoDataError",
    "IndexNotFoundError",
)


def _build_query(event: dict[str, Any]) -> str:
    """Semantic query for vector similarity search against stored event chunks."""
    parts: list[str] = []

    question = event.get("market_question", "")
    category = event.get("category", "")
    trigger = event.get("trigger", "")
    narrative = event.get("narrative", "")

    parts.append(question)
    if category:
        parts.append(f"category: {category}")
    if trigger:
        parts.append(f"triggered by: {trigger}")
    if narrative:
        parts.append(narrative[:200])

    return " | ".join(parts)


async def _safe_search(
    query: str,
    search_type: SearchType,
    top_k: int = 10,
) -> list | None:
    """
    Run a cognee.search() call, returning:
      None  — index not found (add() hasn't run yet)
      []    — search returned no results
      list  — actual results
    """
    try:
        return await cognee.search(
            query_text=query,
            query_type=search_type,
            datasets=[DATASET_NAME],
            top_k=top_k,
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        exc_str = str(exc)
        if exc_name in _MISSING_INDEX_ERRORS or any(
            m in exc_str for m in _MISSING_INDEX_ERRORS
        ):
            return None
        if (
            "RateLimitError" in exc_name
            or "429" in exc_str
            or "RESOURCE_EXHAUSTED" in exc_str
        ):
            return []
        raise


def _extract_chunk_text(item: Any) -> str:
    """Extract plain text from a Cognee search result item."""
    if hasattr(item, "text") and item.text:
        return item.text.strip()
    if isinstance(item, dict):
        sr = item.get("search_result", [])
        if sr:
            return str(sr[0]).strip()
        return ""   # dict wrapper with empty search_result — no actual text
    return str(item).strip()


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
    chunks: list,
) -> str | None:
    """Save a QA entry to Cognee's session manager for later feedback."""
    try:
        from cognee.infrastructure.session.get_session_manager import get_session_manager
        from cognee.modules.users.methods import get_default_user

        user = await get_default_user()
        session_manager = get_session_manager()

        answer_text = ""
        if chunks:
            answer_text = _extract_chunk_text(chunks[0])

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
    Find past market events analogous to new_event.

    Primary path: local FastEmbed cosine similarity search (0 LLM calls, instant).
    Fallback: cognee.search(CHUNKS) if local store is empty.

    Returns:
        {
            "query":    str         — the semantic query used
            "chunks":   list[str]   — text of top matching event chunks
            "qa_id":    str | None  — saved for feedback via improve.py
        }
    """
    market_id = new_event.get("market_id", "unknown")
    query = _build_query(new_event)

    chunks: list[str] = []
    raw_results = None

    # ── primary: local vector store (FastEmbed, 0 LLM calls) ─────────────────
    n_stored = vs_count()
    if n_stored > 0:
        hits = vs_search(query, top_k=8)
        for hit in hits:
            # Skip the event itself (would trivially match)
            if hit["market_id"] == market_id:
                continue
            if hit["score"] > 0.3 and hit["text"]:
                chunks.append(hit["text"])

    # ── fallback: cognee CHUNKS search ───────────────────────────────────────
    if not chunks:
        raw_results = await _safe_search(query, SearchType.CHUNKS, top_k=8)
        if raw_results:
            for item in raw_results:
                text = _extract_chunk_text(item)
                if text:
                    chunks.append(text)

    qa_id = await _save_qa_interaction(market_id, query, chunks)

    return {
        "query": query,
        "session_id": LOOM_SESSION_ID,
        "chunks": chunks,
        "raw_results": raw_results,
        "qa_id": qa_id,
        "n_stored": n_stored,
    }


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
    parser.add_argument("market_id", help="Market ID from sample_events.json, e.g. FM-001")
    args = parser.parse_args()

    event = _load_fixture_event(args.market_id)

    async def _main() -> None:
        print(f"\nRecalling analogues for {args.market_id}: {event['market_question']!r}\n")
        result = await find_analogous_events(event)

        print(f"Query: {result['query'][:120]}…")
        print(f"Chunks found: {len(result['chunks'])}")
        print()
        for i, chunk in enumerate(result["chunks"][:5], 1):
            print(f"[{i}] {chunk[:200]}")
            print()

    asyncio.run(_main())
