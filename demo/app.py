"""
Loom — live prediction-market memory agent demo.

Run:
    streamlit run demo/app.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import streamlit as st

st.set_page_config(
    page_title="Loom — Market Memory",
    page_icon="🧵",
    layout="wide",
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    try:
        return asyncio.get_event_loop().run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@st.cache_data(ttl=120, show_spinner="Fetching live markets from Jupiter…")
def _fetch_live_events(category: str, max_events: int) -> list[dict]:
    from ingest.jupiter_client import get_events
    from ingest.jupiter_adapter import jupiter_event_to_loom_event
    raw = get_events(
        category=None if category == "all" else category,
        max_events=max_events,
    )
    return [jupiter_event_to_loom_event(e) for e in raw]


# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🧵 Loom")
    st.caption("Live prediction-market memory agent")
    st.divider()

    # Key status
    llm_key = os.environ.get("LLM_API_KEY", "")
    jup_key = os.environ.get("JUPITER_API_KEY", "")

    if llm_key:
        st.success(f"LLM key ✓ `{llm_key[:8]}…`")
    else:
        st.error("No LLM_API_KEY in .env")

    if jup_key:
        st.success(f"Jupiter key ✓ `{jup_key[:8]}…`")
    else:
        st.info("No JUPITER_API_KEY — using public API (50 events/page)")

    st.caption(f"Model: `{os.environ.get('LLM_MODEL','—')}`")

    try:
        from memory.vector_store import count as vs_count
        n = vs_count()
        st.metric("Events in memory", n)
    except Exception:
        pass
    st.divider()

    page = st.radio(
        "Go to",
        ["🏠 Live Markets", "📥 Ingest", "🔍 Analyze", "📚 Learn", "🗑️ Forget"],
        label_visibility="collapsed",
    )

# ── LIVE MARKETS ──────────────────────────────────────────────────────────────

if page == "🏠 Live Markets":
    st.title("🏠 Live Prediction Markets")
    st.caption("Data from [Jupiter Prediction API](https://api.jup.ag/prediction/v1) · refreshes every 2 min")

    col_cat, col_n, col_refresh = st.columns([2, 2, 1])
    with col_cat:
        cat = st.selectbox("Category", ["all", "crypto", "economics", "politics", "sports"], index=0)
    with col_n:
        n = st.slider("Max events to load", 10, 100, 30, step=10)
    with col_refresh:
        st.write("")
        if st.button("🔄 Refresh"):
            st.cache_data.clear()

    events = _fetch_live_events(cat, n)

    if not events:
        st.error("Jupiter API returned no events. Check your network or try again.")
    else:
        st.success(f"Loaded {len(events)} live markets")

        rows = []
        for e in events:
            oa = e.get("odds_after")
            rows.append({
                "Market ID": e["market_id"],
                "Category": e["category"],
                "Question": e["market_question"][:80] + ("…" if len(e["market_question"]) > 80 else ""),
                "Implied prob": f"{oa:.1%}" if oa is not None else "—",
                "Status": e.get("outcome", "pending"),
            })

        st.dataframe(rows, use_container_width=True, hide_index=True)

        st.caption("💡 Go to **Ingest** to load these into the knowledge graph, then **Analyze** to query them.")


# ── INGEST ────────────────────────────────────────────────────────────────────

elif page == "📥 Ingest":
    st.title("📥 Ingest — `cognee.remember()`")
    st.markdown(
        """
        Loads live Jupiter markets into Cognee's persistent vector memory via `cognee.add()`.

        **Zero LLM calls** — uses FastEmbed (local) for vectorization.
        Ingest is instant and unlimited: no Gemini API quota consumed.
        """
    )

    col1, col2 = st.columns(2)
    with col1:
        cat = st.selectbox("Category", ["all", "crypto", "economics", "politics", "sports"])
    with col2:
        limit = st.slider("Number of events to ingest", 1, 100, 20,
                          help="No LLM calls — ingest as many as you want.")

    st.markdown("**Preview — events that will be ingested:**")
    with st.spinner("Loading live events…"):
        events = _fetch_live_events(cat, limit)

    if events:
        preview = [
            {
                "ID": e["market_id"],
                "Question": e["market_question"][:70],
                "Implied prob": f"{e['odds_after']:.1%}" if e.get("odds_after") is not None else "—",
            }
            for e in events[:limit]
        ]
        st.dataframe(preview, use_container_width=True, hide_index=True)
    else:
        st.warning("No live events loaded — check Jupiter API connectivity.")

    if st.button("▶ Ingest into Cognee", type="primary", disabled=not events):
        llm_key = os.environ.get("LLM_API_KEY", "")
        if not llm_key:
            st.error("Set LLM_API_KEY in .env before ingesting.")
        else:
            with st.spinner(f"Ingesting {min(limit, len(events))} events via cognee.add()… (FastEmbed, no LLM)"):
                try:
                    from ingest.loader import ingest
                    result = _run(ingest(events[:limit]))
                    st.success(
                        f"✅ {result['events_ingested']} events ingested  \n"
                        f"Dataset: `{result['dataset_name']}`  \n"
                        f"Status: `{result['status']}`  \n"
                        f"Time: {result['elapsed_seconds']}s"
                    )
                    st.info("Now go to **Analyze** to query the graph.")
                except Exception as e:
                    err = str(e)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        st.error(
                            "**Rate limited (429)** — unexpected during ingest (ingest uses no LLM).\n\n"
                            "This should not happen with the new cognee.add() pipeline. "
                            "Check the error details below."
                        )
                    else:
                        st.error(f"Ingest failed:\n```\n{err[:500]}\n```")


# ── ANALYZE ───────────────────────────────────────────────────────────────────

elif page == "🔍 Analyze":
    st.title("🔍 Analyze — Graph Recall")
    st.markdown(
        """
        Finds semantically similar past markets via `cognee.search(SearchType.CHUNKS)`,
        then makes **1 LLM call** to synthesize a trader brief from the retrieved context.
        """
    )

    st.info("Type a market ID (from Ingest) or pick from live markets below.")

    col1, col2 = st.columns([3, 1])
    with col1:
        market_id_input = st.text_input("Market ID", placeholder="e.g. POLY-287395")
    with col2:
        st.write("")
        load_live = st.button("Load live markets")

    selected_event = None

    if load_live or "live_events_analyze" in st.session_state:
        if load_live:
            with st.spinner("Loading live events…"):
                st.session_state["live_events_analyze"] = _fetch_live_events("all", 30)
        live = st.session_state.get("live_events_analyze", [])
        if live:
            opts = {f"{e['market_id']} — {e['market_question'][:65]}": e for e in live}
            choice = st.selectbox("Or pick from live", list(opts.keys()))
            selected_event = opts[choice]
            market_id_input = selected_event["market_id"]

    # If typed manually, find it
    if market_id_input and not selected_event:
        live = st.session_state.get("live_events_analyze", [])
        selected_event = next((e for e in live if e["market_id"] == market_id_input), None)
        if not selected_event:
            # Build a minimal stub so analyze can still run
            selected_event = {
                "market_id": market_id_input,
                "market_question": market_id_input,
                "category": "unknown",
            }

    if selected_event:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Category", selected_event.get("category", "—"))
        with col2:
            oa = selected_event.get("odds_after")
            st.metric("Implied prob", f"{oa:.1%}" if oa is not None else "—")
        with col3:
            st.metric("Status", selected_event.get("outcome", "pending"))

        st.markdown(f"**Question:** {selected_event.get('market_question', '—')}")

    if st.button("▶ Analyze", type="primary", disabled=not selected_event):
        with st.spinner("Querying knowledge graph…"):
            try:
                from agent.core import LoomAgent
                agent = LoomAgent()
                result = _run(agent.analyze(selected_event))

                brief = result["brief"]
                st.subheader("Brief (1 LLM call)")
                if "Graph is empty" in brief or "No analogous precedents" in brief:
                    st.warning(brief)
                    st.info("Run **Ingest** first to populate vector memory.")
                else:
                    st.success(brief)

                qa_id = result.get("qa_id")
                if qa_id:
                    st.session_state[f"qa_{selected_event['market_id']}"] = qa_id
                    st.caption(f"qa_id saved: `{qa_id[:16]}…` — go to **Learn** to record the outcome")

                chunks = result.get("chunks", [])
                with st.expander(f"Retrieved memory chunks ({len(chunks)} matches — FastEmbed cosine similarity)"):
                    if chunks:
                        for i, chunk in enumerate(chunks[:6], 1):
                            st.markdown(f"**[{i}]** {chunk[:400]}")
                    else:
                        st.text("[empty — no events ingested yet]")

            except Exception as e:
                st.error(f"Analyze failed:\n```\n{str(e)[:600]}\n```")


# ── LEARN ─────────────────────────────────────────────────────────────────────

elif page == "📚 Learn":
    st.title("📚 Learn — `session_manager.add_feedback()`")
    st.markdown(
        """
        Record the actual market outcome. Loom fetches the original recall answer from
        Cognee's session cache, scores it 1–5, and stores feedback via
        `session_manager.add_feedback()`. Returns **True** if the qa_id was found,
        **False** otherwise — reported honestly.
        """
    )

    market_id = st.text_input("Market ID", placeholder="e.g. POLY-287395")

    col1, col2 = st.columns(2)
    with col1:
        outcome = st.radio("Actual outcome", ["YES", "NO"], horizontal=True)
    with col2:
        score_label = st.select_slider(
            "Score override",
            options=["auto", "1 — wrong", "2 — poor", "3 — ok", "4 — good", "5 — perfect"],
            value="auto",
        )
    score_int = None if score_label == "auto" else int(score_label[0])
    feedback_text = st.text_input("Note (optional)", placeholder="e.g. Correctly called Fed hold")

    if st.button("▶ Record outcome", type="primary", disabled=not market_id):
        with st.spinner("Fetching session entry and recording feedback…"):
            try:
                from agent.core import LoomAgent
                result = _run(LoomAgent().learn_from_outcome(
                    market_id, outcome,
                    feedback_score=score_int,
                    feedback_text=feedback_text or None,
                ))

                n = result.get("qa_ids_found", 0)
                if n == 0:
                    st.warning(
                        f"No recall interactions found for `{market_id}`. "
                        "Run **Analyze** on this market first."
                    )
                else:
                    st.success(f"Feedback stored for {n} recall interaction(s).")
                    for fb in result.get("feedback_results", []):
                        icon = "✅" if fb["add_feedback_returned"] else "❌"
                        st.markdown(
                            f"{icon} `qa_id={fb['qa_id'][:10]}…` "
                            f"score **{fb['score']}/5** · "
                            f"`add_feedback` → **{fb['add_feedback_returned']}** · "
                            f"_{fb['reasoning']}_"
                        )
                    aw = result.get("apply_weights_result") or {}
                    if aw:
                        st.caption(f"apply_weights: {aw.get('note', aw)}")

            except Exception as e:
                st.error(f"Learn failed:\n```\n{str(e)[:500]}\n```")


# ── FORGET ────────────────────────────────────────────────────────────────────

elif page == "🗑️ Forget":
    st.title("🗑️ Forget — `cognee.forget()` pruning")
    st.markdown(
        """
        Identifies markets that were repeatedly recalled as analogies but consistently
        scored ≤ threshold — chronic false positives — and removes them from the graph.

        **Deletion semantics (from Cognee source):**
        - ✅ SQLite Data record removed
        - ✅ Unique graph nodes/edges removed
        - ⚠️ Shared entity nodes (e.g. "Federal Reserve") — *detagged only*, graph stays coherent
        """
    )

    col1, col2 = st.columns(2)
    with col1:
        min_fb = st.number_input("Min feedback entries to qualify", min_value=1, value=2)
    with col2:
        max_score = st.number_input("Max avg score (stale threshold)", min_value=1, max_value=5, value=2)

    col_dry, col_commit = st.columns(2)
    with col_dry:
        dry = st.button("🔍 Show candidates (dry-run)", use_container_width=True)
    with col_commit:
        commit = st.button("🗑️ Delete stale events", type="primary", use_container_width=True)

    if dry or commit:
        try:
            from memory.forget import find_stale_candidates, prune_stale_events
            candidates = find_stale_candidates(min_feedbacks=int(min_fb), max_score=float(max_score))

            if not candidates:
                st.info(
                    f"No stale events. Need ≥{int(min_fb)} feedback entries with avg score ≤{max_score} "
                    "on the same market. Run **Learn** a few times first."
                )
            else:
                st.warning(f"{len(candidates)} stale candidate(s):")
                for c in candidates:
                    st.markdown(
                        f"- **`{c['market_id']}`** — avg {c['avg_score']:.1f}/5 "
                        f"across {c['n_feedbacks']} feedbacks — _{c['reason']}_"
                    )

                if commit:
                    with st.spinner("Deleting…"):
                        result = _run(prune_stale_events(
                            reason="stale false-positive",
                            dry_run=False,
                            min_feedbacks=int(min_fb),
                            max_score=float(max_score),
                        ))
                    deleted = [r for r in result if r.get("status") == "deleted"]
                    not_found = [r for r in result if r.get("status") == "not_found"]
                    st.success(f"Deleted {len(deleted)} event(s).")
                    for r in deleted:
                        st.markdown(f"- ✅ `{r['market_id']}` · `data_id={r.get('data_id','?')}`")
                    for r in not_found:
                        st.markdown(f"- ⚠️ `{r['market_id']}` not found in dataset (not ingested?)")

        except Exception as e:
            st.error(f"Forget failed:\n```\n{str(e)[:500]}\n```")
