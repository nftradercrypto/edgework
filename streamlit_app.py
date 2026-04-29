"""Edgework — Streamlit app.

Wave 1 demo entry point. Lets a trader:
1. Upload (or paste) their SoDEX trade history as JSON or CSV
2. See conditional performance slices across time, behavior, regime
3. Generate an AI Briefing paragraph (combines edge + market context)

Deploy: Streamlit Community Cloud, free tier.
"""

from __future__ import annotations

import json
from io import StringIO

import pandas as pd
import plotly.express as px
import streamlit as st

from edgework import briefing, slicer
from edgework.config import get_settings
from edgework.sosovalue_client import SoSoValueClient


# --------------------------------------------------------------------------- #
# Page config
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="Edgework — trade analytics for pro traders",
    page_icon="▍",
    layout="wide",
)

# Brand colors (TokenBar palette)
BG = "#0a0a0a"
ACCENT = "#f5841f"
MUTED = "#999999"

st.markdown(
    f"""
    <style>
    .stApp {{ background-color: {BG}; }}
    h1, h2, h3 {{ color: white; letter-spacing: -0.02em; }}
    .accent {{ color: {ACCENT}; }}
    .muted {{ color: {MUTED}; }}
    .stMetric {{ background: rgba(245,132,31,0.04); padding: 12px;
                 border-left: 2px solid {ACCENT}; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #

st.markdown(
    f"""
    <div style="margin-bottom: 4px;">
      <span style="font-family: 'Space Mono', monospace; font-size: 11px;
                   letter-spacing: 0.2em; color: {ACCENT}; text-transform: uppercase;">
        ▍ Edgework
      </span>
    </div>
    <h1 style="margin-top: 0; font-weight: 800; font-size: 38px;">
      Trade analytics for <span class="accent">pro traders</span>.
    </h1>
    <p class="muted" style="max-width: 640px; margin-top: -4px;">
      PNL doesn't show you where your edge is. Edgework slices your SoDEX
      history across time, behavior, and market regime — so you know which
      setups make you money and which ones quietly bleed it.
    </p>
    """,
    unsafe_allow_html=True,
)

st.divider()


# --------------------------------------------------------------------------- #
# Sidebar — data input
# --------------------------------------------------------------------------- #

st.sidebar.header("Trade history")

source = st.sidebar.radio(
    "Data source",
    ["Upload file", "Paste JSON", "Use demo data"],
    index=2,
    help="Wave 1 prototype: upload your SoDEX history export, paste JSON, "
         "or explore with synthetic demo data.",
)

raw_orders: list[dict] = []

if source == "Upload file":
    f = st.sidebar.file_uploader("Orders / fills CSV or JSON", type=["csv", "json"])
    if f is not None:
        try:
            if f.name.endswith(".json"):
                raw_orders = json.loads(f.getvalue().decode("utf-8"))
            else:
                df = pd.read_csv(f)
                raw_orders = df.to_dict(orient="records")
        except Exception as e:  # noqa: BLE001
            st.sidebar.error(f"Could not parse file: {e}")

elif source == "Paste JSON":
    text = st.sidebar.text_area("JSON array of orders/fills", height=200)
    if text.strip():
        try:
            raw_orders = json.loads(text)
        except json.JSONDecodeError as e:
            st.sidebar.error(f"Invalid JSON: {e}")

else:
    # Synthetic demo data — same generator as the smoke test
    import numpy as np

    rng = np.random.default_rng(42)
    n = 200
    now = pd.Timestamp.now(tz="UTC")
    opens = pd.date_range(end=now, periods=n, freq="3h")
    holds = pd.to_timedelta(rng.exponential(60, size=n), unit="m")
    closes = opens + holds
    side = rng.choice(["long", "short"], size=n, p=[0.55, 0.45])
    base_pnl = pd.Series(
        np.where(
            side == "long",
            rng.normal(15, 80, n),
            rng.normal(-5, 80, n),
        )
    )
    night_penalty = pd.Series(
        np.where((opens.hour >= 23) | (opens.hour <= 3), -25, 0)
    )
    pnl = (base_pnl + night_penalty).to_numpy()
    raw_orders = pd.DataFrame(
        {
            "opened_at": opens,
            "closed_at": closes,
            "symbol": rng.choice(["BTC-USD", "ETH-USD", "SOL-USD"], n),
            "side": side,
            "entry_price": rng.uniform(20000, 70000, n),
            "exit_price": rng.uniform(20000, 70000, n),
            "size": rng.uniform(500, 5000, n),
            "pnl": pnl,
        }
    ).to_dict(orient="records")


if not raw_orders:
    st.info(
        "Pick a data source in the sidebar to begin. "
        "Demo mode shows what Edgework looks like with 200 synthetic trades.",
        icon="◇",
    )
    st.stop()


# --------------------------------------------------------------------------- #
# Normalize + slice
# --------------------------------------------------------------------------- #

trades = slicer.normalize_orders(raw_orders)

if trades.empty:
    st.error(
        "No usable trades found. Make sure the data has open/close timestamps "
        "and a realized PNL field."
    )
    st.stop()

overall = slicer.overall(trades)
slices = slicer.slice_all(trades)


# --------------------------------------------------------------------------- #
# Top metrics row
# --------------------------------------------------------------------------- #

c1, c2, c3, c4 = st.columns(4)
c1.metric("Trades", f"{overall.n_trades}")
c2.metric("Winrate", f"{overall.winrate:.1%}")
c3.metric("Expectancy", f"${overall.expectancy:.2f}")
c4.metric("Total PNL", f"${overall.total_pnl:,.0f}")

st.divider()


# --------------------------------------------------------------------------- #
# Conditional Performance Mapping
# --------------------------------------------------------------------------- #

st.subheader("Conditional performance")
st.markdown(
    "<p class='muted'>Where you make money, and where you give it back.</p>",
    unsafe_allow_html=True,
)

tab_hour, tab_streak, tab_size, tab_hold, tab_side = st.tabs(
    ["By hour", "By streak", "By size", "By hold", "By side"]
)


def _expectancy_chart(df: pd.DataFrame, x: str, title: str):
    """Render an expectancy bar chart with sample-size annotation."""
    if df.empty:
        st.info("Not enough trades to compute this slice.")
        return
    fig = px.bar(
        df,
        x=x,
        y="expectancy",
        text="n_trades",
        color="expectancy",
        color_continuous_scale=["#cc4422", "#444", "#22cc66"],
        color_continuous_midpoint=0,
    )
    fig.update_traces(texttemplate="n=%{text}", textposition="outside")
    fig.update_layout(
        title=title,
        plot_bgcolor=BG,
        paper_bgcolor=BG,
        font=dict(color="white"),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#1a1a1a", title="Expectancy ($)"),
        coloraxis_showscale=False,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)


with tab_hour:
    _expectancy_chart(slices["hour_of_day"], "hour", "Expectancy by hour of day (UTC)")
    st.dataframe(slices["hour_of_day"], use_container_width=True, hide_index=True)

with tab_streak:
    st.markdown(
        "<p class='muted'>Trades grouped by how many losses came right before. "
        "If '2L' or '4L+' is much worse than 'fresh', you're revenge-trading.</p>",
        unsafe_allow_html=True,
    )
    _expectancy_chart(
        slices["consecutive_losses"], "streak_bucket",
        "Expectancy by losing-streak state",
    )
    st.dataframe(
        slices["consecutive_losses"], use_container_width=True, hide_index=True
    )

with tab_size:
    _expectancy_chart(
        slices["size_quartile"], "size_quartile",
        "Expectancy by your own size quartile",
    )
    st.dataframe(slices["size_quartile"], use_container_width=True, hide_index=True)

with tab_hold:
    _expectancy_chart(
        slices["hold_duration"], "hold_bucket",
        "Expectancy by hold duration",
    )
    st.dataframe(slices["hold_duration"], use_container_width=True, hide_index=True)

with tab_side:
    _expectancy_chart(slices["side"], "side", "Expectancy by side")
    st.dataframe(slices["side"], use_container_width=True, hide_index=True)


st.divider()


# --------------------------------------------------------------------------- #
# AI Briefing
# --------------------------------------------------------------------------- #

st.subheader("Pre-session briefing")
st.markdown(
    "<p class='muted'>Your edge + today's regime, condensed into one paragraph. "
    "Powered by Anthropic Claude with live SoSoValue data.</p>",
    unsafe_allow_html=True,
)

if st.button("Generate today's briefing", type="primary"):
    s = get_settings()
    if not s.anthropic_api_key:
        st.error("Set ANTHROPIC_API_KEY in your .env to generate briefings.")
    else:
        with st.spinner("Pulling market context and generating…"):
            try:
                with SoSoValueClient() as soso:
                    market_ctx = (
                        briefing.build_market_context_from_sosovalue(soso)
                        if s.sosovalue_api_key
                        else briefing.MarketContext(
                            btc_dominance=None,
                            btc_etf_net_flow_usd=None,
                            eth_etf_net_flow_usd=None,
                            top_sector_24h=None,
                            bottom_sector_24h=None,
                            news_sentiment=None,
                            notable_news=None,
                            btc_regime=None,
                        )
                    )
                edge = briefing.extract_trader_edge(overall, slices)
                paragraph = briefing.generate_briefing(edge, market_ctx)
                st.markdown(
                    f"""
                    <div style="border-left: 3px solid {ACCENT};
                                padding: 16px 20px;
                                background: rgba(245,132,31,0.04);
                                margin-top: 8px;
                                font-size: 16px;
                                line-height: 1.6;
                                color: #ddd;">
                      {paragraph}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            except Exception as e:  # noqa: BLE001
                st.error(f"Briefing failed: {e}")


st.divider()
st.caption(
    "Edgework — Wave 1 prototype · "
    "[GitHub](https://github.com/nftradercrypto/edgework) · "
    "Built solo by @nftradercrypto for the SoSoValue Buildathon."
)
