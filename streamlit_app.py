"""Edgework — Streamlit app.

Wave 1 demo entry point. Lets a trader:
1. Load their SoDEX trade history (cached parquet, parquet/CSV/JSON upload, or demo data)
2. See conditional performance: stat cards highlight the extremes, charts
   show how each metric breaks down across slices
3. Generate an AI Briefing paragraph (combines edge + market context)

Deploy: Streamlit Community Cloud, free tier.
"""

from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# --------------------------------------------------------------------------- #
# Secrets loading — runs BEFORE edgework.config is imported (lru_cached)
# --------------------------------------------------------------------------- #
# Two sources, in priority order:
#   1. Streamlit Cloud Secrets (st.secrets) — used in deployed environment
#   2. Local .env file via python-dotenv — used in dev
#
# Both bridge into os.environ so pydantic-settings just reads env vars
# regardless of where we're running. We override env vars only when the
# existing value is empty/missing — some shells (Claude Code, CI) pre-set
# keys like ANTHROPIC_API_KEY="" for isolation, which would otherwise
# silently shadow the .env value if we used load_dotenv(override=False).

# 1) Streamlit Cloud Secrets
try:
    _secrets = dict(st.secrets)  # raises if no secrets.toml AND not on Cloud
    for _key in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
                 "SOSOVALUE_API_KEY", "SODEX_USER_ADDRESS"):
        if _key in _secrets and not os.environ.get(_key):
            os.environ[_key] = str(_secrets[_key])
except (FileNotFoundError, KeyError, AttributeError):
    pass  # local dev without secrets.toml — fall through to .env

# 2) Local .env (search cwd, app dir, then walk up two levels)
try:
    from dotenv import dotenv_values

    _here = Path(__file__).resolve().parent
    for _p in (Path.cwd() / ".env", _here / ".env",
               _here.parent / ".env", _here.parent.parent / ".env"):
        if _p.is_file():
            for _k, _v in dotenv_values(_p).items():
                if _v and not os.environ.get(_k):
                    os.environ[_k] = _v
            break
except ImportError:
    pass


from edgework import briefing, slicer  # noqa: E402
from edgework.config import get_settings  # noqa: E402
from edgework.sosovalue_client import SoSoValueClient  # noqa: E402


# --------------------------------------------------------------------------- #
# Page config + brand palette
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
BORDER_HI   = "#262626"
ACCENT      = "#f5841f"
ACCENT_DIM  = "rgba(245,132,31,0.07)"
ACCENT_GLOW = "rgba(245,132,31,0.25)"
TEXT        = "#e8e8e8"
MUTED       = "#666666"
GREEN       = "#00d97e"
GREEN_DIM   = "rgba(0,217,126,0.08)"
RED         = "#ff4560"
RED_DIM     = "rgba(255,69,96,0.08)"
GRID        = "#141414"


# Inline SVG logo (4 ascending bars in accent color — "edge growing").
LOGO_SVG = (
    '<svg width="22" height="22" viewBox="0 0 24 24" '
    'xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle">'
    '<rect x="2"  y="15" width="3" height="5"  fill="#f5841f" opacity="0.35"/>'
    '<rect x="7"  y="11" width="3" height="9"  fill="#f5841f" opacity="0.6"/>'
    '<rect x="12" y="7"  width="3" height="13" fill="#f5841f" opacity="0.85"/>'
    '<rect x="17" y="3"  width="3" height="17" fill="#f5841f"/>'
    '</svg>'
)


