"""
Smoke test: confirms the local self-hosted Cognee setup works end-to-end.
Uses file-based storage only (SQLite + LanceDB + Ladybug) — no cloud required.
Embeddings: fastembed/BAAI-bge-small-en-v1.5 (local, no API key needed).
LLM: Gemini 2.5 Flash via Google AI Studio.
"""

import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import cognee
from cognee.api.v1.search.search import SearchType


MARKET_EVENT = (
    "On June 23 2026, NVDA surged 8% in pre-market trading after the company "
    "announced a new sovereign AI partnership with three G7 governments, sending "
    "the semiconductor sector ETF (SOXX) up 3.2% on heavy volume."
)


async def main():
    print("=== Cognee smoke test ===\n")

    await cognee.prune.prune_data()
    await cognee.prune.prune_system(metadata=True)

    print("[1] cognee.add() ...")
    await cognee.add(MARKET_EVENT)
    print("    done.\n")

    print("[2] cognee.cognify() — building graph (this may take ~30 s) ...")
    await cognee.cognify()
    print("    done.\n")

    print("[3] cognee.search() ...")
    results = await cognee.search(
        "NVDA semiconductor AI partnership",
        query_type=SearchType.SUMMARIES,
    )
    print("    done.\n")

    print("=== Results ===")
    if not results:
        print("(no results returned)")
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r}")

    print("\n=== Smoke test PASSED ===")


if __name__ == "__main__":
    asyncio.run(main())
