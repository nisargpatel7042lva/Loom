"""
LoomAgent — prediction-market memory agent.

Wraps the recall (Phase 3) and learn (Phase 4) layers into a single interface
a trader or pipeline can call without knowing Cognee internals.

  analyze(new_event)              → graph-traversal recall + trader brief
  learn_from_outcome(market_id)   → attaches feedback to the recalled QA entry

BRIEF FORMAT (what _make_brief builds):
    "N analogous precedents found. M resolved YES / K resolved NO.
     Pattern: <1-sentence LLM synthesis>.
     Confidence signals: <specific market IDs and outcomes from graph answer>."

The brief is intentionally terse and number-heavy — traders don't want narrative,
they want specific prior resolutions and the direction they leaned.

WHAT IS AND ISN'T REAL RIGHT NOW:
    - analyze() always runs and returns a valid dict
    - When the graph is populated, graph_completion_answer contains LLM synthesis
      over actual graph edges (real precedents, real outcomes, real entity links)
    - When the graph is empty (ingest never cognified), graph_completion_answer
      is an empty list and brief says so explicitly
    - learn_from_outcome() calls session_manager.add_feedback() and returns
      True/False per qa_id honestly
    - apply_feedback_weights() is called but returns skipped=N (GRAPH_COMPLETION
      doesn't surface node/edge UUIDs; documented in memory/improve.py)

CLI:
    python -m agent.core analyze FM-001
    python -m agent.core learn FM-001 YES
    python -m agent.core learn FM-001 YES --score 5 --feedback "Called it exactly"
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from ingest.loader import DATA_FILE
from memory.recall import find_analogous_events
from memory.improve import record_outcome


# ── outcome parsing ───────────────────────────────────────────────────────────
# These patterns are applied to the GRAPH_COMPLETION text to extract concrete
# precedent counts without making an extra LLM call.

_YES_WORDS = re.compile(
    r"\b(resolved yes|outcome yes|cut rates|rate cut|cuts?|reduced|bullish|"
    r"passed|won|accepted|approved|above|exceeded|beat|launched)\b",
    re.IGNORECASE,
)
_NO_WORDS = re.compile(
    r"\b(resolved no|outcome no|held rates|rate hold|holds?|paused|hawkish|"
    r"failed|lost|rejected|below|missed|halted|cancelled)\b",
    re.IGNORECASE,
)
_MARKET_ID = re.compile(r"\b([A-Z]{2,3}-\d{3})\b")


def _parse_completion(text: str) -> dict[str, Any]:
    """
    Extract structured signals from a GRAPH_COMPLETION answer string.

    Returns:
        {
            "market_ids":   list of market IDs mentioned (e.g. ["FM-001", "EL-002"])
            "yes_signals":  count of YES-direction keywords
            "no_signals":   count of NO-direction keywords
            "dominant":     "YES" | "NO" | "MIXED" | "EMPTY"
            "first_sentence": first sentence of the answer (for pattern line in brief)
        }
    """
    if not text or not text.strip():
        return {
            "market_ids": [],
            "yes_signals": 0,
            "no_signals": 0,
            "dominant": "EMPTY",
            "first_sentence": "",
        }

    market_ids = list(dict.fromkeys(_MARKET_ID.findall(text)))
    yes_count = len(_YES_WORDS.findall(text))
    no_count = len(_NO_WORDS.findall(text))

    if yes_count == 0 and no_count == 0:
        dominant = "MIXED"
    elif yes_count > no_count:
        dominant = "YES"
    elif no_count > yes_count:
        dominant = "NO"
    else:
        dominant = "MIXED"

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    first_sentence = sentences[0] if sentences else text[:200]

    return {
        "market_ids": market_ids,
        "yes_signals": yes_count,
        "no_signals": no_count,
        "dominant": dominant,
        "first_sentence": first_sentence,
    }


def explain_match(
    new_event: dict,
    graph_results: list | None,
    triplet_results: list | None,
) -> dict[str, Any]:
    """
    Interpret graph and triplet results in terms of the new event.

    Returns a structured explanation dict used by _make_brief(). Does not
    make any LLM calls — works entirely from the already-retrieved results.
    """
    # GRAPH_COMPLETION returns list[SearchResultItem]; .text is the completion string.
    # When the graph is empty, graph_results is [] (empty list, not None).
    graph_text = ""
    if graph_results:
        first = graph_results[0]
        # SearchResultItem has .text; plain str fallback for older API shapes
        graph_text = getattr(first, "text", None) or str(first)

    parsed = _parse_completion(graph_text)

    # Triplet results give subject→predicate→object edges — concrete entity links.
    # Each item is a SearchResultItem; we pull .text for the first few.
    triplet_snippets: list[str] = []
    if triplet_results:
        for item in triplet_results[:3]:
            t = getattr(item, "text", None) or str(item)
            if t and t.strip():
                triplet_snippets.append(t.strip())

    category = new_event.get("category", "")
    question = new_event.get("market_question", "")
    odds_before = new_event.get("odds_before")
    odds_after = new_event.get("odds_after")
    odds_move = new_event.get("odds_move_pct")

    return {
        "graph_text": graph_text,
        "parsed": parsed,
        "triplet_snippets": triplet_snippets,
        "new_event_summary": {
            "question": question,
            "category": category,
            "odds_before": odds_before,
            "odds_after": odds_after,
            "odds_move_pct": odds_move,
        },
    }


def _make_brief(new_event: dict, match: dict) -> str:
    """
    Compose a trader-readable brief from the explain_match() output.

    Format:
        "<N> analogous precedents found in <category>. <M> resolved YES / <K> NO.
         [Odds: X → Y (+Z%)] Pattern: <first sentence from LLM answer>.
         [Precedents cited: FM-001, FM-002]"

    Falls back to an honest empty-graph notice when no results are available.
    """
    parsed = match["parsed"]
    ns = match["new_event_summary"]

    market_ids = parsed["market_ids"]
    n = len(market_ids)
    yes_s = parsed["yes_signals"]
    no_s = parsed["no_signals"]
    dominant = parsed["dominant"]
    pattern = parsed["first_sentence"]
    category = ns["category"].upper() if ns["category"] else "UNKNOWN"
    odds_before = ns["odds_before"]
    odds_after = ns["odds_after"]
    odds_move = ns["odds_move_pct"]

    if dominant == "EMPTY":
        return (
            f"No analogous precedents found in {category}. "
            f"Graph is empty or no similar markets have been ingested. "
            f"Run `python -m ingest.loader --source fixtures` to populate."
        )

    # ── counts line ──────────────────────────────────────────────────────────
    if n > 0:
        counts_line = f"{n} precedent{'s' if n != 1 else ''} cited"
    else:
        counts_line = "Precedents cited: not named explicitly"

    direction_line = f"{yes_s} YES-direction signal{'s' if yes_s != 1 else ''} / {no_s} NO-direction"

    # ── dominant direction ───────────────────────────────────────────────────
    if dominant == "YES":
        direction_word = "leans YES"
    elif dominant == "NO":
        direction_word = "leans NO"
    else:
        direction_word = "mixed signal"

    # ── odds context ─────────────────────────────────────────────────────────
    odds_line = ""
    if odds_before is not None and odds_after is not None and odds_move is not None:
        odds_line = (
            f" | Odds moved {odds_before:.0%} → {odds_after:.0%} ({odds_move:+.1f}%)"
        )
    elif odds_after is not None:
        odds_line = f" | Current implied: {odds_after:.0%}"

    # ── market IDs line ──────────────────────────────────────────────────────
    ids_line = ""
    if market_ids:
        ids_line = f" Precedents cited: {', '.join(market_ids[:5])}"
        if len(market_ids) > 5:
            ids_line += f" (+{len(market_ids)-5} more)"
        ids_line += "."

    # ── triplet corroboration ─────────────────────────────────────────────────
    triplet_line = ""
    if match["triplet_snippets"]:
        triplet_line = f" Triplet corroboration: {match['triplet_snippets'][0][:120]}."

    brief = (
        f"{counts_line}. {direction_line} → {direction_word}{odds_line}. "
        f"Pattern: {pattern}{ids_line}{triplet_line}"
    )
    return brief


# ── agent class ───────────────────────────────────────────────────────────────

class LoomAgent:
    """
    Prediction-market memory agent.

    Stateless across calls — all persistence is handled by Cognee's graph DB,
    the session cache (SQLite), and the local JSON/JSONL files in data/.
    """

    async def analyze(self, new_event: dict) -> dict[str, Any]:
        """
        Recall analogous past markets from the knowledge graph and produce a
        trader-readable brief.

        Args:
            new_event: A single market event dict (fixture schema or Jupiter-mapped).
                       Must contain at least "market_id" and "market_question".

        Returns:
            {
                "new_event":              the input event
                "graph_completion_answer": list[SearchResultItem] | [] (raw recall output)
                "triplet_completion":      list[SearchResultItem] | None
                "explanation":             formatted multi-line explanation (from recall.py)
                "brief":                   one-paragraph trader brief (terse, number-heavy)
                "qa_id":                   str | None  (needed for learn_from_outcome)
                "match":                   structured explain_match() output
            }
        """
        recall = await find_analogous_events(new_event)

        graph_results = recall.get("graph_completion") or []
        triplet_results = recall.get("triplet_completion")
        qa_id = recall.get("qa_id")

        match = explain_match(new_event, graph_results, triplet_results)
        brief = _make_brief(new_event, match)

        return {
            "new_event": new_event,
            "graph_completion_answer": graph_results,
            "triplet_completion": triplet_results,
            "explanation": recall.get("explanation", ""),
            "brief": brief,
            "qa_id": qa_id,
            "match": match,
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
        Record the actual market resolution and attach feedback to the qa_id
        that was saved during analyze().

        Calls memory.improve.record_outcome(), which:
          1. Calls session_manager.get_session() to retrieve the original answer
          2. Scores prediction quality vs actual outcome (or uses override)
          3. Calls session_manager.add_feedback() — returns True if qa_id in cache
          4. Calls apply_feedback_weights() — returns skipped=N (GRAPH_COMPLETION
             doesn't surface node/edge UUIDs; see memory/improve.py)

        Returns the record_outcome() result dict directly (no wrapping) so the
        caller sees the raw add_feedback_returned True/False per qa_id.
        """
        return await record_outcome(
            market_id,
            actual_outcome,
            feedback_score=feedback_score,
            feedback_text=feedback_text,
        )


