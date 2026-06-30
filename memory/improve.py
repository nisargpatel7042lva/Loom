"""
Self-improvement loop using Cognee's real feedback system.

After a prediction market resolves, this module:
  1. Fetches the original recall answer from Cognee's session cache via get_session()
  2. Scores how well that answer predicted the actual outcome (1–5)
  3. Records feedback via session_manager.add_feedback()
  4. Attempts apply_feedback_weights() to update graph edge weights

API CORRECTIONS vs. common documentation errors:
  cognee.session.add_feedback()     → does NOT exist as a top-level namespace
  cognee.session.get_session()      → does NOT exist as a top-level namespace
  save_interaction=True             → does NOT exist in cognee.search()
  SearchType.FEEDBACK               → does NOT exist in Cognee 1.2.1

The real APIs used here:
  get_session_manager()             from cognee.infrastructure.session.get_session_manager
  session_manager.get_session()     returns list[SessionQAEntry] when formatted=False
  session_manager.add_feedback()    returns True if qa_id found and updated, False otherwise

  GRAPH_COMPLETION searches do NOT auto-save qa_ids — only AGENTIC_COMPLETION does
  (agentic_retriever.py:452). We call session_manager.add_qa() manually in recall.py
  and persist the returned qa_id to data/recall_interactions.json.

WHAT WORKS:
  add_feedback()       — durably stores score (1-5) in SQLite. Returns True/False.
  get_session()        — retrieves original answer text for scoring and display.
  apply_feedback_weights() — IS called, but returns skipped=N because
                         used_graph_element_ids=None (GRAPH_COMPLETION doesn't expose
                         which node/edge UUIDs it traversed). No edge weights change.

CLI:
    python -m memory.improve FM-001 YES
    python -m memory.improve FM-001 YES --score 5 --feedback "Correctly recalled cut"
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


async def _fetch_original_entry(user_id: str, qa_id: str) -> Any | None:
    """
    Retrieve the SessionQAEntry for a specific qa_id from Cognee's session cache.

    Calls session_manager.get_session() (the real API; cognee.session.get_session()
    does not exist) and searches the returned list for the matching qa_id.

    Returns the SessionQAEntry, or None if not found (cache was pruned) or unavailable.
    """
    try:
        from cognee.infrastructure.session.get_session_manager import get_session_manager
        session_manager = get_session_manager()
        entries = await session_manager.get_session(
            user_id=user_id,
            session_id=LOOM_SESSION_ID,
            formatted=False,
        )
        for entry in (entries or []):
            if str(getattr(entry, "qa_id", "")) == qa_id:
                return entry
        return None
    except Exception:
        return None


def _score_answer_vs_outcome(answer_text: str, actual_outcome: str) -> tuple[int, str]:
    """
    Score (1–5) how well the recall answer predicted the actual outcome.

      5 = answer clearly leaned toward the correct outcome direction
      3 = answer was ambiguous or answer text is empty (graph was empty at recall time)
      1 = answer clearly leaned toward the WRONG outcome direction

    Uses keyword heuristics on the answer text. This is imperfect — a real scorer
    would parse the LLM's explicit prediction. But it's deterministic and auditable.
    """
    text = answer_text.lower() if answer_text else ""
    outcome = actual_outcome.upper()

    if not text:
        return 3, "no answer text (graph was empty when this recall was run)"

    yes_signals = sum(1 for w in (
        "cut", "cuts", "cutting", "reduced", "reduction",
        "likely", "probable", "high probability", "will", "yes", "positive",
        "expect", "expected", "anticipat",
    ) if w in text)

    no_signals = sum(1 for w in (
        "pause", "paused", "hold", "holding", "halt", "unchanged",
        "unlikely", "improbable", "low probability", "won't", "no ",
        "negative", "not expected", "hawkish",
    ) if w in text)

    if outcome == "YES":
        if yes_signals > no_signals:
            return 5, f"answer leaned YES (yes={yes_signals} > no={no_signals}) → correct"
        elif yes_signals == no_signals:
            return 3, f"answer was ambiguous (yes={yes_signals} == no={no_signals}), outcome YES"
        else:
            return 1, f"answer leaned NO (no={no_signals} > yes={yes_signals}) → wrong, outcome YES"
    elif outcome == "NO":
        if no_signals > yes_signals:
            return 5, f"answer leaned NO (no={no_signals} > yes={yes_signals}) → correct"
        elif no_signals == yes_signals:
            return 3, f"answer was ambiguous (no={no_signals} == yes={yes_signals}), outcome NO"
        else:
            return 1, f"answer leaned YES (yes={yes_signals} > no={no_signals}) → wrong, outcome NO"
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

    Steps:
      1. Load market_id → qa_id mapping from data/recall_interactions.json
      2. Call get_session() to fetch the original SessionQAEntry (full answer text)
      3. Score how well the original answer predicted the actual outcome
      4. Call add_feedback() and report True/False honestly
      5. Attempt apply_feedback_weights() (will skip — no graph element IDs)

    Args:
        market_id:      e.g. "FM-001"
        actual_outcome: "YES", "NO", or "pending"
        feedback_score: Manual override (1–5). None = auto-scored from answer text.
        feedback_text:  Manual override. None = auto-generated from scoring reasoning.

    Returns a dict with per-qa_id results including add_feedback_returned (bool).
    """
    from cognee.infrastructure.session.get_session_manager import get_session_manager
    from cognee.modules.users.methods import get_default_user

    interactions = _load_interactions()
    market_interactions = interactions.get(market_id, [])

    if not market_interactions:
        note = (
            f"No recall interactions found for {market_id!r}. "
            "Run `python -m memory.recall {market_id}` with a populated graph first."
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
        interaction_session = interaction.get("session_id", LOOM_SESSION_ID)

        # ── Step 1: fetch the original SessionQAEntry ─────────────────────────
        # get_session() is the real API. cognee.session.get_session() doesn't exist.
        original_entry = await _fetch_original_entry(user_id, qa_id)

        if original_entry is not None:
            original_answer = getattr(original_entry, "answer", "") or ""
            original_question = getattr(original_entry, "question", "")
            entry_source = "live from session cache"
        else:
            # Fallback: use the 200-char preview stored at recall time
            original_answer = interaction.get("answer_preview", "")
            original_question = interaction.get("query", "")
            entry_source = "fallback: 200-char preview (session entry not found — cache may have been pruned)"

        print(f"\n  [{market_id}] qa_id={qa_id[:8]}…")
        print(f"  Entry source: {entry_source}")
        if original_answer:
            preview = original_answer[:200] + ("…" if len(original_answer) > 200 else "")
            print(f"  Original answer: {preview}")
        else:
            print(f"  Original answer: [empty — graph was not populated when recall ran]")

        # ── Step 2: score the recall quality ──────────────────────────────────
        if feedback_score is None:
            score, reasoning = _score_answer_vs_outcome(original_answer, actual_outcome)
        else:
            score = feedback_score
            reasoning = "manually set"

        text = feedback_text or (
            f"Market {market_id} resolved as {actual_outcome}. "
            f"Recall quality: {reasoning}"
        )

        print(f"  Score: {score}/5  ({reasoning})")

        # ── Step 3: call add_feedback() ───────────────────────────────────────
        # Real API: session_manager.add_feedback() NOT cognee.session.add_feedback()
        # Returns True if qa_id found in SQLite cache, False if not found or unavailable.
        returned = await session_manager.add_feedback(
            user_id=user_id,
            qa_id=qa_id,
            feedback_text=text,
            feedback_score=score,
            session_id=interaction_session,
        )

        if returned:
            print(f"  add_feedback → True  ✓ (stored in SQLite)")
        else:
            print(f"  add_feedback → False ✗ (qa_id not in cache — graph/session was pruned)")

        result: dict[str, Any] = {
            "qa_id": qa_id,
            "score": score,
            "reasoning": reasoning,
            "feedback_text": text,
            "add_feedback_returned": returned,
            "original_answer_chars": len(original_answer),
        }
        feedback_results.append(result)

        _log_entry({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market_id": market_id,
            "actual_outcome": actual_outcome,
            **result,
        })

    # ── Step 4: apply_feedback_weights() ──────────────────────────────────────
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
    Attempt apply_feedback_weights for QA entries with successful add_feedback.

    HONEST RESULT: returns skipped=N because used_graph_element_ids=None.
    GRAPH_COMPLETION does not expose traversed node/edge UUIDs.
    apply_feedback_weights._process_feedback_item() explicitly returns skipped=1
    when both node_ids and edge_ids are empty (lines 163-170 of apply_feedback_weights.py).

    This call is NOT skipped here — we run it so the mechanism is exercised and the
    honest skipped count is visible. To get applied>0, switch to AGENTIC_COMPLETION.
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
            f"skipped={result.get('skipped', '?')} (expected): used_graph_element_ids=None. "
            "GRAPH_COMPLETION does not surface traversed node/edge UUIDs. "
            "Switch to AGENTIC_COMPLETION to get applied>0."
        )
        return result

    except Exception as exc:
        return {"error": str(exc)}


