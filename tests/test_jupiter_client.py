"""
Integration test: Jupiter Prediction API client + adapter.

Hits the real API (no key required for reads). All tests share a single
session-scoped fixture to avoid hammering the API and hitting 429s.

Skip in CI:
    pytest -m "not integration"

Run manually:
    pytest tests/test_jupiter_client.py -v -s
"""

import json
import time
import pytest
from ingest.jupiter_client import get_events, search_events
from ingest.jupiter_adapter import jupiter_event_to_loom_event


pytestmark = pytest.mark.integration


# ── shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def crypto_events():
    """Fetch crypto events ONCE for the entire test session."""
    events = get_events(category="crypto", include_markets=True)
    assert events, "Jupiter API returned zero crypto events — is it down?"
    return events


@pytest.fixture(scope="session")
def search_results():
    """Search for bitcoin ONCE; rate-limit buffer between session fixtures."""
    time.sleep(1)  # small buffer after the get_events call above
    return search_events("bitcoin", limit=5)


# ── client tests ─────────────────────────────────────────────────────────────

class TestGetEvents:
    def test_returns_list(self, crypto_events):
        assert isinstance(crypto_events, list)

    def test_crypto_category_returns_events(self, crypto_events):
        assert len(crypto_events) > 0, "Expected at least one crypto event"

    def test_raw_event_has_required_keys(self, crypto_events):
        e = crypto_events[0]
        assert "eventId" in e
        assert "category" in e
        assert "metadata" in e
        assert "title" in e["metadata"]

    def test_markets_included_when_requested(self, crypto_events):
        events_with_markets = [e for e in crypto_events if e.get("markets")]
        assert events_with_markets, "No events returned with market data"
        m = events_with_markets[0]["markets"][0]
        assert "pricing" in m
        pricing = m["pricing"]
        assert "sellYesPriceUsd" in pricing
        assert "buyYesPriceUsd" in pricing


class TestSearchEvents:
    def test_bitcoin_search_returns_results(self, search_results):
        assert isinstance(search_results, list)
        assert len(search_results) > 0, "Expected bitcoin search to return results"

    def test_search_results_have_title(self, search_results):
        for r in search_results:
            assert r.get("metadata", {}).get("title"), "Missing title in search result"


# ── adapter tests ────────────────────────────────────────────────────────────

class TestAdapter:
    def test_crypto_event_maps_correctly(self, crypto_events):
        events_with_markets = [e for e in crypto_events if e.get("markets")]
        assert events_with_markets, "No crypto events with markets"
        mapped = jupiter_event_to_loom_event(events_with_markets[0])

        raw = events_with_markets[0]
        assert mapped["market_id"] == raw["eventId"]
        assert mapped["market_question"] == raw["metadata"]["title"].strip()
        assert mapped["category"] == "crypto"
        assert mapped["outcome"] in ("pending", "YES", "NO") or mapped["outcome"]

    def test_odds_after_in_range(self, crypto_events):
        events_with_markets = [e for e in crypto_events if e.get("markets")]
        for raw in events_with_markets[:3]:
            mapped = jupiter_event_to_loom_event(raw)
            if mapped["odds_after"] is not None:
                assert 0.0 <= mapped["odds_after"] <= 1.0, (
                    f"odds_after out of range for {raw['eventId']}: {mapped['odds_after']}"
                )

    def test_null_fields_are_honest(self, crypto_events):
        """Fields we cannot source from Jupiter must be None, never fabricated."""
        mapped = jupiter_event_to_loom_event(crypto_events[0])
        assert mapped["trigger"] is None
        assert mapped["narrative"] is None
        assert mapped["odds_before"] is None
        assert mapped["odds_move_pct"] is None

    def test_end_to_end_mapping_shows_real_data(self, crypto_events):
        """Print raw + mapped for 3 events so the mapping can be manually verified."""
        events_with_markets = [e for e in crypto_events if e.get("markets")]
        sample = events_with_markets[:3] if len(events_with_markets) >= 3 else events_with_markets

        print("\n\n" + "=" * 60)
        print("JUPITER → LOOM MAPPING DEMO (crypto, first 3 events with markets)")
        print("=" * 60)

        for raw in sample:
            mapped = jupiter_event_to_loom_event(raw)

            # Identify the actual representative market (highest volume)
            rep_market = max(
                raw["markets"], key=lambda m: m.get("pricing", {}).get("volume", 0)
            )

            raw_summary = {
                "eventId": raw["eventId"],
                "category": raw["category"],
                "title": raw["metadata"]["title"],
                "markets_count": len(raw["markets"]),
                "rep_market": {
                    "title": rep_market.get("title"),
                    "sellYesPriceUsd": rep_market.get("pricing", {}).get("sellYesPriceUsd"),
                    "implied_prob": (
                        round(rep_market["pricing"]["sellYesPriceUsd"] / 1_000_000, 4)
                        if rep_market.get("pricing", {}).get("sellYesPriceUsd") is not None
                        else None
                    ),
                    "volume": rep_market.get("pricing", {}).get("volume"),
                },
            }
            mapped_public = {k: v for k, v in mapped.items() if not k.startswith("_")}

            print(f"\n--- RAW: {raw['eventId']} ---")
            print(json.dumps(raw_summary, indent=2))
            print(f"\n--- MAPPED (Loom schema) ---")
            print(json.dumps(mapped_public, indent=2))
            print()

        for raw in sample:
            mapped = jupiter_event_to_loom_event(raw)
            assert mapped["market_question"], f"Empty market_question for {raw['eventId']}"
