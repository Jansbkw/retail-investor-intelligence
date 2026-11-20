from __future__ import annotations

import html
import sys
from pathlib import Path

import httpx
import streamlit as st

# Streamlit executes this file as a script, so the repository root is not always
# present on sys.path (notably in fresh virtual environments and containers).
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings


st.set_page_config(page_title="Investor Intelligence", page_icon="◉", layout="wide")
st.markdown("""
<style>
  .block-container {max-width: 1180px; padding-top: 2rem;}
  [data-testid="stMetric"] {background:#f7f8fa; border:1px solid #e7e9ee; padding:16px; border-radius:12px;}
  .eyebrow {font-size:.75rem; letter-spacing:.12em; text-transform:uppercase; color:#667085; font-weight:700;}
  .headline {font-size:1.65rem; line-height:1.25; font-weight:650; margin:.25rem 0 1.2rem; color:#17202a;}
  .evidence {border:1px solid #e7e9ee; border-radius:12px; padding:16px; margin:8px 0; background:white;}
  .meta {font-size:.8rem; color:#667085; margin-bottom:7px;}
  @media (max-width: 600px) {.headline {font-size:1.25rem;} .block-container {padding:1rem;}}
</style>
""", unsafe_allow_html=True)

API = get_settings().api_base_url.rstrip("/")