# ── before/after comparison ───────────────────────────────────────────────────

async def compare_before_after(market_id: str) -> None:
    """
    Print the original recall answer (from session cache) vs a fresh call now.

    HONEST NOTE about what to expect:
      apply_feedback_weights was called but returned skipped=N (no graph element IDs).
      No graph edge weights were updated. Therefore the GRAPH_COMPLETION answer
      WILL NOT CHANGE between before and after.

      A real difference would require:
        1. AGENTIC_COMPLETION (populates used_graph_element_ids automatically)
        2. apply_feedback_weights to successfully run with those IDs (applied > 0)
        3. Re-querying after weights propagate

      With GRAPH_COMPLETION, this comparison demonstrates the mechanism is wired up
      and feedback is stored in SQLite — it does NOT demonstrate weight-based change.
    """
    events = json.loads(DATA_FILE.read_text())
    event = next((e for e in events if e["market_id"] == market_id), None)
    if not event:
        print(f"[ERROR] {market_id!r} not found in fixtures.")
        return

    from cognee.infrastructure.session.get_session_manager import get_session_manager
    from cognee.modules.users.methods import get_default_user

    user = await get_default_user()
    user_id = str(user.id)

    # ── BEFORE: fetch from session cache ──────────────────────────────────────
    interactions = _load_interactions()
    before_answer = None
    before_score = None
    before_text = None

    if market_id in interactions and interactions[market_id]:
        last = interactions[market_id][-1]
        qa_id = last["qa_id"]
        entry = await _fetch_original_entry(user_id, qa_id)
        if entry is not None:
            before_answer = getattr(entry, "answer", "") or ""
            before_score = getattr(entry, "feedback_score", None)
            before_text = getattr(entry, "feedback_text", None)
        else:
            before_answer = last.get("answer_preview", "")

    print(f"\n{'='*60}")
    print(f"BEFORE — original recall answer (from session cache)")
    print(f"{'='*60}")
    if before_answer:
        print(before_answer)
        if before_score is not None:
            print(f"\n[feedback already recorded: score={before_score}, text={before_text!r}]")
    else:
        print("[no session entry found — either graph was empty or session was pruned]")

    # ── AFTER: fresh GRAPH_COMPLETION call ────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"AFTER  — fresh GRAPH_COMPLETION call now")
    print(f"{'='*60}")
    try:
        result = await find_analogous_events(event)
        graph_answer = result.get("graph_completion")
        if isinstance(graph_answer, list) and graph_answer:
            after_text = str(graph_answer[0])
            print(after_text)
        elif graph_answer:
            after_text = str(graph_answer)
            print(after_text)
        else:
            after_text = ""
            print("[GRAPH_COMPLETION returned empty — graph empty or LLM quota exhausted]")
    except Exception as exc:
        after_text = ""
        print(f"[ERROR: {exc}]")

    # ── verdict ───────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("VERDICT")
    print(f"{'='*60}")
    if not before_answer and not after_text:
        print("Both empty — graph not populated. Ingest fixtures first.")
    elif before_answer == after_text:
        print("Before == After  (identical)")
        print("Expected: apply_feedback_weights returned skipped=N — no edge weights changed.")
        print("To get ranking shifts: switch to AGENTIC_COMPLETION so used_graph_element_ids")
        print("is populated, then run apply_feedback_weights (it will return applied>0).")
    else:
        print("Before != After  (answers differ)")
        print("This may reflect graph updates from ingest re-runs or LLM non-determinism,")
        print("NOT from feedback weights (which were skipped — no graph element IDs).")


