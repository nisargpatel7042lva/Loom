"""
LoomAgent — prediction-market memory agent.

Architecture (designed for 20 RPD free-tier Gemini key):
  - Ingest:   cognee.add()  → 0 LLM calls (FastEmbed local vectorization)
  - Recall:   cognee.search(CHUNKS) → 0 LLM calls (vector similarity)
  - Analyze:  1 litellm.completion() call → brief synthesis from retrieved chunks
  - Learn:    session_manager.add_feedback() → 0 LLM calls
  - Forget:   cognee.prune() → 0 LLM calls

Net result: 20 live market analyses per day; unlimited ingest.

CLI:
    python -m agent.core analyze FM-001
    python -m agent.core learn FM-001 YES
    python -m agent.core learn FM-001 YES --score 5 --feedback "Called it exactly"
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from ingest.loader import DATA_FILE
from memory.recall import find_analogous_events
from memory.improve import record_outcome


# ── brief synthesis (the 1 LLM call per analyze) ─────────────────────────────

_BRIEF_SYSTEM = (
    "You are a quantitative prediction-market analyst. "
    "Given recalled similar past markets, produce a concise trader brief. "
    "Focus on: how many analogous markets exist, how they resolved (YES/NO), "
    "what pattern they suggest, and what confidence level is warranted. "
    "Be specific and number-heavy. Under 80 words."
)


async def _synthesize_brief(new_event: dict, chunks: list[str]) -> str:
    """
    Make exactly 1 LLM call to synthesize a trader brief from retrieved chunks.

    Falls back to a deterministic summary when no chunks are available
    (preserving the 0-LLM-call path for empty-graph cases).
    """
    if not chunks:
        cat = new_event.get("category", "UNKNOWN").upper()
        oa = new_event.get("odds_after")
        odds_str = f" (current implied: {oa:.0%})" if oa is not None else ""
        return (
            f"No analogous precedents found in {cat}{odds_str}. "
            "Graph is empty — run ingest first to populate market memory."
        )

    import litellm

    context = "\n\n".join(f"[Past market {i+1}]: {c}" for i, c in enumerate(chunks[:6]))
    question = new_event.get("market_question", "")
    category = new_event.get("category", "")
    oa = new_event.get("odds_after")
    odds_line = f" (current implied probability: {oa:.0%})" if oa is not None else ""

    prompt = (
        f"New market: {question} [Category: {category}{odds_line}]\n\n"
        f"Retrieved analogous past markets from memory:\n{context}\n\n"
        "Write a trader brief (under 80 words): precedent count, YES/NO resolution pattern, "
        "dominant direction, and one-sentence confidence assessment."
    )

    try:
        resp = await litellm.acompletion(
            model=os.environ["LLM_MODEL"],
            messages=[
                {"role": "system", "content": _BRIEF_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            api_key=os.environ["LLM_API_KEY"],
            max_tokens=200,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        exc_str = str(exc)
        if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
            # Quota hit — return deterministic summary from the chunks
            resolved_yes = sum(1 for c in chunks if "resolved YES" in c or "resolved yes" in c)
            resolved_no = sum(1 for c in chunks if "resolved NO" in c or "resolved no" in c)
            return (
                f"{len(chunks)} analogous precedents found. "
                f"{resolved_yes} resolved YES / {resolved_no} resolved NO. "
                f"(LLM synthesis unavailable — API quota exhausted. "
                f"Chunks returned for manual review.)"
            )
        raise


# ── agent class ───────────────────────────────────────────────────────────────

class LoomAgent:
    """
    Prediction-market memory agent.

    Stateless across calls — all persistence is in Cognee's vector DB
    and SQLite session cache.
    """

    async def analyze(self, new_event: dict) -> dict[str, Any]:
        """
        Recall analogous past markets and produce a trader-readable brief.

        LLM calls: exactly 1 (synthesis). Recall is pure vector similarity.

        Returns:
            {
                "new_event":  the input event
                "chunks":     list[str] — top matching text chunks from memory
                "brief":      str — one-paragraph trader brief
                "qa_id":      str | None — for learn_from_outcome()
            }
        """
        recall = await find_analogous_events(new_event)

        chunks = recall.get("chunks", [])
        qa_id = recall.get("qa_id")

        brief = await _synthesize_brief(new_event, chunks)

        return {
            "new_event": new_event,
            "chunks": chunks,
            "brief": brief,
            "qa_id": qa_id,
        }

    async def learn_from_outcome(
        self,
        market_id: str,
        actual_outcome: str,
        *,
        feedback_score: int | None = None,
        feedback_text: str | None = None,
    ) -> dict[str, Any]:
        """
        Record the actual market resolution and attach feedback.

        Calls memory.improve.record_outcome(), which:
          1. Retrieves original answer from Cognee's session cache
          2. Scores prediction quality vs actual outcome
          3. Calls session_manager.add_feedback() — True if qa_id found

        Zero LLM calls.
        """
        return await record_outcome(
            market_id,
            actual_outcome,
            feedback_score=feedback_score,
            feedback_text=feedback_text,
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

def _load_event(market_id: str) -> dict:
    events = json.loads(DATA_FILE.read_text())
    event = next((e for e in events if e["market_id"] == market_id), None)
    if event is None:
        ids = [e["market_id"] for e in events]
        raise SystemExit(
            f"Market ID {market_id!r} not found. Available: {ids}"
        )
    return event


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Loom prediction-market memory agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m agent.core analyze FM-001\n"
            "  python -m agent.core learn FM-001 YES\n"
            "  python -m agent.core learn FM-001 YES --score 5 --feedback 'Perfect recall'\n"
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_analyze = sub.add_parser("analyze", help="Recall analogous markets and produce a brief.")
    p_analyze.add_argument("market_id", help="Market ID from sample_events.json, e.g. FM-001")

    p_learn = sub.add_parser("learn", help="Record actual outcome and train on the result.")
    p_learn.add_argument("market_id")
    p_learn.add_argument("actual_outcome", choices=["YES", "NO", "pending"])
    p_learn.add_argument("--score", type=int, choices=[1, 2, 3, 4, 5])
    p_learn.add_argument("--feedback")

    args = parser.parse_args()
    agent = LoomAgent()

    async def _main() -> None:
        if args.cmd == "analyze":
            event = _load_event(args.market_id)
            print(f"\nAnalyzing {args.market_id}: {event['market_question']!r}")
            print(f"Category: {event['category']}  |  Outcome: {event.get('outcome', 'pending')}\n")

            result = await agent.analyze(event)

            print("── BRIEF ─────────────────────────────────────────────────────")
            print(result["brief"])
            print()
            print(f"── CHUNKS RETRIEVED: {len(result['chunks'])} ─────────────────────────────────")
            for i, chunk in enumerate(result["chunks"][:3], 1):
                print(f"[{i}] {chunk[:200]}")
            print()
            print(f"qa_id: {result['qa_id'] or 'None (session unavailable)'}")

        elif args.cmd == "learn":
            print(f"\nRecording outcome for {args.market_id}: {args.actual_outcome}")
            result = await agent.learn_from_outcome(
                args.market_id,
                args.actual_outcome,
                feedback_score=args.score,
                feedback_text=args.feedback,
            )
            print(f"\nSummary:")
            print(f"  qa_ids_found:    {result.get('qa_ids_found', 0)}")
            for fb in result.get("feedback_results", []):
                returned = "True ✓" if fb["add_feedback_returned"] else "False ✗"
                print(
                    f"  qa_id={fb['qa_id'][:8]}…  score={fb['score']}  "
                    f"add_feedback→{returned}  reason: {fb['reasoning']}"
                )
            apply = result.get("apply_weights_result") or {}
            if apply:
                print(f"  apply_weights: {apply.get('note', apply)}")
            if result.get("note"):
                print(f"  note: {result['note']}")

    asyncio.run(_main())