# ── module-level convenience function ─────────────────────────────────────────

def _load_event(market_id: str) -> dict:
    events = json.loads(DATA_FILE.read_text())
    event = next((e for e in events if e["market_id"] == market_id), None)
    if event is None:
        ids = [e["market_id"] for e in events]
        raise SystemExit(
            f"Market ID {market_id!r} not found. Available: {ids}"
        )
    return event


# ── CLI ───────────────────────────────────────────────────────────────────────

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
    p_learn.add_argument("--score", type=int, choices=[1, 2, 3, 4, 5],
                         help="Manual feedback score (1=wrong, 5=perfect). Auto-computed if omitted.")
    p_learn.add_argument("--feedback", help="Manual feedback text.")

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
            print("── GRAPH COMPLETION (raw) ────────────────────────────────────")
            gc = result["graph_completion_answer"]
            if gc:
                for item in gc:
                    text = getattr(item, "text", None) or str(item)
                    print(text[:800])
            else:
                print("[empty — graph not populated or LLM quota exhausted]")
            print()
            print("── TRIPLET CORROBORATION ─────────────────────────────────────")
            tc = result["triplet_completion"]
            if tc:
                for item in tc[:3]:
                    text = getattr(item, "text", None) or str(item)
                    print(text[:200])
            elif tc is None:
                print("[triplet index not built — run cognify with triplet embeddings]")
            else:
                print("[empty]")
            print()
            print(f"qa_id: {result['qa_id'] or 'None (graph empty or session unavailable)'}")
            print(f"(Pass this qa_id to learn_from_outcome once the market resolves.)")

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