# ── batch mode ────────────────────────────────────────────────────────────────

async def batch_record_outcomes() -> None:
    """
    Record outcomes for all resolved fixture events.

    Simulates a week of markets resolving. For each resolved event:
      - Fetches the original recall answer from session cache (get_session())
      - Scores it against the known outcome
      - Calls add_feedback() and reports True/False honestly

    If no qa_ids exist yet (graph never populated or recall never run),
    all events will show qa_ids_found=0 and add_feedback won't be called.
    """
    events = json.loads(DATA_FILE.read_text())
    resolved = [e for e in events if e["outcome"] != "pending"]
    pending  = [e for e in events if e["outcome"] == "pending"]

    print(f"\nBatch mode: {len(resolved)} resolved, {len(pending)} pending (skipped)")
    print("="*60)

    total_with_qa   = 0
    total_without_qa = 0
    total_true  = 0
    total_false = 0
    total_skipped_weights = 0

    for event in resolved:
        mid = event["market_id"]
        outcome = event["outcome"]
        print(f"\n▶ {mid} ({event['category']}) → {outcome}")
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
        skipped = apply.get("skipped", 0)
        total_skipped_weights += skipped
        if skipped > 0 or "error" in apply:
            print(f"  apply_feedback_weights → {apply.get('note', apply)}")

    print(f"\n{'='*60}")
    print("Batch complete:")
    print(f"  Events processed:                 {len(resolved)}")
    print(f"  Had prior recall interaction:     {total_with_qa}")
    print(f"  No prior recall (qa_id absent):   {total_without_qa}")
    print(f"  add_feedback → True  (stored):    {total_true}")
    print(f"  add_feedback → False (not found): {total_false}")
    print(f"  apply_weights skipped:            {total_skipped_weights}")
    print(f"  Feedback log: {_FEEDBACK_LOG}")

    if total_without_qa > 0:
        print(f"\nNOTE: {total_without_qa} events had no qa_id. Fix:")
        print("  1. Get a key with higher RPD: https://aistudio.google.com/app/apikey")
        print("  2. python -m ingest.loader --source fixtures --limit 5")
        print("  3. python -m memory.recall <market_id>   (for each market)")
        print("  4. python -m memory.improve --batch      (then re-run this)")

    if total_true > 0 and total_skipped_weights > 0:
        print(f"\nFEEDBACK STORED: {total_true} qa_id(s) have feedback in SQLite.")
        print("EDGE WEIGHTS: unchanged (apply_feedback_weights skipped — no graph element IDs).")
        print("Run --compare <market_id> to see before/after answers.")
        print("Expected result: identical (no weight changes occurred).")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Record market outcomes and feed back to Cognee's session manager."
    )
    parser.add_argument("market_id", nargs="?",
                        help="Market ID to record (e.g. FM-001)")
    parser.add_argument("actual_outcome", nargs="?",
                        choices=["YES", "NO", "pending"],
                        help="Actual market resolution")
    parser.add_argument("--score", type=int, choices=[1, 2, 3, 4, 5],
                        help="Override auto-computed score (1=wrong, 5=perfect)")
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
            print(f"\nSummary:")
            print(f"  qa_ids_found:     {result['qa_ids_found']}")
            print(f"  feedback_results: {len(result['feedback_results'])} entries")
            for r in result["feedback_results"]:
                returned = "True ✓" if r["add_feedback_returned"] else "False ✗"
                print(f"    qa_id={r['qa_id'][:8]}… score={r['score']}  add_feedback→{returned}")
            print(f"  apply_weights:    {result.get('apply_weights_result')}")
            if result.get("note"):
                print(f"  note: {result['note']}")
        else:
            parser.print_help()
            print("\nExamples:")
            print("  python -m memory.improve FM-001 YES")
            print("  python -m memory.improve FM-001 YES --score 5 --feedback 'Perfect'")
            print("  python -m memory.improve --batch")
            print("  python -m memory.improve --compare FM-001")
            sys.exit(1)

    asyncio.run(_main())
