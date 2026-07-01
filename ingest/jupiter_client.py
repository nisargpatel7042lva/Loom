"""
Thin HTTP client for Jupiter Prediction API v1 (BETA).

All methods return an empty list on ANY error — network failures, rate limits,
auth errors, schema surprises — so callers can treat a live outage the same
as "no results available" and fall back to fixtures without crashing.

Pricing note: Jupiter's `pricing.sellYesPriceUsd` is in micro-USD
(1_000_000 units = $1.00), so divide by 1_000_000 to get implied probability.

Pagination: API supports ?limit=N&offset=M. Default page size = 10 (unauthed)
or up to 100 (with key). get_events() fetches up to `max_events` total by
walking pages automatically.
"""

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.jup.ag/prediction/v1"
_TIMEOUT = 15.0
_PAGE_SIZE = 50       # works unauthed; authenticated keys may allow 100


def _headers() -> dict[str, str]:
    key = os.getenv("JUPITER_API_KEY", "").strip()
    h: dict[str, str] = {"Accept": "application/json"}
    if key:
        h["x-api-key"] = key
    return h


def _get(path: str, params: dict[str, Any] | None = None) -> dict:
    """GET and return the full response body dict, or {"data": [], "pagination": {}} on error."""
    url = f"{_BASE_URL}{path}"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(url, params=params, headers=_headers())
            resp.raise_for_status()
            body = resp.json()
            if isinstance(body, list):
                return {"data": body, "pagination": {"total": len(body)}}
            return body
    except httpx.TimeoutException:
        logger.error("jupiter: timeout after %.1fs (%s)", _TIMEOUT, url)
        return {"data": [], "pagination": {}}
    except httpx.HTTPStatusError as exc:
        logger.error(
            "jupiter: HTTP %s from %s — %s",
            exc.response.status_code, url, exc.response.text[:200],
        )
        return {"data": [], "pagination": {}}
    except Exception as exc:
        logger.error("jupiter: %s calling %s — %s", type(exc).__name__, url, exc)
        return {"data": [], "pagination": {}}


def get_events(
    category: str | None = None,
    include_markets: bool = True,
    max_events: int = 50,
) -> list[dict]:
    """
    Fetch active events from Jupiter, walking pagination up to `max_events`.

    Args:
        category: "crypto" | "economics" | "politics" | "sports" | None (all)
        include_markets: include per-event market pricing data (default True)
        max_events: cap total events fetched (default 50 — keeps ingest manageable)

    Returns:
        List of raw Jupiter event dicts, or [] on any error.
    """
    all_events: list[dict] = []
    offset = 0

    while len(all_events) < max_events:
        remaining = max_events - len(all_events)
        page_size = min(_PAGE_SIZE, remaining)

        params: dict[str, Any] = {
            "includeMarkets": str(include_markets).lower(),
            "limit": page_size,
            "offset": offset,
        }
        if category:
            params["category"] = category

        body = _get("/events", params)
        page = body.get("data", [])
        if not page:
            break

        all_events.extend(page)
        pagination = body.get("pagination", {})
        total = pagination.get("total", 0)
        has_next = pagination.get("hasNext", False)

        if not has_next or len(all_events) >= total:
            break

        offset += len(page)

    return all_events[:max_events]


def search_events(query: str, limit: int = 10) -> list[dict]:
    """Full-text search across event titles."""
    body = _get("/events/search", {"query": query, "limit": limit})
    return body.get("data", [])


def get_categories() -> list[str]:
    """Return the list of available categories from the API, or a hardcoded fallback."""
    try:
        body = _get("/categories")
        data = body.get("data", [])
        if data and isinstance(data[0], str):
            return data
        if data and isinstance(data[0], dict):
            return [d.get("name", d.get("id", "")) for d in data]
    except Exception:
        pass
    return ["crypto", "economics", "politics", "sports", "culture"]
