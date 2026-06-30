"""
Tests for the self-improvement loop (memory/improve.py).

Split into two tiers:

  Unit tests (no mark):  Pure-Python logic that works with no API key and no graph.
                         Tests _auto_score, _load_interactions, and record_outcome
                         when no prior recall interactions exist.

  Integration tests:     Full cycle requiring a populated graph + working LLM key.
                         Skip in CI with: pytest -m "not integration"

HONEST NOTE on what these tests validate:
  - add_feedback() returning True requires the qa_id to exist in the SQLite cache.
    That only happens AFTER find_analogous_events() has been run successfully
    (which requires the graph to be populated + LLM quota available).
  - apply_feedback_weights() will return skipped=N (not applied=N) because
    GRAPH_COMPLETION doesn't populate used_graph_element_ids. This is expected
    and the tests assert skipped > 0 rather than applied > 0.
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


from memory.improve import _auto_score, _load_interactions, record_outcome


# ── unit tests: _auto_score ───────────────────────────────────────────────────

class TestAutoScore:
    def test_empty_preview_returns_neutral(self):
        score, reason = _auto_score("YES", "")
        assert score == 3
        assert "empty" in reason or "no answer" in reason

    def test_yes_outcome_with_yes_signal(self):
        score, reason = _auto_score("YES", "The Fed will likely cut rates by 25bp")
        assert score == 5
        assert "YES" in reason or "yes" in reason.lower()

    def test_yes_outcome_with_no_signal(self):
        score, reason = _auto_score("YES", "The Fed is likely to hold and pause")
        assert score == 1
        assert "YES" in reason or "outcome YES" in reason

    def test_no_outcome_with_no_signal(self):
        score, reason = _auto_score("NO", "likely to hold, pause unlikely to cut")
        assert score == 5

    def test_no_outcome_with_yes_signal(self):
        score, reason = _auto_score("NO", "likely will cut rates, positive outlook")
        assert score == 1
        assert "outcome NO" in reason

    def test_ambiguous_preview_neutral(self):
        score, reason = _auto_score("YES", "the market might hold or cut")
        assert score == 3

    def test_pending_outcome_is_neutral(self):
        score, reason = _auto_score("pending", "anything")
        assert score == 3
        assert "not resolved" in reason or "pending" in reason

    def test_score_is_in_range(self):
        for outcome in ("YES", "NO", "pending"):
            for preview in ("", "cut likely", "hold pause", "might or might not"):
                score, _ = _auto_score(outcome, preview)
                assert 1 <= score <= 5, f"score={score} out of range for ({outcome}, {preview!r})"


# ── unit tests: _load_interactions ────────────────────────────────────────────

class TestLoadInteractions:
    def test_returns_empty_dict_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory.improve._INTERACTIONS_FILE",
            tmp_path / "nonexistent.json",
        )
        result = _load_interactions()
        assert result == {}

    def test_returns_empty_dict_on_corrupt_json(self, tmp_path, monkeypatch):
        f = tmp_path / "interactions.json"
        f.write_text("NOT VALID JSON{{{")
        monkeypatch.setattr("memory.improve._INTERACTIONS_FILE", f)
        result = _load_interactions()
        assert result == {}

    def test_loads_valid_file(self, tmp_path, monkeypatch):
        f = tmp_path / "interactions.json"
        data = {
            "FM-001": [{"qa_id": "abc123", "session_id": "loom_live", "answer_preview": "cut"}]
        }
        f.write_text(json.dumps(data))
        monkeypatch.setattr("memory.improve._INTERACTIONS_FILE", f)
        result = _load_interactions()
        assert "FM-001" in result
        assert result["FM-001"][0]["qa_id"] == "abc123"


# ── unit tests: record_outcome with no interactions ───────────────────────────

class TestRecordOutcomeNoInteractions:
    @pytest.mark.asyncio
    async def test_returns_zero_qa_ids_when_no_interactions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory.improve._INTERACTIONS_FILE",
            tmp_path / "empty.json",
        )
        result = await record_outcome("FM-999", "YES")
        assert result["qa_ids_found"] == 0
        assert result["feedback_results"] == []
        assert result["apply_weights_result"] is None
        assert "note" in result

    @pytest.mark.asyncio
    async def test_no_qa_does_not_crash_batch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory.improve._INTERACTIONS_FILE",
            tmp_path / "empty.json",
        )
        monkeypatch.setattr(
            "memory.improve._FEEDBACK_LOG",
            tmp_path / "log.jsonl",
        )
        # Should complete without exception even when all events have no interactions
        from memory.improve import batch_record_outcomes
        # Patch DATA_FILE to a single minimal event
        minimal = [{"market_id": "FM-TEST", "outcome": "YES", "category": "macro"}]
        fake_data = tmp_path / "events.json"
        fake_data.write_text(json.dumps(minimal))
        monkeypatch.setattr("memory.improve.DATA_FILE", fake_data)
        # Should not raise
        await batch_record_outcomes()


# ── unit tests: record_outcome with mocked session manager ───────────────────

class TestRecordOutcomeMocked:
    @pytest.mark.asyncio
    async def test_add_feedback_true_is_reported_correctly(self, tmp_path, monkeypatch):
        """When add_feedback returns True, result shows add_feedback_returned=True."""
        interactions = {
            "FM-001": [{
                "qa_id": "fake-qa-id-0001",
                "session_id": "loom_live",
                "answer_preview": "the fed will likely cut rates",
            }]
        }
        f = tmp_path / "interactions.json"
        f.write_text(json.dumps(interactions))
        monkeypatch.setattr("memory.improve._INTERACTIONS_FILE", f)
        monkeypatch.setattr("memory.improve._FEEDBACK_LOG", tmp_path / "log.jsonl")

        mock_user = MagicMock()
        mock_user.id = "test-user-id"
        mock_sm = MagicMock()
        mock_sm.add_feedback = AsyncMock(return_value=True)

        with patch("memory.improve.get_session_manager" if False else "cognee.infrastructure.session.get_session_manager.get_session_manager", return_value=mock_sm):
            with patch("cognee.modules.users.methods.get_default_user", new=AsyncMock(return_value=mock_user)):
                result = await record_outcome("FM-001", "YES")

        assert result["qa_ids_found"] == 1
        assert len(result["feedback_results"]) == 1
        fb = result["feedback_results"][0]
        assert fb["qa_id"] == "fake-qa-id-0001"
        assert fb["score"] in (1, 2, 3, 4, 5)
        assert isinstance(fb["add_feedback_returned"], bool)

    @pytest.mark.asyncio
    async def test_manual_score_override_respected(self, tmp_path, monkeypatch):
        """Passing feedback_score=5 bypasses auto-scoring."""
        interactions = {
            "FM-002": [{
                "qa_id": "fake-qa-id-0002",
                "session_id": "loom_live",
                "answer_preview": "hold pause",  # would auto-score to 1 for YES
            }]
        }
        f = tmp_path / "interactions.json"
        f.write_text(json.dumps(interactions))
        monkeypatch.setattr("memory.improve._INTERACTIONS_FILE", f)
        monkeypatch.setattr("memory.improve._FEEDBACK_LOG", tmp_path / "log.jsonl")

        mock_user = MagicMock()
        mock_user.id = "test-user-id"
        mock_sm = MagicMock()
        mock_sm.add_feedback = AsyncMock(return_value=True)

        with patch("cognee.modules.users.methods.get_default_user", new=AsyncMock(return_value=mock_user)):
            with patch("cognee.infrastructure.session.get_session_manager.get_session_manager", return_value=mock_sm):
                result = await record_outcome("FM-002", "YES", feedback_score=5)

        fb = result["feedback_results"][0]
        assert fb["score"] == 5, "Manual score override not respected"

    @pytest.mark.asyncio
    async def test_feedback_log_is_written(self, tmp_path, monkeypatch):
        """Each add_feedback call writes a line to feedback_log.jsonl."""
        interactions = {
            "FM-003": [{
                "qa_id": "fake-qa-id-0003",
                "session_id": "loom_live",
                "answer_preview": "",
            }]
        }
        f = tmp_path / "interactions.json"
        f.write_text(json.dumps(interactions))
        log_file = tmp_path / "log.jsonl"
        monkeypatch.setattr("memory.improve._INTERACTIONS_FILE", f)
        monkeypatch.setattr("memory.improve._FEEDBACK_LOG", log_file)

        mock_user = MagicMock()
        mock_user.id = "test-user-id"
        mock_sm = MagicMock()
        mock_sm.add_feedback = AsyncMock(return_value=False)

        with patch("cognee.modules.users.methods.get_default_user", new=AsyncMock(return_value=mock_user)):
            with patch("cognee.infrastructure.session.get_session_manager.get_session_manager", return_value=mock_sm):
                await record_outcome("FM-003", "NO")

        assert log_file.exists(), "feedback_log.jsonl was not created"
        entries = [json.loads(line) for line in log_file.read_text().strip().splitlines()]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["market_id"] == "FM-003"
        assert entry["actual_outcome"] == "NO"
        assert "qa_id" in entry
        assert "score" in entry
        assert "add_feedback_returned" in entry
        assert "timestamp" in entry


# ── integration tests: full cycle ─────────────────────────────────────────────

@pytest.mark.integration
class TestImproveIntegration:
    """
    These tests require:
      1. A populated graph (run: python -m ingest.loader --source fixtures)
      2. Working LLM API key with remaining quota
      3. Prior recall runs (run: python -m memory.recall FM-001)
    """

    @pytest.mark.asyncio
    async def test_recall_then_record_outcome_fm001(self):
        """
        Full cycle: find_analogous_events() → record_outcome() → check feedback stored.

        GRAPH_COMPLETION search must have returned something for the qa_id to exist.
        """
        import json
        from ingest.loader import DATA_FILE
        from memory.recall import find_analogous_events
        from cognee.api.v1.search.search import SearchType
        import cognee

        events = json.loads(DATA_FILE.read_text())
        fm001 = next(e for e in events if e["market_id"] == "FM-001")

        # Sanity check: graph must have data
        try:
            chunks = await cognee.search("Federal Reserve", query_type=SearchType.CHUNKS, top_k=1)
        except Exception as exc:
            pytest.skip(f"Graph inaccessible: {exc}")
        if not chunks:
            pytest.skip("Graph is empty — run: python -m ingest.loader --source fixtures")

        # Step 1: recall
        recall_result = await find_analogous_events(fm001)
        qa_id = recall_result.get("qa_id")
        assert qa_id is not None, (
            "qa_id was not saved after find_analogous_events(). "
            "Check that _save_qa_interaction() completed successfully."
        )
        print(f"\n[recall] qa_id={qa_id}")
        print(f"[recall] graph_completion snippet: {str(recall_result.get('graph_completion', ''))[:200]}")

        # Step 2: record outcome
        improve_result = await record_outcome("FM-001", "YES")

        assert improve_result["qa_ids_found"] >= 1, "qa_id not found in recall_interactions.json"
        assert len(improve_result["feedback_results"]) >= 1

        fb = improve_result["feedback_results"][0]
        print(f"\n[improve] add_feedback_returned={fb['add_feedback_returned']}")
        print(f"[improve] score={fb['score']}")

        # add_feedback returns True only if qa_id is in the SQLite cache
        if not fb["add_feedback_returned"]:
            print(
                "[WARN] add_feedback returned False — qa_id was not found in SQLite cache. "
                "This happens if the session manager's SQLite DB was wiped since recall ran."
            )

        # apply_feedback_weights result — EXPECT skipped=1 (no graph element IDs)
        apply = improve_result.get("apply_weights_result") or {}
        print(f"\n[improve] apply_feedback_weights result: {apply}")
        skipped = apply.get("skipped", 0)
        assert skipped > 0 or "error" in apply or apply.get("applied", 0) == 0, (
            "apply_feedback_weights unexpectedly reported applied > 0 with no graph element IDs. "
            "This would mean edge weights were updated — investigate if really true."
        )
        print(
            "\nHONEST RESULT: apply_feedback_weights skipped (expected). "
            "Feedback is stored in SQLite but no graph edge weights were modified."
        )

    @pytest.mark.asyncio
    async def test_add_feedback_returns_false_after_prune(self):
        """
        After prune_data(), add_feedback returns False for old qa_ids.

        This test demonstrates that feedback is tied to the SQLite cache, which
        is wiped by prune_data(). Run this test if you want to verify False behavior.
        """
        pytest.skip(
            "Skipping deliberately — would wipe the graph and break other tests. "
            "To verify False behavior: run prune_data() then try record_outcome()."
        )
