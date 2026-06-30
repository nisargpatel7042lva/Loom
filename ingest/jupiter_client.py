"""
Thin HTTP client for Jupiter Prediction API v1 (BETA).

All methods return an empty list on ANY error — network failures, rate limits,
auth errors, schema surprises — so callers can treat a live outage the same
as "no results available" and fall back to fixtures without crashing.

Pricing note: Jupiter's `pricing.sellYesPriceUsd` is in micro-USD
(1_000_000 units = $1.00), so divide by 1_000_000 to get implied probability.
"""

import logging
from typing import Any

import httpx
from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.jup.ag/prediction/v1"
_TIMEOUT = 10.0  # seconds — avoids hanging ingestion on slow API


def _headers() -> dict[str, str]:
    key = os.getenv("JUPITER_API_KEY", "")
    h: dict[str, str] = {"Accept": "application/json"}
    if key:
        h["x-api-key"] = key
    return h


def _get(path: str, params: dict[str, Any] | None = None) -> list[dict]:
    """GET {_BASE_URL}{path} and return the data array, or [] on any error."""
    url = f"{_BASE_URL}{path}"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(url, params=params, headers=_headers())
            resp.raise_for_status()
            body = resp.json()
            # API returns either {"data": [...]} or a bare list
            if isinstance(body, dict):
                return body.get("data", [])
            if isinstance(body, list):
                return body
            logger.error("jupiter: unexpected response shape from %s: %s", url, type(body))
            return []
    except httpx.TimeoutException:
        logger.error("jupiter: request timed out after %.1fs (%s)", _TIMEOUT, url)
        return []
    except httpx.HTTPStatusError as exc:
        logger.error(
            "jupiter: HTTP %s from %s — %s",
            exc.response.status_code,
            url,
            exc.response.text[:200],
        )
        return []
    except Exception as exc:  # schema change, network error, parse error, etc.
        logger.error("jupiter: unexpected error calling %s — %s: %s", url, type(exc).__name__, exc)
        return []


def get_events(
    category: str | None = None,
    include_markets: bool = True,
) -> list[dict]:
    """
    Fetch active events, optionally filtered by category.

    Args:
        category: Jupiter category string — "crypto", "economics", "politics",
                  "sports". None = all categories.
        include_markets: include per-event market pricing data (default True).

    Returns:
        List of raw Jupiter event dicts, or [] on any error.
    """
    params: dict[str, Any] = {"includeMarkets": str(include_markets).lower()}
    if category:
        params["category"] = category
    return _get("/events", params)


def search_events(query: str, limit: int = 10) -> list[dict]:
    """
    Full-text search across event titles.

    Args:
        query: search string (e.g. "bitcoin", "FOMC", "World Cup").
        limit: max events to return (API may return fewer).

    Returns:
        List of raw Jupiter event dicts, or [] on any error.
    """
    return _get("/events/search", {"query": query, "limit": limit})
