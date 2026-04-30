"""Edgework — Streamlit app.

Wave 1 demo entry point. Lets a trader:
1. Load their SoDEX trade history (cached parquet, parquet/CSV/JSON upload, or demo data)
2. See conditional performance: stat cards highlight the extremes, waterfall
   shows total PNL contribution per slice
3. Generate an AI Briefing paragraph (combines edge + market context)

Deploy: Streamlit Community Cloud, free tier.
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from edgework import briefing, slicer
from edgework.config import get_settings
from edgework.sosovalue_client import SoSoValueClient


# --------------------------------------------------------------------------- #
# Page config + brand palette
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="Edgework — trade analytics for pro traders",
    page_icon="▍",
    layout="wide",
    initial_sidebar_state="expanded",
)

BG = "#0a0a0a"
PANEL = "#141414"
ACCENT = "#f5841f"
ACCENT_DIM = "rgba(245,132,31,0.06)"
TEXT = "#ffffff"
MUTED = "#888888"
GREEN = "#22cc66"
RED = "#cc4422"
NEUTRAL = "#555555"
GRID = "#1f1f1f"


st.markdown(
    f"""
    <style>
    h1, h2, h3, h4 {{ color: {TEXT} !important; letter-spacing: -0.01em; }}

    [data-testid="stMetricLabel"] {{
        color: {MUTED} !important;
        font-size: 11px !important;
        text-transform: uppercase;
        letter-spacing: 0.15em;
    }}
    [data-testid="stMetricValue"] {{
        color: {TEXT} !important;
        font-weight: 800 !important;
    }}

    [data-baseweb="tab-list"] {{
        gap: 8px;
        border-bottom: 1px solid {GRID};
    }}
    [data-baseweb="tab"] {{
        color: {MUTED} !important;
        font-weight: 500;
    }}
    [data-baseweb="tab"][aria-selected="true"] {{
        color: {ACCENT} !important;
        font-weight: 700;
    }}

    [data-testid="stSidebar"] h2 {{
        color: {ACCENT} !important;
        font-size: 14px !important;
        text-transform: uppercase;
        letter-spacing: 0.18em;
    }}

    .stButton > button {{
        background: {ACCENT} !important;
        color: #000 !important;
        border: none !important;
        font-weight: 700 !important;
        letter-spacing: 0.04em;
    }}
    .stButton > button:hover {{
        background: #ffa340 !important;
    }}

    hr {{ border-color: {GRID} !important; }}

    [data-testid="stDataFrame"] {{ border: 1px solid {GRID}; }}

    .edgework-brand {{
        font-family: 'Space Mono', ui-monospace, monospace;
        font-size: 11px;
        letter-spacing: 0.25em;
        color: {ACCENT};
        text-transform: uppercase;
        margin-bottom: 4px;
    }}
    .edgework-headline {{
        font-size: 38px;
        font-weight: 800;
        letter-spacing: -0.02em;
        line-height: 1.05;
        margin: 0 0 8px 0;
        color: {TEXT};
    }}
    .edgework-headline .accent {{ color: {ACCENT}; }}
    .edgework-sub {{
        color: {MUTED};
        max-width: 720px;
        font-size: 15px;
        line-height: 1.5;
    }}

    /* Stat card grid */
    .ew-card-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
        margin: 12px 0 24px 0;
    }}
    .ew-card {{
        background: {PANEL};
        border-radius: 6px;
        padding: 14px 16px;
        border-left: 3px solid {NEUTRAL};
    }}
    .ew-card.win {{ border-left-color: {GREEN}; }}
    .ew-card.loss {{ border-left-color: {RED}; }}
    .ew-card-tag {{
        font-family: 'Space Mono', ui-monospace, monospace;
        font-size: 10px;
        letter-spacing: 0.2em;
        color: {ACCENT};
        text-transform: uppercase;
        margin-bottom: 4px;
    }}
    .ew-card-label {{
        font-family: 'Space Mono', ui-monospace, monospace;
        font-size: 11px;
        letter-spacing: 0.15em;
        color: {MUTED};
        text-transform: uppercase;
        margin-bottom: 6px;
    }}
    .ew-card-value {{
        font-size: 24px;
        font-weight: 700;
        line-height: 1;
        margin-bottom: 4px;
        color: {MUTED};
    }}
    .ew-card-value.win {{ color: {GREEN}; }}
    .ew-card-value.loss {{ color: {RED}; }}
    .ew-card-meta {{
        font-size: 12px;
        color: {MUTED};
        line-height: 1.5;
    }}
    .ew-card-meta .strong {{ color: {TEXT}; font-weight: 600; }}
    .ew-card-meta .pos {{ color: {GREEN}; font-weight: 600; }}
    .ew-card-meta .neg {{ color: {RED}; font-weight: 600; }}

    .edgework-briefing {{
        border-left: 3px solid {ACCENT};
        padding: 18px 22px;
        background: {ACCENT_DIM};
        font-size: 16px;
        line-height: 1.65;
        color: #eaeaea;
        margin-top: 8px;
        border-radius: 0 6px 6px 0;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #

st.markdown(
    """
    <div class="edgework-brand">▍ Edgework</div>
    <h1 class="edgework-headline">Trade analytics for <span class="accent">pro traders</span>.</h1>
    <p class="edgework-sub">
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

EXAMPLE_ADDRESS = "0x2d74A7CC2E31D85bf3988c3F62B593521362f83B"


def _is_valid_evm_address(addr: str) -> bool:
    """Check that the string looks like a 0x-prefixed 40-hex-char EVM address."""
    if not addr or not isinstance(addr, str):
        return False
    addr = addr.strip()
    if not addr.startswith("0x") or len(addr) != 42:
        return False
    try:
        int(addr[2:], 16)
        return True
    except ValueError:
        return False


with st.sidebar:
    st.header("Trade history")

    parquet_path = Path("data/history.parquet")
    has_cached = parquet_path.exists()

    options = ["From wallet address"]
    if has_cached:
        options.append("Cached file (data/history.parquet)")
    options += ["Upload file", "Use demo data"]

    source = st.radio(
        "Data source",
        options,
        index=0,
        help=(
            "Paste any SoDEX wallet address to pull its closed positions live "
            "from the public API. No login or signature required."
        ),
    )

    if has_cached:
        modtime = pd.Timestamp(parquet_path.stat().st_mtime, unit="s", tz="UTC")
        st.caption(
            f"Cached file last updated: {modtime.strftime('%Y-%m-%d %H:%M UTC')}"
        )

    st.markdown("---")
    st.caption(
        "Wave 1 prototype · "
        "[GitHub](https://github.com/nftradercrypto/edgework)"
    )


# --------------------------------------------------------------------------- #
# Load data
# --------------------------------------------------------------------------- #

raw_orders: list[dict] = []
trades: pd.DataFrame | None = None

# Stable session-state cache so we don't re-fetch on every interaction.
if "wallet_cache" not in st.session_state:
    st.session_state.wallet_cache = {}  # {address: DataFrame}


if source == "From wallet address":
    st.markdown(
        "<h3 style='margin-top: 0;'>Pull live SoDEX history</h3>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Paste any wallet address that has traded perpetuals on SoDEX. "
        "Edgework will fetch the closed positions directly from the public API."
    )

    col_input, col_btn = st.columns([4, 1])
    with col_input:
        address = st.text_input(
            "Wallet address",
            value=st.session_state.get("active_address", ""),
            placeholder="0x...",
            label_visibility="collapsed",
        )
    with col_btn:
        fetch_clicked = st.button("Fetch", use_container_width=True)

    st.caption(
        f"Try the demo address: `{EXAMPLE_ADDRESS}` "
        "(top-3 weekly volume trader, 277 closed positions in the last 30 days)."
    )

    if fetch_clicked:
        addr_clean = address.strip()
        if not _is_valid_evm_address(addr_clean):
            st.error(
                "That doesn't look like a valid EVM address. "
                "Expected format: `0x` followed by 40 hex characters."
            )
        elif addr_clean in st.session_state.wallet_cache:
            st.session_state.active_address = addr_clean
            st.toast(f"Loaded cached history for {addr_clean[:10]}…")
        else:
            with st.spinner(f"Fetching positions for {addr_clean[:10]}…"):
                try:
                    from edgework.sodex_client import SodexClient

                    end_ms = int(pd.Timestamp.utcnow().value // 1_000_000)
                    start_ms = end_ms - 90 * 86_400_000

                    with SodexClient(user_address=addr_clean) as c:
                        positions = c.get_position_history(
                            start_ms=start_ms,
                            end_ms=end_ms,
                            limit=500,
                        )

                    if not positions:
                        st.warning(
                            "No closed positions found for this address in "
                            "the last 90 days. The wallet may not have traded "
                            "on SoDEX, or the address is incorrect."
                        )
                    else:
                        df = slicer.normalize_orders(positions)
                        st.session_state.wallet_cache[addr_clean] = df
                        st.session_state.active_address = addr_clean
                        st.success(f"Loaded {len(df)} closed positions.")
                except Exception as e:  # noqa: BLE001
                    st.error(f"Could not fetch history: {e}")

    # Pull whichever address is currently active
    active = st.session_state.get("active_address")
    if active and active in st.session_state.wallet_cache:
        trades = st.session_state.wallet_cache[active]
        st.caption(
            f"Showing data for **`{active}`** "
            f"(fetched {len(trades)} positions)."
        )

elif source.startswith("Cached file"):
    try:
        trades = pd.read_parquet(parquet_path)
    except Exception as e:  # noqa: BLE001
        st.error(f"Could not read cached parquet: {e}")
        st.stop()

elif source == "Upload file":
    f = st.sidebar.file_uploader(
        "Trade history (parquet, CSV, or JSON)",
        type=["parquet", "csv", "json"],
    )
    if f is not None:
        try:
            if f.name.endswith(".parquet"):
                trades = pd.read_parquet(BytesIO(f.getvalue()))
            elif f.name.endswith(".json"):
                raw_orders = json.loads(f.getvalue().decode("utf-8"))
            else:
                raw = pd.read_csv(f)
                raw_orders = raw.to_dict(orient="records")
        except Exception as e:  # noqa: BLE001
            st.sidebar.error(f"Could not parse file: {e}")

else:  # Use demo data
    rng = np.random.default_rng(42)
    n = 200
    now = pd.Timestamp.now(tz="UTC")
    opens = pd.date_range(end=now, periods=n, freq="3h")
    holds = pd.to_timedelta(rng.exponential(60, size=n), unit="m")
    closes = opens + holds
    side = rng.choice(["LONG", "SHORT"], size=n, p=[0.55, 0.45])
    base_pnl = np.where(
        side == "LONG", rng.normal(15, 80, n), rng.normal(-5, 80, n)
    )
    night_penalty = np.where((opens.hour >= 23) | (opens.hour <= 3), -25, 0)
    pnl = base_pnl + night_penalty
    raw_orders = pd.DataFrame(
        {
            "createdAt": (opens.astype("int64") // 1_000_000),
            "updatedAt": (closes.astype("int64") // 1_000_000),
            "symbol": rng.choice(["BTC-USD", "ETH-USD", "SOL-USD"], n),
            "positionSide": side,
            "avgEntryPrice": rng.uniform(20000, 70000, n),
            "avgClosePrice": rng.uniform(20000, 70000, n),
            "cumClosedSize": rng.uniform(0.001, 0.05, n),
            "realizedPnL": pnl,
        }
    ).to_dict(orient="records")


if trades is None:
    if not raw_orders:
        # Nothing loaded yet — show a hint and stop rendering the rest.
        if source == "From wallet address":
            st.info(
                "Paste a wallet address above and click **Fetch** to begin. "
                "Or click the example address to try with real data."
            )
        else:
            st.info(
                "Pick a data source in the sidebar to begin. "
                "If you've run `python scripts/pull_history.py`, "
                "the cached file option will appear automatically."
            )
        st.stop()
    trades = slicer.normalize_orders(raw_orders)

if trades is None or trades.empty:
    st.error(
        "No usable trades found. The data is missing open/close timestamps "
        "or a realized PNL field."
    )
    st.stop()


# --------------------------------------------------------------------------- #
# Top metrics row
# --------------------------------------------------------------------------- #

overall = slicer.overall(trades)
slices = slicer.slice_all(trades)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Trades", f"{overall.n_trades:,}")
c2.metric("Winrate", f"{overall.winrate:.1%}")
c3.metric("Expectancy", f"${overall.expectancy:,.2f}")
c4.metric("Total PNL", f"${overall.total_pnl:,.0f}")

st.divider()


# --------------------------------------------------------------------------- #
# Conditional Performance — stat cards + waterfall
# --------------------------------------------------------------------------- #

st.subheader("Conditional performance")
st.caption(
    "Where you make money, and where you give it back. "
    "Top cards highlight the extremes; chart shows total PNL contribution per slice."
)


def _money(x: float) -> str:
    """Format currency with sign before symbol: -$5.20, +$12.40."""
    if x is None or pd.isna(x):
        return "—"
    sign = "−" if x < 0 else ("+" if x > 0 else "")
    return f"{sign}${abs(x):,.2f}"


def _money_int(x: float) -> str:
    if x is None or pd.isna(x):
        return "—"
    sign = "−" if x < 0 else ("+" if x > 0 else "")
    return f"{sign}${abs(x):,.0f}"


def _stat_card(
    tag: str,
    label: str,
    value: float,
    n_trades: int,
    winrate: float,
    total_pnl: float,
    *,
    kind: str,  # "win" | "loss" | "neutral"
) -> str:
    """Build the HTML for a single stat card (one-line, no indentation)."""
    kind_class = kind if kind in ("win", "loss") else ""
    value_class = kind if kind in ("win", "loss") else ""
    total_class = "pos" if total_pnl >= 0 else "neg"
    return (
        f'<div class="ew-card {kind_class}">'
        f'<div class="ew-card-tag">{tag}</div>'
        f'<div class="ew-card-label">{label}</div>'
        f'<div class="ew-card-value {value_class}">{_money(value)}</div>'
        f'<div class="ew-card-meta">'
        f'<span class="strong">{n_trades:,}</span> trades · {winrate:.0%} win'
        f'<br>Total: <span class="{total_class}">{_money_int(total_pnl)}</span>'
        f"</div>"
        f"</div>"
    )


def _render_cards(slice_df: pd.DataFrame, key_col: str, key_label_fn=None) -> None:
    """Render the most-losing and most-winning slices as cards.

    - Filters out small samples (n < 5) to avoid noise.
    - Deduplicates: a slice never appears as both Worst and Best.
    - "Best" cards are only colored as wins if expectancy is genuinely positive.
      If all slices are negative, the "best" cards stay neutral (grey).
    """
    if slice_df.empty:
        st.info("Not enough trades to extract extremes.")
        return

    df = slice_df.copy()
    if "n_trades" in df.columns:
        df = df[df["n_trades"] >= 5]
    if df.empty:
        st.info("All slices have fewer than 5 trades — not enough signal.")
        return

    df = df.sort_values("expectancy").reset_index(drop=True)

    # How many to show on each side, scaling with sample size.
    n = len(df)
    if n <= 2:
        # Tiny pool — show what we have without splitting
        worst_n, best_n = n, 0
    elif n <= 4:
        worst_n, best_n = 1, 1
    else:
        worst_n, best_n = 2, 2

    worst = df.iloc[:worst_n]
    best = df.iloc[-best_n:][::-1] if best_n > 0 else df.iloc[:0]

    # Deduplicate: never show the same slice on both sides
    worst_keys = set(worst[key_col].astype(str).tolist())
    best = best[~best[key_col].astype(str).isin(worst_keys)]

    label_fn = key_label_fn or (lambda v: str(v))

    rows: list[tuple[str, str, dict]] = []
    for _, row in worst.iterrows():
        # Always loss-colored if expectancy negative; else neutral
        kind = "loss" if row["expectancy"] < 0 else "neutral"
        rows.append(("Worst", kind, row.to_dict()))
    for _, row in best.iterrows():
        # Only paint green if genuinely profitable; else neutral
        if row["expectancy"] > 0:
            tag, kind = "Best", "win"
        else:
            tag, kind = "Least bad", "neutral"
        rows.append((tag, kind, row.to_dict()))

    if not rows:
        st.info("Not enough distinct slices to render cards.")
        return

    cols = st.columns(len(rows))
    for col, (tag, kind, row) in zip(cols, rows):
        with col:
            col.markdown(
                _stat_card(
                    tag=tag,
                    label=label_fn(row[key_col]),
                    value=row["expectancy"],
                    n_trades=int(row["n_trades"]),
                    winrate=row["winrate"],
                    total_pnl=row["total_pnl"],
                    kind=kind,
                ),
                unsafe_allow_html=True,
            )


def _waterfall_chart(
    slice_df: pd.DataFrame,
    key_col: str,
    title: str,
    *,
    sort_by_key: bool = False,
    key_label_fn=None,
) -> None:
    """Render a PNL contribution chart: total_pnl per slice, color-coded by sign.

    sort_by_key=True keeps natural ordering (e.g. hour 0,1,2...23).
    sort_by_key=False sorts by total_pnl asc (worst first).
    """
    if slice_df.empty:
        st.info("Not enough trades to render the chart.")
        return

    df = slice_df.copy()
    if sort_by_key:
        df = df.sort_values(key_col)
    else:
        df = df.sort_values("total_pnl")

    label_fn = key_label_fn or (lambda v: str(v))
    labels = [label_fn(v) for v in df[key_col]]
    values = df["total_pnl"].tolist()
    colors = [GREEN if v >= 0 else RED for v in values]
    n_trades = df["n_trades"].astype(int).tolist()

    customdata = list(zip(n_trades, df["winrate"], df["expectancy"]))

    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=values,
                marker=dict(color=colors, line=dict(width=0)),
                text=[f"n={n}" for n in n_trades],
                textposition="outside",
                textfont=dict(color=MUTED, size=10),
                customdata=customdata,
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Total PNL: %{y:$,.0f}<br>"
                    "Trades: %{customdata[0]}<br>"
                    "Winrate: %{customdata[1]:.1%}<br>"
                    "Expectancy: $%{customdata[2]:,.2f}"
                    "<extra></extra>"
                ),
            )
        ]
    )
    fig.update_layout(
        title=dict(text=title, font=dict(color=TEXT, size=14), x=0, xanchor="left"),
        plot_bgcolor=BG,
        paper_bgcolor=BG,
        font=dict(color=TEXT, family="sans-serif"),
        xaxis=dict(
            showgrid=False,
            color=MUTED,
            tickangle=0,
            type="category",
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=GRID,
            zerolinecolor=MUTED,
            zerolinewidth=1,
            color=MUTED,
            title=dict(text="Total PNL ($)", font=dict(color=MUTED, size=11)),
            tickprefix="$",
        ),
        margin=dict(l=20, r=20, t=44, b=20),
        height=380,
        bargap=0.25,
    )
    st.plotly_chart(fig, use_container_width=True)


def _format_slice_table(df: pd.DataFrame) -> pd.DataFrame:
    """Pretty-format slice DataFrames for display."""
    if df.empty:
        return df
    out = df.copy()
    rename = {
        "n_trades": "Trades",
        "winrate": "Winrate",
        "avg_pnl": "Avg PNL",
        "expectancy": "Expectancy",
        "total_pnl": "Total PNL",
        "avg_hold_minutes": "Avg hold (min)",
    }
    out = out.rename(columns=rename)
    if "Winrate" in out.columns:
        out["Winrate"] = out["Winrate"].map(lambda x: f"{x:.1%}")
    for col in ("Avg PNL", "Expectancy"):
        if col in out.columns:
            out[col] = out[col].map(lambda x: f"${x:,.2f}")
    if "Total PNL" in out.columns:
        out["Total PNL"] = out["Total PNL"].map(lambda x: f"${x:,.0f}")
    if "Avg hold (min)" in out.columns:
        out["Avg hold (min)"] = out["Avg hold (min)"].map(lambda x: f"{x:.1f}")
    return out


# --------------------------------------------------------------------------- #
# Tabs
# --------------------------------------------------------------------------- #

tab_hour, tab_streak, tab_size, tab_hold, tab_side, tab_symbol = st.tabs(
    ["By hour", "By streak", "By size", "By hold", "By side", "By symbol"]
)

with tab_hour:
    _render_cards(
        slices["hour_of_day"],
        key_col="hour",
        key_label_fn=lambda h: f"{int(h):02d}:00 UTC",
    )
    _waterfall_chart(
        slices["hour_of_day"],
        key_col="hour",
        title="Total PNL by hour of day (UTC)",
        sort_by_key=True,
        key_label_fn=lambda h: f"{int(h):02d}h",
    )
    with st.expander("Full table"):
        st.dataframe(
            _format_slice_table(slices["hour_of_day"]),
            use_container_width=True,
            hide_index=True,
        )

with tab_streak:
    st.caption(
        "Trades grouped by how many losses preceded them. If buckets after "
        "multiple losses look much worse than 'fresh', that's a revenge-trading pattern."
    )
    _render_cards(slices["consecutive_losses"], key_col="streak_bucket")
    _waterfall_chart(
        slices["consecutive_losses"],
        key_col="streak_bucket",
        title="Total PNL by losing-streak state",
    )
    with st.expander("Full table"):
        st.dataframe(
            _format_slice_table(slices["consecutive_losses"]),
            use_container_width=True,
            hide_index=True,
        )

with tab_size:
    st.caption(
        "Bucketed by your own size quartile (Q1 = smallest 25%, "
        "Q4 = largest 25%). Reveals whether you actually make money on big bets."
    )
    _render_cards(slices["size_quartile"], key_col="size_quartile")
    _waterfall_chart(
        slices["size_quartile"],
        key_col="size_quartile",
        title="Total PNL by your own size quartile",
        sort_by_key=True,
    )
    with st.expander("Full table"):
        st.dataframe(
            _format_slice_table(slices["size_quartile"]),
            use_container_width=True,
            hide_index=True,
        )

with tab_hold:
    _render_cards(slices["hold_duration"], key_col="hold_bucket")
    _waterfall_chart(
        slices["hold_duration"],
        key_col="hold_bucket",
        title="Total PNL by hold duration",
    )
    with st.expander("Full table"):
        st.dataframe(
            _format_slice_table(slices["hold_duration"]),
            use_container_width=True,
            hide_index=True,
        )

with tab_side:
    _render_cards(slices["side"], key_col="side", key_label_fn=lambda s: str(s).upper())
    _waterfall_chart(
        slices["side"],
        key_col="side",
        title="Total PNL by side",
        key_label_fn=lambda s: str(s).upper(),
    )
    with st.expander("Full table"):
        st.dataframe(
            _format_slice_table(slices["side"]),
            use_container_width=True,
            hide_index=True,
        )

with tab_symbol:
    _render_cards(slices["symbol"], key_col="symbol")
    _waterfall_chart(
        slices["symbol"],
        key_col="symbol",
        title="Total PNL by symbol",
    )
    with st.expander("Full table"):
        st.dataframe(
            _format_slice_table(slices["symbol"]),
            use_container_width=True,
            hide_index=True,
        )


st.divider()


# --------------------------------------------------------------------------- #
# AI Briefing
# --------------------------------------------------------------------------- #

st.subheader("Pre-session briefing")
st.caption(
    "Your edge + today's regime, condensed into one paragraph. "
    "Powered by Anthropic Claude with live SoSoValue data."
)

if st.button("Generate today's briefing", type="primary"):
    s = get_settings()
    if not s.anthropic_api_key:
        st.warning(
            "Set `ANTHROPIC_API_KEY` in your `.env` to generate briefings. "
            "The slicer above already works without it."
        )
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
                    f"<div class='edgework-briefing'>{paragraph}</div>",
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
