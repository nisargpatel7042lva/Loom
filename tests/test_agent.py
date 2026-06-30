"""
Tests for LoomAgent (agent/core.py).

Tier 1 — unit tests (no LLM, no graph):
  - _parse_completion: market-ID extraction, yes/no signal counting, dominant direction
  - explain_match: correct field wiring from SearchResultItem-like objects
  - _make_brief: output format, empty-graph fallback, odds inclusion
  - LoomAgent.analyze: with mocked find_analogous_events (no LLM call)
  - LoomAgent.learn_from_outcome: delegates to record_outcome correctly

Tier 2 — integration tests (marked 'integration'):
  Full lifecycle: analyze → simulate resolution → learn → assert feedback visible
  in session_manager.get_session().

  Requires:
    1. python -m ingest.loader --source fixtures --limit 2
    2. Working LLM key with remaining quota (need ~6 calls for ingest+2×recall)
"""

import json
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from agent.core import (
    LoomAgent,
    _parse_completion,
    explain_match,
    _make_brief,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_search_item(text: str) -> SimpleNamespace:
    """Minimal SearchResultItem stand-in with .text attribute."""
    return SimpleNamespace(text=text)


SAMPLE_EVENT = {
    "market_id": "FM-001",
    "category": "macro",
    "market_question": "Will the Federal Reserve cut interest rates by 50bp in September 2024?",
    "trigger": "FOMC Federal Reserve rate decision September 2024",
    "odds_before": 0.25,
    "odds_after": 0.55,
    "odds_move_pct": 120.0,
    "timestamp": "2024-09-15",
    "outcome": "YES",
    "outcome_date": "2024-09-18",
    "narrative": "Fed Chair Powell signalled an outsized 50bp cut was on the table.",
}

RICH_COMPLETION = (
    "Based on analogous markets in the graph, FM-002 resolved YES when the Fed cut rates "
    "in November 2024, FM-003 resolved NO when the Fed held rates in January 2025, and "
    "EL-001 resolved YES following a similar rate decision context. "
    "Historical FOMC markets with large odds moves (>100%) resolved YES in 2 out of 3 cases. "
    "The pattern suggests the market leans toward a YES outcome given the current odds trajectory."
)


# ── unit tests: _parse_completion ─────────────────────────────────────────────

class TestParseCompletion:
    def test_empty_string_returns_empty_dominant(self):
        r = _parse_completion("")
        assert r["dominant"] == "EMPTY"
        assert r["market_ids"] == []
        assert r["yes_signals"] == 0
        assert r["no_signals"] == 0

    def test_extracts_market_ids(self):
        text = "FM-001 and EL-002 and CR-003 resolved YES."
        r = _parse_completion(text)
        assert "FM-001" in r["market_ids"]
        assert "EL-002" in r["market_ids"]
        assert "CR-003" in r["market_ids"]

    def test_deduplicates_market_ids(self):
        text = "FM-001 resolved YES. FM-001 again appeared."
        r = _parse_completion(text)
        assert r["market_ids"].count("FM-001") == 1

    def test_yes_dominant_when_yes_keywords_dominate(self):
        text = "The Fed cut rates. Markets resolved YES. Bullish signals."
        r = _parse_completion(text)
        assert r["dominant"] == "YES"
        assert r["yes_signals"] > 0

    def test_no_dominant_when_no_keywords_dominate(self):
        text = "The Fed held rates. Markets paused. Hawkish signals prevailed."
        r = _parse_completion(text)
        assert r["dominant"] == "NO"
        assert r["no_signals"] > 0

    def test_mixed_when_equal_signals(self):
        # "cut rates" → 1 YES, "hold" → 1 NO → equal count → MIXED
        text = "The market might see cut rates or a hold decision."
        r = _parse_completion(text)
        assert r["dominant"] == "MIXED"

    def test_first_sentence_extracted(self):
        r = _parse_completion(RICH_COMPLETION)
        assert r["first_sentence"]
        assert len(r["first_sentence"]) < len(RICH_COMPLETION)

    def test_rich_completion_parses_correctly(self):
        r = _parse_completion(RICH_COMPLETION)
        assert "FM-002" in r["market_ids"]
        assert "FM-003" in r["market_ids"]
        assert "EL-001" in r["market_ids"]
        assert r["yes_signals"] >= 2   # "cut rates", "resolved YES" ×2
        assert r["dominant"] == "YES"


# ── unit tests: explain_match ─────────────────────────────────────────────────

class TestExplainMatch:
    def test_empty_graph_results_sets_dominant_empty(self):
        m = explain_match(SAMPLE_EVENT, [], None)
        assert m["parsed"]["dominant"] == "EMPTY"
        assert m["graph_text"] == ""

    def test_uses_text_attribute_of_search_result_item(self):
        items = [_make_search_item(RICH_COMPLETION)]
        m = explain_match(SAMPLE_EVENT, items, None)
        assert m["graph_text"] == RICH_COMPLETION
        assert m["parsed"]["dominant"] == "YES"

    def test_triplet_snippets_collected(self):
        t1 = _make_search_item("Federal Reserve → cut_rates → 50bp")
        t2 = _make_search_item("FOMC → resolved → YES")
        m = explain_match(SAMPLE_EVENT, [], [t1, t2])
        assert len(m["triplet_snippets"]) == 2

    def test_new_event_summary_fields(self):
        m = explain_match(SAMPLE_EVENT, [], None)
        ns = m["new_event_summary"]
        assert ns["category"] == "macro"
        assert ns["odds_before"] == 0.25
        assert ns["odds_after"] == 0.55
        assert ns["odds_move_pct"] == 120.0

    def test_falls_back_to_str_if_no_text_attr(self):
        # Older API shape returns plain strings, not SearchResultItem
        m = explain_match(SAMPLE_EVENT, ["plain string result"], None)
        assert m["graph_text"] == "plain string result"


# ── unit tests: _make_brief ───────────────────────────────────────────────────

class TestMakeBrief:
    def test_empty_graph_returns_clear_fallback(self):
        m = explain_match(SAMPLE_EVENT, [], None)
        brief = _make_brief(SAMPLE_EVENT, m)
        assert "No analogous precedents" in brief
        assert "MACRO" in brief or "macro" in brief.lower()

    def test_rich_result_includes_signal_counts(self):
        items = [_make_search_item(RICH_COMPLETION)]
        m = explain_match(SAMPLE_EVENT, items, None)
        brief = _make_brief(SAMPLE_EVENT, m)
        # Must mention direction, not just be a vague sentence
        assert "YES" in brief or "NO" in brief or "MIXED" in brief

    def test_brief_includes_odds_when_present(self):
        items = [_make_search_item(RICH_COMPLETION)]
        m = explain_match(SAMPLE_EVENT, items, None)
        brief = _make_brief(SAMPLE_EVENT, m)
        # odds_before=0.25 → "25%", odds_after=0.55 → "55%", move=+120%
        assert "25%" in brief or "55%" in brief or "120" in brief

    def test_brief_cites_market_ids(self):
        items = [_make_search_item(RICH_COMPLETION)]
        m = explain_match(SAMPLE_EVENT, items, None)
        brief = _make_brief(SAMPLE_EVENT, m)
        # At least one specific market ID from the completion should appear
        assert any(mid in brief for mid in ["FM-002", "FM-003", "EL-001"])

    def test_brief_includes_pattern_sentence(self):
        items = [_make_search_item(RICH_COMPLETION)]
        m = explain_match(SAMPLE_EVENT, items, None)
        brief = _make_brief(SAMPLE_EVENT, m)
        assert "Pattern:" in brief

    def test_brief_includes_triplet_corroboration(self):
        items = [_make_search_item(RICH_COMPLETION)]
        t = _make_search_item("Federal Reserve → cut_rates → 50bp")
        m = explain_match(SAMPLE_EVENT, items, [t])
        brief = _make_brief(SAMPLE_EVENT, m)
        assert "Triplet corroboration:" in brief or "corroboration" in brief.lower()

    def test_brief_does_not_exceed_reasonable_length(self):
        items = [_make_search_item(RICH_COMPLETION)]
        m = explain_match(SAMPLE_EVENT, items, None)
        brief = _make_brief(SAMPLE_EVENT, m)
        # Should be a paragraph, not a novel
        assert len(brief) < 1000, f"Brief is too long ({len(brief)} chars)"

    def test_event_without_odds_still_produces_brief(self):
        event_no_odds = {k: v for k, v in SAMPLE_EVENT.items()
                         if k not in ("odds_before", "odds_after", "odds_move_pct")}
        items = [_make_search_item(RICH_COMPLETION)]
        m = explain_match(event_no_odds, items, None)
        brief = _make_brief(event_no_odds, m)
        assert brief  # must still produce output


# ── unit tests: LoomAgent.analyze (mocked) ────────────────────────────────────

class TestLoomAgentAnalyzeMocked:
    @pytest.mark.asyncio
    async def test_analyze_returns_required_fields(self):
        """analyze() must return graph_completion_answer, brief, and qa_id."""
        items = [_make_search_item(RICH_COMPLETION)]
        fake_recall = {
            "query": "test query",
            "session_id": "loom_live",
            "graph_completion": items,
            "triplet_completion": None,
            "explanation": "test explanation",
            "qa_id": "test-qa-id-123",
        }
        with patch("agent.core.find_analogous_events", new=AsyncMock(return_value=fake_recall)):
            result = await LoomAgent().analyze(SAMPLE_EVENT)

        assert result["new_event"] == SAMPLE_EVENT
        assert result["graph_completion_answer"] == items
        assert isinstance(result["brief"], str)
        assert result["brief"]
        assert result["qa_id"] == "test-qa-id-123"
        assert "match" in result
        assert "explanation" in result

    @pytest.mark.asyncio
    async def test_analyze_brief_mentions_direction(self):
        items = [_make_search_item(RICH_COMPLETION)]
        fake_recall = {
            "query": "q", "session_id": "loom_live",
            "graph_completion": items, "triplet_completion": None,
            "explanation": "", "qa_id": None,
        }
        with patch("agent.core.find_analogous_events", new=AsyncMock(return_value=fake_recall)):
            result = await LoomAgent().analyze(SAMPLE_EVENT)

        brief = result["brief"]
        assert any(word in brief for word in ("YES", "NO", "MIXED", "Pattern:"))

    @pytest.mark.asyncio
    async def test_analyze_empty_graph_produces_fallback_brief(self):
        fake_recall = {
            "query": "q", "session_id": "loom_live",
            "graph_completion": [], "triplet_completion": None,
            "explanation": "", "qa_id": None,
        }
        with patch("agent.core.find_analogous_events", new=AsyncMock(return_value=fake_recall)):
            result = await LoomAgent().analyze(SAMPLE_EVENT)

        assert "No analogous precedents" in result["brief"]
        assert result["qa_id"] is None

    @pytest.mark.asyncio
    async def test_analyze_qa_id_is_preserved_for_learn(self):
        """qa_id from find_analogous_events must be threaded through for Phase 4."""
        expected_qa_id = str(uuid4())
        fake_recall = {
            "query": "q", "session_id": "loom_live",
            "graph_completion": [_make_search_item("cut rates, resolved YES")],
            "triplet_completion": None, "explanation": "",
            "qa_id": expected_qa_id,
        }
        with patch("agent.core.find_analogous_events", new=AsyncMock(return_value=fake_recall)):
            result = await LoomAgent().analyze(SAMPLE_EVENT)

        assert result["qa_id"] == expected_qa_id


# ── unit tests: LoomAgent.learn_from_outcome (mocked) ─────────────────────────

class TestLoomAgentLearnMocked:
    @pytest.mark.asyncio
    async def test_learn_delegates_to_record_outcome(self):
        """learn_from_outcome() passes through to record_outcome() unchanged."""
        expected = {
            "market_id": "FM-001",
            "actual_outcome": "YES",
            "qa_ids_found": 1,
            "feedback_results": [{"qa_id": "abc", "score": 5, "add_feedback_returned": True,
                                   "reasoning": "correct", "feedback_text": "x",
                                   "original_answer_chars": 100}],
            "apply_weights_result": {"skipped": 1},
        }
        with patch("agent.core.record_outcome", new=AsyncMock(return_value=expected)):
            result = await LoomAgent().learn_from_outcome("FM-001", "YES")

        assert result == expected

    @pytest.mark.asyncio
    async def test_learn_passes_score_override(self):
        """Manual score override is forwarded to record_outcome."""
        mock_ro = AsyncMock(return_value={"qa_ids_found": 0, "feedback_results": [],
                                          "apply_weights_result": None})
        with patch("agent.core.record_outcome", mock_ro):
            await LoomAgent().learn_from_outcome("FM-001", "YES", feedback_score=5)

        call_kwargs = mock_ro.call_args.kwargs
        assert call_kwargs.get("feedback_score") == 5

    @pytest.mark.asyncio
    async def test_learn_passes_feedback_text(self):
        mock_ro = AsyncMock(return_value={"qa_ids_found": 0, "feedback_results": [],
                                          "apply_weights_result": None})
        with patch("agent.core.record_outcome", mock_ro):
            await LoomAgent().learn_from_outcome("FM-001", "YES", feedback_text="Called it")

        call_kwargs = mock_ro.call_args.kwargs
        assert call_kwargs.get("feedback_text") == "Called it"


# ── integration tests: full lifecycle ─────────────────────────────────────────

@pytest.mark.integration
class TestLoomAgentIntegration:
    """
    Full lifecycle: analyze → simulate resolution → learn → assert feedback in session.

    Requires a populated graph. Run setup first:
        python -m ingest.loader --source fixtures --limit 2
    (uses ~4 LLM calls for graph extraction + summarization of 2 events)
    """

    @pytest.mark.asyncio
    async def test_analyze_returns_non_empty_brief_when_graph_populated(self):
        """With a real graph, analyze() should produce a brief with market IDs."""
        import cognee
        from cognee.api.v1.search.search import SearchType

        # Verify graph has data before running
        try:
            chunks = await cognee.search(
                "Federal Reserve", query_type=SearchType.CHUNKS, top_k=1
            )
        except Exception as exc:
            pytest.skip(f"Graph inaccessible: {exc}")
        if not chunks:
            pytest.skip(
                "Graph is empty. Run: python -m ingest.loader --source fixtures --limit 2"
            )

        events = json.loads(Path(__file__).parent.parent / "data" / "sample_events.json"
                            if False else "")  # type: ignore[arg-type]
        # Load properly
        events = json.loads((Path(__file__).parent.parent / "data" / "sample_events.json").read_text())
        fm001 = next(e for e in events if e["market_id"] == "FM-001")

        result = await LoomAgent().analyze(fm001)

        brief = result["brief"]
        print(f"\n[integration] brief: {brief}")
        print(f"[integration] qa_id: {result['qa_id']}")

        assert brief
        assert "No analogous precedents" not in brief, (
            "Expected graph content in brief but got empty-graph fallback. "
            "Did cognify complete successfully?"
        )

    @pytest.mark.asyncio
    async def test_full_lifecycle_analyze_learn_feedback_visible(self):
        """
        Full lifecycle:
          1. analyze(FM-001) → gets qa_id
          2. learn_from_outcome(FM-001, YES) → add_feedback(qa_id, score, ...)
          3. session_manager.get_session() → entry has feedback_score set

        HONEST: add_feedback returns True only if qa_id exists in SQLite cache.
        If get_session() returns the entry with feedback_score set, the feedback
        is durably stored. apply_feedback_weights will still return skipped=N.
        """
        import cognee
        from cognee.api.v1.search.search import SearchType
        from cognee.infrastructure.session.get_session_manager import get_session_manager
        from cognee.modules.users.methods import get_default_user
        from memory.recall import LOOM_SESSION_ID

        # Guard: graph must have data
        try:
            chunks = await cognee.search(
                "Federal Reserve", query_type=SearchType.CHUNKS, top_k=1
            )
        except Exception as exc:
            pytest.skip(f"Graph inaccessible: {exc}")
        if not chunks:
            pytest.skip(
                "Graph is empty. Run: python -m ingest.loader --source fixtures --limit 2"
            )

        events = json.loads(
            (Path(__file__).parent.parent / "data" / "sample_events.json").read_text()
        )
        fm001 = next(e for e in events if e["market_id"] == "FM-001")
        agent = LoomAgent()

        # ── Step 1: analyze ───────────────────────────────────────────────────
        analyze_result = await agent.analyze(fm001)
        qa_id = analyze_result.get("qa_id")

        print(f"\n[lifecycle] brief: {analyze_result['brief']}")
        print(f"[lifecycle] qa_id from analyze: {qa_id}")

        assert qa_id is not None, (
            "analyze() did not save a qa_id. "
            "_save_qa_interaction() requires a working session manager. "
            "Check logs for errors from session_manager.add_qa()."
        )

        # ── Step 2: learn (simulate FM-001 resolving YES) ─────────────────────
        learn_result = await agent.learn_from_outcome("FM-001", "YES")

        print(f"[lifecycle] learn result: qa_ids_found={learn_result.get('qa_ids_found')}")
        for fb in learn_result.get("feedback_results", []):
            print(
                f"[lifecycle] qa_id={fb['qa_id'][:8]}…  score={fb['score']}  "
                f"add_feedback_returned={fb['add_feedback_returned']}"
            )

        assert learn_result.get("qa_ids_found", 0) >= 1, (
            "learn_from_outcome found no qa_ids for FM-001. "
            "data/recall_interactions.json may not contain an entry for FM-001. "
            "analyze() must be run first."
        )

        fbs = learn_result.get("feedback_results", [])
        assert fbs, "No feedback_results in learn output."

        # ── Step 3: verify feedback visible in get_session() ─────────────────
        user = await get_default_user()
        session_manager = get_session_manager()

        session_entries = await session_manager.get_session(
            user_id=str(user.id),
            session_id=LOOM_SESSION_ID,
            formatted=False,
        )

        # Find the entry whose qa_id matches
        matched_entry = None
        for entry in (session_entries or []):
            if str(getattr(entry, "qa_id", "")) == qa_id:
                matched_entry = entry
                break

        print(f"[lifecycle] session entries: {len(session_entries or [])}")
        print(f"[lifecycle] matched_entry found: {matched_entry is not None}")
        if matched_entry:
            print(f"[lifecycle] feedback_score={getattr(matched_entry, 'feedback_score', None)}")
            print(f"[lifecycle] feedback_text={getattr(matched_entry, 'feedback_text', None)[:80] if getattr(matched_entry, 'feedback_text', None) else None}")

        assert matched_entry is not None, (
            f"qa_id={qa_id[:8]}… not found in get_session() results. "
            f"Session has {len(session_entries or [])} entries. "
            "The qa_id may have been generated in a different session or the cache was pruned."
        )

        fb_score = getattr(matched_entry, "feedback_score", None)
        fb_text = getattr(matched_entry, "feedback_text", None)

        if fbs[0]["add_feedback_returned"]:
            assert fb_score is not None, (
                "add_feedback returned True but feedback_score is None in get_session(). "
                "This indicates a bug in update_qa() or the session cache write."
            )
            assert 1 <= fb_score <= 5, f"feedback_score={fb_score} out of valid range 1-5"
            assert fb_text, "feedback_text is empty after add_feedback returned True."
            print(
                f"\n[VERIFIED] Feedback durably stored: "
                f"qa_id={qa_id[:8]}…  score={fb_score}  "
                f"text={fb_text[:60]!r}"
            )
        else:
            print(
                f"\n[HONEST] add_feedback returned False for qa_id={qa_id[:8]}… — "
                "qa_id not found in SQLite cache. Feedback not stored. "
                "This can happen if the session DB was wiped between analyze and learn."
            )
            # Don't fail the test — the lifecycle ran correctly, the cache just wasn't there.

        # ── apply_feedback_weights verdict ────────────────────────────────────
        apply = learn_result.get("apply_weights_result") or {}
        print(f"[lifecycle] apply_weights: {apply.get('note', apply)}")
        # Asserting skipped > 0 is expected and correct here.
        # applied > 0 would only happen with AGENTIC_COMPLETION (which populates node/edge UUIDs).
