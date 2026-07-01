"""
Local FastEmbed vector store — zero LLM calls.

Used by ingest/loader.py to save event vectors and by memory/recall.py
to search them. This runs entirely locally (BAAI/bge-small-en-v1.5 model
cached in ~/.cache/huggingface/) and never touches the Gemini API.

Architecture:
    ingest → event_to_text() → embed() → save to data/vector_store.json
    recall → embed(query) → cosine_similarity → top-k texts → LLM synthesis

This runs alongside Cognee (which handles improve/forget/session) but is the
primary retrieval path because Cognee's chunk search requires cognify (LLM).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

_STORE_FILE = Path(__file__).parent.parent / "data" / "vector_store.json"
_MODEL_NAME = "BAAI/bge-small-en-v1.5"

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding(model_name=_MODEL_NAME)
    return _embedder


def _embed(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts, returning one float list per text."""
    model = _get_embedder()
    return [vec.tolist() for vec in model.embed(texts)]


def _load_store() -> dict[str, Any]:
    if _STORE_FILE.exists():
        try:
            return json.loads(_STORE_FILE.read_text())
        except Exception:
            pass
    return {"entries": []}


def _save_store(store: dict[str, Any]) -> None:
    _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STORE_FILE.write_text(json.dumps(store, indent=2))


def upsert(market_id: str, text: str) -> None:
    """Add or replace a market event in the vector store."""
    store = _load_store()
    vec = _embed([text])[0]

    entries = store["entries"]
    for entry in entries:
        if entry["market_id"] == market_id:
            entry["text"] = text
            entry["vector"] = vec
            _save_store(store)
            return

    entries.append({"market_id": market_id, "text": text, "vector": vec})
    _save_store(store)


def search(query: str, top_k: int = 8) -> list[dict[str, Any]]:
    """
    Find the top-k most similar entries to a query using cosine similarity.

    Returns list of dicts: [{"market_id": ..., "text": ..., "score": ...}, ...]
    """
    store = _load_store()
    entries = store["entries"]

    if not entries:
        return []

    q_vec = np.array(_embed([query])[0])
    q_norm = np.linalg.norm(q_vec)
    if q_norm == 0:
        return []

    scored = []
    for entry in entries:
        v = np.array(entry["vector"])
        v_norm = np.linalg.norm(v)
        if v_norm == 0:
            continue
        score = float(np.dot(q_vec, v) / (q_norm * v_norm))
        scored.append({
            "market_id": entry["market_id"],
            "text": entry["text"],
            "score": score,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def delete(market_id: str) -> bool:
    """Remove a market event from the vector store. Returns True if found."""
    store = _load_store()
    before = len(store["entries"])
    store["entries"] = [e for e in store["entries"] if e["market_id"] != market_id]
    if len(store["entries"]) < before:
        _save_store(store)
        return True
    return False


def list_market_ids() -> list[str]:
    """Return all market IDs currently in the store."""
    store = _load_store()
    return [e["market_id"] for e in store["entries"]]


def count() -> int:
    return len(_load_store()["entries"])
