"""
Self-improvement loop using Cognee's real feedback system.

After a prediction market resolves, this module scores the historical recall
quality and records feedback via SessionManager.add_feedback(). Cognee then
runs apply_feedback_weights() to update graph edge weights so future recalls
surface better-matching precedents.

HONEST DISCLOSURE about what works and what doesn't:

  add_feedback()          REAL — stores feedback_score (1–5) and feedback_text
                          in SQLite. Returns True on success, False if the
                          qa_id doesn't exist yet.

  apply_feedback_weights() REAL — reads QA entries and tries to update graph
                           edge weights using EMA:
                             new_weight = prev + alpha * (normalized - prev)
                           Maps score 1→0.0, 3→0.5, 5→1.0.

  THE SKIP CONDITION: apply_feedback_weights._process_feedback_item() returns
                      {"processed": 0, "applied": 0, "skipped": 1} when
                      used_graph_element_ids has no node_ids or edge_ids.
                      GRAPH_COMPLETION does NOT expose which graph nodes/edges
                      it traversed. Only AGENTIC_COMPLETION (agentic_retriever.py)
                      populates used_graph_element_ids automatically.

  CONSEQUENCE: With our GRAPH_COMPLETION-based recall, feedback is durably
               stored in SQLite (add_feedback returns True), but apply_feedback_
               weights skips weight updates. Recall quality won't improve via
               the weight mechanism unless used_graph_element_ids is populated.
               Switching to SearchType.AGENTIC_COMPLETION would fix this.

CLI:
    python -m memory.improve FM-001 YES
    python -m memory.improve FM-001 YES --score 5 --feedback "Perfect recall"
    python -m memory.improve --batch
    python -m memory.improve --compare FM-001
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from memory.recall import LOOM_SESSION_ID, find_analogous_events
from ingest.loader import DATA_FILE

_INTERACTIONS_FILE = Path(__file__).parent.parent / "data" / "recall_interactions.json"
_FEEDBACK_LOG = Path(__file__).parent.parent / "data" / "feedback_log.jsonl"


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_interactions() -> dict[str, list]:
    if not _INTERACTIONS_FILE.exists():
        return {}
    try:
        return json.loads(_INTERACTIONS_FILE.read_text())
    except Exception:
        return {}


def _log_entry(entry: dict) -> None:
    _FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_FEEDBACK_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _auto_score(actual_outcome: str, answer_preview: str) -> tuple[int, str]:
    """
    Infer feedback_score (1–5) from actual outcome vs recall answer preview.

    Returns (score, reasoning).
      5 = recall signalled the correct direction
      3 = recall was ambiguous or answer preview was empty
      1 = recall signalled the wrong direction

    This is a best-effort keyword heuristic — answer_preview is the first 200
    chars of the GRAPH_COMPLETION result stored in recall_interactions.json at
    recall time. If the graph was empty, the preview will be empty → score=3.
    """
    preview = answer_preview.lower()
    outcome = actual_outcome.upper()

    if not preview:
        return 3, "no answer preview (graph was empty or recall not yet run)"

    yes_signals = sum(1 for w in ("cut", "likely", "high", "will", "yes", "positive", "expect") if w in preview)
    no_signals  = sum(1 for w in ("pause", "hold", "unlikely", "low", "no", "halt", "won't") if w in preview)

    if outcome == "YES":
        if yes_signals > no_signals:
            return 5, f"recall leaned YES (yes_signals={yes_signals} > no_signals={no_signals}), outcome YES"
        elif yes_signals == no_signals:
            return 3, f"recall was ambiguous (signals tied {yes_signals}:{no_signals}), outcome YES"
        else:
            return 1, f"recall leaned NO (no_signals={no_signals} > yes_signals={yes_signals}), but outcome YES"
    elif outcome == "NO":
        if no_signals > yes_signals:
            return 5, f"recall leaned NO (no_signals={no_signals} > yes_signals={yes_signals}), outcome NO"
        elif no_signals == yes_signals:
            return 3, f"recall was ambiguous (signals tied {no_signals}:{yes_signals}), outcome NO"
        else:
            return 1, f"recall leaned YES (yes_signals={yes_signals} > no_signals={no_signals}), but outcome NO"
    else:
        return 3, f"outcome is {actual_outcome!r} (not resolved, neutral score)"


# ── core API ──────────────────────────────────────────────────────────────────

async def record_outcome(
    market_id: str,
    actual_outcome: str,
    *,
    feedback_score: int | None = None,
    feedback_text: str | None = None,
) -> dict[str, Any]:
    """
    Record the actual market outcome and attach feedback to historical recall QA entries.

    Args:
        market_id:      e.g. "FM-001"
        actual_outcome: "YES", "NO", or "pending"
        feedback_score: Override auto-computed score (1–5). None = auto-compute from answer preview.
        feedback_text:  Override feedback text. None = auto-generated.

    Returns a dict with honest reporting of:
        - qa_ids_found: how many recall interactions exist for this market
        - feedback_results: per-qa_id {score, add_feedback_returned: True/False}
        - apply_weights_result: raw result from apply_feedback_weights (skipped=N is expected)
    """
    from cognee.infrastructure.session.get_session_manager import get_session_manager
    from cognee.modules.users.methods import get_default_user

    interactions = _load_interactions()
    market_interactions = interactions.get(market_id, [])

    if not market_interactions:
        note = (
            f"No recall interactions found for {market_id!r}. "
            "Run `python -m memory.recall {market_id}` first (requires populated graph + LLM key). "
            "Or run `python -m ingest.loader --source fixtures` to populate the graph."
        )
        print(f"  [WARN] {note}")
        return {
            "market_id": market_id,
            "actual_outcome": actual_outcome,
            "qa_ids_found": 0,
            "feedback_results": [],
            "apply_weights_result": None,
            "note": note,
        }

    user = await get_default_user()
    user_id = str(user.id)
    session_manager = get_session_manager()

    feedback_results = []

    for interaction in market_interactions:
        qa_id = interaction["qa_id"]
        answer_preview = interaction.get("answer_preview", "")
        interaction_session = interaction.get("session_id", LOOM_SESSION_ID)

        if feedback_score is None:
            score, reasoning = _auto_score(actual_outcome, answer_preview)
        else:
            score = feedback_score
            reasoning = "manually set"

        text = feedback_text or (
            f"Market {market_id} resolved as {actual_outcome}. "
            f"Recall quality assessment: {reasoning}"
        )

        # add_feedback returns True if the qa_id exists in the cache and was updated,
        # False if the qa_id was not found (e.g. graph was pruned since recall was run).
        returned = await session_manager.add_feedback(
            user_id=user_id,
            qa_id=qa_id,
            feedback_text=text,
            feedback_score=score,
            session_id=interaction_session,
        )

        result: dict[str, Any] = {
            "qa_id": qa_id,
            "score": score,
            "feedback_text": text,
            "add_feedback_returned": returned,
        }
        feedback_results.append(result)

        _log_entry({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_id": market_id,
            "actual_outcome": actual_outcome,
            **result,
        })

        status = "True" if returned else "False — qa_id not in cache (graph may have been pruned)"
        print(f"  [{market_id}] qa_id={qa_id[:8]}… score={score}  add_feedback→{status}")

    apply_result = await _try_apply_weights(user, feedback_results)

    return {
        "market_id": market_id,
        "actual_outcome": actual_outcome,
        "qa_ids_found": len(market_interactions),
        "feedback_results": feedback_results,
        "apply_weights_result": apply_result,
    }


async def _try_apply_weights(user: Any, feedback_results: list[dict]) -> dict[str, Any]:
    """
    Attempt to run apply_feedback_weights on the QA entries that got successful add_feedback.

    Returns the raw result dict, which will honestly show skipped=N because
    used_graph_element_ids is None — GRAPH_COMPLETION does not expose traversed
    node/edge UUIDs. apply_feedback_weights._process_feedback_item() explicitly
    returns skipped=1 when both node_ids and edge_ids are empty.
    """
    try:
        from cognee.tasks.memify.apply_feedback_weights import apply_feedback_weights
        from cognee.context_global_variables import session_user

        successful = [r for r in feedback_results if r["add_feedback_returned"]]
        if not successful:
            return {
                "processed": 0, "applied": 0, "skipped": 0,
                "note": "no successful add_feedback calls — nothing to apply",
            }

        feedback_items = [
            {
                "qa_id": r["qa_id"],
                "session_id": LOOM_SESSION_ID,
                "feedback_score": r["score"],
                "used_graph_element_ids": None,
                "memify_metadata": {},
            }
            for r in successful
        ]

        token = session_user.set(user)
        try:
            result = await apply_feedback_weights(feedback_items)
        finally:
            session_user.reset(token)

        result["note"] = (
            f"skipped={result.get('skipped', '?')} (expected): used_graph_element_ids=None "
            "because GRAPH_COMPLETION does not expose traversed node/edge UUIDs. "
            "No graph edge weights were modified. Switch to AGENTIC_COMPLETION "
            "to get a fully feedback-trainable system."
        )
        return result

    except Exception as exc:
        return {"error": str(exc)}


# ── before/after comparison ───────────────────────────────────────────────────

async def compare_before_after(market_id: str) -> None:
    """
    Show the GRAPH_COMPLETION answer before (from stored snapshot) and after
    (fresh call) for a given market_id.

    HONEST NOTE: Without used_graph_element_ids, apply_feedback_weights skips
    weight updates, so before and after answers are expected to be identical.
    A real difference would require AGENTIC_COMPLETION-based recall.
    """
    events = json.loads(DATA_FILE.read_text())
    event = next((e for e in events if e["market_id"] == market_id), None)
    if not event:
        print(f"[ERROR] {market_id!r} not found in fixtures.")
        return

    interactions = _load_interactions()
    before_preview = None
    if market_id in interactions and interactions[market_id]:
        before_preview = interactions[market_id][-1].get("answer_preview", "")

    print(f"\n{'='*60}")
    print(f"BEFORE (snapshot from recall_interactions.json):")
    print(f"{'='*60}")
    if before_preview:
        print(before_preview or "[empty answer]")
    else:
        print("[no prior recall stored — run `python -m memory.recall {market_id}` first]")

    print(f"\n{'='*60}")
    print(f"AFTER  (fresh GRAPH_COMPLETION call):")
    print(f"{'='*60}")
    try:
        result = await find_analogous_events(event)
        graph_answer = result.get("graph_completion")
        if isinstance(graph_answer, list) and graph_answer:
            print(str(graph_answer[0]))
        elif graph_answer:
            print(str(graph_answer))
        else:
            print("[GRAPH_COMPLETION returned empty — LLM quota exhausted or graph empty]")
    except Exception as exc:
        print(f"[ERROR calling find_analogous_events: {exc}]")

    print()
    print("INTERPRETATION:")
    print("  If before == after: expected — weight updates were skipped (no graph element IDs).")
    print("  A real difference requires AGENTIC_COMPLETION + feedback weight pipeline.")


# ── batch mode ────────────────────────────────────────────────────────────────

async def batch_record_outcomes() -> None:
    """
    Simulate a week of markets resolving: record outcomes for all resolved fixture events.

    If recall interactions don't exist yet (graph was never populated / recall never run),
    all events will show qa_ids_found=0 and no feedback will be stored.
    """
    events = json.loads(DATA_FILE.read_text())
    resolved = [e for e in events if e["outcome"] != "pending"]
    pending  = [e for e in events if e["outcome"] == "pending"]

    print(f"\nBatch mode: {len(resolved)} resolved, {len(pending)} pending (skipped)")
    print("="*60)
    print()

    total_with_qa = 0
    total_without_qa = 0
    total_true = 0
    total_false = 0

    for event in resolved:
        mid = event["market_id"]
        outcome = event["outcome"]
        print(f"▶ {mid} ({event['category']}) → {outcome}")
        result = await record_outcome(mid, outcome)

        if result["qa_ids_found"] == 0:
            total_without_qa += 1
        else:
            total_with_qa += 1
            for r in result["feedback_results"]:
                if r["add_feedback_returned"]:
                    total_true += 1
                else:
                    total_false += 1

        apply = result.get("apply_weights_result") or {}
        if apply.get("skipped", 0) > 0 or apply.get("error"):
            print(f"  apply_feedback_weights → {apply}")
        print()

    print("="*60)
    print(f"Batch complete:")
    print(f"  Events processed:           {len(resolved)}")
    print(f"  Had prior recall (qa_id):   {total_with_qa}")
    print(f"  No prior recall:            {total_without_qa}")
    print(f"  add_feedback → True:        {total_true}")
    print(f"  add_feedback → False:       {total_false}")
    print(f"  Feedback log:               {_FEEDBACK_LOG}")
    print()

    if total_without_qa > 0:
        print(
            f"NOTE: {total_without_qa}/{len(resolved)} events had no qa_id. "
            "To fix:\n"
            "  1. Get a fresh API key (500+ RPD): https://aistudio.google.com/app/apikey\n"
            "  2. python -m ingest.loader --source fixtures\n"
            "  3. for each market: python -m memory.recall <market_id>\n"
            "  4. python -m memory.improve --batch"
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Record market outcomes and feed back to Cognee's session manager."
    )
    subparsers = parser.add_subparsers(dest="cmd")

    # python -m memory.improve FM-001 YES [--score 5] [--feedback "..."]
    p_single = parser.add_argument_group("single event")
    parser.add_argument(
        "market_id",
        nargs="?",
        help="Market ID to record outcome for (e.g. FM-001)",
    )
    parser.add_argument(
        "actual_outcome",
        nargs="?",
        choices=["YES", "NO", "pending"],
        help="Actual market resolution",
    )
    parser.add_argument("--score", type=int, choices=[1, 2, 3, 4, 5],
                        help="Override auto-computed feedback score (1=bad, 5=perfect)")
    parser.add_argument("--feedback", help="Override feedback text")
    parser.add_argument("--batch", action="store_true",
                        help="Record outcomes for all resolved fixture events")
    parser.add_argument("--compare", metavar="MARKET_ID",
                        help="Show before/after GRAPH_COMPLETION for a market")

    args = parser.parse_args()

    async def _main() -> None:
        if args.batch:
            await batch_record_outcomes()
        elif args.compare:
            await compare_before_after(args.compare)
        elif args.market_id and args.actual_outcome:
            print(f"\nRecording outcome for {args.market_id}: {args.actual_outcome}")
            result = await record_outcome(
                args.market_id,
                args.actual_outcome,
                feedback_score=args.score,
                feedback_text=args.feedback,
            )
            print()
            print(f"qa_ids_found:      {result['qa_ids_found']}")
            print(f"feedback_results:  {len(result['feedback_results'])} entries")
            print(f"apply_weights:     {result.get('apply_weights_result')}")
            if result.get("note"):
                print(f"note: {result['note']}")
        else:
            parser.print_help()
            print()
            print("Examples:")
            print("  python -m memory.improve FM-001 YES")
            print("  python -m memory.improve FM-001 YES --score 5 --feedback 'Perfect recall'")
            print("  python -m memory.improve --batch")
            print("  python -m memory.improve --compare FM-001")
            sys.exit(1)

    asyncio.run(_main())
