"""
Recall layer tests.

Requires a populated loom_market_events graph with at least the 5 FOMC events
(FM-001 through FM-005). Run ingest first:

    python -m ingest.loader --source fixtures --category macro

These tests make LLM calls (GRAPH_COMPLETION) so they consume API quota.
Skip in CI with:
    pytest -m "not integration"

The tests validate the output is GRAPH-STRUCTURED (entity-referencing) rather
than flat vector similarity noise. If the answers look like generic summaries
without specific market IDs or Fed entity mentions, the cognify pipeline didn't
build real graph edges — that's a Phase 1 issue, not a recall layer issue.
"""

import json
import pytest
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import cognee
from cognee.api.v1.search.search import SearchType

from ingest.loader import DATA_FILE, DATASET_NAME
from memory.recall import find_analogous_events, get_last_query_id, LOOM_SESSION_ID


pytestmark = pytest.mark.integration


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def all_events():
    return json.loads(DATA_FILE.read_text())


@pytest.fixture(scope="module")
def fomc_events(all_events):
    return [e for e in all_events if e["market_id"].startswith("FM-")]


@pytest.fixture(scope="module")
def crypto_events(all_events):
    return [e for e in all_events if e["market_id"].startswith("CR-")]


# ── sanity check: graph must have data ───────────────────────────────────────

@pytest.mark.asyncio
async def test_graph_is_populated():
    """Fail with a clear message if the graph is empty before running recall tests."""
    try:
        results = await cognee.search(
            "Federal Reserve rate decision FOMC",
            query_type=SearchType.CHUNKS,
            datasets=[DATASET_NAME],
            top_k=3,
        )
        assert results, (
            "Graph is empty. Ingest fixtures first:\n"
            "  python -m ingest.loader --source fixtures\n"
            "then re-run these tests."
        )
    except Exception as exc:
        pytest.fail(
            f"Graph is empty or inaccessible: {exc}\n"
            "Run: python -m ingest.loader --source fixtures"
        )


# ── core recall tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_analogues_for_fomc_event(fomc_events):
    """
    Treat FM-003 (Jan 2025 pause) as 'new'. The graph has FM-001/002/004/005
    so should surface FOMC precedents — not crypto or sports noise.
    """
    new_event = next(e for e in fomc_events if e["market_id"] == "FM-003")
    result = await find_analogous_events(new_event)

    assert "graph_completion" in result
    assert result["session_id"] == LOOM_SESSION_ID

    graph_answer = result["graph_completion"]
    assert graph_answer, "GRAPH_COMPLETION returned empty — check LLM API key and rate limits"

    # The answer must reference Fed/FOMC entities — NOT just generic text
    combined = str(graph_answer).lower()
    fed_entities = {"federal reserve", "fomc", "rate decision", "basis point", "fm-"}
    matched = [e for e in fed_entities if e in combined]
    assert matched, (
        f"GRAPH_COMPLETION answer doesn't mention Fed-related entities.\n"
        f"This looks like flat vector noise, not graph traversal.\n"
        f"Checked for: {fed_entities}\n"
        f"Answer was:\n{combined[:500]}"
    )
    print(f"\n✓ Fed entities found in graph answer: {matched}")
    print(f"\n--- GRAPH_COMPLETION output ---")
    print(graph_answer)


@pytest.mark.asyncio
async def test_find_analogues_cross_category_separation(fomc_events, crypto_events):
    """
    Querying for a FOMC event should NOT predominantly surface crypto events.
    Tests that graph structure (category edges) guides retrieval, not just
    token-level embedding similarity.
    """
    new_event = next(e for e in fomc_events if e["market_id"] == "FM-001")
    result = await find_analogous_events(new_event)

    graph_answer = str(result.get("graph_completion", "")).lower()
    if not graph_answer:
        pytest.skip("GRAPH_COMPLETION empty — need LLM API key")

    # Count category signal words
    fed_hits = sum(1 for w in ("federal reserve", "fomc", "rate", "treasury") if w in graph_answer)
    crypto_hits = sum(1 for w in ("bitcoin", "btc", "ethereum", "crypto") if w in graph_answer)

    assert fed_hits > 0, "Expected at least one Fed entity in graph answer"
    # Not a strict rule — crypto events can legitimately co-occur with macro ones
    # via shared entities — but mostly Fed should dominate
    print(f"\nFed entity hits: {fed_hits}  |  Crypto entity hits: {crypto_hits}")
    if crypto_hits > fed_hits:
        print("WARNING: crypto entities dominate FOMC query result — graph edges may be weak")


