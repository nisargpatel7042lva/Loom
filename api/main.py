"""
Loom FastAPI backend — exposes all 4 Cognee lifecycle endpoints to the React UI.

Run:
    uvicorn api.main:app --reload --port 8000

All endpoints are async and call the same Python modules used by the Streamlit demo.
CORS is open to localhost:5173 (Vite dev server).
"""

import json
import logging
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("loom.api")

app = FastAPI(title="Loom API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── lazy imports (avoid loading cognee at startup) ──────────────────────────

def _get_agent():
    from agent.core import LoomAgent
    return LoomAgent()

# ── request/response models ─────────────────────────────────────────────────

class IngestRequest(BaseModel):
    source: str = "live"       # always live Jupiter API
    category: str | None = None
    max_events: int = 10

class RecallRequest(BaseModel):
    market_id: str | None = None
    market_question: str | None = None
    category: str = "macro"

class AnalyzeRequest(BaseModel):
    market_id: str | None = None
    market_question: str | None = None
    category: str = "macro"
    odds_after: float | None = None

class ImproveRequest(BaseModel):
    market_id: str
    actual_outcome: str    # "YES" | "NO" | "pending"
    feedback_score: int | None = None
    feedback_text: str | None = None

class ForgetRequest(BaseModel):
    dry_run: bool = True
    min_feedbacks: int = 2
    max_score: int = 2


# ── endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def status():
    """Memory stats — events in vector store, backend health."""
    from memory.vector_store import count as vs_count
    try:
        n = vs_count()
    except Exception:
        n = 0
    return {"events_in_memory": n, "status": "ok"}


@app.get("/api/events")
async def list_events(category: str | None = None, limit: int = 50):
    """List events previously ingested via Remember. Populates UI market selectors."""
    from ingest.loader import _load_ingested_events
    events = _load_ingested_events(category)
    return {
        "events": events[:limit],
        "total": len(events),
    }


@app.get("/api/preview")
async def preview_events(category: str | None = None, limit: int = 8):
    """Fetch a live sample from Jupiter without ingesting. Used by the dashboard."""
    from ingest.loader import _load_live_events
    try:
        events = _load_live_events(category)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Jupiter API error: {exc}")
    return {
        "events": events[:limit],
        "total": len(events),
    }


@app.post("/api/remember")
async def remember(req: IngestRequest):
    """
    Ingest prediction market events into Cognee vector memory.

    cognee.add() + local FastEmbed vectorization — zero LLM calls.
    """
    from ingest.loader import ingest, _load_fixture_events, _load_live_events

    if req.source == "live":
        try:
            events = _load_live_events(req.category)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Jupiter API error: {exc}")
        if not events:
            raise HTTPException(status_code=404, detail="Jupiter API returned no events for this category")
    else:
        events = _load_fixture_events(req.category)

    events = events[: req.max_events]
    if not events:
        raise HTTPException(status_code=404, detail="No events found")

    logger.info("remember: ingesting %d events (source=%s)", len(events), req.source)
    result = await ingest(events)
    return result


@app.post("/api/recall")
async def recall(req: RecallRequest):
    """
    Find analogous past events via local FastEmbed cosine similarity.

    Zero LLM calls — pure vector search over stored events.
    """
    from memory.recall import find_analogous_events
    from ingest.loader import DATA_FILE

    if req.market_id:
        events = json.loads(DATA_FILE.read_text())
        event = next((e for e in events if e["market_id"] == req.market_id), None)
        if not event:
            raise HTTPException(status_code=404, detail=f"Market {req.market_id} not found")
    elif req.market_question:
        event = {
            "market_id": "custom-query",
            "market_question": req.market_question,
            "category": req.category,
        }
    else:
        raise HTTPException(status_code=422, detail="Provide market_id or market_question")

    logger.info("recall: market=%s question=%s", req.market_id, (req.market_question or "")[:60])
    result = await find_analogous_events(event)
    # remove raw_results (not serializable)
    result.pop("raw_results", None)
    return result


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    """
    Full analysis: recall analogues + 1 LLM call for synthesis brief.
    """
    from ingest.loader import DATA_FILE

    if req.market_id:
        events = json.loads(DATA_FILE.read_text())
        event = next((e for e in events if e["market_id"] == req.market_id), None)
        if not event:
            raise HTTPException(status_code=404, detail=f"Market {req.market_id} not found")
    elif req.market_question:
        event = {
            "market_id": "custom-query",
            "market_question": req.market_question,
            "category": req.category,
            "odds_after": req.odds_after,
        }
    else:
        raise HTTPException(status_code=422, detail="Provide market_id or market_question")

    logger.info("analyze: market=%s", req.market_id or req.market_question[:40])
    agent = _get_agent()
    result = await agent.analyze(event)
    result["new_event"] = event
    return result


@app.post("/api/improve")
async def improve(req: ImproveRequest):
    """
    Record actual market outcome and score the original recall via add_feedback().

    Zero LLM calls.
    """
    from memory.improve import record_outcome

    if req.actual_outcome not in ("YES", "NO", "pending"):
        raise HTTPException(status_code=422, detail="actual_outcome must be YES, NO, or pending")

    logger.info("improve: market=%s outcome=%s", req.market_id, req.actual_outcome)
    result = await record_outcome(
        req.market_id,
        req.actual_outcome,
        feedback_score=req.feedback_score,
        feedback_text=req.feedback_text,
    )
    return result


@app.post("/api/forget")
async def forget(req: ForgetRequest):
    """
    Detect and optionally prune chronic false-positive events via cognee.forget().

    Zero LLM calls.
    """
    from memory.forget import prune_stale_events

    logger.info(
        "forget: dry_run=%s min_feedbacks=%d max_score=%d",
        req.dry_run, req.min_feedbacks, req.max_score,
    )
    result = await prune_stale_events(
        dry_run=req.dry_run,
        min_feedbacks=req.min_feedbacks,
        max_score=req.max_score,
    )
    # make sure UUIDs are strings
    if result.get("dataset_id") and not isinstance(result["dataset_id"], str):
        result["dataset_id"] = str(result["dataset_id"])
    return result