@st.cache_data(ttl=30, show_spinner=False)
def api_get(path: str, params: dict | None = None):
    response = httpx.get(f"{API}{path}", params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def source_badges(coverage: list[dict]) -> None:
    labels = []
    for item in coverage:
        icon = "●" if item["status"] == "success" else "○"
        labels.append(f"{icon} {item['source'].title()}: {item['status'].replace('_', ' ')}")
    st.caption("   ·   ".join(labels) if labels else "No collection run recorded")
    issues = [item for item in coverage if item.get("error") or item.get("limitations") or item.get("restrictions")]
    if issues:
        with st.expander("Coverage details"):
            for item in issues:
                detail = item.get("error") or item.get("limitations") or item.get("restrictions")
                st.markdown(f"**{item['source'].title()} — {item['status'].replace('_', ' ')}:** {detail}")


def evidence_card(item: dict, *, show_engagement: bool = False) -> None:
    sentiment = item.get("sentiment") or item.get("sentiment_label") or "Not analysed"
    metadata = f"{item['source'].title()} · {item['created_at'][:16].replace('T', ' ')} UTC · {sentiment}"
    if show_engagement:
        engagement = "unknown" if item.get("engagement") is None else str(item["engagement"])
        metadata += f" · engagement {engagement}"
    st.markdown(
        f'<div class="evidence"><div class="meta">{html.escape(metadata)}</div>'
        f'{html.escape(item["text"])}<br><a href="{html.escape(item["source_url"], quote=True)}" '
        f'target="_blank">Open original evidence ↗</a></div>',
        unsafe_allow_html=True,
    )


st.sidebar.markdown("### Investor Intelligence")
page = st.sidebar.radio("View", ["Overview", "Discussions"], label_visibility="collapsed")
ticker = st.sidebar.selectbox("Company", ["TTWO", "VEON", "STB"])
days = st.sidebar.selectbox("Analysis window", [7, 30, 90], index=1, format_func=lambda value: f"Last {value} days")

try:
    overview = api_get("/analytics/overview", {"ticker": ticker, "days": days})
except Exception:
    st.error("The analytics API is unavailable. Start it with `uvicorn app.api.main:app --reload` and refresh.")
    st.stop()

if page == "Overview":
    st.markdown('<div class="eyebrow">Retail investor pulse</div>', unsafe_allow_html=True)
    company = next((item for item in api_get("/companies") if item["ticker"] == ticker), None)
    st.title(f"{ticker} · {company['name'] if company else ''}")
    st.caption("Real public-data snapshot · Source text preserved · Synthetic data: none")
    source_badges(overview["coverage"])
    st.markdown(f'<div class="headline">{overview["headline"]}</div>', unsafe_allow_html=True)

    a, b, c, d = st.columns(4)
    a.metric("Relevant discussions", overview["sample_size"], help=f"Public posts retained after relevance filtering; {overview['analysed_count']} AI-analysed.")
    if overview.get("pending_candidate_count"):
        a.caption(f"{overview['pending_candidate_count']} additional comments await AI relevance review.")
    leading = max(overview["sentiment"], key=overview["sentiment"].get) if overview["sentiment"] else "Not analysed"
    b.metric("Leading sentiment", leading)
    b.caption(f"Direction: {overview['mood_direction']}")
    c.metric("Top theme", overview["topics"][0]["name"] if overview["topics"] else "Not analysed")
    c.caption(f"n={overview['topics'][0]['count']}" if overview["topics"] else "")
    d.metric("Latest evidence", (overview["freshness"] or "No data")[:10])

    left, right = st.columns([1.1, 1])
    with left:
        st.subheader("Sentiment")
        if overview["sentiment"]:
            st.bar_chart(overview["sentiment"], horizontal=True)
            st.caption(f"Based on {overview['analysed_count']} AI-analysed relevant records.")
        elif overview["sample_size"]:
            st.info("Relevant records exist, but AI enrichment has not been run.")
        else:
            st.info("No relevant records are available from the current sources and time window.")
    with right:
        st.subheader("What deserves attention")
        if overview["concerns"]:
            for concern in overview["concerns"][:5]:
                st.markdown(f"**{concern['name']}**  ·  {concern['count']} supporting record(s)")
        elif overview["sample_size"]:
            st.info("No supported investor concerns have been classified yet.")
        else:
            st.info("No relevant evidence is available for this company and period.")

    st.subheader("Discussion themes")
    if overview["topics"]:
        st.bar_chart({item["name"]: item["count"] for item in overview["topics"]}, horizontal=True)
    else:
        st.caption("No topic analysis available.")

    st.subheader("Discussion volume")
    if overview["volume"]:
        st.line_chart(overview["volume"], x="date", y="count")
    else:
        st.info("No relevant discussion was found in the available sources.")

    st.subheader("Evidence")
    for item in overview["evidence"][:5]:
        evidence_card(item, show_engagement=True)

    st.subheader("Ask about investor discussions")
    question = st.text_input("Question", placeholder=f"What are investors most concerned about for {ticker}?", label_visibility="collapsed")
    if st.button("Ask", type="primary", disabled=not question):
        with st.spinner("Reviewing the collected evidence…"):
            try:
                response = httpx.post(f"{API}/ask", json={"ticker": ticker, "question": question}, timeout=45)
                response.raise_for_status()
                answer = response.json()
                st.write(answer["answer"])
                for finding in answer.get("supporting_findings", []):
                    st.markdown(f"- {finding}")
                for citation in answer.get("citations", []):
                    st.markdown(f"[{citation['post_id']}]({citation['url']})")
                if answer.get("limitations"):
                    st.caption(answer["limitations"])
            except Exception:
                st.error("The question could not be answered right now. No unsupported answer was generated.")
    st.caption(overview["caveat"])

else:
    st.title(f"{ticker} discussions")
    st.caption("Inspect the public evidence behind the overview classifications.")
    c1, c2, c3 = st.columns(3)
    source = c1.selectbox("Source", ["All", "stocktwits", "youtube", "x"])
    sentiment = c2.selectbox("Sentiment", ["All", "Bullish", "Bearish", "Neutral", "Unclear / Not investment-related"])
    search = c3.text_input("Search")
    params = {"ticker": ticker, "days": days}
    if source != "All": params["source"] = source
    if sentiment != "All": params["sentiment"] = sentiment
    if search: params["search"] = search
    records = api_get("/discussions", params)
    st.caption(f"{len(records)} matching record(s)")
    if not records:
        st.info("No relevant evidence matches these filters.")
    for item in records:
        evidence_card(item)
