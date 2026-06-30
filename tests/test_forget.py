"""
Tests for the forgetting/pruning layer (memory/forget.py).

Tier 1 — unit tests (no API key, no graph, no Cognee I/O):
  - find_stale_candidates: scoring threshold logic, min_feedbacks guard
  - _content_hash: matches Cognee's TextData.get_metadata() MD5 scheme
  - prune_stale_events: with mocked dataset + data lookup

Tier 2 — integration tests (marked 'integration'):
  - Require a populated graph and data records in the DB
  - Verify actual deletion via list_data() and recall()

HONEST NOTE on deletion granularity:
  The real cognee.forget(data_id, dataset_id) removes:
    - The Data record (SQLite)
    - Graph nodes UNIQUE to this data item
    - Vector embeddings for those unique nodes
  It does NOT remove:
    - Nodes shared with other surviving data items
    - The dataset itself (delete_dataset_if_empty=False by default)
  Tests assert on what actually changes, not on a theoretical full wipe.
"""

import hashlib
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from ingest.loader import event_to_text
from memory.forget import (
    find_stale_candidates,
    _content_hash,
    prune_stale_events,
    _FEEDBACK_LOG,
    _PRUNE_LOG,
    DATASET_NAME,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_EVENT = {
    "market_id": "FM-001",
    "category": "macro",
    "market_question": "Will the Fed cut rates by 25bp in September 2024?",
    "trigger": "FOMC meeting",
    "timestamp": "2024-09-15",
    "outcome": "YES",
    "outcome_date": "2024-09-18",
    "narrative": "The Fed cut rates 25bp at the September 2024 FOMC meeting.",
    "odds_before": 0.72,
    "odds_after": 0.95,
    "odds_move_pct": 31.9,
}

SAMPLE_FEEDBACK_ENTRIES = [
    {"market_id": "FM-001", "score": 1, "actual_outcome": "YES"},
    {"market_id": "FM-001", "score": 2, "actual_outcome": "YES"},
    {"market_id": "FM-002", "score": 4, "actual_outcome": "NO"},
    {"market_id": "FM-002", "score": 5, "actual_outcome": "NO"},
    {"market_id": "CR-001", "score": 1, "actual_outcome": "YES"},
    {"market_id": "CR-001", "score": 1, "actual_outcome": "NO"},
    {"market_id": "CR-001", "score": 2, "actual_outcome": "NO"},
]


def _write_feedback(tmp_path: Path, entries: list[dict]) -> Path:
    f = tmp_path / "feedback_log.jsonl"
    with open(f, "w") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")
    return f


# ── unit tests: find_stale_candidates ────────────────────────────────────────

class TestFindStaleCandidates:
    def test_empty_log_returns_no_candidates(self, tmp_path, monkeypatch):
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", tmp_path / "nonexistent.jsonl")
        result = find_stale_candidates()
        assert result == []

    def test_high_scoring_events_not_stale(self, tmp_path, monkeypatch):
        f = _write_feedback(tmp_path, [
            {"market_id": "FM-002", "score": 4},
            {"market_id": "FM-002", "score": 5},
        ])
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", f)
        result = find_stale_candidates(max_score=2, min_feedbacks=2)
        assert all(c["market_id"] != "FM-002" for c in result)

    def test_low_scoring_event_is_stale(self, tmp_path, monkeypatch):
        f = _write_feedback(tmp_path, [
            {"market_id": "FM-001", "score": 1},
            {"market_id": "FM-001", "score": 2},
        ])
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", f)
        result = find_stale_candidates(max_score=2, min_feedbacks=2)
        assert len(result) == 1
        assert result[0]["market_id"] == "FM-001"
        assert result[0]["avg_score"] == 1.5
        assert result[0]["feedback_count"] == 2

    def test_min_feedbacks_guard(self, tmp_path, monkeypatch):
        """An event with only 1 feedback entry is never stale regardless of score."""
        f = _write_feedback(tmp_path, [{"market_id": "FM-001", "score": 1}])
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", f)
        result = find_stale_candidates(max_score=2, min_feedbacks=2)
        assert result == []

    def test_mixed_log_returns_only_stale(self, tmp_path, monkeypatch):
        f = _write_feedback(tmp_path, SAMPLE_FEEDBACK_ENTRIES)
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", f)
        result = find_stale_candidates(max_score=2, min_feedbacks=2)
        stale_ids = {c["market_id"] for c in result}
        assert "FM-001" in stale_ids   # avg=1.5, count=2 → stale
        assert "CR-001" in stale_ids   # avg=1.33, count=3 → stale
        assert "FM-002" not in stale_ids  # avg=4.5 → not stale

    def test_candidates_sorted_by_avg_score_ascending(self, tmp_path, monkeypatch):
        f = _write_feedback(tmp_path, SAMPLE_FEEDBACK_ENTRIES)
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", f)
        result = find_stale_candidates(max_score=2, min_feedbacks=2)
        scores = [c["avg_score"] for c in result]
        assert scores == sorted(scores)

    def test_reason_field_present_and_informative(self, tmp_path, monkeypatch):
        f = _write_feedback(tmp_path, [
            {"market_id": "FM-001", "score": 1},
            {"market_id": "FM-001", "score": 1},
        ])
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", f)
        result = find_stale_candidates()
        assert result[0]["reason"]
        assert "false-positive" in result[0]["reason"] or "avg_score" in result[0]["reason"]


# ── unit tests: _content_hash ─────────────────────────────────────────────────

class TestContentHash:
    def test_matches_cognee_texdata_scheme(self):
        """
        Cognee TextData.get_metadata() sets content_hash = md5(text.encode("utf-8")).hexdigest().
        _content_hash() must produce the same value so we can match Data records.
        """
        text = event_to_text(SAMPLE_EVENT)
        expected = hashlib.md5(text.encode("utf-8")).hexdigest()
        assert _content_hash(SAMPLE_EVENT) == expected

    def test_different_events_different_hashes(self):
        other = {**SAMPLE_EVENT, "market_id": "FM-002", "narrative": "Different narrative text."}
        assert _content_hash(SAMPLE_EVENT) != _content_hash(other)

    def test_same_event_same_hash(self):
        assert _content_hash(SAMPLE_EVENT) == _content_hash(SAMPLE_EVENT)

    def test_hash_is_32_hex_chars(self):
        h = _content_hash(SAMPLE_EVENT)
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)