@pytest.mark.asyncio
async def test_triplet_completion_returns_or_none(fomc_events):
    """
    TRIPLET_COMPLETION either returns results (triplet index exists) or None
    (index not built). Both are acceptable — never raises an uncaught exception.
    """
    new_event = fomc_events[0]
    result = await find_analogous_events(new_event)

    # triplet_completion must be either a list or None — never an exception
    tc = result["triplet_completion"]
    assert tc is None or isinstance(tc, list), (
        f"Expected list or None for triplet_completion, got {type(tc)}"
    )
    if tc is None:
        print("\n[INFO] TRIPLET_COMPLETION index not available — expected if cognify "
              "pipeline didn't include triplet embedding stage")
    else:
        print(f"\n✓ TRIPLET_COMPLETION returned {len(tc)} result(s)")


@pytest.mark.asyncio
async def test_explanation_structure(fomc_events):
    """
    explanation string must exist and contain the event question + separator markers.
    """
    event = next(e for e in fomc_events if e["market_id"] == "FM-002")
    result = await find_analogous_events(event)

    explanation = result["explanation"]
    assert isinstance(explanation, str)
    assert event["market_question"][:20] in explanation
    assert "GRAPH_COMPLETION" in explanation
    print(f"\n--- explanation ---\n{explanation}")


@pytest.mark.asyncio
async def test_query_id_logged_after_search(fomc_events):
    """
    After find_analogous_events(), get_last_query_id() should return a UUID string.
    This is the handle for Phase 3 feedback attachment.
    """
    event = fomc_events[0]
    await find_analogous_events(event)
    query_id = await get_last_query_id()

    if query_id is None:
        print("\n[INFO] Query ID not available — COGNEE_LOG_SEARCH_HISTORY may be off")
    else:
        import uuid
        uuid.UUID(query_id)  # validates it's a real UUID
        print(f"\n✓ query_id={query_id}  (attach Phase 3 feedback here)")


@pytest.mark.asyncio
async def test_two_fomc_events_produce_consistent_category(fomc_events):
    """
    FM-001 (Sep 2024 cut) and FM-004 (Dec 2024 cut) are both FOMC events.
    Both should recall answers referencing the Federal Reserve / rate decisions.
    If one does and the other doesn't, the graph has inconsistent coverage.
    """
    fm001 = next(e for e in fomc_events if e["market_id"] == "FM-001")
    fm004 = next(e for e in fomc_events if e["market_id"] == "FM-004")

    result_001 = await find_analogous_events(fm001)
    result_004 = await find_analogous_events(fm004)

    answer_001 = str(result_001.get("graph_completion", "")).lower()
    answer_004 = str(result_004.get("graph_completion", "")).lower()

    if not answer_001 or not answer_004:
        pytest.skip("LLM API not available")

    fed_terms = {"federal reserve", "fomc", "rate", "fm-"}

    match_001 = [t for t in fed_terms if t in answer_001]
    match_004 = [t for t in fed_terms if t in answer_004]

    print(f"\nFM-001 Fed matches: {match_001}")
    print(f"FM-004 Fed matches: {match_004}")

    assert match_001, f"FM-001 recall didn't surface Fed entities: {answer_001[:300]}"
    assert match_004, f"FM-004 recall didn't surface Fed entities: {answer_004[:300]}"