# --------------------------------------------------------------------------- #
# CSS
# --------------------------------------------------------------------------- #

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700;800&display=swap');

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
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 11px !important;
        text-transform: uppercase;
        letter-spacing: 0.22em;
    }}
    [data-testid="stSidebar"] .stRadio label {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 12px;
        color: {TEXT};
    }}

    /* ── Typography ── */
    html, body, [class*="css"], .stMarkdown, p, span, div, label {{
        font-family: 'IBM Plex Mono', ui-monospace, monospace;
    }}
    h1, h2, h3, h4 {{
        color: {TEXT} !important;
        font-family: 'IBM Plex Sans', sans-serif !important;
        letter-spacing: -0.02em;
        font-weight: 700;
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
        font-size: 12px !important;
        border-radius: 4px 4px 0 0 !important;
        padding: 8px 16px !important;
        transition: all 0.15s ease;
        font-family: 'IBM Plex Mono', monospace !important;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }}
    [data-baseweb="tab"]:hover {{
        color: {TEXT} !important;
        background: rgba(255,255,255,0.04) !important;
    }}
    [data-baseweb="tab"][aria-selected="true"] {{
        color: {ACCENT} !important;
        font-weight: 600 !important;
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
        font-weight: 600 !important;
        letter-spacing: 0.05em;
        font-size: 12px !important;
        text-transform: uppercase;
        border-radius: 5px !important;
        transition: all 0.15s ease !important;
        padding: 8px 20px !important;
        font-family: 'IBM Plex Mono', monospace !important;
    }}
    .stButton > button:hover {{
        background: #ff9a3c !important;
        box-shadow: 0 4px 24px {ACCENT_GLOW} !important;
        transform: translateY(-1px);
    }}

    /* ── Segmented control (metric switcher) ── */
    [data-testid="stSegmentedControl"] button {{
        background: {SURFACE} !important;
        border: 1px solid {BORDER} !important;
        color: {MUTED} !important;
        font-family: 'IBM Plex Mono', monospace !important;
        font-size: 10px !important;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        padding: 5px 12px !important;
        font-weight: 500 !important;
    }}
    [data-testid="stSegmentedControl"] button:hover {{
        color: {TEXT} !important;
        border-color: {BORDER_HI} !important;
    }}
    [data-testid="stSegmentedControl"] button[aria-checked="true"],
    [data-testid="stSegmentedControl"] button[data-selected="true"] {{
        background: {ACCENT_DIM} !important;
        border-color: {ACCENT} !important;
        color: {ACCENT} !important;
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
        font-size: 10px !important;
        font-family: 'IBM Plex Mono', monospace !important;
        letter-spacing: 0.1em;
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

    /* ── Topbar / brand ── */
    .ew-topbar {{
        display: flex;
        align-items: center;
        gap: 18px;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.2em;
        color: {MUTED};
        text-transform: uppercase;
        padding-bottom: 18px;
        border-bottom: 1px solid {BORDER};
        margin-bottom: 32px;
    }}
    .ew-brand {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        color: {ACCENT};
        font-weight: 700;
        font-size: 12px;
        letter-spacing: 0.18em;
    }}
    .ew-topbar-sep {{ color: {BORDER_HI}; }}
    .ew-live-badge {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        color: {GREEN};
        font-weight: 600;
    }}
    .ew-live-dot {{
        width: 6px; height: 6px;
        border-radius: 50%;
        background: {GREEN};
        display: inline-block;
        animation: ew-pulse 2.2s ease-in-out infinite;
    }}
    @keyframes ew-pulse {{
        0%, 100% {{ opacity: 1; box-shadow: 0 0 0 0 rgba(0,217,126,0.5); }}
        50% {{ opacity: 0.6; box-shadow: 0 0 0 5px rgba(0,217,126,0); }}
    }}

    /* ── Headline ── */
    .ew-headline {{
        font-size: 46px;
        font-weight: 800;
        letter-spacing: -0.035em;
        line-height: 1.02;
        margin: 0 0 14px 0;
        color: {TEXT};
        font-family: 'IBM Plex Sans', sans-serif;
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
        font-size: 14px;
        line-height: 1.65;
        font-weight: 400;
        font-family: 'IBM Plex Sans', sans-serif;
    }}

    /* ── Metric grid ── */
    .ew-metrics {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 1px;
        background: {BORDER};
        border: 1px solid {BORDER};
        border-radius: 8px;
        overflow: hidden;
        margin: 24px 0 16px 0;
    }}
    .ew-metric {{
        background: {SURFACE};
        padding: 22px 24px 18px;
        position: relative;
    }}
    .ew-metric-label {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 9px;
        letter-spacing: 0.28em;
        color: {MUTED};
        text-transform: uppercase;
        margin-bottom: 10px;
    }}
    .ew-metric-value {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 28px;
        font-weight: 600;
        color: {TEXT};
        line-height: 1;
        letter-spacing: -0.03em;
    }}
    .ew-metric-value.pos {{ color: {GREEN}; }}
    .ew-metric-value.neg {{ color: {RED}; }}
    .ew-metric-sub {{
        font-family: 'IBM Plex Mono', monospace;
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
        opacity: 0.4;
    }}

    /* ── Section header ── */
    .ew-section {{ margin-bottom: 14px; margin-top: 18px; }}
    .ew-section-title {{
        font-size: 14px;
        font-weight: 700;
        color: {TEXT};
        letter-spacing: 0.05em;
        margin-bottom: 4px;
        text-transform: uppercase;
        font-family: 'IBM Plex Mono', monospace;
    }}
    .ew-section-sub {{
        font-size: 12px;
        color: {MUTED};
        line-height: 1.5;
        font-family: 'IBM Plex Sans', sans-serif;
    }}

    /* ── Panel header (inside each tab) ── */
    .ew-panel-head {{
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        padding: 10px 0 12px 0;
        border-bottom: 1px solid {BORDER};
        margin-bottom: 14px;
    }}
    .ew-panel-title {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.18em;
        color: {TEXT};
        font-weight: 600;
    }}
    .ew-panel-meta {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 10px;
        color: {MUTED};
        letter-spacing: 0.05em;
    }}
    .ew-panel-meta .pos {{ color: {GREEN}; }}
    .ew-panel-meta .neg {{ color: {RED}; }}

    /* ── Stat cards ── */
    .ew-card-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        gap: 10px;
        margin: 4px 0 18px 0;
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
        background: {BORDER_HI};
        border-radius: 8px 0 0 8px;
    }}
    .ew-card.win {{ border-color: rgba(0,217,126,0.22); background: {GREEN_DIM}; }}
    .ew-card.win::before {{ background: {GREEN}; }}
    .ew-card.loss {{ border-color: rgba(255,69,96,0.22); background: {RED_DIM}; }}
    .ew-card.loss::before {{ background: {RED}; }}
    .ew-card-tag {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 9px;
        letter-spacing: 0.25em;
        color: {MUTED};
        text-transform: uppercase;
        margin-bottom: 5px;
    }}
    .ew-card.win .ew-card-tag {{ color: {GREEN}; }}
    .ew-card.loss .ew-card-tag {{ color: {RED}; }}
    .ew-card-label {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 13px;
        font-weight: 600;
        color: {TEXT};
        margin-bottom: 10px;
        letter-spacing: 0.02em;
    }}
    .ew-card-value {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 21px;
        font-weight: 600;
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
        font-family: 'IBM Plex Mono', monospace;
        font-size: 10px;
        color: {MUTED};
        line-height: 1.9;
        letter-spacing: 0.02em;
    }}
    .ew-card-meta .hi {{ color: {TEXT}; }}
    .ew-card-meta .pos {{ color: {GREEN}; }}
    .ew-card-meta .neg {{ color: {RED}; }}

    /* ── Briefing ── */
    .ew-briefing-wrap {{
        border: 1px solid rgba(245,132,31,0.28);
        border-left: 3px solid {ACCENT};
        padding: 22px 26px 22px 28px;
        background: {ACCENT_DIM};
        font-family: 'IBM Plex Sans', sans-serif;
        font-size: 15px;
        line-height: 1.75;
        color: #ddd;
        margin-top: 14px;
        border-radius: 0 8px 8px 0;
        font-weight: 400;
    }}
    .ew-briefing-eyebrow {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 9px;
        letter-spacing: 0.28em;
        color: {ACCENT};
        text-transform: uppercase;
        margin-bottom: 10px;
    }}

    /* ── Misc labels ── */
    .ew-chart-label {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.18em;
        color: {MUTED};
        text-transform: uppercase;
        margin-bottom: 6px;
    }}

    /* ── Empty state ── */
    .ew-empty {{
        border: 1px dashed {BORDER_HI};
        border-radius: 8px;
        padding: 40px 32px;
        text-align: center;
        margin: 20px 0;
    }}
    .ew-empty-icon {{
        font-size: 24px;
        margin-bottom: 12px;
        color: {ACCENT};
        font-family: 'IBM Plex Mono', monospace;
        letter-spacing: 0.2em;
    }}
    .ew-empty-title {{
        font-family: 'IBM Plex Sans', sans-serif;
        font-size: 15px;
        font-weight: 600;
        color: {TEXT};
        margin-bottom: 6px;
    }}
    .ew-empty-sub {{
        font-size: 13px;
        color: {MUTED};
        line-height: 1.6;
        font-family: 'IBM Plex Sans', sans-serif;
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
        <span class="ew-brand">{LOGO_SVG}<span>EDGEWORK</span></span>
        <span class="ew-topbar-sep">|</span>
        <span class="ew-live-badge"><span class="ew-live-dot"></span>LIVE</span>
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
        st.caption(f"Cached: {modtime.strftime('%Y-%m-%d %H:%M UTC')}")

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
        """
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
        st.caption(f"Showing **`{active}`** · {len(trades):,} positions")

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
                """
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
                """
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
# Top metric row
# --------------------------------------------------------------------------- #

exp_cls  = "pos" if overall.expectancy >= 0 else "neg"
pnl_cls  = "pos" if overall.total_pnl  >= 0 else "neg"
exp_sign = "+" if overall.expectancy > 0 else ""
pnl_sign = "+" if overall.total_pnl  > 0 else ""
n_wins   = int(round(overall.winrate * overall.n_trades))

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
    close_col = next(
        (c for c in ("closed_at", "close_time", "updatedAt") if c in df.columns),
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

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=eq[close_col], y=eq["cum"],
            fill="tozeroy",
            fillcolor=fill_color,
            line=dict(color="rgba(0,0,0,0)", width=0),
            showlegend=False, hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=eq[close_col], y=eq["cum"],
            mode="lines",
            line=dict(color=line_color, width=2),
            showlegend=False,
            hovertemplate="<b>%{x|%b %d, %H:%M}</b><br>Cum. PNL: $%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_annotation(
        x=eq[close_col].iloc[-1], y=eq["cum"].iloc[-1],
        text=f"  {'+' if final>=0 else ''}${final:,.0f}",
        showarrow=False,
        font=dict(color=line_color, family="IBM Plex Mono, monospace", size=12, weight=600),
        xanchor="left",
    )

    fig.update_layout(
        plot_bgcolor=BG, paper_bgcolor=BG,
        font=dict(color=TEXT, family="IBM Plex Mono, monospace"),
        xaxis=dict(
            showgrid=False, color=MUTED,
            tickfont=dict(family="IBM Plex Mono, monospace", size=9),
            linecolor=BORDER, linewidth=1,
        ),
        yaxis=dict(
            showgrid=True, gridcolor=GRID, gridwidth=1,
            zerolinecolor=MUTED, zerolinewidth=1, color=MUTED,
            tickfont=dict(family="IBM Plex Mono, monospace", size=9),
            tickprefix="$",
        ),
        margin=dict(l=10, r=50, t=10, b=10),
        height=200,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=PANEL, bordercolor=BORDER,
            font=dict(family="IBM Plex Mono, monospace", size=11),
        ),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


st.markdown('<div class="ew-chart-label">Equity Curve · cumulative PNL</div>', unsafe_allow_html=True)
_equity_curve(trades)

st.divider()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

# Metric registry — what goes in the segmented control above each chart.
METRICS = {
    "PNL":        {"col": "total_pnl",  "label": "Total PNL",      "axis": "Total PNL (USD)",  "fmt": "$%{y:,.0f}",  "is_pct": False},
    "Expectancy": {"col": "expectancy", "label": "Expectancy",     "axis": "Expectancy (USD)", "fmt": "$%{y:,.2f}",  "is_pct": False},
    "Winrate":    {"col": "winrate",    "label": "Win Rate",       "axis": "Win Rate",         "fmt": "%{y:.1%}",    "is_pct": True},
}
METRIC_KEYS = list(METRICS.keys())


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
    tag: str, label: str, value: float, n_trades: int,
    winrate: float, total_pnl: float, *, kind: str,
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
            tag=tag, label=label_fn(row[key_col]),
            value=row["expectancy"], n_trades=int(row["n_trades"]),
            winrate=row["winrate"], total_pnl=row["total_pnl"], kind=kind,
        )
        for (tag, kind, row) in rows
    )
    st.markdown(f'<div class="ew-card-grid">{html_cards}</div>', unsafe_allow_html=True)


def _bar_chart(
    slice_df: pd.DataFrame,
    key_col: str,
    metric_key: str,
    *,
    sort_by_key: bool = False,
    key_label_fn=None,
) -> None:
    """Render a bar chart for the chosen metric (PNL / Expectancy / Winrate)."""
    if slice_df.empty:
        return
    meta = METRICS[metric_key]

    df = slice_df.copy()
    if sort_by_key:
        df = df.sort_values(key_col)
    else:
        df = df.sort_values(meta["col"])

    label_fn = key_label_fn or (lambda v: str(v))
    labels = [label_fn(v) for v in df[key_col]]
    values = df[meta["col"]].tolist()

    if meta["is_pct"]:
        # Winrate: 50% baseline; green above, red below
        colors = [GREEN if v >= 0.5 else RED for v in values]
    else:
        colors = [GREEN if v >= 0 else RED for v in values]

    n_trades = df["n_trades"].astype(int).tolist()
    customdata = list(zip(
        n_trades,
        df["winrate"].tolist(),
        df["expectancy"].tolist(),
        df["total_pnl"].tolist(),
    ))

    n_bars = len(labels)
    bar_kwargs: dict = dict(
        x=labels, y=values,
        marker=dict(color=colors, opacity=0.88, line=dict(width=0)),
        text=[f"n={n}" for n in n_trades],
        textposition="outside",
        textfont=dict(color=MUTED, size=9, family="IBM Plex Mono, monospace"),
        customdata=customdata,
        hovertemplate=(
            "<b>%{x}</b><br>"
            f"{meta['label']}: <b>{meta['fmt']}</b><br>"
            "Trades: %{customdata[0]}<br>"
            "Winrate: %{customdata[1]:.1%}<br>"
            "Expectancy: $%{customdata[2]:,.2f}<br>"
            "Total PNL: $%{customdata[3]:,.0f}"
            "<extra></extra>"
        ),
    )
    xaxis_range = None
    if n_bars <= 4:
        bar_kwargs["width"] = 0.45
        target_span = 7
        pad = max(1.0, (target_span - n_bars) / 2)
        xaxis_range = [-0.5 - pad, n_bars - 0.5 + pad]

    fig = go.Figure(data=[go.Bar(**bar_kwargs)])

    yaxis_kwargs: dict = dict(
        showgrid=True, gridcolor=GRID, gridwidth=1,
        zerolinecolor=MUTED, zerolinewidth=1.5, color=MUTED,
        tickfont=dict(family="IBM Plex Mono, monospace", size=10),
        title=dict(text=meta["axis"], font=dict(color=MUTED, size=10)),
    )
    if meta["is_pct"]:
        yaxis_kwargs["tickformat"] = ".0%"
    else:
        yaxis_kwargs["tickprefix"] = "$"

    fig.update_layout(
        plot_bgcolor=SURFACE, paper_bgcolor=BG,
        font=dict(color=TEXT, family="IBM Plex Mono, monospace"),
        xaxis=dict(
            showgrid=False, color=MUTED,
            tickfont=dict(family="IBM Plex Mono, monospace", size=10),
            tickangle=0, type="category",
            linecolor=BORDER, linewidth=1, range=xaxis_range,
        ),
        yaxis=yaxis_kwargs,
        margin=dict(l=10, r=10, t=20, b=10),
        height=360, bargap=0.28,
        hoverlabel=dict(
            bgcolor=PANEL, bordercolor=BORDER,
            font=dict(family="IBM Plex Mono, monospace", size=11),
        ),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _hour_dow_heatmap(df: pd.DataFrame, metric_key: str) -> None:
    """Day-of-week × hour-of-day heatmap. Replaces the bar chart for Hour tab."""
    open_col = next(
        (c for c in ("opened_at", "createdAt", "open_time") if c in df.columns),
        None,
    )
    pnl_col = next(
        (c for c in ("pnl", "realizedPnL", "realized_pnl") if c in df.columns),
        None,
    )
    if open_col is None or pnl_col is None:
        return

    d = df[[open_col, pnl_col]].copy().dropna()
    if not pd.api.types.is_datetime64_any_dtype(d[open_col]):
        d[open_col] = pd.to_datetime(d[open_col], unit="ms", utc=True, errors="coerce")
    d = d.dropna()
    d["dow"] = d[open_col].dt.dayofweek
    d["hour"] = d[open_col].dt.hour
    d["win"] = (d[pnl_col] > 0).astype(int)

    if metric_key == "PNL":
        agg = d.groupby(["dow", "hour"])[pnl_col].sum()
        cnt = d.groupby(["dow", "hour"]).size()
        z_label, fmt = "Total PNL", "$%{z:,.0f}"
    elif metric_key == "Winrate":
        agg = d.groupby(["dow", "hour"])["win"].mean()
        cnt = d.groupby(["dow", "hour"]).size()
        z_label, fmt = "Win Rate", "%{z:.1%}"
    else:  # Expectancy
        agg = d.groupby(["dow", "hour"])[pnl_col].mean()
        cnt = d.groupby(["dow", "hour"]).size()
        z_label, fmt = "Expectancy", "$%{z:,.2f}"

    matrix = (
        agg.unstack(fill_value=np.nan)
        .reindex(index=range(7), columns=range(24))
    )
    counts = (
        cnt.unstack(fill_value=0)
        .reindex(index=range(7), columns=range(24), fill_value=0)
    )

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    hours = [f"{h:02d}" for h in range(24)]

    if metric_key == "Winrate":
        zmid, zmin, zmax = 0.5, 0.0, 1.0
    else:
        # Use 85th percentile of |values| so outliers don't crush
        # the rest of the cells toward the (dim) midpoint.
        finite = matrix.values[np.isfinite(matrix.values)]
        if finite.size:
            absmax = float(np.nanpercentile(np.abs(finite), 85)) or 1.0
        else:
            absmax = 1.0
        zmid, zmin, zmax = 0, -absmax, absmax

    # Diverging scale with vivid extremes and a visible mid-tone so
    # near-zero cells still register as cells rather than disappearing
    # into the background.
    colorscale = [
        [0.0,  RED],         # full red
        [0.35, "#5a1820"],   # dark red
        [0.5,  "#1c1c1c"],   # dark gray (not pure black)
        [0.65, "#0f4a30"],   # dark green
        [1.0,  GREEN],       # full green
    ]

    fig = go.Figure(
        data=go.Heatmap(
            z=matrix.values,
            x=hours,
            y=days,
            customdata=counts.values,
            colorscale=colorscale,
            zmid=zmid, zmin=zmin, zmax=zmax,
            showscale=False,
            xgap=2, ygap=2,
            hovertemplate=(
                f"<b>%{{y}} %{{x}}:00 UTC</b><br>"
                f"{z_label}: <b>{fmt}</b><br>"
                "Trades: %{customdata}"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        plot_bgcolor=BG, paper_bgcolor=BG,
        font=dict(color=TEXT, family="IBM Plex Mono, monospace"),
        xaxis=dict(
            side="bottom",
            tickfont=dict(family="IBM Plex Mono, monospace", size=9),
            color=MUTED, dtick=2, ticks="",
            showline=False, fixedrange=True,
        ),
        yaxis=dict(
            autorange="reversed",
            tickfont=dict(family="IBM Plex Mono, monospace", size=10),
            color=MUTED, ticks="", fixedrange=True,
        ),
        margin=dict(l=10, r=10, t=10, b=10),
        height=240,
        hoverlabel=dict(
            bgcolor=PANEL, bordercolor=BORDER,
            font=dict(family="IBM Plex Mono, monospace", size=11),
        ),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _format_slice_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    rename = {
        "n_trades": "Trades", "winrate": "Winrate", "avg_pnl": "Avg PNL",
        "expectancy": "Expectancy", "total_pnl": "Total PNL",
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


def _panel_header(title: str, slice_df: pd.DataFrame) -> None:
    """Mini header above each tab's chart: title + best/worst inline KPI."""
    if slice_df.empty or "n_trades" not in slice_df.columns:
        st.markdown(
            f'<div class="ew-panel-head"><span class="ew-panel-title">{title}</span></div>',
            unsafe_allow_html=True,
        )
        return
    df = slice_df[slice_df["n_trades"] >= 5]
    if df.empty:
        df = slice_df
    best = df.loc[df["expectancy"].idxmax()]
    worst = df.loc[df["expectancy"].idxmin()]
    best_pnl = "+" + f"${best['expectancy']:,.2f}" if best["expectancy"] >= 0 else f"−${abs(best['expectancy']):,.2f}"
    worst_pnl = "+" + f"${worst['expectancy']:,.2f}" if worst["expectancy"] >= 0 else f"−${abs(worst['expectancy']):,.2f}"
    st.markdown(
        f"""
        <div class="ew-panel-head">
            <span class="ew-panel-title">{title} · {len(df)} buckets</span>
            <span class="ew-panel-meta">
                Best <span class="pos">{best_pnl}</span>
                &nbsp;·&nbsp;
                Worst <span class="neg">{worst_pnl}</span>
                &nbsp;·&nbsp;
                expectancy / trade
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _metric_pills(key: str) -> str:
    """Render the Total PNL / Expectancy / Winrate switcher and return the chosen key."""
    chosen = st.segmented_control(
        "metric",
        options=METRIC_KEYS,
        default="PNL",
        key=key,
        label_visibility="collapsed",
    )
    return chosen or "PNL"


# --------------------------------------------------------------------------- #
# Conditional performance section
# --------------------------------------------------------------------------- #

st.markdown(
    """
    <div class="ew-section">
        <div class="ew-section-title">Conditional Performance</div>
        <div class="ew-section-sub">
            Where you make money — and where you give it back.
            Cards show the extremes; charts break the chosen metric down per slice.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_hour, tab_streak, tab_size, tab_hold, tab_side, tab_symbol = st.tabs(
    ["Hour of Day", "Loss Streak", "Size", "Hold Time", "Side", "Symbol"]
)


with tab_hour:
    _panel_header("Hour of Day", slices["hour_of_day"])
    metric = _metric_pills("m_hour")
    _render_cards(
        slices["hour_of_day"], key_col="hour",
        key_label_fn=lambda h: f"{int(h):02d}:00 UTC",
    )
    st.markdown(
        '<div class="ew-chart-label">Heatmap · day-of-week × hour-of-day</div>',
        unsafe_allow_html=True,
    )
    _hour_dow_heatmap(trades, metric)
    with st.expander("Bar view + full table"):
        _bar_chart(
            slices["hour_of_day"], key_col="hour", metric_key=metric,
            sort_by_key=True, key_label_fn=lambda h: f"{int(h):02d}h",
        )
        st.dataframe(
            _format_slice_table(slices["hour_of_day"]),
            use_container_width=True, hide_index=True,
        )


with tab_streak:
    _panel_header("Loss Streak", slices["consecutive_losses"])
    metric = _metric_pills("m_streak")
    st.caption(
        "Trades grouped by prior consecutive losses. "
        "If later buckets look much worse, that's a revenge-trading pattern."
    )
    _render_cards(slices["consecutive_losses"], key_col="streak_bucket")
    _bar_chart(
        slices["consecutive_losses"], key_col="streak_bucket", metric_key=metric,
    )
    with st.expander("Full table"):
        st.dataframe(
            _format_slice_table(slices["consecutive_losses"]),
            use_container_width=True, hide_index=True,
        )


with tab_size:
    _panel_header("Position Size", slices["size_quartile"])
    metric = _metric_pills("m_size")
    st.caption(
        "Bucketed by your own size quartile (Q1 = smallest 25%, Q4 = largest 25%). "
        "Reveals whether you actually make money on big bets."
    )
    _render_cards(slices["size_quartile"], key_col="size_quartile")
    _bar_chart(
        slices["size_quartile"], key_col="size_quartile",
        metric_key=metric, sort_by_key=True,
    )
    with st.expander("Full table"):
        st.dataframe(
            _format_slice_table(slices["size_quartile"]),
            use_container_width=True, hide_index=True,
        )


with tab_hold:
    _panel_header("Hold Time", slices["hold_duration"])
    metric = _metric_pills("m_hold")
    _render_cards(slices["hold_duration"], key_col="hold_bucket")
    _bar_chart(
        slices["hold_duration"], key_col="hold_bucket", metric_key=metric,
    )
    with st.expander("Full table"):
        st.dataframe(
            _format_slice_table(slices["hold_duration"]),
            use_container_width=True, hide_index=True,
        )


with tab_side:
    _panel_header("Side", slices["side"])
    metric = _metric_pills("m_side")
    _render_cards(
        slices["side"], key_col="side", key_label_fn=lambda s: str(s).upper(),
    )
    _bar_chart(
        slices["side"], key_col="side", metric_key=metric,
        key_label_fn=lambda s: str(s).upper(),
    )
    with st.expander("Full table"):
        st.dataframe(
            _format_slice_table(slices["side"]),
            use_container_width=True, hide_index=True,
        )


with tab_symbol:
    _panel_header("Symbol", slices["symbol"])
    metric = _metric_pills("m_symbol")
    _render_cards(slices["symbol"], key_col="symbol")
    _bar_chart(slices["symbol"], key_col="symbol", metric_key=metric)
    with st.expander("Full table"):
        st.dataframe(
            _format_slice_table(slices["symbol"]),
            use_container_width=True, hide_index=True,
        )


st.divider()


# --------------------------------------------------------------------------- #
# AI Briefing
# --------------------------------------------------------------------------- #

st.markdown(
    """
    <div class="ew-section">
        <div class="ew-section-title">Pre-Session Briefing</div>
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
            "**Anthropic API key not configured.** Add it in one of:\n\n"
            "- **Streamlit Cloud:** "
            "*Manage app → Settings → Secrets* and paste:\n"
            "  ```\n"
            "  ANTHROPIC_API_KEY = \"sk-ant-...\"\n"
            "  SOSOVALUE_API_KEY = \"...\"   # optional, for live market context\n"
            "  ```\n"
            "- **Local:** add the same keys to your `.env` file.\n\n"
            "The conditional performance dashboard above works without these keys."
        )
    else:
        with st.spinner("Pulling market context and generating…"):
            try:
                with SoSoValueClient() as soso:
                    market_ctx = (
                        briefing.build_market_context_from_sosovalue(soso)
                        if s.sosovalue_api_key
                        else briefing.MarketContext(
                            btc_dominance=None, btc_etf_net_flow_usd=None,
                            eth_etf_net_flow_usd=None, top_sector_24h=None,
                            bottom_sector_24h=None, news_sentiment=None,
                            notable_news=None, btc_regime=None,
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