# ── unit tests: prune_stale_events (mocked) ───────────────────────────────────

class TestPruneStaleEventsMocked:
    def _mock_data_item(self, content_hash: str) -> MagicMock:
        item = MagicMock()
        item.id = uuid4()
        item.content_hash = content_hash
        item.name = f"text_{content_hash}.txt"
        return item

    @pytest.mark.asyncio
    async def test_no_feedback_log_returns_empty_result(self, tmp_path, monkeypatch):
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", tmp_path / "missing.jsonl")
        result = await prune_stale_events(dry_run=True)
        assert result["candidates"] == []
        assert result["pruned"] == []

    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_cognee_forget(self, tmp_path, monkeypatch):
        f = _write_feedback(tmp_path, [
            {"market_id": "FM-001", "score": 1},
            {"market_id": "FM-001", "score": 1},
        ])
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", f)
        monkeypatch.setattr("memory.forget._PRUNE_LOG", tmp_path / "prune.jsonl")

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_dataset = MagicMock()
        mock_dataset.name = DATASET_NAME
        mock_dataset.id = uuid4()

        # Use SAMPLE_EVENT directly and point DATA_FILE at it
        fake_data_file = tmp_path / "events.json"
        fake_data_file.write_text(json.dumps([SAMPLE_EVENT]))
        monkeypatch.setattr("memory.forget.DATA_FILE", fake_data_file)

        matching_item = self._mock_data_item(_content_hash(SAMPLE_EVENT))
        forget_mock = AsyncMock()

        with (
            patch("memory.forget.cognee.datasets.list_datasets",
                  new=AsyncMock(return_value=[mock_dataset])),
            patch("memory.forget.cognee.datasets.list_data",
                  new=AsyncMock(return_value=[matching_item])),
            patch("memory.forget.cognee.forget", forget_mock),
            patch("cognee.modules.users.methods.get_default_user",
                  new=AsyncMock(return_value=mock_user)),
            patch("cognee.low_level.setup", new=AsyncMock()),
        ):
            result = await prune_stale_events(dry_run=True, min_feedbacks=2, max_score=2)

        forget_mock.assert_not_awaited()
        assert len(result["pruned"]) == 1
        assert result["pruned"][0]["dry_run"] is True

    @pytest.mark.asyncio
    async def test_commit_calls_cognee_forget(self, tmp_path, monkeypatch):
        f = _write_feedback(tmp_path, [
            {"market_id": "FM-001", "score": 1},
            {"market_id": "FM-001", "score": 2},
        ])
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", f)
        monkeypatch.setattr("memory.forget._PRUNE_LOG", tmp_path / "prune.jsonl")

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_dataset = MagicMock()
        mock_dataset.name = DATASET_NAME
        mock_dataset.id = uuid4()

        fm001_event = SAMPLE_EVENT
        matching_item = self._mock_data_item(_content_hash(fm001_event))

        forget_result = {"data_id": str(matching_item.id),
                         "dataset_id": str(mock_dataset.id), "status": "success"}
        forget_mock = AsyncMock(return_value=forget_result)

        # Patch DATA_FILE to use a minimal fixture with just FM-001
        fake_events = [fm001_event]
        fake_data_file = tmp_path / "events.json"
        fake_data_file.write_text(json.dumps(fake_events))
        monkeypatch.setattr("memory.forget.DATA_FILE", fake_data_file)

        with (
            patch("memory.forget.cognee.datasets.list_datasets",
                  new=AsyncMock(return_value=[mock_dataset])),
            patch("memory.forget.cognee.datasets.list_data",
                  new=AsyncMock(return_value=[matching_item])),
            patch("memory.forget.cognee.forget", forget_mock),
            patch("cognee.modules.users.methods.get_default_user",
                  new=AsyncMock(return_value=mock_user)),
            patch("cognee.low_level.setup", new=AsyncMock()),
        ):
            result = await prune_stale_events(dry_run=False, min_feedbacks=2, max_score=2)

        forget_mock.assert_awaited_once()
        call_kwargs = forget_mock.call_args.kwargs
        assert call_kwargs["data_id"] == matching_item.id
        assert call_kwargs["dataset_id"] == mock_dataset.id

        assert result["pruned"][0]["dry_run"] is False
        assert result["pruned"][0]["forget_result"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_prune_log_written_on_commit(self, tmp_path, monkeypatch):
        f = _write_feedback(tmp_path, [
            {"market_id": "FM-001", "score": 1},
            {"market_id": "FM-001", "score": 1},
        ])
        prune_log = tmp_path / "prune.jsonl"
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", f)
        monkeypatch.setattr("memory.forget._PRUNE_LOG", prune_log)

        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_dataset = MagicMock()
        mock_dataset.name = DATASET_NAME
        mock_dataset.id = uuid4()

        fake_events = [SAMPLE_EVENT]
        fake_data_file = tmp_path / "events.json"
        fake_data_file.write_text(json.dumps(fake_events))
        monkeypatch.setattr("memory.forget.DATA_FILE", fake_data_file)

        matching_item = self._mock_data_item(_content_hash(SAMPLE_EVENT))
        forget_mock = AsyncMock(return_value={"status": "success"})

        with (
            patch("memory.forget.cognee.datasets.list_datasets",
                  new=AsyncMock(return_value=[mock_dataset])),
            patch("memory.forget.cognee.datasets.list_data",
                  new=AsyncMock(return_value=[matching_item])),
            patch("memory.forget.cognee.forget", forget_mock),
            patch("cognee.modules.users.methods.get_default_user",
                  new=AsyncMock(return_value=mock_user)),
            patch("cognee.low_level.setup", new=AsyncMock()),
        ):
            await prune_stale_events(dry_run=False, min_feedbacks=2, max_score=2)

        assert prune_log.exists()
        entries = [json.loads(line) for line in prune_log.read_text().strip().splitlines()]
        assert len(entries) == 1
        e = entries[0]
        assert e["market_id"] == "FM-001"
        assert e["data_id"] == str(matching_item.id)
        assert e["dataset_id"] == str(mock_dataset.id)
        assert e["avg_score"] == 1.0
        assert "timestamp" in e
        assert "reason" in e

    @pytest.mark.asyncio
    async def test_no_dataset_found_returns_not_found(self, tmp_path, monkeypatch):
        """When the dataset doesn't exist, all candidates go to not_found."""
        f = _write_feedback(tmp_path, [
            {"market_id": "FM-001", "score": 1},
            {"market_id": "FM-001", "score": 1},
        ])
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", f)

        with (
            patch("memory.forget.cognee.datasets.list_datasets",
                  new=AsyncMock(return_value=[])),
            patch("cognee.modules.users.methods.get_default_user",
                  new=AsyncMock(return_value=MagicMock(id=uuid4()))),
            patch("cognee.low_level.setup", new=AsyncMock()),
        ):
            result = await prune_stale_events(dry_run=True, min_feedbacks=2, max_score=2)

        assert result["dataset_id"] is None
        assert result["pruned"] == []

    @pytest.mark.asyncio
    async def test_event_not_in_dataset_goes_to_not_found(self, tmp_path, monkeypatch):
        """When list_data returns no matching content_hash, event goes to not_found."""
        f = _write_feedback(tmp_path, [
            {"market_id": "FM-001", "score": 1},
            {"market_id": "FM-001", "score": 1},
        ])
        monkeypatch.setattr("memory.forget._FEEDBACK_LOG", f)

        mock_dataset = MagicMock()
        mock_dataset.name = DATASET_NAME
        mock_dataset.id = uuid4()

        fake_events = [SAMPLE_EVENT]
        fake_data_file = tmp_path / "events.json"
        fake_data_file.write_text(json.dumps(fake_events))
        monkeypatch.setattr("memory.forget.DATA_FILE", fake_data_file)

        # No items in dataset (empty list)
        with (
            patch("memory.forget.cognee.datasets.list_datasets",
                  new=AsyncMock(return_value=[mock_dataset])),
            patch("memory.forget.cognee.datasets.list_data",
                  new=AsyncMock(return_value=[])),
            patch("cognee.modules.users.methods.get_default_user",
                  new=AsyncMock(return_value=MagicMock(id=uuid4()))),
            patch("cognee.low_level.setup", new=AsyncMock()),
        ):
            result = await prune_stale_events(dry_run=True, min_feedbacks=2, max_score=2)

        assert "FM-001" in result["not_found"]
        assert result["pruned"] == []


# ── integration tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
class TestForgetIntegration:
    """
    Requires:
      1. python -m ingest.loader --source fixtures --limit 5
         (populates both Data records AND graph)
      2. python -m memory.recall FM-001  (or any market that resolves to a stale score)
      3. python -m memory.improve FM-001 YES --score 1  (twice, to hit min_feedbacks=2)
    """

    @pytest.mark.asyncio
    async def test_dry_run_shows_candidates_when_stale_feedback_exists(self):
        """
        With real feedback_log.jsonl containing stale entries:
          find_stale_candidates() returns them, prune_stale_events(dry_run=True)
          resolves their data_ids without deleting.
        """
        from memory.forget import find_stale_candidates, prune_stale_events, _FEEDBACK_LOG

        if not _FEEDBACK_LOG.exists():
            pytest.skip(
                "No feedback_log.jsonl — run memory.recall + memory.improve first. "
                "Then run memory.improve FM-001 YES --score 1 twice to create stale entry."
            )

        candidates = find_stale_candidates(min_feedbacks=2, max_score=2)
        if not candidates:
            pytest.skip(
                "No stale candidates in feedback_log. "
                "Need avg_score ≤ 2 across ≥ 2 feedback entries for at least one market."
            )

        result = await prune_stale_events(dry_run=True, min_feedbacks=2, max_score=2)
        print(f"\n[dry-run] candidates={result['candidates']}")
        print(f"[dry-run] dataset_id={result['dataset_id']}")
        print(f"[dry-run] pruned (would-be)={result['pruned']}")

        assert result["dry_run"] is True
        assert result["dataset_id"] is not None or len(result["not_found"]) > 0

    @pytest.mark.asyncio
    async def test_commit_then_verify_data_record_gone(self):
        """
        Commit deletion and verify via list_data() that data_id is absent.

        HONEST: if graph was never cognified, the recall_empty check is trivially
        True for all events and doesn't confirm deletion. Only the data_record_gone
        check is meaningful in that case.
        """
        from memory.forget import (
            prune_stale_events, verify_deletion, _FEEDBACK_LOG, find_stale_candidates
        )

        if not _FEEDBACK_LOG.exists():
            pytest.skip("No feedback_log.jsonl — run ingest + recall + improve first.")

        candidates = find_stale_candidates(min_feedbacks=2, max_score=2)
        if not candidates:
            pytest.skip("No stale candidates — need avg_score ≤ 2 with ≥ 2 feedbacks.")

        # Commit deletion
        result = await prune_stale_events(dry_run=False, min_feedbacks=2, max_score=2)
        print(f"\n[commit] pruned={result['pruned']}")
        print(f"[commit] not_found={result['not_found']}")

        actually_deleted = [p for p in result["pruned"] if "error" not in p and not p.get("dry_run")]

        if not actually_deleted:
            pytest.skip(
                "No events were actually deleted — all candidates had no data record. "
                "This is expected if ingest.loader add phase never completed."
            )

        # Verify the first deleted item is gone
        p = actually_deleted[0]
        v = await verify_deletion(p["market_id"], result["dataset_id"])
        print(f"\n[verify] data_record_gone={v['data_record_gone']}")
        print(f"[verify] recall_empty={v['recall_empty']}")
        print(f"[verify] recall_note={v['recall_note']}")

        assert v["data_record_gone"], (
            f"data_id for {p['market_id']} still present in list_data() after forget(). "
            "This means cognee.forget() did not delete the relational record."
        )
        # recall_empty is not asserted — it may be trivially True if graph was never built
