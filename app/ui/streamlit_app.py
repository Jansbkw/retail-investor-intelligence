from __future__ import annotations

import html
import sys
from pathlib import Path

import httpx
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings


st.set_page_config(page_title="Curation · Investor Intelligence", page_icon="◉", layout="wide")
st.markdown(
    """
<style>
  :root {--ink:#132a2a; --muted:#657474; --paper:#f5f5ef; --card:#fff;
         --line:#dde3dd; --green:#165c4c; --mint:#dff1e9;}
  .stApp {background:var(--paper); color:var(--ink);}
  .block-container {max-width:1160px; padding:2rem 2rem 4rem;}
  #MainMenu, footer, header [data-testid="stHeaderActionElements"] {visibility:hidden;}
  h1, h2, h3 {color:var(--ink); letter-spacing:-.025em;}
  h1 {font-size:2.45rem !important; line-height:1.08 !important;}
  .brand {font-size:.78rem; font-weight:800; letter-spacing:.16em; color:var(--green);
          text-transform:uppercase; margin-bottom:3.8rem;}
  .hero {max-width:760px; margin:0 auto 2.2rem; text-align:center;}
  .hero h1 {font-size:3.25rem !important; margin:.35rem 0 .8rem;}
  .hero p {font-size:1.08rem; color:var(--muted); line-height:1.65;}
  .eyebrow {font-size:.75rem; letter-spacing:.14em; text-transform:uppercase;
            color:var(--green); font-weight:800;}
  .identity-line {color:var(--muted); font-size:.95rem; margin-top:-.6rem;}
  .ticker-pill {display:inline-block; border-radius:999px; padding:.28rem .68rem;
                background:var(--mint); color:var(--green); font-weight:800;
                font-size:.82rem; letter-spacing:.05em; vertical-align:middle;}
  .verified {display:inline-block; color:var(--green); font-weight:700; font-size:.82rem;}
  [data-testid="stTextInputRootElement"] {background:white; border-radius:14px;}
  [data-testid="stVerticalBlockBorderWrapper"] {background:var(--card) !important;
    border:1px solid var(--line) !important; border-radius:16px !important;
    box-shadow:0 7px 24px rgba(19,42,42,.035);}
  [data-testid="stMetric"] {background:white; border:1px solid var(--line);
    padding:1rem 1.1rem; border-radius:14px; min-height:128px;}
  [data-testid="stMetricLabel"] {color:var(--muted);}
  .result-name {font-size:1.08rem; font-weight:750; color:var(--ink); margin-bottom:.3rem;}
  .result-meta, .section-note {font-size:.88rem; color:var(--muted);}
  .headline {font-size:1.5rem; line-height:1.35; font-weight:680; margin:.1rem 0 1.4rem;}
  .coverage-box {border-radius:18px; padding:2rem; background:linear-gradient(135deg,#fff8e9,#fff);
                 border:1px solid #ead9b5; margin:1.2rem 0 2rem;}
  .coverage-box h2 {margin:.35rem 0 .5rem; font-size:1.55rem;}
  .coverage-box p {color:#6e624d; max-width:760px; line-height:1.6;}
  .evidence {border:1px solid var(--line); border-radius:14px; padding:1rem 1.1rem;
             margin:.65rem 0; background:white; line-height:1.55;}
  .meta {font-size:.78rem; color:var(--muted); margin-bottom:.5rem; text-transform:capitalize;}
  .stButton > button {border-radius:10px; font-weight:700;}
  .stButton > button[kind="primary"] {background:var(--green); border-color:var(--green);}
  [data-baseweb="tab-list"] {gap:1.2rem; border-bottom:1px solid var(--line);}
  [data-baseweb="tab"] {padding-left:0; padding-right:0;}
  @media (max-width:700px) {
    .block-container {padding:1.2rem 1rem 3rem;} .brand {margin-bottom:2.3rem;}
    .hero h1 {font-size:2.25rem !important;} h1 {font-size:2rem !important;}
  }
</style>
""",
    unsafe_allow_html=True,
)

API = get_settings().api_base_url.rstrip("/")


