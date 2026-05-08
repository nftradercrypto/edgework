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
# Page config
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="Edgework — trade analytics for pro traders",
    page_icon="▍",
    layout="wide",
    initial_sidebar_state="expanded",
)

BG          = "#060606"
SURFACE     = "#0d0d0d"
PANEL       = "#111111"
BORDER      = "#1c1c1c"
ACCENT      = "#f5841f"
ACCENT_DIM  = "rgba(245,132,31,0.07)"
ACCENT_GLOW = "rgba(245,132,31,0.25)"
TEXT        = "#e8e8e8"
MUTED       = "#606060"
GREEN       = "#00d97e"
GREEN_DIM   = "rgba(0,217,126,0.07)"
RED         = "#ff4560"
RED_DIM     = "rgba(255,69,96,0.07)"
GRID        = "#141414"


st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Inter:wght@300;400;500;600;700;800;900&display=swap');

    /* ── App shell ── */
    .stApp {{ background: {BG}; }}
    #MainMenu, footer {{ visibility: hidden; }}
    .stDeployButton {{ display: none !important; }}

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {{
        background: {SURFACE} !important;
        border-right: 1px solid {BORDER};
    }}
    [data-testid="stSidebar"] h2 {{
        color: {ACCENT} !important;
        font-family: 'Space Mono', monospace !important;
        font-size: 11px !important;
        text-transform: uppercase;
        letter-spacing: 0.22em;
    }}
    [data-testid="stSidebar"] .stRadio label {{
        font-size: 13px;
        color: {TEXT};
    }}

    /* ── Typography ── */
    html, body, [class*="css"] {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }}
    h1, h2, h3, h4 {{
        color: {TEXT} !important;
        font-family: 'Inter', sans-serif !important;
        letter-spacing: -0.02em;
    }}

    /* ── Tabs ── */
    [data-baseweb="tab-list"] {{
        gap: 2px !important;
        background: {SURFACE};
        border-radius: 6px 6px 0 0;
        padding: 4px 4px 0 4px;
        border: 1px solid {BORDER};
        border-bottom: none;
    }}
    [data-baseweb="tab"] {{
        color: {MUTED} !important;
        font-weight: 500;
        font-size: 13px !important;
        border-radius: 4px 4px 0 0 !important;
        padding: 7px 16px !important;
        transition: all 0.15s ease;
        font-family: 'Inter', sans-serif !important;
    }}
    [data-baseweb="tab"]:hover {{
        color: {TEXT} !important;
        background: rgba(255,255,255,0.04) !important;
    }}
    [data-baseweb="tab"][aria-selected="true"] {{
        color: {ACCENT} !important;
        font-weight: 700 !important;
        background: {ACCENT_DIM} !important;
        border-bottom: 2px solid {ACCENT} !important;
    }}
    [data-baseweb="tab-highlight"] {{ display: none; }}
    [data-baseweb="tab-border"] {{ display: none; }}

    /* ── Buttons ── */
    .stButton > button {{
        background: {ACCENT} !important;
        color: #000 !important;
        border: none !important;
        font-weight: 700 !important;
        letter-spacing: 0.04em;
        font-size: 13px !important;
        border-radius: 5px !important;
        transition: all 0.15s ease !important;
        padding: 8px 20px !important;
    }}
    .stButton > button:hover {{
        background: #ff9a3c !important;
        box-shadow: 0 4px 24px {ACCENT_GLOW} !important;
        transform: translateY(-1px);
    }}

    /* ── Dividers ── */
    hr {{ border: none; border-top: 1px solid {BORDER} !important; margin: 28px 0 !important; }}

    /* ── Expander ── */
    [data-testid="stExpander"] {{
        border: 1px solid {BORDER} !important;
        border-radius: 6px !important;
        background: {SURFACE} !important;
    }}
    [data-testid="stExpander"] summary {{
        color: {MUTED} !important;
        font-size: 11px !important;
        font-family: 'Space Mono', monospace !important;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }}

    /* ── Dataframe ── */
    [data-testid="stDataFrame"] {{
        border: 1px solid {BORDER} !important;
        border-radius: 6px;
        overflow: hidden;
    }}

    /* ── Spinner ── */
    [data-testid="stSpinner"] > div {{ border-top-color: {ACCENT} !important; }}

    /* ── HEADER ── */
    .ew-topbar {{
        display: flex;
        align-items: center;
        gap: 20px;
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.22em;
        color: {MUTED};
        text-transform: uppercase;
        padding-bottom: 20px;
        border-bottom: 1px solid {BORDER};
        margin-bottom: 32px;
    }}
    .ew-topbar-brand {{ color: {ACCENT}; font-weight: 700; font-size: 11px; }}
    .ew-topbar-sep {{ color: {BORDER}; }}
    .ew-live-badge {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        color: {GREEN};
        font-weight: 700;
    }}
    .ew-live-dot {{
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: {GREEN};
        display: inline-block;
        animation: ew-pulse 2.2s ease-in-out infinite;
    }}
    @keyframes ew-pulse {{
        0%, 100% {{ opacity: 1; box-shadow: 0 0 0 0 rgba(0,217,126,0.5); }}
        50% {{ opacity: 0.7; box-shadow: 0 0 0 5px rgba(0,217,126,0); }}
    }}
    .ew-headline {{
        font-size: 46px;
        font-weight: 900;
        letter-spacing: -0.035em;
        line-height: 1.02;
        margin: 0 0 14px 0;
        color: {TEXT};
        font-family: 'Inter', sans-serif;
    }}
    .ew-headline .accent {{
        background: linear-gradient(110deg, {ACCENT} 0%, #ffb347 60%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }}
    .ew-sub {{
        color: {MUTED};
        max-width: 680px;
        font-size: 15px;
        line-height: 1.65;
        font-weight: 400;
        margin-bottom: 4px;
    }}

    /* ── METRIC GRID ── */
    .ew-metrics {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 1px;
        background: {BORDER};
        border: 1px solid {BORDER};
        border-radius: 8px;
        overflow: hidden;
        margin: 24px 0 32px 0;
    }}
    .ew-metric {{
        background: {SURFACE};
        padding: 22px 24px 18px;
        position: relative;
    }}
    .ew-metric-label {{
        font-family: 'Space Mono', monospace;
        font-size: 9px;
        letter-spacing: 0.28em;
        color: {MUTED};
        text-transform: uppercase;
        margin-bottom: 10px;
    }}
    .ew-metric-value {{
        font-family: 'Space Mono', monospace;
        font-size: 28px;
        font-weight: 700;
        color: {TEXT};
        line-height: 1;
        letter-spacing: -0.02em;
    }}
    .ew-metric-value.pos {{ color: {GREEN}; }}
    .ew-metric-value.neg {{ color: {RED}; }}
    .ew-metric-sub {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        color: {MUTED};
        margin-top: 7px;
        letter-spacing: 0.05em;
    }}
    .ew-metric-glow {{
        position: absolute;
        bottom: 0; left: 0; right: 0;
        height: 2px;
        background: linear-gradient(90deg, {ACCENT} 0%, transparent 70%);
        opacity: 0.45;
    }}

    /* ── SECTION HEADER ── */
    .ew-section {{
        margin-bottom: 16px;
    }}
    .ew-section-title {{
        font-size: 15px;
        font-weight: 700;
        color: {TEXT};
        letter-spacing: -0.01em;
        margin-bottom: 3px;
    }}
    .ew-section-sub {{
        font-size: 12px;
        color: {MUTED};
        line-height: 1.5;
    }}

    /* ── STAT CARDS ── */
    .ew-card-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        gap: 10px;
        margin: 4px 0 20px 0;
    }}
    .ew-card {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 16px 18px 14px;
        position: relative;
        overflow: hidden;
    }}
    .ew-card::before {{
        content: '';
        position: absolute;
        top: 0; left: 0;
        width: 3px; height: 100%;
        background: {BORDER};
        border-radius: 8px 0 0 8px;
    }}
    .ew-card.win {{ border-color: rgba(0,217,126,0.22); background: {GREEN_DIM}; }}
    .ew-card.win::before {{ background: {GREEN}; }}
    .ew-card.loss {{ border-color: rgba(255,69,96,0.22); background: {RED_DIM}; }}
    .ew-card.loss::before {{ background: {RED}; }}
    .ew-card-tag {{
        font-family: 'Space Mono', monospace;
        font-size: 9px;
        letter-spacing: 0.25em;
        color: {MUTED};
        text-transform: uppercase;
        margin-bottom: 5px;
    }}
    .ew-card.win .ew-card-tag {{ color: {GREEN}; }}
    .ew-card.loss .ew-card-tag {{ color: {RED}; }}
    .ew-card-label {{
        font-size: 14px;
        font-weight: 600;
        color: {TEXT};
        margin-bottom: 10px;
        letter-spacing: -0.01em;
    }}
    .ew-card-value {{
        font-family: 'Space Mono', monospace;
        font-size: 21px;
        font-weight: 700;
        line-height: 1;
        margin-bottom: 10px;
        color: {MUTED};
        letter-spacing: -0.02em;
    }}
    .ew-card-value.win {{ color: {GREEN}; }}
    .ew-card-value.loss {{ color: {RED}; }}
    .ew-wr-track {{
        height: 3px;
        background: {BORDER};
        border-radius: 2px;
        margin-bottom: 9px;
        overflow: hidden;
    }}
    .ew-wr-fill {{
        height: 100%;
        border-radius: 2px;
        background: {MUTED};
    }}
    .ew-card.win .ew-wr-fill {{ background: {GREEN}; }}
    .ew-card.loss .ew-wr-fill {{ background: {RED}; }}
    .ew-card-meta {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        color: {MUTED};
        line-height: 1.9;
        letter-spacing: 0.02em;
    }}
    .ew-card-meta .hi {{ color: {TEXT}; }}
    .ew-card-meta .pos {{ color: {GREEN}; }}
    .ew-card-meta .neg {{ color: {RED}; }}

    /* ── BRIEFING ── */
    .ew-briefing-wrap {{
        border: 1px solid rgba(245,132,31,0.28);
        border-left: 3px solid {ACCENT};
        padding: 22px 26px 22px 28px;
        background: {ACCENT_DIM};
        font-size: 15px;
        line-height: 1.75;
        color: #ddd;
        margin-top: 14px;
        border-radius: 0 8px 8px 0;
        font-weight: 400;
        position: relative;
    }}
    .ew-briefing-eyebrow {{
        font-family: 'Space Mono', monospace;
        font-size: 9px;
        letter-spacing: 0.28em;
        color: {ACCENT};
        text-transform: uppercase;
        margin-bottom: 10px;
    }}

    /* ── EQUITY CURVE LABEL ── */
    .ew-chart-label {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.18em;
        color: {MUTED};
        text-transform: uppercase;
        margin-bottom: 6px;
    }}

    /* ── EMPTY STATE ── */
    .ew-empty {{
        border: 1px dashed {BORDER};
        border-radius: 8px;
        padding: 40px 32px;
        text-align: center;
        margin: 20px 0;
    }}
    .ew-empty-icon {{
        font-size: 28px;
        margin-bottom: 12px;
        color: {MUTED};
        font-family: 'Space Mono', monospace;
    }}
    .ew-empty-title {{
        font-size: 15px;
        font-weight: 600;
        color: {TEXT};
        margin-bottom: 6px;
    }}
    .ew-empty-sub {{
        font-size: 13px;
        color: {MUTED};
        line-height: 1.6;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #

st.markdown(
    f"""
    <div class="ew-topbar">
        <span class="ew-topbar-brand">▍ EDGEWORK</span>
        <span class="ew-topbar-sep">|</span>
        <span class="ew-live-badge">
            <span class="ew-live-dot"></span>LIVE
        </span>
        <span class="ew-topbar-sep">|</span>
        <span>SoDEX Perps</span>
        <span class="ew-topbar-sep">|</span>
        <span>SoSoValue Buildathon · Wave 1</span>
    </div>
    <h1 class="ew-headline">Know your edge.<br><span class="accent">Cut the noise.</span></h1>
    <p class="ew-sub">
        PNL doesn't show where your edge is. Edgework slices your SoDEX history
        across time, behavior, and market regime — so you see exactly which setups
        make you money, and which ones quietly bleed it.
    </p>
    """,
    unsafe_allow_html=True,
)

st.divider()


# --------------------------------------------------------------------------- #
# Sidebar — data input
# --------------------------------------------------------------------------- #

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
            f"Cached: {modtime.strftime('%Y-%m-%d %H:%M UTC')}"
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

if "wallet_cache" not in st.session_state:
    st.session_state.wallet_cache = {}


if source == "From wallet address":
    st.markdown(
        f"""
        <div class="ew-section">
            <div class="ew-section-title">Pull live SoDEX history</div>
            <div class="ew-section-sub">
                Paste any wallet address that has traded perpetuals on SoDEX.
                Fetched directly from the public API — no auth required.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_input, col_btn = st.columns([4, 1])
    with col_input:
        address = st.text_input(
            "Wallet address",
            value=st.session_state.get("active_address", ""),
            placeholder="0x…",
            label_visibility="collapsed",
        )
    with col_btn:
        fetch_clicked = st.button("Fetch", use_container_width=True)

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

    active = st.session_state.get("active_address")
    if active and active in st.session_state.wallet_cache:
        trades = st.session_state.wallet_cache[active]
        st.caption(
            f"Showing **`{active}`** · {len(trades):,} positions"
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
        if source == "From wallet address":
            st.markdown(
                f"""
                <div class="ew-empty">
                    <div class="ew-empty-icon">[ 0x ]</div>
                    <div class="ew-empty-title">Paste a wallet address to begin</div>
                    <div class="ew-empty-sub">
                        Enter any SoDEX trader's wallet above and click <strong>Fetch</strong>.<br>
                        No login or private key required — public API only.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""
                <div class="ew-empty">
                    <div class="ew-empty-icon">[ — ]</div>
                    <div class="ew-empty-title">Select a data source to begin</div>
                    <div class="ew-empty-sub">
                        Choose from the sidebar. If you've run
                        <code>python scripts/pull_history.py</code>, the cached file
                        option will appear automatically.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
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
# Compute stats
# --------------------------------------------------------------------------- #

overall = slicer.overall(trades)
slices = slicer.slice_all(trades)


# --------------------------------------------------------------------------- #
# Top metric row — custom HTML
# --------------------------------------------------------------------------- #

exp_cls = "pos" if overall.expectancy >= 0 else "neg"
pnl_cls = "pos" if overall.total_pnl >= 0 else "neg"
exp_sign = "+" if overall.expectancy > 0 else ""
pnl_sign = "+" if overall.total_pnl > 0 else ""
n_wins = int(round(overall.winrate * overall.n_trades))

st.markdown(
    f"""
    <div class="ew-metrics">
        <div class="ew-metric">
            <div class="ew-metric-label">Total Trades</div>
            <div class="ew-metric-value">{overall.n_trades:,}</div>
            <div class="ew-metric-sub">closed positions</div>
            <div class="ew-metric-glow"></div>
        </div>
        <div class="ew-metric">
            <div class="ew-metric-label">Win Rate</div>
            <div class="ew-metric-value">{overall.winrate:.1%}</div>
            <div class="ew-metric-sub">{n_wins:,} of {overall.n_trades:,} wins</div>
            <div class="ew-metric-glow"></div>
        </div>
        <div class="ew-metric">
            <div class="ew-metric-label">Expectancy / Trade</div>
            <div class="ew-metric-value {exp_cls}">{exp_sign}${overall.expectancy:,.2f}</div>
            <div class="ew-metric-sub">per trade avg</div>
            <div class="ew-metric-glow"></div>
        </div>
        <div class="ew-metric">
            <div class="ew-metric-label">Realized PNL</div>
            <div class="ew-metric-value {pnl_cls}">{pnl_sign}${overall.total_pnl:,.0f}</div>
            <div class="ew-metric-sub">all closed trades</div>
            <div class="ew-metric-glow"></div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Equity curve
# --------------------------------------------------------------------------- #

def _equity_curve(df: pd.DataFrame) -> None:
    """Cumulative PNL line chart sorted by close time."""
    close_col = next(
        (c for c in ("close_time", "updatedAt", "closedAt") if c in df.columns),
        None,
    )
    pnl_col = next(
        (c for c in ("pnl", "realizedPnL", "realized_pnl") if c in df.columns),
        None,
    )
    if close_col is None or pnl_col is None:
        return

    eq = df[[close_col, pnl_col]].copy().dropna()
    eq = eq.sort_values(close_col)
    eq["cum"] = eq[pnl_col].cumsum()

    final = eq["cum"].iloc[-1]
    line_color = GREEN if final >= 0 else RED
    fill_color = GREEN_DIM if final >= 0 else RED_DIM

    x_vals = eq[close_col].tolist()
    y_vals = eq["cum"].tolist()

    fig = go.Figure()

    # Fill area
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=y_vals,
            fill="tozeroy",
            fillcolor=fill_color,
            line=dict(color="rgba(0,0,0,0)", width=0),
            showlegend=False,
            hoverinfo="skip",
        )
    )

    # Main line
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines",
            line=dict(color=line_color, width=2),
            showlegend=False,
            hovertemplate="<b>%{x|%b %d, %H:%M}</b><br>Cum. PNL: $%{y:,.0f}<extra></extra>",
        )
    )

    # Final value annotation
    fig.add_annotation(
        x=x_vals[-1],
        y=y_vals[-1],
        text=f"  {'+'if final>=0 else ''}${final:,.0f}",
        showarrow=False,
        font=dict(color=line_color, family="Space Mono, monospace", size=12),
        xanchor="left",
    )

    fig.update_layout(
        plot_bgcolor=BG,
        paper_bgcolor=BG,
        font=dict(color=TEXT, family="Inter, sans-serif"),
        xaxis=dict(
            showgrid=False,
            color=MUTED,
            tickfont=dict(family="Space Mono, monospace", size=9),
            linecolor=BORDER,
            linewidth=1,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=GRID,
            gridwidth=1,
            zerolinecolor=MUTED,
            zerolinewidth=1,
            color=MUTED,
            tickfont=dict(family="Space Mono, monospace", size=9),
            tickprefix="$",
        ),
        margin=dict(l=10, r=40, t=10, b=10),
        height=200,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=PANEL,
            bordercolor=BORDER,
            font=dict(family="Space Mono, monospace", size=11),
        ),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


st.markdown('<div class="ew-chart-label">Equity curve — cumulative PNL</div>', unsafe_allow_html=True)
_equity_curve(trades)

st.divider()


# --------------------------------------------------------------------------- #
# Helpers — formatting
# --------------------------------------------------------------------------- #

def _money(x: float) -> str:
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
    kind: str,
) -> str:
    kind_class = kind if kind in ("win", "loss") else ""
    value_class = kind if kind in ("win", "loss") else ""
    total_class = "pos" if total_pnl >= 0 else "neg"
    wr_class = "pos" if winrate >= 0.5 else "neg"
    wr_width = f"{winrate * 100:.1f}"
    return (
        f'<div class="ew-card {kind_class}">'
        f'  <div class="ew-card-tag">{tag}</div>'
        f'  <div class="ew-card-label">{label}</div>'
        f'  <div class="ew-card-value {value_class}">{_money(value)}</div>'
        f'  <div class="ew-wr-track">'
        f'    <div class="ew-wr-fill" style="width:{wr_width}%"></div>'
        f'  </div>'
        f'  <div class="ew-card-meta">'
        f'    <span class="hi">{n_trades:,}</span> trades'
        f'    &nbsp;·&nbsp;'
        f'    <span class="{wr_class}">{winrate:.0%}</span> win'
        f'    <br>'
        f'    Total: <span class="{total_class}">{_money_int(total_pnl)}</span>'
        f'  </div>'
        f'</div>'
    )


def _render_cards(slice_df: pd.DataFrame, key_col: str, key_label_fn=None) -> None:
    if slice_df.empty:
        return
    df = slice_df.copy()
    if "n_trades" in df.columns:
        df = df[df["n_trades"] >= 5]
    if df.empty:
        st.caption("All slices have fewer than 5 trades — not enough signal.")
        return

    df = df.sort_values("expectancy").reset_index(drop=True)
    n = len(df)
    if n <= 2:
        worst_n, best_n = n, 0
    elif n <= 4:
        worst_n, best_n = 1, 1
    else:
        worst_n, best_n = 2, 2

    worst = df.iloc[:worst_n]
    best = df.iloc[-best_n:][::-1] if best_n > 0 else df.iloc[:0]

    worst_keys = set(worst[key_col].astype(str).tolist())
    best = best[~best[key_col].astype(str).isin(worst_keys)]

    label_fn = key_label_fn or (lambda v: str(v))

    rows: list[tuple[str, str, dict]] = []
    for _, row in worst.iterrows():
        kind = "loss" if row["expectancy"] < 0 else "neutral"
        rows.append(("Worst", kind, row.to_dict()))
    for _, row in best.iterrows():
        if row["expectancy"] > 0:
            tag, kind = "Best", "win"
        else:
            tag, kind = "Least bad", "neutral"
        rows.append((tag, kind, row.to_dict()))

    if not rows:
        return

    html_cards = "".join(
        _stat_card(
            tag=tag,
            label=label_fn(row[key_col]),
            value=row["expectancy"],
            n_trades=int(row["n_trades"]),
            winrate=row["winrate"],
            total_pnl=row["total_pnl"],
            kind=kind,
        )
        for (tag, kind, row) in rows
    )
    st.markdown(
        f'<div class="ew-card-grid">{html_cards}</div>',
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
    if slice_df.empty:
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
                marker=dict(color=colors, opacity=0.88, line=dict(width=0)),
                text=[f"n={n}" for n in n_trades],
                textposition="outside",
                textfont=dict(color=MUTED, size=9, family="Space Mono, monospace"),
                customdata=customdata,
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "PNL: <b>%{y:$,.0f}</b><br>"
                    "Trades: %{customdata[0]}<br>"
                    "Winrate: %{customdata[1]:.1%}<br>"
                    "Expectancy: $%{customdata[2]:,.2f}"
                    "<extra></extra>"
                ),
            )
        ]
    )
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(color=MUTED, size=11, family="Space Mono, monospace"),
            x=0,
            xanchor="left",
        ),
        plot_bgcolor=SURFACE,
        paper_bgcolor=BG,
        font=dict(color=TEXT, family="Inter, sans-serif"),
        xaxis=dict(
            showgrid=False,
            color=MUTED,
            tickfont=dict(family="Space Mono, monospace", size=10),
            tickangle=0,
            type="category",
            linecolor=BORDER,
            linewidth=1,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=GRID,
            gridwidth=1,
            zerolinecolor=MUTED,
            zerolinewidth=1.5,
            color=MUTED,
            tickfont=dict(family="Space Mono, monospace", size=10),
            title=dict(text="Total PNL (USD)", font=dict(color=MUTED, size=10)),
            tickprefix="$",
        ),
        margin=dict(l=10, r=10, t=40, b=10),
        height=360,
        bargap=0.28,
        hoverlabel=dict(
            bgcolor=PANEL,
            bordercolor=BORDER,
            font=dict(family="Space Mono, monospace", size=11),
        ),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _format_slice_table(df: pd.DataFrame) -> pd.DataFrame:
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
# Conditional performance section
# --------------------------------------------------------------------------- #

st.markdown(
    """
    <div class="ew-section">
        <div class="ew-section-title">Conditional performance</div>
        <div class="ew-section-sub">
            Where you make money — and where you give it back.
            Cards show the extremes; charts show total PNL contribution per slice.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_hour, tab_streak, tab_size, tab_hold, tab_side, tab_symbol = st.tabs(
    ["Hour of Day", "Loss Streak", "Size", "Hold Time", "Side", "Symbol"]
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
        title="TOTAL PNL BY HOUR OF DAY (UTC)",
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
        "Trades grouped by prior consecutive losses. "
        "If later buckets look much worse, that's a revenge-trading pattern."
    )
    _render_cards(slices["consecutive_losses"], key_col="streak_bucket")
    _waterfall_chart(
        slices["consecutive_losses"],
        key_col="streak_bucket",
        title="TOTAL PNL BY LOSING-STREAK STATE",
    )
    with st.expander("Full table"):
        st.dataframe(
            _format_slice_table(slices["consecutive_losses"]),
            use_container_width=True,
            hide_index=True,
        )

with tab_size:
    st.caption(
        "Bucketed by your own size quartile (Q1 = smallest 25%, Q4 = largest 25%). "
        "Reveals whether you actually make money on big bets."
    )
    _render_cards(slices["size_quartile"], key_col="size_quartile")
    _waterfall_chart(
        slices["size_quartile"],
        key_col="size_quartile",
        title="TOTAL PNL BY POSITION SIZE QUARTILE",
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
        title="TOTAL PNL BY HOLD DURATION",
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
        title="TOTAL PNL BY SIDE",
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
        title="TOTAL PNL BY SYMBOL",
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

st.markdown(
    """
    <div class="ew-section">
        <div class="ew-section-title">Pre-session briefing</div>
        <div class="ew-section-sub">
            Your historical edge + today's market regime, condensed into one paragraph.
            Powered by Anthropic Claude with live SoSoValue data.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.button("Generate today's briefing", type="primary"):
    s = get_settings()
    if not s.anthropic_api_key:
        st.warning(
            "Set `ANTHROPIC_API_KEY` in your `.env` to generate briefings. "
            "The slicer above works without it."
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
                    f"""
                    <div class="ew-briefing-wrap">
                        <div class="ew-briefing-eyebrow">Pre-session briefing</div>
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
