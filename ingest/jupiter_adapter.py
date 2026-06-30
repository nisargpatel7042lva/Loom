"""
Maps a raw Jupiter Prediction API event dict into Loom's event schema.

HONESTY CONTRACT — what we do NOT invent for live events:
  - trigger    : null  (Jupiter has no causal-event field; only fixture data has invented triggers)
  - narrative  : null  (Jupiter has no prose description field)
  - odds_before: null  (single API snapshot; no historical pricing available)
  - odds_move_pct: null (can't compute without odds_before)
  - outcome_date: null (Jupiter doesn't expose resolution timestamps)

What we DO derive:
  - odds_after : sellYesPriceUsd / 1_000_000 from the highest-volume market
    (sellYes = implied probability that the trader can lock in right now — the
    most honest single-number representation of current consensus)
  - outcome    : "pending" if result=null/status=open, else the raw result string
  - category   : mapped from Jupiter categories to Loom categories
  - timestamp  : market openTime → ISO date (falls back to event closeTime)

Multi-market events (e.g. "World Cup Winner" with one market per team):
  We pick the market with the highest contract volume as the representative.
  This is the most-actively-traded outcome — the one the crowd cares most about.
"""

from datetime import datetime, timezone
from typing import Any


_CATEGORY_MAP = {
    "economics": "macro",
    "politics": "elections",
    "crypto": "crypto",
    "sports": "sports",
    "culture": "macro",     # fallback for less common categories
    "science": "macro",
}


def _pick_representative_market(markets: list[dict]) -> dict:
    """Return the highest-volume market from the list, or {} if none."""
    if not markets:
        return {}
    return max(markets, key=lambda m: m.get("pricing", {}).get("volume", 0))


def _unix_to_date(ts: int | str | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return None


def jupiter_event_to_loom_event(raw_event: dict) -> dict[str, Any]:
    """
    Convert one Jupiter event dict to Loom's event schema.

    Returns a dict with the same keys as sample_events.json. Fields that
    cannot be sourced from Jupiter are explicitly set to None so callers
    know they are absent, not forgotten.
    """
    event_id: str = raw_event.get("eventId", "UNKNOWN")
    title: str = raw_event.get("metadata", {}).get("title", "").strip()
    jupiter_category: str = raw_event.get("category", "")
    category: str = _CATEGORY_MAP.get(jupiter_category, "macro")

    markets: list[dict] = raw_event.get("markets", [])
    rep = _pick_representative_market(markets)

    # Pricing — micro-USD → decimal probability
    pricing: dict = rep.get("pricing", {})
    sell_yes_raw: int | None = pricing.get("sellYesPriceUsd")
    odds_after: float | None = (
        round(sell_yes_raw / 1_000_000, 4) if sell_yes_raw is not None else None
    )

    # Outcome
    result = rep.get("result")
    market_status: str = rep.get("status", "open")
    if result is not None:
        outcome: str = str(result).upper()
    elif market_status == "open":
        outcome = "pending"
    else:
        outcome = "pending"

    # Timestamp: prefer the representative market's openTime
    open_time = rep.get("openTime")
    close_time_iso: str | None = raw_event.get("metadata", {}).get("closeTime")
    if open_time:
        timestamp = _unix_to_date(open_time)
    elif raw_event.get("beginAt"):
        timestamp = _unix_to_date(raw_event["beginAt"])
    elif close_time_iso:
        timestamp = close_time_iso[:10]
    else:
        timestamp = None

    return {
        "market_id": event_id,
        "market_question": title,
        "category": category,
        # ── NOT available from Jupiter ──────────────────────────────────
        # trigger and narrative require external context we don't have.
        # Setting to None keeps the data honest; event_to_text() handles None.
        "trigger": None,
        "narrative": None,
        # ── Derived from pricing snapshot ───────────────────────────────
        # odds_before and odds_move_pct require historical data not in API.
        "odds_before": None,
        "odds_after": odds_after,
        "odds_move_pct": None,
        "timestamp": timestamp,
        "outcome": outcome,
        "outcome_date": None,
        # ── Metadata passthrough (not in fixture schema, but useful) ────
        "_source": "jupiter",
        "_jupiter_category": jupiter_category,
        "_rep_market_title": rep.get("title"),
        "_rep_market_volume": pricing.get("volume"),
        "_event_volume_usd_raw": raw_event.get("volumeUsd"),
    }