@st.cache_data(ttl=20, show_spinner=False)
def api_get(path: str, params: dict | None = None):
    response = httpx.get(f"{API}{path}", params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def api_available() -> bool:
    try:
        api_get("/health")
        return True
    except Exception:
        return False


def evidence_card(item: dict, *, show_engagement: bool = False) -> None:
    sentiment = item.get("sentiment") or item.get("sentiment_label") or "Not analysed"
    metadata = f"{item['source']} · {item['created_at'][:16].replace('T', ' ')} UTC · {sentiment}"
    if show_engagement:
        engagement = "unknown" if item.get("engagement") is None else str(item["engagement"])
        metadata += f" · engagement {engagement}"
    st.markdown(
        f'<div class="evidence"><div class="meta">{html.escape(metadata)}</div>'
        f'{html.escape(item["text"])}<br><a href="{html.escape(item["source_url"], quote=True)}" '
        'target="_blank">View original evidence ↗</a></div>',
        unsafe_allow_html=True,
    )


def company_picker() -> None:
    st.markdown('<div class="brand">◉ Curation · Investor Intelligence</div>', unsafe_allow_html=True)
    st.markdown(
        """<div class="hero"><div class="eyebrow">Retail investor intelligence</div>
        <h1>Find a listed company</h1>
        <p>Search by ticker or company name. We verify the exchange-qualified company before
        showing any discussion, so identical tickers are never mixed.</p></div>""",
        unsafe_allow_html=True,
    )
    query = st.text_input(
        "Search by ticker or company name", key="company_search",
        placeholder="Try STB, TTWO or VEON", label_visibility="collapsed",
    )
    try:
        results = api_get("/companies/search", {"q": query})
    except Exception:
        st.error("The intelligence service is not running yet. Please refresh in a moment.")
        return

    label = f"{len(results)} verified result{'s' if len(results) != 1 else ''}" if query else "Available companies"
    st.markdown(f"<p class='section-note'>{html.escape(label)}</p>", unsafe_allow_html=True)
    if not results:
        st.info("No verified company matches that search. Try a ticker or full company name.")
        return

    for company in results:
        with st.container(border=True):
            info, action = st.columns([5, 1.25], vertical_alignment="center")
            with info:
                isin = f' · ISIN {html.escape(company["isin"])}' if company.get("isin") else ""
                st.markdown(
                    f'<div class="result-name">{html.escape(company["name"])} '
                    f'<span class="ticker-pill">{html.escape(company["ticker"])}</span></div>'
                    f'<div class="result-meta">{html.escape(company["exchange"])} · '
                    f'{html.escape(company["country"])}{isin}</div>',
                    unsafe_allow_html=True,
                )
            with action:
                if st.button("View company", key=f"select_{company['company_id']}", width="stretch"):
                    st.session_state.selected_company_id = company["company_id"]
                    st.rerun()

    if query.strip().upper() == "STB":
        st.caption(
            "STB is used by multiple listed companies. Choose the exchange-qualified company you mean; "
            "their records and analysis remain completely separate."
        )


def coverage_summary(items: list[dict]) -> None:
    if not items:
        st.caption("No collection run has been recorded for this company.")
        return
    labels = []
    for item in items:
        icon = "●" if item["status"] == "success" else "○"
        labels.append(f"{icon} {item['source'].title()} · {item['status'].replace('_', ' ')}")
    st.caption("    ".join(labels))


def limited_coverage(company: dict, overview: dict) -> None:
    st.markdown(
        """<div class="coverage-box"><div class="eyebrow">Limited coverage</div>
        <h2>Company identity verified</h2>
        <p>No matching investor discussions were retrieved from the connected sources for this
        company and time window. This does not mean investors are not discussing it elsewhere.</p></div>""",
        unsafe_allow_html=True,
    )
    left, right = st.columns([1, 1.5])
    with left:
        st.metric("Verified discussions", 0)
    with right:
        st.markdown("#### Why this matters")
        if company["ticker"] == "STB":
            st.write(
                "Ticker symbols are not globally unique. The system excluded records belonging to "
                "other STB companies instead of producing misleading intelligence."
            )
        else:
            st.write("The current public sources returned no evidence that passed company and investor-relevance checks.")
    st.markdown("#### Source coverage")
    coverage_summary(overview["coverage"])
    st.caption("Coverage gaps are shown explicitly; the product never fills them with synthetic posts.")


def dashboard(company_id: str) -> None:
    try:
        company = api_get(f"/companies/{company_id}")
    except Exception:
        st.session_state.pop("selected_company_id", None)
        st.rerun()

    top_left, top_right = st.columns([5, 1])
    with top_left:
        st.markdown('<div class="brand" style="margin-bottom:1.4rem">◉ Curation · Investor Intelligence</div>', unsafe_allow_html=True)
    with top_right:
        if st.button("← Change company", width="stretch"):
            st.session_state.pop("selected_company_id", None)
            st.rerun()

    st.markdown('<div class="eyebrow">Company intelligence</div>', unsafe_allow_html=True)
    st.title(company["name"])
    identity = f"{company['exchange']}: {company['ticker']} · {company['country']}"
    if company.get("isin"):
        identity += f" · ISIN {company['isin']}"
    st.markdown(
        f'<div class="identity-line">{html.escape(identity)} &nbsp; '
        '<span class="verified">✓ Identity verified</span></div>', unsafe_allow_html=True,
    )

    _, control = st.columns([4, 1])
    with control:
        days = st.selectbox("Time window", [7, 30, 90], index=1, format_func=lambda value: f"Last {value} days")
    try:
        overview = api_get("/analytics/overview", {"company_id": company_id, "days": days})
    except Exception:
        st.error("The analytics service is temporarily unavailable. Please refresh in a moment.")
        return

    if overview["coverage_status"] == "limited":
        limited_coverage(company, overview)
        return

    overview_tab, evidence_tab = st.tabs(["Overview", "Evidence"])
    with overview_tab:
        coverage_summary(overview["coverage"])
        st.markdown(f'<div class="headline">{html.escape(overview["headline"])}</div>', unsafe_allow_html=True)
        a, b, c, d = st.columns(4)
        a.metric("Relevant discussions", overview["sample_size"])
        leading = max(overview["sentiment"], key=overview["sentiment"].get) if overview["sentiment"] else "Not analysed"
        b.metric("Leading sentiment", leading)
        c.metric("Top theme", overview["topics"][0]["name"] if overview["topics"] else "Not analysed")
        d.metric("Latest evidence", (overview["freshness"] or "No data")[:10])

        left, right = st.columns([1.05, 1])
        with left:
            st.subheader("Investor mood")
            if overview["sentiment"]:
                st.bar_chart(overview["sentiment"], horizontal=True)
                st.caption(f"Based on {overview['analysed_count']} AI-analysed records · trend {overview['mood_direction']}.")
            else:
                st.info("Relevant evidence exists, but AI enrichment has not run yet.")
        with right:
            st.subheader("What deserves attention")
            if overview["concerns"]:
                for concern in overview["concerns"][:5]:
                    st.markdown(f"**{concern['name']}**  ·  {concern['count']} supporting record(s)")
            else:
                st.info("No supported investor concerns have been classified yet.")

        st.subheader("Discussion themes")
        if overview["topics"]:
            st.bar_chart({item["name"]: item["count"] for item in overview["topics"]}, horizontal=True)
        else:
            st.caption("No topic analysis is available yet.")

        st.subheader("Ask the evidence")
        st.caption("Answers use only the selected company’s retrieved posts and include citations.")
        question = st.text_input(
            "Question", placeholder=f"What are investors most concerned about for {company['ticker']}?",
            label_visibility="collapsed",
        )
        if st.button("Ask question", type="primary", disabled=not question):
            with st.spinner("Reviewing the evidence…"):
                try:
                    response = httpx.post(
                        f"{API}/ask", json={"company_id": company_id, "question": question}, timeout=45,
                    )
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
                    st.error("The question could not be answered. No unsupported answer was generated.")
        st.caption(overview["caveat"])

    with evidence_tab:
        st.subheader("Source evidence")
        st.caption("Inspect the public posts behind the classifications and summaries.")
        c1, c2, c3 = st.columns(3)
        source = c1.selectbox("Source", ["All", "stocktwits", "youtube", "hackernews", "x"])
        sentiment = c2.selectbox("Sentiment", ["All", "Bullish", "Bearish", "Neutral", "Unclear / Not investment-related"])
        search = c3.text_input("Search evidence")
        params = {"company_id": company_id, "days": days}
        if source != "All": params["source"] = source
        if sentiment != "All": params["sentiment"] = sentiment
        if search: params["search"] = search
        records = api_get("/discussions", params)
        st.caption(f"{len(records)} matching record(s)")
        if not records:
            st.info("No evidence matches these filters.")
        for item in records:
            evidence_card(item)


if not api_available():
    st.error("The local intelligence service is not running. Start the API and refresh this page.")
elif st.session_state.get("selected_company_id"):
    dashboard(st.session_state.selected_company_id)
else:
    company_picker()
