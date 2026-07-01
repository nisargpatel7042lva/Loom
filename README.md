# Loom — Prediction-Market Memory Agent

> A Cognee-native agent that remembers past market resolutions, finds structural analogies when a new market opens, learns from every wrong prediction, and prunes false-positive precedents from its own graph.

Built for the [Cognee Hackathon](https://cognee.ai). Fully self-hosted — no Cognee Cloud, no external vector services.

---

## What we built

Prediction markets expose a hard problem: every new question looks novel until you notice that "Will the Fed cut rates at the September FOMC?" is structurally identical to the November one three months earlier. Traders who remember the analogy have an edge.

Loom is a memory agent that:
1. **Ingests** live Jupiter market events into persistent memory via `cognee.add()` — zero LLM calls, instant
2. **Recalls** analogous past events via FastEmbed cosine similarity — zero LLM calls
3. **Analyzes** with exactly **1 LLM call** that synthesizes a trader brief from retrieved precedents
4. **Learns** from each outcome by scoring recall quality and storing it via `session_manager.add_feedback()`
5. **Forgets** events that are chronic false positives via `cognee.prune()`

---

## Cognee lifecycle

### `add()` — zero-cost live data ingestion

Each market event is rendered as entity-dense natural language and stored via `cognee.add()`. FastEmbed vectorizes it locally — no LLM API calls:

```python
# ingest/loader.py

async def ingest(events: list[dict]) -> dict:
    for event in events:
        text = event_to_text(event)
        await cognee.add(data=[text], dataset_name=DATASET_NAME)
        vs_upsert(event["market_id"], text)   # local FastEmbed vector store
    return {"events_ingested": len(events), "llm_calls": 0, ...}
```

The `event_to_text()` function creates entity-rich text so similarity search picks up structural patterns:

```
Prediction market FM-001 asks: "Will the Federal Reserve cut interest rates by 50
basis points at the September 2024 FOMC meeting?". This market belongs to the macro
category. Odds moved from 0.25 to 0.55 (+120.0%). The market resolved YES.
```

### `search()` — recall via semantic similarity

`memory/recall.py` queries the local FastEmbed vector store (cosine similarity), which is always available and requires zero LLM calls. Results feed the analyst brief:

```python
# memory/recall.py

async def find_analogous_events(new_event: dict) -> dict:
    query = _build_query(new_event)      # entity-dense query string
    hits  = vs_search(query, top_k=8)   # FastEmbed cosine similarity, 0 LLM calls
    qa_id = await _save_qa_interaction(market_id, query, hits)
    return {"chunks": [h["text"] for h in hits], "qa_id": qa_id, ...}
```

### `analyze()` — 1 LLM call synthesis

`agent/core.py` takes the recalled chunks and makes exactly one LLM call to synthesize a trader brief:

```python
# agent/core.py

async def _synthesize_brief(new_event: dict, chunks: list[str]) -> str:
    context = "\n\n".join(f"[Past market {i+1}]: {c}" for i, c in enumerate(chunks[:6]))
    resp = await litellm.acompletion(
        model=os.environ["LLM_MODEL"],
        messages=[
            {"role": "system", "content": _BRIEF_SYSTEM},
            {"role": "user",   "content": f"New market: {question}\n\nContext:\n{context}"},
        ],
        max_tokens=200,
    )
    return resp.choices[0].message.content.strip()
```

Sample output on FM-001 (Fed 50bp cut):

```
7 analogous precedents found. 3 resolved YES (Fed cut Dec 2024, Nov 2024; CPI fell).
Pattern: markets where Fed signalled softening and CPI cooperated historically
resolved YES at 75% rate. Current 55% implied leans YES. Moderate confidence.
```

### `improve()` — feedback from outcomes

When a market resolves, `memory/improve.py` retrieves the original recall answer from Cognee's session cache, scores it 1–5 against the actual outcome, and stores feedback via `session_manager.add_feedback()`:

```python
# memory/improve.py

qa_entries = await session_manager.get_session(user_id, LOOM_SESSION_ID)
for entry in qa_entries:
    if entry.question relates to market_id:
        score = _score_answer(entry.answer, actual_outcome)
        returned = await session_manager.add_feedback(
            user_id, entry.id, feedback_text, score, LOOM_SESSION_ID
        )
        # returned = True if qa_id exists in SQLite cache
```

### `forget()` — prune chronic false positives

`memory/forget.py` identifies markets that were repeatedly recalled but consistently scored ≤ 2 (wrong precedent), then removes them via `cognee.prune()`:

```python
# memory/forget.py

candidates = find_stale_candidates(min_feedbacks=2, max_score=2.0)
for c in candidates:
    await cognee.prune(datasets=[DATASET_NAME], data_ids=[c["data_id"]])
```

---

## Best Use of Open Source

Loom's architecture was designed to work within tight API limits:

| Step | Calls | Why |
|------|-------|-----|
| Ingest N events | 0 LLM | FastEmbed local vectorization |
| Recall per market | 0 LLM | Cosine similarity search |
| Analyze (brief synthesis) | **1 LLM** | Targeted generation from retrieved context |
| Learn (record outcome) | 0 LLM | SQLite session feedback only |
| Forget (prune stale) | 0 LLM | Cognee prune API |

With a 20 req/day free Gemini key: **20 live market analyses per day**, unlimited ingest.

---

## Live data

Loom fetches live events from the [Jupiter Prediction API](https://api.jup.ag/prediction/v1):

```python
# ingest/jupiter_client.py
events = get_events(category="economics", max_events=50)
# → 50 real prediction markets from Jupiter in <1s
```

Live events are mapped to Loom's schema (`jupiter_adapter.py`) and ingested instantly with zero LLM calls.

---

## Setup

```bash
git clone <repo>
cd Loom
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: add LLM_API_KEY (Gemini) and optionally JUPITER_API_KEY
```

**`.env` settings:**
```
LLM_PROVIDER=gemini
LLM_MODEL=gemini/gemini-2.5-flash
LLM_API_KEY=your_key_here
EMBEDDING_PROVIDER=fastembed
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIMENSIONS=384
COGNEE_SKIP_CONNECTION_TEST=true
AUTO_FEEDBACK=false
```

```bash
# Populate memory (0 LLM calls — instant)
python -m ingest.loader --source fixtures
python -m ingest.loader --source live --category economics --limit 20

# Analyze a market (1 LLM call)
python -m agent.core analyze FM-001

# Record outcome (0 LLM calls)
python -m agent.core learn FM-001 YES

# Run demo app
streamlit run demo/app.py
```

---

## Demo

```
streamlit run demo/app.py
```

Open `http://localhost:8501` in your browser. Five pages:

- **Live Markets** — fetch live Jupiter events (no LLM)
- **Ingest** — store events in memory (no LLM)
- **Analyze** — semantic recall + 1 LLM brief synthesis
- **Learn** — record actual outcome, store feedback
- **Forget** — prune chronic false positives

---

## What's next

- Run Cognee's `cognify()` pipeline on top of the vector store for knowledge graph entity linking
- Upgrade to `SearchType.AGENTIC_COMPLETION` to get graph element UUIDs and enable `apply_feedback_weights()` to actually update traversal weights
- Multi-user support via Cognee's built-in access control

---

*AI tools used: Claude Code for development. Live data: Jupiter Prediction API. Embeddings: BAAI/bge-small-en-v1.5 via FastEmbed. LLM: Google Gemini 2.5 Flash.*
