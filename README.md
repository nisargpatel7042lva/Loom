# Loom — Prediction-Market Memory Agent

> A Cognee-native agent that remembers past market resolutions, finds structural analogies when a new market opens, learns from every wrong prediction, and prunes false-positive precedents from its own graph.

Built for the [Cognee Hackathon](https://cognee.ai). Fully self-hosted — no Cognee Cloud, no external vector services.

---

## What we built

Prediction markets expose a hard problem: every new question looks novel until you notice that "Will the Fed cut rates at the September FOMC?" is structurally identical to the November one three months earlier. Traders who remember the analogy have an edge.

Loom is a memory agent that:
1. **Ingests** resolved market events into a persistent knowledge graph via `cognee.remember()`
2. **Recalls** analogous past events for any new incoming market using graph-traversal search
3. **Learns** from each outcome by scoring its own recall quality and storing that score in Cognee's session feedback system
4. **Forgets** events that are chronic false positives — structurally similar to new markets but systematically wrong — so they stop polluting future recall

---

## Cognee lifecycle

### `remember()` — permanent dataset ingestion

Each market event is rendered as entity-dense natural language before ingestion, so the graph extractor can pull structured entities (Federal Reserve, FOMC, rate cut, basis points) and their relationships:

```python
# ingest/loader.py

async def ingest(events: list[dict]) -> dict:
    texts = [event_to_text(e) for e in events]
    result = await cognee.remember(
        data=texts,
        dataset_name="loom_market_events",
        # no session_id — permanent graph memory, not a session context blob
    )
    final_status = await _wait_for_completion(UUID(result.dataset_id))
    return {"events_ingested": len(events), "status": final_status, ...}
```

The `event_to_text()` function explicitly names entities and their causal relationships:

```
Prediction market FM-001 asks: "Will the Federal Reserve cut interest rates by 50
basis points at the September 2024 FOMC meeting?". This market belongs to the macro
category. The market was triggered by FOMC Federal Reserve rate decision September 2024
on 2024-09-15. Odds moved from 0.25 to 0.55 (a +120.0% change). The market resolved
YES on 2024-09-18. Fed Chair Jerome Powell signalled an outsized 50bp cut...
```

Run it:
```bash
python -m ingest.loader --source fixtures --limit 2   # 2 events ≈ 4 LLM calls
python -m ingest.loader --source live --category crypto  # real Jupiter API data
```

---

### `recall()` — graph-traversal search + TRIPLET cross-check

Two search types are combined per recall call. Neither makes redundant LLM calls when the graph is empty — both check for empty graph before any synthesis step:

```python
# memory/recall.py

async def find_analogous_events(new_event: dict) -> dict:
    query = _build_query(new_event)  # entity-dense query from event fields

    # Primary: LLM synthesis over graph traversal
    graph_results = await _safe_search(query, SearchType.GRAPH_COMPLETION, top_k=10)

    # Secondary: triplet-level subject→predicate→object edges, no LLM call
    triplet_results = await _safe_search(query, SearchType.TRIPLET_COMPLETION, top_k=5)

    # Manually save qa_id for feedback attachment — GRAPH_COMPLETION doesn't auto-save
    # qa_ids (only AGENTIC_COMPLETION does at agentic_retriever.py:452)
    qa_id = await _save_qa_interaction(market_id, query, graph_results)

    return {
        "graph_completion": graph_results,
        "triplet_completion": triplet_results,
        "qa_id": qa_id,          # used by improve.py
        ...
    }
```

`_safe_search` degrades gracefully — returns `None` for missing index, `[]` for quota-exhausted or empty graph, never hangs:

```python
async def _safe_search(query, search_type, top_k=10) -> list | None:
    try:
        return await cognee.search(
            query_text=query, query_type=search_type,
            datasets=["loom_market_events"], top_k=top_k,
        )
    except Exception as exc:
        exc_name, exc_str = type(exc).__name__, str(exc)
        if exc_name in _MISSING_INDEX_ERRORS or any(m in exc_str for m in _MISSING_INDEX_ERRORS):
            return None    # triplet index not built yet — caller shows honest notice
        if "RateLimitError" in exc_name or "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
            return []      # quota exhausted — show empty-graph brief, don't crash
        raise
```

Run it:
```bash
python -m memory.recall FM-001
```

---

### `improve()` — real Feedback System, not a stub

After a market resolves, `improve.py` attaches a feedback score to the specific `qa_id` that was produced during recall. This uses Cognee's session manager directly — `cognee.session.add_feedback()` is a documentation shorthand that doesn't exist; the real path is:

```python
# memory/improve.py

async def record_outcome(market_id: str, actual_outcome: str, ...) -> dict:
    from cognee.infrastructure.session.get_session_manager import get_session_manager
    session_manager = get_session_manager()

    # Step 1: retrieve the original recall answer for this qa_id
    entries = await session_manager.get_session(
        user_id=str(user.id),
        session_id="loom_live",
        formatted=False,
    )
    entry = next((e for e in entries if str(e.qa_id) == qa_id), None)

    # Step 2: score recall quality against the actual outcome
    score, reasoning = _score_answer_vs_outcome(entry.answer, actual_outcome)

    # Step 3: record feedback — returns True if qa_id found in SQLite, False otherwise
    returned = await session_manager.add_feedback(
        user_id=str(user.id),
        qa_id=qa_id,
        feedback_text=reasoning,
        feedback_score=score,
        session_id="loom_live",
    )
    # Honest reporting: we log whether add_feedback returned True or False
    print(f"  add_feedback → {'True ✓' if returned else 'False ✗'} (stored in SQLite)")
    ...
```

Actual output when a recall answer is scored:
```
[FM-001] qa_id=ecd69a34…
  Entry source: live from session cache
  Original answer: [empty — graph was not populated when recall ran]
  Score: 3/5  (no answer text)
  add_feedback → True  ✓ (stored in SQLite)
```

`apply_feedback_weights()` is called but honestly reports `skipped=1` because `GRAPH_COMPLETION` doesn't surface the `used_graph_element_ids` (node/edge UUIDs it traversed) — that requires switching to `AGENTIC_COMPLETION`.

Run it:
```bash
python -m memory.improve FM-001 YES
python -m memory.improve FM-001 YES --score 5 --feedback "Correctly recalled cut"
python -m memory.improve --batch    # score all 20 resolved fixture events
```

---

### `forget()` — item-level graph pruning with honest semantics

Stale events — those surfaced repeatedly as analogies but consistently scored ≤ 2 across ≥ 2 feedback entries — are pruned via `cognee.forget()`:

```python
# memory/forget.py

async def prune_stale_events(reason: str, dry_run: bool = True) -> list[dict]:
    candidates = find_stale_candidates(min_feedbacks=2, max_score=2)
    dataset_id = await _resolve_dataset_id()

    for event in candidates:
        data_record = await _find_data_record(dataset_id, event)
        # data_record matched by content_hash = md5(event_to_text(event))

        if not dry_run:
            await cognee.forget(
                data_id=data_record.id,
                dataset_id=dataset_id,
            )
```

**Deletion granularity (verified from `delete_data_nodes_and_edges.py`):**
- ✓ SQLite Data record — removed
- ✓ Graph nodes/edges unique to this event — removed from graph + vector
- ✗ Shared entity nodes (e.g. "Federal Reserve" referenced by FM-001 and FM-002) — *detagged only*, not removed. The graph stays coherent for structure shared with surviving events.

Run it:
```bash
python -m memory.forget --dry-run           # shows candidates, no deletion
python -m memory.forget --commit            # deletes stale events
```

---

## Best Use of Open Source

Everything runs locally:
- Graph database: Cognee's embedded KuzuDB / LanceDB (file-based, no server)
- Embeddings: `fastembed` with `BAAI/bge-small-en-v1.5` — runs fully offline, no API call
- LLM: pluggable via `litellm` (configured to Gemini in `.env`, swap to any provider)
- Session cache: Cognee's SQLite-backed session manager
- No Cognee Cloud, no external vector service, no hosted dependencies

```env
EMBEDDING_PROVIDER=fastembed
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIMENSIONS=384
COGNEE_SKIP_CONNECTION_TEST=true
AUTO_FEEDBACK=false   # disable pre-retrieval LLM call; we attach feedback manually
```

All state lives in `.cognee_system/` (graph + vector DBs) and `data/` (JSON/JSONL logs).

---

## Live data — Jupiter Prediction API

Loom can ingest real, live prediction market events from [Jupiter's Prediction API](https://api.jup.ag/prediction/v1) (beta):

```bash
python -m ingest.loader --source live --category crypto
python -m ingest.loader --source live --category economics
```

The adapter maps Jupiter's schema to Loom's internal schema:

```python
# ingest/jupiter_adapter.py

def jupiter_event_to_loom_event(raw: dict) -> dict:
    return {
        "market_id": raw["id"],
        "market_question": raw.get("title", ""),
        "category": raw.get("category", ""),
        "odds_after": _extract_probability(raw),
        "outcome": "pending" if not raw.get("resolved") else ...,
        ...
    }
```

**Note:** The Jupiter Prediction API is in beta and subject to change. Fields like `trigger`, `narrative`, `odds_before`, and `odds_move_pct` are not available from the live API and are omitted rather than fabricated — `event_to_text()` handles `None` values cleanly. Fixtures (`data/sample_events.json`) remain the reliable fallback path for demo and testing.

---

## Setup

```bash
# 1. Clone and create environment
git clone <repo>
cd Loom
uv venv && source .venv/bin/activate
uv pip install -e .

# 2. Configure API key
cp .env.example .env
# Edit .env — set LLM_API_KEY to your Gemini key (or any litellm-compatible LLM)

# 3. Ingest fixture events into the knowledge graph
python -m ingest.loader --source fixtures --limit 2   # ~4 LLM calls per run

# 4. Run unit tests (no LLM calls)
pytest tests/ -m 'not integration' -v
```

**.env example:**
```env
LLM_PROVIDER=gemini
LLM_MODEL=gemini/gemini-2.5-flash
LLM_API_KEY=<your-key>

EMBEDDING_PROVIDER=fastembed
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIMENSIONS=384
COGNEE_SKIP_CONNECTION_TEST=true
AUTO_FEEDBACK=false
```

---

## Demo

Full lifecycle — ingest → recall → learn → prune:

```bash
# Populate the graph (requires LLM quota)
python -m ingest.loader --source fixtures --limit 4

# Recall analogous events for a new market
python -m agent.core analyze FM-005

# Record the actual outcome and score the recall
python -m agent.core learn FM-005 YES

# Check what's stale
python -m memory.forget --dry-run

# Prune it
python -m memory.forget --commit

# Verify it's gone
python -m agent.core analyze FM-005
```

Sample brief output (with populated graph):
```
3 precedents cited. 5 YES-direction signals / 1 NO-direction → leans YES | Odds moved 25% → 55% (+120.0%).
Pattern: The Federal Reserve delivered a 50bp cut at the September 2024 FOMC meeting, the first reduction in four years.
Precedents cited: FM-001, FM-002, FM-003.
Triplet corroboration: Federal Reserve → cut → interest rates by 50 basis points.
```

With empty graph (before ingest or quota exhausted):
```
No analogous precedents found in MACRO. Graph is empty or no similar markets have been ingested.
Run `python -m ingest.loader --source fixtures` to populate.
```

---

## What's next

- **Broader live coverage:** expand Jupiter adapter to handle `politics` and `sports` categories with category-specific entity phrasing
- **Pre-trade sanity check:** narrow the product framing from "memory agent" to "pre-trade sanity check" — before a trader takes a position, Loom surfaces the 3 most structurally similar resolved markets with direction and outcome, in under 2 seconds
- **AGENTIC_COMPLETION:** switch from `GRAPH_COMPLETION` to `AGENTIC_COMPLETION` so `apply_feedback_weights()` can update actual graph edge weights (currently skipped because `GRAPH_COMPLETION` doesn't surface `used_graph_element_ids`)

---

## AI tool disclosure

This project was built with [Claude Code](https://claude.ai/code) (Anthropic), used for code generation, test writing, and API verification against Cognee 1.2.1 source. Per hackathon rules, all AI-assisted code has been reviewed and is disclosed here. The core logic — Cognee API selection, feedback scoring heuristics, deletion granularity documentation — reflects verified understanding of the actual library internals, not generated documentation boilerplate.
