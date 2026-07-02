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

# Branded favicon: the orange bar from the logo, as an inline SVG data URI.
_FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='6' fill='%230a0a0a'/%3E"
    "%3Crect x='9' y='6' width='6' height='20' rx='3' fill='%23f5841f'/%3E"
    "%3Crect x='18' y='6' width='5' height='20' rx='2.5' fill='%23f5841f' opacity='0.35'/%3E"
    "%3C/svg%3E"
)

st.set_page_config(
    page_title="Edgework — trade analytics for pro traders",
    page_icon=_FAVICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Palette aligned with Edgework design system (Autopsy Engine).
BG          = "#0a0a0a"
SURFACE     = "#0c0c0c"
PANEL       = "#0c0c0c"
BORDER      = "#1a1a1a"   # was --line
BORDER_HI   = "#222222"   # was --line2
ACCENT      = "#f5841f"
ACCENT_DIM  = "rgba(245,132,31,0.06)"
ACCENT_GLOW = "rgba(245,132,31,0.25)"
TEXT        = "#f5f5f5"
MUTED       = "#a8a8a8"   # was --mid (was #888 — bumped for readability on dark bg)
DIM         = "#7a7a7a"   # was --dim (was #555 — bumped for readability)
VDIM        = "#3a3a3a"
GREEN       = "#22cc66"
GREEN_DIM   = "rgba(34,204,102,0.08)"
RED         = "#cc4422"
RED_DIM     = "rgba(204,68,34,0.08)"
GRID        = "#1a1a1a"


# Square dot brand mark (matches Dashboard.html design — blinking amber dot).
LOGO_SVG = (
    '<span style="display:inline-block;width:8px;height:8px;'
    'background:#f5841f;animation:ew-blink 2.4s ease-in-out infinite;'
    'vertical-align:1px"></span>'
)


def _logo_html(size: str = "lg") -> str:
    """Edgework brand lockup: orange bar + 'Edgework' + 'Trade Analytics'.

    size="lg" for the sidebar / landing, "sm" for the compact topbar.
    """
    return (
        f'<span class="ew-logo {size}">'
        '<span class="bar"></span>'
        '<span class="wordmark">'
        '<span class="name">Edgework</span>'
        '<span class="tag">Trade Analytics</span>'
        '</span></span>'
    )


# --------------------------------------------------------------------------- #
# CSS
# --------------------------------------------------------------------------- #

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Space+Mono:wght@400;700&display=swap');

    :root {{
      --ew-amber: {ACCENT};
      --ew-bg: {BG};
    }}

    /* ── App shell ── */
    .stApp {{ background: {BG}; color: {TEXT}; }}
    #MainMenu, footer {{ visibility: hidden; }}
    .stDeployButton {{ display: none !important; }}

    /* Streamlit content above ambient layers */
    .stApp > header, .stApp > div {{ position: relative; z-index: 2; }}

    /* ── Ambient layers (CSS-only port of ambient-layer.css) ── */
    .ew-ambient, .ew-ambient * {{
        position: fixed; inset: 0; pointer-events: none; z-index: 0;
    }}
    .ew-ambient .ew-grid {{
        background-image: repeating-linear-gradient(
            to right, #1a1a1a 0px, #1a1a1a 1px, transparent 1px, transparent 80px
        );
        width: calc(100vw + 240px);
        animation: ew-grid-drift 200s linear infinite;
        will-change: transform;
    }}
    @keyframes ew-grid-drift {{
        from {{ transform: translateX(0); }}
        to   {{ transform: translateX(80px); }}
    }}
    .ew-ambient .ew-spot {{
        background: radial-gradient(
            900px circle at 50% -10%,
            rgba(245,132,31,0.05) 0%,
            rgba(245,132,31,0.02) 35%,
            transparent 70%
        );
    }}
    .ew-ambient .ew-particles {{ overflow: hidden; }}
    .ew-ambient .ew-particles .ew-dot {{
        position: absolute; top: 0; left: 0;
        width: 1px; height: 1px;
        background: {ACCENT};
        opacity: 0;
        animation: ew-dot-drift var(--ew-dur, 28s) linear infinite,
                   ew-dot-fade  var(--ew-dur, 28s) ease-in-out infinite;
        animation-delay: var(--ew-delay, 0s);
        will-change: transform, opacity;
    }}
    @keyframes ew-dot-drift {{
        from {{ transform: translate(var(--ew-x0), var(--ew-y0)); }}
        to   {{ transform: translate(var(--ew-x1), var(--ew-y1)); }}
    }}
    @keyframes ew-dot-fade {{
        0%   {{ opacity: 0; }}
        20%  {{ opacity: 0.7; }}
        80%  {{ opacity: 0.7; }}
        100% {{ opacity: 0; }}
    }}
    .ew-ambient .ew-scan {{
        background-image: repeating-linear-gradient(
            0deg,
            rgba(255,255,255,0.015) 0px,
            rgba(255,255,255,0.015) 1px,
            transparent 1px,
            transparent 3px
        );
        mix-blend-mode: screen;
    }}
    @media (prefers-reduced-motion: reduce) {{
        .ew-ambient .ew-grid {{ animation: none; }}
        .ew-ambient .ew-particles, .ew-ambient .ew-spot {{ display: none; }}
    }}

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
        font-weight: 700;
    }}
    [data-testid="stSidebar"] .stRadio label {{
        font-family: 'Outfit', sans-serif;
        font-size: 13px;
        color: {TEXT};
    }}

    ::selection {{ background: {ACCENT}; color: {BG}; }}

    /* ── Typography ── */
    html, body, [class*="css"], .stMarkdown, p, span, div, label {{
        font-family: 'Outfit', system-ui, sans-serif;
    }}
    h1, h2, h3, h4 {{
        color: {TEXT} !important;
        font-family: 'Outfit', sans-serif !important;
        letter-spacing: -0.02em;
        font-weight: 600;
    }}

    /* ── Tabs ── */
    [data-baseweb="tab-list"] {{
        gap: 0 !important;
        background: transparent;
        padding: 0;
        border: none;
        border-bottom: 1px solid {BORDER};
    }}
    [data-baseweb="tab"] {{
        color: {DIM} !important;
        font-weight: 400;
        font-size: 11px !important;
        border-radius: 0 !important;
        padding: 14px 22px !important;
        transition: color 0.15s ease;
        font-family: 'Space Mono', monospace !important;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        border-right: 1px solid {BORDER} !important;
        background: transparent !important;
    }}
    [data-baseweb="tab"]:hover {{
        color: {TEXT} !important;
        background: rgba(255,255,255,0.02) !important;
    }}
    [data-baseweb="tab"][aria-selected="true"] {{
        color: {ACCENT} !important;
        font-weight: 700 !important;
        background: transparent !important;
        border-bottom: 1px solid {ACCENT} !important;
        margin-bottom: -1px;
    }}
    [data-baseweb="tab-highlight"], [data-baseweb="tab-border"] {{ display: none; }}

    /* ── Buttons ── */
    .stButton > button {{
        background: transparent !important;
        color: {ACCENT} !important;
        border: 1px solid {ACCENT} !important;
        font-weight: 600 !important;
        letter-spacing: 0.18em;
        font-size: 11px !important;
        text-transform: uppercase;
        border-radius: 0 !important;
        transition: all 0.15s ease !important;
        padding: 10px 22px !important;
        font-family: 'Space Mono', monospace !important;
    }}
    .stButton > button:hover {{
        background: {ACCENT} !important;
        color: {BG} !important;
        box-shadow: 0 0 24px {ACCENT_GLOW} !important;
    }}

    /* ── Segmented control ── */
    [data-testid="stSegmentedControl"] button {{
        background: transparent !important;
        border: 1px solid {BORDER} !important;
        color: {DIM} !important;
        font-family: 'Space Mono', monospace !important;
        font-size: 10px !important;
        text-transform: uppercase;
        letter-spacing: 0.18em;
        padding: 5px 12px !important;
        font-weight: 400 !important;
        border-radius: 0 !important;
    }}
    [data-testid="stSegmentedControl"] button:hover {{
        color: {TEXT} !important;
        border-color: {BORDER_HI} !important;
    }}
    [data-testid="stSegmentedControl"] button[aria-checked="true"],
    [data-testid="stSegmentedControl"] button[data-selected="true"] {{
        background: transparent !important;
        border-color: {ACCENT} !important;
        color: {ACCENT} !important;
    }}

    /* ── Inputs ── */
    [data-testid="stTextInput"] input {{
        background: {SURFACE} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 0 !important;
        color: {TEXT} !important;
        font-family: 'Space Mono', monospace !important;
        font-size: 12px !important;
    }}
    [data-testid="stTextInput"] input:focus {{
        border-color: {ACCENT} !important;
        box-shadow: none !important;
    }}

    hr {{ border: none; border-top: 1px solid {BORDER} !important; margin: 28px 0 !important; }}

    [data-testid="stExpander"] {{
        border: 1px solid {BORDER} !important;
        border-radius: 0 !important;
        background: {SURFACE} !important;
    }}
    [data-testid="stExpander"] summary {{
        color: {DIM} !important;
        font-size: 10px !important;
        font-family: 'Space Mono', monospace !important;
        letter-spacing: 0.18em;
        text-transform: uppercase;
    }}

    [data-testid="stDataFrame"] {{
        border: 1px solid {BORDER} !important;
        border-radius: 0 !important;
        overflow: hidden;
    }}

    [data-testid="stSpinner"] > div {{ border-top-color: {ACCENT} !important; }}

    /* ── Animations ── */
    @keyframes ew-blink {{
        0%, 100% {{ opacity: 0.45; }}
        50% {{ opacity: 1; }}
    }}
    @keyframes ew-pulse {{
        0%, 100% {{ opacity: 1; box-shadow: 0 0 0 0 rgba(34,204,102,0.5); }}
        50% {{ opacity: 0.6; box-shadow: 0 0 0 5px rgba(34,204,102,0); }}
    }}

    /* ── Topbar / brand ── */
    .ew-topbar {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 18px;
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        letter-spacing: 0.16em;
        color: {MUTED};
        text-transform: uppercase;
        padding-bottom: 14px;
        border-bottom: 1px solid {BORDER};
        margin-bottom: 20px;
    }}
    .ew-brand {{
        display: inline-flex;
        align-items: center;
        gap: 10px;
        color: {TEXT};
        font-weight: 700;
        font-size: 12px;
        letter-spacing: 0.18em;
    }}
    .ew-topbar-right {{
        display: flex; align-items: center; gap: 22px;
        color: {DIM};
    }}
    .ew-topbar-sep {{ color: {VDIM}; margin: 0 6px; }}
    .ew-crumb {{ color: {DIM}; }}
    .ew-crumb .v {{ color: {TEXT}; }}
    .ew-pill {{
        display: inline-flex; align-items: center; gap: 8px;
        padding: 6px 10px; border: 1px solid {BORDER_HI}; color: {MUTED};
    }}
    .ew-pill-dot {{
        width: 6px; height: 6px; background: {GREEN};
        display: inline-block;
        animation: ew-pulse 2.2s ease-in-out infinite;
    }}

    /* ── Brand logo lockup (orange bar + Edgework + Trade Analytics) ── */
    .ew-logo {{
        display: inline-flex;
        align-items: center;
        gap: 11px;
        text-decoration: none;
        white-space: nowrap;
    }}
    .ew-logo .bar {{
        display: inline-block;
        width: 5px;
        border-radius: 3px;
        background: linear-gradient(180deg, {ACCENT}, #b0560d);
        box-shadow: 0 0 14px {ACCENT_GLOW};
        flex: none;
    }}
    .ew-logo .wordmark {{ display: inline-flex; flex-direction: column; justify-content: center; }}
    .ew-logo .name {{
        font-family: 'Outfit', sans-serif;
        font-weight: 700;
        color: {TEXT};
        line-height: 1;
        letter-spacing: -0.02em;
        text-transform: none;
    }}
    .ew-logo .tag {{
        display: block;
        font-family: 'Space Mono', monospace;
        color: {MUTED};
        text-transform: uppercase;
        margin-top: 5px;
    }}
    .ew-logo.lg .bar  {{ height: 42px; }}
    .ew-logo.lg .name {{ font-size: 28px; }}
    .ew-logo.lg .tag  {{ font-size: 9px; letter-spacing: 0.34em; }}
    .ew-logo.sm .bar  {{ height: 24px; width: 4px; }}
    .ew-logo.sm .name {{ font-size: 17px; letter-spacing: 0.01em; }}
    .ew-logo.sm .tag  {{ display: none; }}

    /* ── Sidebar polish ── */
    section[data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {SURFACE}, {BG});
        border-right: 1px solid {BORDER};
    }}
    .ew-sb-logo {{ padding: 6px 0 4px; }}
    .ew-sb-eyebrow {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        color: {DIM};
        margin: 22px 0 10px;
    }}
    /* Radio → friendly card rows */
    section[data-testid="stSidebar"] div[role="radiogroup"] {{ gap: 7px; }}
    section[data-testid="stSidebar"] div[role="radiogroup"] > label {{
        border: 1px solid {BORDER};
        border-radius: 9px;
        padding: 11px 13px;
        margin: 0 0 7px 0;
        background: {SURFACE};
        transition: border-color .15s, background .15s, transform .1s;
        cursor: pointer;
    }}
    section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {{
        border-color: {ACCENT};
        background: {ACCENT_DIM};
        transform: translateX(2px);
    }}
    section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {{
        border-color: {ACCENT};
        background: {ACCENT_DIM};
        box-shadow: inset 3px 0 0 {ACCENT};
    }}

    /* ── Consistent buttons (brand) ── */
    .stButton > button {{
        font-family: 'Space Mono', monospace !important;
        letter-spacing: 0.09em !important;
        text-transform: uppercase;
        font-size: 12px !important;
        border-radius: 8px !important;
        transition: transform .12s ease, background .15s ease,
                    border-color .15s ease, color .15s ease !important;
    }}
    .stButton > button[kind="primary"] {{
        background: {ACCENT} !important;
        color: #0a0a0a !important;
        border: 1px solid {ACCENT} !important;
        font-weight: 700 !important;
    }}
    .stButton > button[kind="primary"]:hover {{
        background: #ffa64d !important;
        border-color: #ffa64d !important;
        transform: translateY(-1px);
    }}
    .stButton > button[kind="secondary"] {{
        background: transparent !important;
        border: 1px solid {BORDER_HI} !important;
        color: {MUTED} !important;
    }}
    .stButton > button[kind="secondary"]:hover {{
        border-color: {ACCENT} !important;
        color: {ACCENT} !important;
        transform: translateY(-1px);
    }}

    /* ── Headline ── */
    .ew-headline {{
        font-size: 34px;
        font-weight: 700;
        letter-spacing: -0.03em;
        line-height: 1.04;
        margin: 0 0 9px 0;
        color: {TEXT};
        font-family: 'Outfit', sans-serif;
    }}
    .ew-headline .accent {{
        background: linear-gradient(110deg, {ACCENT} 0%, #ffb347 60%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }}
    .ew-sub {{
        color: {MUTED};
        max-width: 720px;
        font-size: 14px;
        line-height: 1.55;
        font-weight: 400;
        font-family: 'Outfit', sans-serif;
    }}

    /* ── Metric grid ── */
    .ew-metrics {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 0;
        border: 1px solid {BORDER};
        margin: 24px 0 16px 0;
    }}
    .ew-metric {{
        background: {SURFACE};
        padding: 22px 24px 18px;
        position: relative;
        border-right: 1px solid {BORDER};
    }}
    .ew-metric:last-child {{ border-right: none; }}
    .ew-metric-label {{
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        letter-spacing: 0.22em;
        color: {MUTED};
        text-transform: uppercase;
        margin-bottom: 10px;
        font-weight: 700;
    }}
    .ew-metric-value {{
        font-family: 'Outfit', sans-serif;
        font-size: 32px;
        font-weight: 500;
        color: {TEXT};
        line-height: 1;
        letter-spacing: -0.02em;
    }}
    .ew-metric-value.pos {{ color: {GREEN}; }}
    .ew-metric-value.neg {{ color: {RED}; }}
    .ew-metric-sub {{
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {DIM};
        margin-top: 9px;
        letter-spacing: 0.06em;
    }}
    .ew-metric-glow {{
        position: absolute;
        bottom: 0; left: 0; right: 0;
        height: 1px;
        background: linear-gradient(90deg, {ACCENT} 0%, transparent 60%);
        opacity: 0.5;
    }}

    /* ── Secondary metric row (risk + fees decomposition) ── */
    .ew-metrics2 {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        border: 1px solid {BORDER};
        border-top: none;
        background: {SURFACE};
    }}
    .ew-metric2 {{
        padding: 12px 22px 13px;
        border-right: 1px solid {BORDER};
        position: relative;
    }}
    .ew-metric2:last-child {{ border-right: none; }}
    .ew-metric2 .k {{
        font-family: 'Space Mono', monospace;
        font-size: 9.5px;
        letter-spacing: 0.2em;
        color: {DIM};
        text-transform: uppercase;
        display: block;
        margin-bottom: 5px;
    }}
    .ew-metric2 .v {{
        font-family: 'Outfit', sans-serif;
        font-size: 19px;
        font-weight: 700;
        color: {TEXT};
    }}
    .ew-metric2 .v.pos {{ color: {GREEN}; }}
    .ew-metric2 .v.neg {{ color: {RED}; }}
    .ew-metric2 .s {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        color: {DIM};
        margin-left: 7px;
    }}
    .ew-fee-flip {{
        border: 1px solid {RED};
        background: rgba(255,59,48,0.05);
        padding: 10px 16px;
        margin-top: 10px;
        font-family: 'Outfit', sans-serif;
        font-size: 13.5px;
        color: {TEXT};
    }}
    .ew-fee-flip strong {{ color: {RED}; }}

    /* ── Tilt watch banner ── */
    .ew-tilt {{
        display: flex;
        align-items: baseline;
        gap: 14px;
        border: 1px solid {ACCENT};
        background: rgba(245,132,31,0.05);
        padding: 12px 18px;
        margin-top: 10px;
        font-family: 'Outfit', sans-serif;
        font-size: 13.5px;
        color: {TEXT};
    }}
    .ew-tilt .tag {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.22em;
        color: {ACCENT};
        font-weight: 700;
        white-space: nowrap;
    }}
    .ew-tilt .neg {{ color: {RED}; font-weight: 700; }}
    .ew-tilt .hi  {{ color: {TEXT}; font-weight: 600; }}

    /* ── Contrarian track record (Wave 3 · Etapa D) ── */
    .ew-track {{
        border: 1px solid {BORDER};
        background: {SURFACE};
        margin-top: 14px;
    }}
    .ew-track-grid {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
    }}
    .ew-track-cell {{
        padding: 16px 20px 14px;
        border-right: 1px solid {BORDER};
    }}
    .ew-track-cell:last-child {{ border-right: none; }}
    .ew-track-cell .k {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        display: block;
        margin-bottom: 8px;
        font-weight: 700;
    }}
    .ew-track-cell.contrarian .k {{ color: {RED}; }}
    .ew-track-cell.aligned    .k {{ color: {GREEN}; }}
    .ew-track-cell.nosignal   .k {{ color: {DIM}; }}
    .ew-track-cell .big {{
        font-family: 'Outfit', sans-serif;
        font-size: 26px;
        font-weight: 700;
        color: {TEXT};
    }}
    .ew-track-cell .sub {{
        font-family: 'Space Mono', monospace;
        font-size: 10.5px;
        color: {DIM};
        margin-top: 6px;
        line-height: 1.7;
    }}
    .ew-track-cell .sub .pos {{ color: {GREEN}; font-weight: 700; }}
    .ew-track-cell .sub .neg {{ color: {RED};   font-weight: 700; }}
    .ew-track-verdict {{
        border-top: 1px solid {BORDER};
        padding: 13px 20px;
        font-family: 'Outfit', sans-serif;
        font-size: 14px;
        color: {TEXT};
    }}
    .ew-track-verdict .pos {{ color: {GREEN}; font-weight: 700; }}
    .ew-track-verdict .neg {{ color: {RED};   font-weight: 700; }}
    .ew-track-caveat {{
        border-top: 1px solid {BORDER};
        padding: 9px 20px;
        font-family: 'Space Mono', monospace;
        font-size: 9.5px;
        color: {DIM};
        line-height: 1.7;
    }}

    /* ── Wave 3 execution layer (simulation panel) ── */
    .ew-sim-eyebrow {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.22em;
        color: {ACCENT};
        text-transform: uppercase;
        margin: 20px 0 8px;
        font-weight: 700;
    }}
    .ew-sim {{
        border: 1px solid {ACCENT};
        background: rgba(245,132,31,0.04);
        padding: 16px 18px 14px;
        margin-top: 6px;
    }}
    .ew-sim-head {{
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        margin-bottom: 13px;
        gap: 12px;
        flex-wrap: wrap;
    }}
    .ew-sim-head .tag {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.18em;
        color: {ACCENT};
        font-weight: 700;
    }}
    .ew-sim-head .meta {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        color: {MUTED};
    }}
    .ew-sim-grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 11px 18px;
    }}
    .ew-sim-grid .wide {{ grid-column: 1 / -1; }}
    .ew-sim-grid .k {{
        display: block;
        font-family: 'Space Mono', monospace;
        font-size: 9px;
        letter-spacing: 0.18em;
        color: {DIM};
        text-transform: uppercase;
        margin-bottom: 3px;
    }}
    .ew-sim-grid .v {{
        font-family: 'Outfit', sans-serif;
        font-size: 13.5px;
        color: {TEXT};
        font-weight: 600;
    }}
    .ew-sim-grid .v.mono {{
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {ACCENT};
        word-break: break-all;
        font-weight: 400;
    }}
    .ew-sim-note {{
        margin-top: 13px;
        padding-top: 11px;
        border-top: 1px solid {BORDER};
        font-family: 'Outfit', sans-serif;
        font-size: 12.5px;
        color: {MUTED};
        line-height: 1.55;
    }}
    .ew-sim-note strong {{ color: {TEXT}; }}

    /* ── Trade Check hero banner (Wave 3 headline) ── */
    .ew-tc-banner {{
        border: 1px solid {ACCENT};
        border-left: 4px solid {ACCENT};
        border-radius: 11px;
        background:
            radial-gradient(120% 160% at 0% 0%, rgba(245,132,31,0.14), transparent 55%),
            linear-gradient(180deg, {SURFACE}, {BG});
        padding: 18px 22px 17px;
        margin: 34px 0 6px;
        box-shadow: 0 0 34px rgba(245,132,31,0.10);
    }}
    .ew-tc-banner-top {{
        display: flex; align-items: center; gap: 13px; flex-wrap: wrap;
    }}
    .ew-tc-banner .title {{
        font-family: 'Outfit', sans-serif;
        font-weight: 700;
        font-size: 23px;
        color: {TEXT};
        letter-spacing: -0.01em;
        line-height: 1;
    }}
    .ew-tc-banner .badge {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.18em;
        font-weight: 700;
        color: #0a0a0a;
        background: {ACCENT};
        padding: 4px 9px;
        border-radius: 5px;
        box-shadow: 0 0 0 0 {ACCENT_GLOW};
        animation: ew-tcpulse 2.6s ease-in-out infinite;
    }}
    @keyframes ew-tcpulse {{
        0%, 100% {{ box-shadow: 0 0 0 0 rgba(245,132,31,0.45); }}
        50%      {{ box-shadow: 0 0 0 7px rgba(245,132,31,0); }}
    }}
    .ew-tc-banner .sub {{
        font-family: 'Outfit', sans-serif;
        font-size: 13.5px;
        color: {MUTED};
        line-height: 1.5;
        margin-top: 9px;
        max-width: 820px;
    }}

    /* ── Trade Check (in-browser pre-trade verdict) ── */
    .ew-tc {{
        border: 1px solid {BORDER_HI};
        border-left: 3px solid {MUTED};
        background: {SURFACE};
        margin-top: 4px;
    }}
    .ew-tc.bad     {{ border-left-color: {RED};   background: rgba(255,59,48,0.04); }}
    .ew-tc.warn    {{ border-left-color: {ACCENT}; background: rgba(245,132,31,0.04); }}
    .ew-tc.neutral {{ border-left-color: {MUTED}; }}
    .ew-tc.ok      {{ border-left-color: {GREEN}; background: rgba(76,175,80,0.03); }}
    .ew-tc.good    {{ border-left-color: {GREEN}; background: rgba(76,175,80,0.05); }}
    .ew-tc .tc-verdict {{
        font-family: 'Outfit', sans-serif;
        font-size: 17px;
        font-weight: 600;
        color: {TEXT};
        padding: 15px 20px 13px;
        border-bottom: 1px solid {BORDER};
    }}
    .ew-tc.bad  .tc-verdict {{ color: {RED}; }}
    .ew-tc.good .tc-verdict {{ color: {GREEN}; }}
    .ew-tc .tc-rows {{ padding: 6px 0; }}
    .ew-tc .tc-row {{
        display: grid;
        grid-template-columns: 28px 200px 1fr;
        align-items: baseline;
        padding: 7px 20px;
        font-family: 'Outfit', sans-serif;
        font-size: 13.5px;
    }}
    .ew-tc .tc-row .i {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        color: {ACCENT};
        font-weight: 700;
    }}
    .ew-tc .tc-row .k {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: {DIM};
    }}
    .ew-tc .tc-row .v {{ color: {TEXT}; }}
    .ew-tc .tc-row .v .pos {{ color: {GREEN}; font-weight: 700; }}
    .ew-tc .tc-row .v .neg {{ color: {RED};   font-weight: 700; }}
    .ew-tc .tc-row .v .lown {{ color: {ACCENT}; font-size: 11px; }}
    .ew-tc .tc-size {{
        display: flex; align-items: baseline; gap: 14px;
        padding: 11px 20px;
        border-top: 1px solid {BORDER};
        background: rgba(255,255,255,0.015);
    }}
    .ew-tc .tc-size .k {{
        font-family: 'Space Mono', monospace; font-size: 10px;
        letter-spacing: 0.16em; text-transform: uppercase; color: {DIM};
    }}
    .ew-tc .tc-size .v {{
        font-family: 'Outfit', sans-serif; font-size: 15px; font-weight: 700;
        color: {TEXT};
    }}
    .ew-tc .tc-size .v.pos {{ color: {GREEN}; }}
    .ew-tc .tc-size .v.neg {{ color: {RED}; }}
    .ew-tc .tc-foot {{
        padding: 10px 20px 12px;
        border-top: 1px solid {BORDER};
        font-family: 'Space Mono', monospace;
        font-size: 9.5px;
        color: {DIM};
        letter-spacing: 0.04em;
    }}

    /* ── Edge Score card (hero) ── */
    @property --ew-ecn {{ syntax: '<integer>'; initial-value: 0; inherits: false; }}
    .ew-edge {{
        display: flex;
        align-items: center;
        gap: 30px;
        border: 1px solid {BORDER_HI};
        border-radius: 14px;
        background:
            radial-gradient(90% 140% at 100% 0%, rgba(245,132,31,0.08), transparent 55%),
            linear-gradient(180deg, {SURFACE}, {BG});
        padding: 22px 28px;
        margin: 8px 0 12px;
        animation: ew-fadeup .5s ease-out both;
    }}
    @keyframes ew-fadeup {{ from {{ opacity: 0; transform: translateY(10px); }}
                            to   {{ opacity: 1; transform: translateY(0); }} }}
    .ew-edge-ring {{ position: relative; width: 128px; height: 128px; flex: none; }}
    .ew-edge-ring svg {{ width: 128px; height: 128px; transform: rotate(-90deg); }}
    .ew-edge-ring .bg {{ fill: none; stroke: {BORDER_HI}; stroke-width: 10; }}
    .ew-edge-ring .arc {{
        fill: none; stroke-width: 10; stroke-linecap: round;
        stroke-dasharray: var(--circ);
        stroke-dashoffset: var(--circ);
        filter: drop-shadow(0 0 6px rgba(245,132,31,0.4));
        animation: ew-ringfill 1.35s ease-out forwards;
    }}
    @keyframes ew-ringfill {{ to {{ stroke-dashoffset: var(--off); }} }}
    .ew-edge-numwrap {{
        position: absolute; inset: 0;
        display: flex; flex-direction: column;
        align-items: center; justify-content: center;
    }}
    .ew-ec-num {{
        font-family: 'Outfit', sans-serif; font-weight: 700;
        font-size: 40px; color: {TEXT}; line-height: 1;
        counter-reset: ecn var(--ew-ecn);
    }}
    .ew-ec-num::after {{ content: counter(ecn); }}
    .ew-edge-numwrap .den {{
        font-family: 'Space Mono', monospace; font-size: 10px; color: {DIM};
        margin-top: 3px; letter-spacing: 0.1em;
    }}
    .ew-edge-meta {{ flex: 1; min-width: 0; }}
    .ew-edge-meta .eyebrow {{
        font-family: 'Space Mono', monospace; font-size: 10px;
        letter-spacing: 0.24em; color: {ACCENT}; font-weight: 700;
    }}
    .ew-edge-meta .grade {{
        font-family: 'Outfit', sans-serif; font-weight: 700;
        font-size: 30px; line-height: 1.05; margin: 3px 0 4px;
    }}
    .ew-edge-meta .desc {{
        font-family: 'Outfit', sans-serif; font-size: 13px;
        color: {MUTED}; line-height: 1.45; max-width: 560px;
    }}
    .ew-edge-stats {{
        display: flex; flex-wrap: wrap; gap: 10px 30px; margin-top: 14px;
    }}
    .ew-edge-stats .k {{
        font-family: 'Space Mono', monospace; font-size: 9.5px;
        letter-spacing: 0.16em; text-transform: uppercase; color: {DIM};
        display: block; margin-bottom: 3px;
    }}
    .ew-edge-stats .v {{
        font-family: 'Outfit', sans-serif; font-size: 18px;
        font-weight: 700; color: {TEXT};
    }}
    .ew-edge-stats .v.pos {{ color: {GREEN}; }}
    .ew-edge-stats .v.neg {{ color: {RED}; }}
    @media (max-width: 740px) {{
        .ew-edge {{ flex-direction: column; text-align: center; }}
    }}

    /* ── TL;DR card (10-second summary) ── */
    .ew-tldr {{
        display: grid;
        grid-template-columns: auto 1fr 1fr 1fr;
        gap: 0;
        border: 1px solid {ACCENT};
        background: linear-gradient(180deg, rgba(245,132,31,0.07), rgba(245,132,31,0.02));
        margin-bottom: 10px;
    }}
    .ew-tldr .cell {{
        padding: 13px 18px;
        border-right: 1px solid {BORDER_HI};
    }}
    .ew-tldr .cell:last-child {{ border-right: none; }}
    .ew-tldr .k {{
        font-family: 'Space Mono', monospace;
        font-size: 9.5px;
        letter-spacing: 0.2em;
        color: {ACCENT};
        text-transform: uppercase;
        display: block;
        margin-bottom: 4px;
        font-weight: 700;
    }}
    .ew-tldr .v {{
        font-family: 'Outfit', sans-serif;
        font-size: 14.5px;
        font-weight: 600;
        color: {TEXT};
    }}
    .ew-tldr .v .pos {{ color: {GREEN}; }}
    .ew-tldr .v .neg {{ color: {RED}; }}
    .ew-tldr .v small {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        color: {DIM};
        margin-left: 6px;
    }}

    /* ── Anchor nav strip ── */
    html {{ scroll-behavior: smooth; }}
    .ew-nav {{
        display: flex;
        flex-wrap: wrap;
        gap: 0;
        border: 1px solid {BORDER};
        background: {SURFACE};
        margin-bottom: 26px;
    }}
    .ew-nav a {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.14em;
        color: {MUTED};
        text-decoration: none;
        text-transform: uppercase;
        padding: 9px 14px;
        border-right: 1px solid {BORDER};
        transition: color .15s, background .15s;
    }}
    .ew-nav a:hover {{ color: {ACCENT}; background: {ACCENT_DIM}; }}
    .ew-nav a .n {{ color: {ACCENT}; margin-right: 6px; }}
    .ew-anchor {{ scroll-margin-top: 64px; }}

    /* ── Term tooltips ── */
    .ew-tip {{
        border-bottom: 1px dotted {DIM};
        cursor: help;
    }}

    /* ── Mobile pass ── */
    @media (max-width: 740px) {{
        .ew-metrics  {{ grid-template-columns: repeat(2, 1fr) !important; }}
        .ew-metrics2 {{ grid-template-columns: repeat(2, 1fr) !important; }}
        .ew-tldr     {{ grid-template-columns: 1fr 1fr !important; }}
        .ew-tldr .cell {{ border-bottom: 1px solid {BORDER_HI}; }}
        .ew-sm-watch, .ew-up-grid {{ overflow-x: auto; }}
        .ew-sm-row, .ew-up-row {{ min-width: 660px; }}
        .ew-headline {{ font-size: 34px !important; }}
        .ew-confront {{ display: block !important; }}
        .ew-confront .left {{ border-right: none !important; border-bottom: 1px solid {BORDER}; }}
    }}

    /* ── Section header ── */
    .ew-section {{ margin-bottom: 14px; margin-top: 24px; }}
    .ew-section-title {{
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        font-weight: 400;
        color: {DIM};
        letter-spacing: 0.22em;
        margin-bottom: 6px;
        text-transform: uppercase;
        display: flex; align-items: center; gap: 12px;
    }}
    .ew-section-title::before {{
        content: ''; display: inline-block;
        width: 18px; height: 1px; background: {DIM};
    }}
    .ew-section-sub {{
        font-size: 14px;
        color: {MUTED};
        line-height: 1.55;
        font-family: 'Outfit', sans-serif;
        font-weight: 400;
    }}
    .ew-section-sub .pos {{ color: {GREEN}; font-weight: 700; }}
    .ew-section-sub .neg {{ color: {RED};   font-weight: 700; }}
    .ew-section-sub strong {{ color: {TEXT}; font-weight: 600; }}
    .ew-section-sub em      {{ color: {TEXT}; font-style: normal; font-weight: 500; }}

    /* ── Panel header ── */
    .ew-panel-head {{
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        padding: 12px 0 14px 0;
        border-bottom: 1px solid {BORDER};
        margin-bottom: 16px;
    }}
    .ew-panel-title {{
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.22em;
        color: {TEXT};
        font-weight: 700;
    }}
    .ew-panel-meta {{
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {MUTED};
        letter-spacing: 0.05em;
    }}
    .ew-panel-meta .pos {{ color: {GREEN}; }}
    .ew-panel-meta .neg {{ color: {RED}; }}

    /* ── Stat cards ── */
    .ew-card-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        gap: 0;
        margin: 4px 0 22px 0;
        border: 1px solid {BORDER};
    }}
    .ew-card {{
        background: {SURFACE};
        padding: 16px 18px 14px;
        position: relative;
        overflow: hidden;
        border-right: 1px solid {BORDER};
    }}
    .ew-card:last-child {{ border-right: none; }}
    .ew-card::before {{
        content: '';
        position: absolute;
        top: 0; left: 0;
        width: 2px; height: 100%;
        background: {BORDER_HI};
    }}
    .ew-card.win::before {{ background: {GREEN}; }}
    .ew-card.loss::before {{ background: {RED}; }}
    .ew-card-tag {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.22em;
        color: {MUTED};
        text-transform: uppercase;
        margin-bottom: 7px;
        font-weight: 700;
    }}
    .ew-card.win .ew-card-tag {{ color: {GREEN}; }}
    .ew-card.loss .ew-card-tag {{ color: {RED}; }}
    .ew-card-lown {{
        display: inline-block;
        font-family: 'Space Mono', monospace;
        font-size: 9px;
        letter-spacing: 0.12em;
        color: {ACCENT};
        border: 1px solid {ACCENT};
        border-radius: 3px;
        padding: 1px 5px;
        margin-left: 8px;
        opacity: 0.85;
        text-transform: uppercase;
        vertical-align: middle;
        cursor: help;
    }}
    .ew-card-label {{
        font-family: 'Outfit', sans-serif;
        font-size: 15px;
        font-weight: 500;
        color: {TEXT};
        margin-bottom: 10px;
        letter-spacing: -0.005em;
    }}
    .ew-card-value {{
        font-family: 'Outfit', sans-serif;
        font-size: 24px;
        font-weight: 500;
        line-height: 1;
        margin-bottom: 10px;
        color: {MUTED};
        letter-spacing: -0.02em;
    }}
    .ew-card-value.win {{ color: {GREEN}; }}
    .ew-card-value.loss {{ color: {RED}; }}
    .ew-wr-track {{
        height: 2px;
        background: {BORDER};
        margin-bottom: 10px;
        overflow: hidden;
    }}
    .ew-wr-fill {{
        height: 100%;
        background: {DIM};
    }}
    .ew-card.win .ew-wr-fill {{ background: {GREEN}; }}
    .ew-card.loss .ew-wr-fill {{ background: {RED}; }}
    .ew-card-meta {{
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {MUTED};
        line-height: 1.85;
        letter-spacing: 0.03em;
    }}
    .ew-card-meta .hi {{ color: {TEXT}; }}
    .ew-card-meta .pos {{ color: {GREEN}; }}
    .ew-card-meta .neg {{ color: {RED}; }}

    /* ── Briefing ── */
    .ew-briefing-wrap {{
        border: 1px solid {BORDER};
        border-left: 2px solid {ACCENT};
        padding: 24px 28px;
        background: {ACCENT_DIM};
        font-family: 'Outfit', sans-serif;
        font-size: 16px;
        line-height: 1.75;
        color: #e8e8e8;
        margin-top: 14px;
        font-weight: 400;
    }}
    .ew-briefing-eyebrow {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.28em;
        color: {ACCENT};
        text-transform: uppercase;
        margin-bottom: 12px;
    }}

    .ew-chart-label {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.2em;
        color: {DIM};
        text-transform: uppercase;
        margin-bottom: 8px;
    }}

    /* ── Counterfactual strip (above equity curve) ── */
    .ew-cf-strip {{
        display: flex;
        gap: 0;
        border-top: 1px solid {BORDER};
        border-bottom: 1px solid {BORDER};
        margin: 4px 0 14px 0;
        background: {SURFACE};
    }}
    .ew-cf-strip .cell {{
        padding: 12px 18px;
        border-right: 1px solid {BORDER};
        display: flex;
        flex-direction: column;
        gap: 6px;
        flex: 1;
        min-width: 0;
    }}
    .ew-cf-strip .cell:last-child {{ border-right: none; }}
    .ew-cf-strip .cell:last-child {{
        background: rgba(245,132,31,0.04);
        border-left: 2px solid {ACCENT};
    }}
    .ew-cf-strip .k {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.16em;
        color: {MUTED};
        text-transform: uppercase;
        font-weight: 700;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .ew-cf-strip .v {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 20px;
        font-weight: 600;
        line-height: 1;
        letter-spacing: -0.02em;
        color: {TEXT};
    }}
    .ew-cf-strip .v.pos {{ color: {GREEN}; }}
    .ew-cf-strip .v.neg {{ color: {RED}; }}

    /* ── Wallet rank banner ── */
    .ew-rank-banner {{
        display: grid;
        grid-template-columns: auto 1fr auto;
        gap: 24px;
        align-items: center;
        padding: 16px 22px;
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-left: 2px solid {ACCENT};
        margin: 16px 0 20px 0;
    }}
    .ew-rank-tier {{
        font-family: 'Space Mono', monospace;
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        padding: 8px 14px;
        border: 1px solid currentColor;
    }}
    .ew-rank-tier.elite    {{ color: {ACCENT}; background: rgba(245,132,31,0.07); }}
    .ew-rank-tier.good     {{ color: {GREEN};  background: rgba(34,204,102,0.06); }}
    .ew-rank-tier.neutral  {{ color: {MUTED}; }}
    .ew-rank-tier.weak     {{ color: {RED};    background: rgba(204,68,34,0.06); }}
    .ew-rank-headline {{
        font-family: 'Outfit', sans-serif;
        font-size: clamp(18px, 1.8vw, 24px);
        font-weight: 500;
        color: {MUTED};
        letter-spacing: -0.01em;
    }}
    .ew-rank-headline .rank,
    .ew-rank-headline .total {{
        color: {TEXT};
        font-weight: 700;
        font-family: 'IBM Plex Mono', monospace;
    }}
    .ew-rank-headline .rank {{ color: {ACCENT}; }}
    .ew-rank-headline .window {{
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        letter-spacing: 0.18em;
        color: {DIM};
        text-transform: uppercase;
        margin-left: 8px;
    }}
    .ew-rank-meta {{
        display: flex;
        gap: 24px;
        align-items: center;
    }}
    .ew-rank-meta .cell {{
        display: flex; flex-direction: column; gap: 4px;
    }}
    .ew-rank-meta .k {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.18em;
        color: {DIM};
        text-transform: uppercase;
        font-weight: 700;
    }}
    .ew-rank-meta .v {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 18px;
        font-weight: 600;
        color: {TEXT};
        letter-spacing: -0.01em;
    }}
    .ew-rank-meta .v.pos {{ color: {GREEN}; }}
    .ew-rank-meta .v.neg {{ color: {RED}; }}

    /* ── AI Q&A box ── */
    .ew-qna-examples {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 10px 0 18px 0;
    }}
    .ew-qna-examples .ex {{
        font-family: 'Outfit', sans-serif;
        font-size: 12px;
        color: {MUTED};
        padding: 5px 11px;
        border: 1px solid {BORDER};
        background: {SURFACE};
        letter-spacing: 0.01em;
        font-weight: 400;
    }}
    .ew-qna-answer {{
        border: 1px solid {BORDER};
        border-left: 2px solid {ACCENT};
        background: {SURFACE};
        padding: 20px 24px;
        margin: 14px 0 4px 0;
    }}
    .ew-qna-question {{
        font-family: 'Space Mono', monospace;
        font-size: 13px;
        color: {ACCENT};
        letter-spacing: 0.04em;
        padding-bottom: 14px;
        margin-bottom: 16px;
        border-bottom: 1px solid {BORDER};
        font-weight: 700;
    }}
    .ew-qna-question .prompt {{ margin-right: 6px; opacity: 0.7; }}
    .ew-qna-body {{
        font-family: 'Outfit', sans-serif;
        font-size: 15px;
        line-height: 1.65;
        color: {TEXT};
        font-weight: 400;
    }}
    .ew-qna-body p {{ margin: 0 0 12px; }}
    .ew-qna-body p:last-child {{ margin-bottom: 0; }}
    .ew-qna-body strong {{ color: {TEXT}; font-weight: 700; }}
    .ew-qna-body code {{
        font-family: 'IBM Plex Mono', monospace;
        background: rgba(245,132,31,0.07);
        color: {ACCENT};
        padding: 1px 6px;
        font-size: 13px;
    }}
    .ew-qna-cost {{
        margin-top: 4px;
        padding: 8px 14px;
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.08em;
        color: {DIM};
        background: {SURFACE};
        border: 1px solid {BORDER};
        display: flex;
        gap: 12px;
        align-items: center;
        flex-wrap: wrap;
    }}
    .ew-qna-cost .k {{
        color: {ACCENT};
        font-weight: 700;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        margin-right: 6px;
    }}
    .ew-qna-cost .cost {{
        color: {TEXT};
        font-weight: 700;
        margin-left: auto;
    }}

    /* ── Smart Money Watch ── */
    .ew-sm-watch {{
        border: 1px solid {BORDER};
        margin: 8px 0 24px 0;
        background: {SURFACE};
    }}
    .ew-sm-row {{
        display: grid;
        grid-template-columns: 1.2fr 1.2fr 1fr 1fr 2fr 1fr;
        gap: 16px;
        padding: 12px 18px;
        border-bottom: 1px solid {BORDER};
        align-items: center;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 13px;
        color: {TEXT};
    }}
    .ew-sm-row:last-child {{ border-bottom: none; }}
    .ew-sm-row.header {{
        background: {BG};
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.22em;
        color: {MUTED};
        text-transform: uppercase;
        font-weight: 700;
    }}
    .ew-sm-row .sym {{
        font-weight: 700;
        letter-spacing: 0.04em;
    }}
    .ew-sm-row .bias {{
        font-family: 'Space Mono', monospace;
        font-size: 12px;
        letter-spacing: 0.06em;
        font-weight: 700;
    }}
    .ew-sm-row .bias.long    {{ color: {GREEN}; }}
    .ew-sm-row .bias.short   {{ color: {RED}; }}
    .ew-sm-row .bias.neutral {{ color: {MUTED}; }}
    .ew-sm-row .size {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 13px;
    }}
    .ew-sm-row .size small {{
        color: {DIM};
        font-size: 11px;
        margin-left: 2px;
    }}
    .ew-sm-row .size.pos {{ color: {GREEN}; }}
    .ew-sm-row .size.neg {{ color: {RED}; }}
    .ew-sm-row .net {{
        font-weight: 700;
        text-align: right;
    }}
    .ew-sm-row .net.pos {{ color: {GREEN}; }}
    .ew-sm-row .net.neg {{ color: {RED}; }}
    .ew-sm-bar {{
        display: flex;
        height: 8px;
        background: {BG};
        overflow: hidden;
    }}
    .ew-sm-bar .long  {{ background: {GREEN}; }}
    .ew-sm-bar .short {{ background: {RED}; }}

    /* ── Your positions vs Smart Money ── */
    .ew-up-grid {{
        border: 1px solid {BORDER};
        margin: 8px 0 24px 0;
        background: {SURFACE};
    }}
    .ew-up-row {{
        display: grid;
        grid-template-columns: 1.1fr 1.8fr 2.6fr 1.6fr;
        gap: 18px;
        padding: 14px 20px;
        border-bottom: 1px solid {BORDER};
        align-items: center;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 13px;
        color: {TEXT};
    }}
    .ew-up-row:last-child {{ border-bottom: none; }}
    .ew-up-row.header {{
        background: {BG};
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.22em;
        color: {MUTED};
        text-transform: uppercase;
        font-weight: 700;
    }}
    .ew-up-row .sym {{
        font-weight: 700;
        letter-spacing: 0.04em;
    }}
    .ew-up-row .my-side {{
        font-family: 'IBM Plex Mono', monospace;
        font-weight: 700;
        font-size: 14px;
    }}
    .ew-up-row .my-side.long  {{ color: {GREEN}; }}
    .ew-up-row .my-side.short {{ color: {RED}; }}
    .ew-up-row .my-side .upnl {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.05em;
        margin-left: 6px;
        opacity: 0.85;
    }}
    .ew-up-row .my-side .upnl.pos {{ color: {GREEN}; }}
    .ew-up-row .my-side .upnl.neg {{ color: {RED}; }}
    .ew-up-row .sm-detail {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 12px;
        color: {MUTED};
    }}
    .ew-up-row .sm-detail .sm-long  {{ color: {GREEN}; }}
    .ew-up-row .sm-detail .sm-short {{ color: {RED}; }}
    .ew-up-row .sm-detail .sm-sep   {{ color: {DIM}; margin: 0 2px; }}
    .ew-up-row .sm-detail .sm-empty {{ color: {DIM}; font-style: italic; }}
    .ew-up-row .status {{
        font-family: 'Space Mono', monospace;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-align: right;
    }}
    .ew-up-row .status.aligned         {{ color: {GREEN}; }}
    .ew-up-row .status.contrarian      {{ color: {RED}; }}
    .ew-up-row .status.weak-contrarian {{ color: {ACCENT}; }}
    .ew-up-row .status.neutral         {{ color: {MUTED}; }}

    .ew-up-warning {{
        padding: 14px 20px;
        margin: 4px 0 0 0;
        background: rgba(204,68,34,0.08);
        border: 1px solid rgba(204,68,34,0.3);
        border-left: 2px solid {RED};
        font-family: 'Outfit', sans-serif;
        font-size: 14px;
        color: {TEXT};
        line-height: 1.5;
    }}
    .ew-up-warning strong {{ color: {RED}; font-weight: 700; }}

    /* ── Empty state ── */
    .ew-empty {{
        border: 1px dashed {BORDER_HI};
        padding: 48px 32px;
        text-align: center;
        margin: 20px 0;
    }}
    .ew-empty-icon {{
        font-size: 22px;
        margin-bottom: 14px;
        color: {ACCENT};
        font-family: 'Space Mono', monospace;
        letter-spacing: 0.22em;
    }}
    .ew-empty-title {{
        font-family: 'Outfit', sans-serif;
        font-size: 16px;
        font-weight: 500;
        color: {TEXT};
        margin-bottom: 6px;
    }}
    .ew-empty-sub {{
        font-size: 14px;
        color: {MUTED};
        line-height: 1.65;
        font-family: 'Outfit', sans-serif;
        font-weight: 400;
    }}

    /* ── Landing (elegant empty state) ── */
    .ew-land-eyebrow {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.24em;
        text-transform: uppercase;
        color: {DIM};
        margin: 22px 0 12px;
        display: flex; align-items: center; gap: 12px;
    }}
    .ew-land-eyebrow::before {{
        content: ""; width: 26px; height: 1px; background: {ACCENT}; opacity: 0.7;
    }}
    .ew-feat-grid {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 14px;
    }}
    .ew-feat-card {{
        position: relative;
        border: 1px solid {BORDER};
        background: linear-gradient(160deg, {SURFACE}, {BG} 70%);
        padding: 15px 17px 16px;
        overflow: hidden;
        transition: border-color .2s ease, transform .18s ease, box-shadow .2s ease;
    }}
    .ew-feat-card::before {{
        content: "";
        position: absolute; top: 0; left: 0; width: 100%; height: 2px;
        background: linear-gradient(90deg, {ACCENT}, transparent 70%);
        opacity: 0; transition: opacity .2s ease;
    }}
    .ew-feat-card:hover {{
        border-color: {BORDER_HI};
        transform: translateY(-3px);
        box-shadow: 0 12px 30px rgba(0,0,0,0.35);
    }}
    .ew-feat-card:hover::before {{ opacity: 1; }}
    .ew-feat-card .n {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.2em;
        color: {ACCENT};
        font-weight: 700;
    }}
    .ew-feat-card .ico {{ font-size: 18px; margin: 9px 0 8px; display: block; }}
    .ew-feat-card .h {{
        font-family: 'Outfit', sans-serif;
        font-weight: 700;
        font-size: 15px;
        color: {TEXT};
        margin-bottom: 5px;
        letter-spacing: -0.01em;
    }}
    .ew-feat-card .d {{
        font-family: 'Outfit', sans-serif;
        font-size: 12px;
        color: {MUTED};
        line-height: 1.45;
    }}
    .ew-trust {{
        display: flex; flex-wrap: wrap; gap: 8px 22px;
        margin-top: 14px;
        font-family: 'Space Mono', monospace;
        font-size: 10.5px;
        letter-spacing: 0.06em;
        color: {DIM};
    }}
    .ew-trust span {{ display: inline-flex; align-items: center; gap: 7px; }}
    .ew-trust .dot {{
        width: 5px; height: 5px; border-radius: 50%; background: {GREEN};
        display: inline-block;
    }}
    @media (max-width: 740px) {{
        .ew-feat-grid {{ grid-template-columns: 1fr !important; }}
    }}

    /* ── Bottombar ── */
    .ew-bottombar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 0 8px 0;
        border-top: 1px solid {BORDER};
        margin-top: 28px;
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        color: {DIM};
        letter-spacing: 0.2em;
        text-transform: uppercase;
    }}
    .ew-bottombar .left,
    .ew-bottombar .right {{
        display: flex; gap: 22px; align-items: center;
    }}
    .ew-bottombar .k {{ color: {DIM}; margin-right: 4px; }}
    .ew-bottombar .v {{ color: {TEXT}; }}
    .ew-bottombar a {{ color: {ACCENT}; text-decoration: none; }}

    /* ── PHASE 3: Slicer bar ── */
    .ew-slicer-section {{
        border-top: 1px solid {BORDER};
        border-bottom: 1px solid {BORDER};
        padding: 0;
        margin: 16px 0 0;
    }}
    .ew-slicer-eyebrow {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.22em;
        color: {DIM};
        text-transform: uppercase;
        padding: 12px 0 8px;
        font-weight: 700;
    }}
    /* Streamlit popover trigger → slicer chip */
    [data-testid="stPopover"] {{
        width: 100%;
    }}
    [data-testid="stPopover"] > div > button,
    [data-testid="stPopover"] button[kind] {{
        background: transparent !important;
        border: 1px solid {BORDER} !important;
        border-radius: 0 !important;
        color: {TEXT} !important;
        font-family: 'Space Mono', monospace !important;
        font-size: 11px !important;
        text-transform: uppercase !important;
        letter-spacing: 0.14em !important;
        padding: 12px 16px !important;
        transition: all 0.15s ease !important;
        width: 100% !important;
        text-align: left !important;
        justify-content: space-between !important;
        font-weight: 700 !important;
        box-shadow: none !important;
    }}
    [data-testid="stPopover"] > div > button:hover,
    [data-testid="stPopover"] button[kind]:hover {{
        border-color: {ACCENT} !important;
        color: {ACCENT} !important;
        background: rgba(245,132,31,0.04) !important;
    }}
    /* Filter status row */
    .ew-filter-status {{
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {MUTED};
        letter-spacing: 0.06em;
        padding: 12px 0;
        margin: 0 0 12px;
        border-bottom: 1px solid {BORDER};
    }}
    .ew-fs-count {{
        color: {TEXT};
        font-weight: 700;
        letter-spacing: 0.08em;
    }}
    .ew-fs-active {{
        color: {DIM};
    }}
    .ew-fs-tag {{
        color: {ACCENT};
        border: 1px solid {ACCENT};
        padding: 3px 9px;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        font-weight: 700;
    }}

    /* ── PHASE 2: Verdict hero ── */
    .ew-verdict {{
        border-top: 1px solid {BORDER};
        border-bottom: 1px solid {BORDER};
        padding: 44px 0 36px;
        margin: 32px 0 24px;
    }}
    .ew-verdict-eyebrow {{
        font-family: 'Space Mono', monospace;
        font-size: 12px;
        color: {MUTED};
        letter-spacing: 0.22em;
        text-transform: uppercase;
        display: flex; align-items: center; gap: 18px;
        margin-bottom: 28px;
        font-weight: 700;
    }}
    .ew-verdict-eyebrow::before {{
        content: ''; display: inline-block;
        width: 18px; height: 1px; background: {DIM};
    }}
    .ew-verdict-eyebrow .v {{ color: {MUTED}; }}
    .ew-conf-meter {{
        display: inline-block; width: 78px; height: 6px;
        background: {BORDER_HI}; border-radius: 3px; overflow: hidden;
        vertical-align: middle; margin: 0 9px;
    }}
    .ew-conf-meter .fill {{
        display: block; height: 100%; border-radius: 3px;
        background: linear-gradient(90deg, {ACCENT}, #ffb347);
        transform: scaleX(0); transform-origin: left;
        animation: ew-confgrow 1.1s ease-out .15s forwards;
    }}
    @keyframes ew-confgrow {{ to {{ transform: scaleX(1); }} }}
    .ew-verdict-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        border-top: 1px solid {BORDER};
        border-bottom: 1px solid {BORDER};
    }}
    .ew-verdict-col {{
        padding: 22px 28px;
        display: grid;
        grid-template-columns: 1fr auto;
        align-items: baseline;
        gap: 4vw;
    }}
    .ew-verdict-col + .ew-verdict-col {{
        border-left: 1px solid {BORDER};
    }}
    .ew-verdict-label {{
        font-family: 'Outfit', sans-serif;
        font-weight: 500;
        font-size: clamp(24px, 3vw, 42px);
        line-height: 1.05;
        letter-spacing: -0.025em;
        color: {TEXT};
    }}
    .ew-verdict-label .em.edge {{ color: {GREEN}; }}
    .ew-verdict-label .em.bleed {{ color: {RED}; }}
    .ew-verdict-num {{
        font-family: 'Space Mono', monospace;
        font-size: clamp(20px, 2.2vw, 28px);
        line-height: 1;
        font-weight: 700;
    }}
    .ew-verdict-num.pos {{ color: {GREEN}; }}
    .ew-verdict-num.neg {{ color: {RED}; }}
    .ew-verdict-rule {{
        margin-top: 28px;
        padding: 0 28px;
        display: flex;
        align-items: center;
        gap: 18px;
        font-family: 'Outfit', sans-serif;
        font-weight: 500;
        font-size: clamp(22px, 2.4vw, 32px);
        letter-spacing: -0.02em;
    }}
    .ew-verdict-rule .arrow {{ color: {ACCENT}; }}
    .ew-verdict-rule .text {{ color: {TEXT}; }}
    .ew-verdict-rule .conf {{
        margin-left: auto;
        font-family: 'Space Mono', monospace;
        font-size: 12px;
        color: {MUTED};
        letter-spacing: 0.18em;
        text-transform: uppercase;
        font-weight: 700;
    }}
    .ew-verdict-rule .conf .v {{ color: {TEXT}; }}
    .ew-verdict-meta {{
        margin-top: 28px;
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        border-top: 1px solid {BORDER};
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {MUTED};
        letter-spacing: 0.14em;
        text-transform: uppercase;
    }}
    .ew-verdict-meta .cell {{ padding: 20px 28px 18px; }}
    .ew-verdict-meta .cell + .cell {{ border-left: 1px solid {BORDER}; }}
    .ew-verdict-meta .k {{ display: block; margin-bottom: 12px; }}
    .ew-verdict-meta .val {{
        display: block;
        color: {TEXT};
        font-family: 'Outfit', sans-serif;
        font-size: 24px;
        letter-spacing: -0.01em;
        font-weight: 600;
        margin-bottom: 8px;
    }}
    .ew-verdict-meta .val.pos {{ color: {GREEN}; }}
    .ew-verdict-meta .val.neg {{ color: {RED}; }}
    .ew-verdict-meta .delta {{
        color: {GREEN};
        font-size: 11px;
        letter-spacing: 0.06em;
    }}
    .ew-verdict-meta .delta.neg {{ color: {RED}; }}
    .ew-verdict-meta .delta.neu {{ color: {MUTED}; }}

    /* ── PHASE 2: Confrontation block ── */
    .ew-confront {{
        display: grid;
        grid-template-columns: 1fr 1.4fr;
        border-top: 1px solid {BORDER};
        border-bottom: 1px solid {BORDER};
        margin: 24px 0;
    }}
    .ew-confront .left, .ew-confront .right {{
        padding: 36px 28px;
    }}
    .ew-confront .left {{ border-right: 1px solid {BORDER}; }}
    .ew-confront h3 {{
        font-family: 'Space Mono', monospace !important;
        font-size: 12px !important;
        color: {MUTED} !important;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        margin-bottom: 22px;
        font-weight: 700 !important;
        display: flex;
        align-items: center;
        gap: 12px;
    }}
    .ew-confront h3::before {{
        content: ''; display: inline-block;
        width: 18px; height: 1px; background: {DIM};
    }}
    .ew-confront h3 .ew-callout {{
        margin-left: auto;
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        color: {ACCENT};
        letter-spacing: 0.18em;
        text-transform: uppercase;
    }}
    .ew-conf-stmt {{
        font-family: 'Outfit', sans-serif;
        font-weight: 400;
        font-size: clamp(18px, 1.6vw, 24px);
        line-height: 1.5;
        letter-spacing: -0.005em;
        color: {MUTED};
    }}
    .ew-conf-stmt .em {{ color: {TEXT}; font-weight: 500; }}
    .ew-conf-stmt .neg {{ color: {RED}; }}
    .ew-conf-stmt .pos {{ color: {GREEN}; }}

    /* Hour-of-day histogram (Confrontation right) */
    .ew-hod {{
        display: grid;
        grid-template-columns: repeat(24, 1fr);
        gap: 2px;
        height: 220px;
        align-items: end;
        margin-top: 8px;
        padding: 8px 0;
        border-top: 1px solid {BORDER};
        border-bottom: 1px solid {BORDER};
        position: relative;
    }}
    .ew-hod-baseline {{
        position: absolute; left: 0; right: 0; top: 50%;
        height: 1px; background: #1f1f1f;
    }}
    .ew-hod-bar {{
        position: relative;
        display: flex;
        flex-direction: column;
        height: 100%;
        justify-content: center;
    }}
    .ew-hod-bar .up, .ew-hod-bar .down {{ display: block; }}
    .ew-hod-bar .up {{ background: {GREEN}; margin-top: auto; }}
    .ew-hod-bar .down {{ background: {RED}; }}
    .ew-hod-bar.peak .up {{ background: {ACCENT}; }}
    .ew-hod-bar.peak::after {{
        content: ""; position: absolute;
        bottom: -8px; left: 50%; transform: translateX(-50%);
        width: 1px; height: 6px; background: {ACCENT};
    }}
    .ew-hod-bar.trough .down {{ background: {ACCENT}; }}
    .ew-hod-axis {{
        display: grid;
        grid-template-columns: repeat(24, 1fr);
        gap: 2px;
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {MUTED};
        margin-top: 8px;
    }}
    .ew-hod-axis span {{ text-align: center; }}
    .ew-hod-legend {{
        margin-top: 18px;
        display: flex;
        gap: 22px;
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {MUTED};
        letter-spacing: 0.1em;
        text-transform: uppercase;
        font-weight: 700;
    }}
    .ew-hod-legend .sw {{
        display: inline-block; width: 10px; height: 10px;
        vertical-align: -1px; margin-right: 8px;
    }}
    .ew-hod-legend .sw.pos {{ background: {GREEN}; }}
    .ew-hod-legend .sw.neg {{ background: {RED}; }}
    .ew-hod-legend .sw.peak {{ background: {ACCENT}; }}

    /* ── PHASE 2: Waterfall ── */
    .ew-waterfall-section {{
        margin: 28px 0 24px;
        padding: 28px;
        border: 1px solid {BORDER};
        background: {SURFACE};
    }}
    .ew-waterfall-header {{
        font-family: 'Space Mono', monospace;
        font-size: 12px;
        color: {MUTED};
        letter-spacing: 0.22em;
        text-transform: uppercase;
        margin-bottom: 20px;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 12px;
    }}
    .ew-waterfall-header::before {{
        content: ''; display: inline-block;
        width: 18px; height: 1px; background: {DIM};
    }}
    .ew-waterfall-wrap {{
        padding: 30px 0 36px;
        margin: 6px 0;
        border-top: 1px solid {BORDER};
        border-bottom: 1px solid {BORDER};
        position: relative;
    }}
    .ew-waterfall {{
        display: grid;
        gap: 8px;
        height: 200px;
        position: relative;
    }}
    .ew-waterfall-baseline {{
        position: absolute; left: 0; right: 0; bottom: 0;
        height: 1px; background: #1f1f1f;
    }}
    .ew-wf-bar {{
        position: relative;
        height: 100%;
    }}
    .ew-wf-bar .body {{
        position: absolute;
        left: 14%; right: 14%;
        background: {GREEN};
        min-height: 2px;
    }}
    .ew-wf-bar.neg .body {{ background: {RED}; }}
    .ew-wf-bar.total .body {{ background: {ACCENT}; }}
    .ew-wf-bar .lbl {{
        position: absolute;
        bottom: -24px; left: 0; right: 0;
        text-align: center;
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {MUTED};
        letter-spacing: 0.12em;
        font-weight: 700;
    }}
    .ew-wf-bar.total .lbl {{ color: {ACCENT}; }}
    .ew-wf-bar .num {{
        position: absolute;
        top: -22px; left: 0; right: 0;
        text-align: center;
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {MUTED};
        font-weight: 700;
    }}
    .ew-wf-bar .num.pos {{ color: {GREEN}; }}
    .ew-wf-bar .num.neg {{ color: {RED}; }}
    .ew-wf-bar .num.acc {{ color: {ACCENT}; }}
    .ew-waterfall-note {{
        margin-top: 22px;
        font-family: 'Outfit', sans-serif;
        font-size: 14px;
        color: {MUTED};
        letter-spacing: 0;
        line-height: 1.7;
        font-weight: 400;
    }}
    .ew-waterfall-note .em {{ color: {ACCENT}; }}
    .ew-waterfall-note .pos {{ color: {GREEN}; }}
    .ew-waterfall-note .neg {{ color: {RED}; }}

    /* ── WAVE 2: Benchmark contrast ── */
    .ew-bench {{
        border: 1px solid {BORDER};
        border-left: 2px solid {ACCENT};
        margin: 24px 0;
        background: {SURFACE};
    }}
    .ew-bench-header {{
        padding: 18px 24px 14px;
        border-bottom: 1px solid {BORDER};
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        flex-wrap: wrap;
        gap: 12px;
    }}
    .ew-bench-title {{
        font-family: 'Space Mono', monospace;
        font-size: 12px;
        color: {ACCENT};
        letter-spacing: 0.22em;
        text-transform: uppercase;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 12px;
    }}
    .ew-bench-title::before {{
        content: ''; display: inline-block;
        width: 18px; height: 1px; background: {ACCENT};
    }}
    .ew-bench-id {{
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {MUTED};
        letter-spacing: 0.12em;
    }}
    .ew-bench-id .v {{ color: {TEXT}; }}
    .ew-bench-grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        border-bottom: 1px solid {BORDER};
    }}
    .ew-bench-cell {{
        padding: 18px 24px 16px;
        border-right: 1px solid {BORDER};
        position: relative;
    }}
    .ew-bench-cell:last-child {{ border-right: none; }}
    .ew-bench-cell-label {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.22em;
        color: {MUTED};
        text-transform: uppercase;
        margin-bottom: 12px;
        font-weight: 700;
    }}
    .ew-bench-cell-row {{
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        margin-bottom: 6px;
        font-family: 'Outfit', sans-serif;
    }}
    .ew-bench-cell-row .who {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        color: {DIM};
        letter-spacing: 0.12em;
        text-transform: uppercase;
        font-weight: 700;
    }}
    .ew-bench-cell-row .who.you {{ color: {ACCENT}; }}
    .ew-bench-cell-row .v {{
        font-family: 'Outfit', sans-serif;
        font-size: 19px;
        font-weight: 600;
        color: {TEXT};
        letter-spacing: -0.01em;
    }}
    .ew-bench-cell-row .v.pos {{ color: {GREEN}; }}
    .ew-bench-cell-row .v.neg {{ color: {RED}; }}
    .ew-bench-diff {{
        margin-top: 8px;
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        color: {MUTED};
        letter-spacing: 0.04em;
    }}
    .ew-bench-diff .em {{ color: {TEXT}; font-weight: 700; }}
    .ew-bench-diff .pos {{ color: {GREEN}; }}
    .ew-bench-diff .neg {{ color: {RED}; }}

    .ew-bench-insights {{
        padding: 22px 24px 20px;
        font-family: 'Outfit', sans-serif;
        font-size: 15px;
        line-height: 1.65;
        color: {TEXT};
        font-weight: 400;
    }}
    .ew-bench-insights .em {{ color: {ACCENT}; font-weight: 600; }}
    .ew-bench-insights .pos {{ color: {GREEN}; font-weight: 600; }}
    .ew-bench-insights .neg {{ color: {RED}; font-weight: 600; }}
    .ew-bench-insights p {{ margin: 0 0 10px; }}
    .ew-bench-insights p:last-child {{ margin-bottom: 0; }}

    /* Scale caveat — quiet footer note clarifying the dollar gaps. */
    .ew-bench-caveat {{
        border-top: 1px solid {BORDER};
        padding: 14px 24px 16px;
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {DIM};
        letter-spacing: 0.04em;
        line-height: 1.7;
    }}
    .ew-bench-caveat .k {{
        color: {ACCENT};
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.16em;
        margin-right: 6px;
    }}
    .ew-bench-caveat .em {{ color: {TEXT}; font-weight: 700; }}
    .ew-bench-caveat strong {{ color: {TEXT}; font-weight: 700; }}

    /* ── WAVE 2 SPRINT 2: Risk filters (anti-patterns) ── */
    .ew-risk {{
        border: 1px solid {BORDER};
        border-left: 2px solid {RED};
        background: {SURFACE};
        margin: 24px 0;
    }}
    .ew-risk-header {{
        padding: 18px 24px 14px;
        border-bottom: 1px solid {BORDER};
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        flex-wrap: wrap;
        gap: 12px;
    }}
    .ew-risk-title {{
        font-family: 'Space Mono', monospace;
        font-size: 12px;
        color: {RED};
        letter-spacing: 0.22em;
        text-transform: uppercase;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 12px;
    }}
    .ew-risk-title::before {{
        content: ''; display: inline-block;
        width: 18px; height: 1px; background: {RED};
    }}
    .ew-risk-id {{
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {MUTED};
        letter-spacing: 0.08em;
    }}
    .ew-risk-list {{ display: flex; flex-direction: column; }}
    .ew-risk-item {{
        padding: 16px 24px;
        border-bottom: 1px solid {BORDER};
        display: grid;
        grid-template-columns: 90px 1fr;
        grid-template-rows: auto auto;
        gap: 4px 18px;
        align-items: center;
    }}
    .ew-risk-item:last-child {{ border-bottom: none; }}
    .ew-risk-tag {{
        font-family: 'Space Mono', monospace;
        font-size: 10px;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        font-weight: 700;
        grid-row: 1 / span 2;
        align-self: center;
        text-align: center;
        padding: 6px 8px;
        border: 1px solid currentColor;
    }}
    .ew-risk-item.warn .ew-risk-tag {{ color: {RED}; }}
    .ew-risk-item.edge .ew-risk-tag {{ color: {GREEN}; }}
    .ew-risk-label {{
        font-family: 'Outfit', sans-serif;
        font-size: 18px;
        color: {TEXT};
        font-weight: 600;
        letter-spacing: -0.005em;
    }}
    .ew-risk-label .k {{
        color: {MUTED}; font-weight: 400; font-family: 'Space Mono', monospace;
        font-size: 12px; letter-spacing: 0.16em; text-transform: uppercase;
    }}
    .ew-risk-label .v {{ color: {TEXT}; }}
    .ew-risk-label .plus {{ color: {MUTED}; margin: 0 10px; font-weight: 300; }}
    .ew-risk-stats {{
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        color: {MUTED};
        letter-spacing: 0.04em;
    }}
    .ew-risk-stats .v {{ color: {TEXT}; font-weight: 700; }}
    .ew-risk-stats .pos {{ color: {GREEN}; font-weight: 700; }}
    .ew-risk-stats .neg {{ color: {RED}; font-weight: 700; }}
    .ew-risk-footer {{
        padding: 14px 24px 16px;
        border-top: 1px solid {BORDER};
        font-family: 'Outfit', sans-serif;
        font-size: 13px;
        color: {MUTED};
        line-height: 1.6;
        font-weight: 400;
    }}
    .ew-risk-footer strong {{ color: {TEXT}; font-weight: 600; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #

# Ambient layers — fixed-position decorative background.
# Pure CSS implementation (no JS): hand-seeded particle positions
# replace the runtime-random ones from ambient-layer.ts. Drifting grid,
# scanlines and top-spotlight are pure CSS.
_PARTICLES = [
    # (x0_vw, y0_vh, x1_vw, y1_vh, dur_s, delay_s)
    (5,  90, 95, 10, 32, -3),
    (80, 95, 20, 5,  38, -12),
    (15, 70, 90, 20, 28, -7),
    (60, 85, 10, 25, 35, -18),
    (40, 60, 95, 95, 26, -22),
    (90, 40, 5,  90, 33, -2),
    (25, 30, 80, 85, 30, -14),
    (70, 15, 15, 75, 36, -8),
    (10, 50, 75, 95, 29, -25),
    (55, 5,  20, 70, 34, -17),
]
_particles_html = "".join(
    (
        f'<div class="ew-dot" style="--ew-x0:{x0}vw;--ew-y0:{y0}vh;'
        f"--ew-x1:{x1}vw;--ew-y1:{y1}vh;"
        f'--ew-dur:{dur}s;--ew-delay:{delay}s"></div>'
    )
    for (x0, y0, x1, y1, dur, delay) in _PARTICLES
)

# --------------------------------------------------------------------------- #
# i18n — minimal lookup for PT/EN UI strings
# --------------------------------------------------------------------------- #

_LANG_DEFAULT = "EN"
_LANG_OPTIONS = ["EN", "PT"]

# Keys are stable IDs; values are dicts keyed by language code.
# Missing key falls back to the default lang's string, then to the key itself.
_TRANSLATIONS: dict[str, dict[str, str]] = {
    # Headline
    "headline_1": {"EN": "Know your edge.", "PT": "Conheça seu edge."},
    "headline_2": {"EN": "Cut the noise.",   "PT": "Corte o ruído."},
    "headline_sub": {
        "EN": (
            "PNL doesn't show where your edge is. Edgework slices your SoDEX history "
            "across time, behavior, and market regime — so you see exactly which setups "
            "make you money, and which ones quietly bleed it."
        ),
        "PT": (
            "PNL não mostra onde está seu edge. O Edgework fatia seu histórico da SoDEX "
            "por tempo, comportamento e regime de mercado — para você ver exatamente "
            "quais setups te dão dinheiro e quais sangram silenciosamente."
        ),
    },

    # Section titles
    "sec_conditional":       {"EN": "Conditional Performance · Deep Dive",     "PT": "Performance Condicional · Análise Profunda"},
    "sec_conditional_sub":   {
        "EN": "Where you make money — and where you give it back. Cards show the extremes; charts break the chosen metric down per slice.",
        "PT": "Onde você ganha dinheiro — e onde devolve. Os cards mostram os extremos; os gráficos quebram a métrica escolhida por slice.",
    },
    "sec_smart_money":       {"EN": "Smart Money Watch · Live",                "PT": "Smart Money Watch · Ao Vivo"},
    "sec_your_positions":    {"EN": "Your positions vs Smart Money · Live",    "PT": "Suas posições vs Smart Money · Ao Vivo"},
    "sec_diagnostic":        {"EN": "Full Diagnostic",                         "PT": "Diagnóstico Completo"},
    "sec_diagnostic_sub":    {
        "EN": "A complete autopsy of your trading: top 5 problems destroying your account, the data behind each, and 3-5 specific rules to implement. Single deterministic call — predictable cost, every number cited comes from a tool call against your data.",
        "PT": "Uma autópsia completa do seu trading: os 5 maiores problemas destruindo sua conta, os dados por trás de cada um, e 3-5 regras específicas pra implementar. Chamada única determinística — custo previsível, todo número citado vem de uma tool call contra seus dados.",
    },
    "btn_diagnostic":        {"EN": "Generate diagnostic",                     "PT": "Gerar diagnóstico"},

    # Equity curve / counterfactual strip
    "eq_label":           {"EN": "Equity Curve · cumulative PNL",                  "PT": "Curva de Equity · PNL acumulado"},
    "eq_label_with_cf":   {"EN": "Equity Curve · cumulative PNL · with counterfactual overlay",
                           "PT": "Curva de Equity · PNL acumulado · com cenário contrafactual"},
    "cf_actual":          {"EN": "ACTUAL",                "PT": "REAL"},
    "cf_if_avoided":      {"EN": "IF AVOIDED",            "PT": "SE EVITADO"},
    "cf_recovered":       {"EN": "RECOVERED",             "PT": "RECUPERADO"},
    "cf_trades_skipped":  {"EN": "trades skipped",        "PT": "trades evitados"},

    # Slicer bar
    "slicer_eyebrow":     {"EN": "— Slicers · filter the dataset",
                           "PT": "— Filtros · refine o dataset"},

    # Smart Money Watch
    "sm_subtitle":        {
        "EN": "Open positions of the top {n_traders} actively-trading SoDEX winners (top 50 by 30d volume, filtered to positive PNL). <strong>{n_in_market}</strong> currently in market · refreshed {fetched} · cached 15 min.",
        "PT": "Posições abertas dos top {n_traders} traders ativos e lucrativos da SoDEX (top 50 por volume 30d, filtrados por PNL positivo). <strong>{n_in_market}</strong> com posição agora · atualizado {fetched} · cache 15 min.",
    },
    "sm_how_to_read":     {
        "EN": "<strong>How to read it:</strong> each row is a symbol. <strong>LONG $ / SHORT $</strong> = combined notional of all qualified traders on each side, with the count in parentheses. <strong>NET EXPOSURE</strong> = where the smart-money <em>book</em> collectively points after long/short netted out. <span class='pos'>Green</span> = net long, <span class='neg'>red</span> = net short.",
        "PT": "<strong>Como ler:</strong> cada linha é um símbolo. <strong>LONG $ / SHORT $</strong> = notional combinado de todos os traders qualificados em cada lado, com a contagem entre parênteses. <strong>NET EXPOSURE</strong> = pra onde o <em>book</em> dos top traders coletivamente aponta após long/short se cancelarem. <span class='pos'>Verde</span> = líquido long, <span class='neg'>vermelho</span> = líquido short.",
    },
    "sm_h_symbol":        {"EN": "SYMBOL",                       "PT": "SÍMBOLO"},
    "sm_h_bias":          {"EN": "BIAS",                         "PT": "VIÉS"},
    "sm_h_long":          {"EN": "LONG $ (TRADERS)",             "PT": "LONG $ (TRADERS)"},
    "sm_h_short":         {"EN": "SHORT $ (TRADERS)",            "PT": "SHORT $ (TRADERS)"},
    "sm_h_split":         {"EN": "SPLIT BY NOTIONAL",            "PT": "DIVISÃO POR NOTIONAL"},
    "sm_h_net":           {"EN": "NET EXPOSURE",                 "PT": "EXPOSIÇÃO LÍQUIDA"},
    "sm_long_word":       {"EN": "long",                         "PT": "long"},
    "sm_short_word":      {"EN": "short",                        "PT": "short"},
    "sm_flat":            {"EN": "flat",                         "PT": "neutro"},
    "sm_no_pos":          {
        "EN": "Top {n} active+profitable SoDEX traders (top 50 by 30d volume, filtered to positive PNL). Right now none of them have open positions — wait for the next snapshot.",
        "PT": "Top {n} traders ativos e lucrativos da SoDEX (top 50 por volume 30d, filtrados por PNL positivo). Agora nenhum tem posição aberta — aguarde o próximo snapshot.",
    },
    "sm_unavailable":     {"EN": "Smart Money Watch unavailable: {err}", "PT": "Smart Money Watch indisponível: {err}"},
    "sm_no_traders":      {"EN": "Smart Money Watch — no active winners found in the leaderboard.",
                           "PT": "Smart Money Watch — nenhum vencedor ativo encontrado no leaderboard."},

    # Your positions vs Smart Money
    "up_subtitle":        {
        "EN": "Live comparison of your <strong>{n}</strong> open position{s} against the qualified smart-money book. <span class='pos'>✓ aligned</span> = you and smart money on the same side. <span class='neg'>⚠ contrarian</span> = you opposite to a clear smart-money bias (≥3 aligned or 2× notional dominance).",
        "PT": "Comparação ao vivo das suas <strong>{n}</strong> posições abertas contra o book dos top traders. <span class='pos'>✓ alinhado</span> = você e smart money do mesmo lado. <span class='neg'>⚠ contrário</span> = você oposto a um viés claro do smart money (≥3 alinhados ou 2× dominância de notional).",
    },
    "up_no_open":         {
        "EN": "You currently have no open positions on SoDEX. The smart-money watch below shows where top traders are positioned right now.",
        "PT": "Você não tem posições abertas na SoDEX agora. O Smart Money Watch abaixo mostra onde os top traders estão posicionados.",
    },
    "up_warning":         {
        "EN": "<strong>⚠ {n}</strong> of your open position{s_be} contrarian to smart-money bias. Once the alert bot is configured, you would have received a Discord notification on entry.",
        "PT": "<strong>⚠ {n}</strong> das suas posições abertas {s_be} contrária{s_pl} ao viés do smart money. Quando o bot de alertas estiver configurado, você receberia uma notificação no Discord na abertura.",
    },
    "up_h_symbol":        {"EN": "SYMBOL",         "PT": "SÍMBOLO"},
    "up_h_your_pos":      {"EN": "YOUR POSITION",  "PT": "SUA POSIÇÃO"},
    "up_h_smart_money":   {"EN": "SMART MONEY",    "PT": "SMART MONEY"},
    "up_h_status":        {"EN": "STATUS",         "PT": "STATUS"},
    "up_status_aligned":           {"EN": "✓ aligned",            "PT": "✓ alinhado"},
    "up_status_contrarian":        {"EN": "⚠ contrarian",         "PT": "⚠ contrário"},
    "up_status_weak_contrarian":   {"EN": "⚠ leaning contrarian", "PT": "⚠ tendendo contrário"},
    "up_status_mixed":             {"EN": "~ mixed signal",       "PT": "~ sinal misto"},
    "up_status_no_consensus":      {"EN": "— no consensus",       "PT": "— sem consenso"},
    "up_sm_no_qualified":          {"EN": "no qualified trader in this symbol",
                                    "PT": "nenhum top trader nesse símbolo"},
    "up_long_word":      {"EN": "long",   "PT": "long"},
    "up_short_word":     {"EN": "short",  "PT": "short"},
    "up_traders_word":   {"EN": "traders", "PT": "traders"},
    "up_split_word":     {"EN": "Smart money split", "PT": "Smart money dividido"},
    "up_you":            {"EN": "You",   "PT": "Você"},
    "up_too_word":       {"EN": "too",   "PT": "também"},
    "up_but_word":       {"EN": "but smart money is", "PT": "mas o smart money está"},

    # Bottombar
    "bb_wallet":          {"EN": "WALLET",         "PT": "CARTEIRA"},
    "bb_readonly":        {"EN": "READ-ONLY",      "PT": "SOMENTE-LEITURA"},
    "bb_build":           {"EN": "BUILD",          "PT": "BUILD"},
    "bb_built_by":        {"EN": "BUILT BY",       "PT": "FEITO POR"},

    # Lang toggle label
    "lang_label":         {"EN": "Language",       "PT": "Idioma"},

    # Diagnostic header + spinners
    "diag_running":       {"EN": "Running diagnostic — analyzing your full history…",
                           "PT": "Rodando diagnóstico — analisando seu histórico completo…"},
    "diag_header":        {"EN": "Full diagnostic · 5 biggest problems & priority actions",
                           "PT": "Diagnóstico completo · 5 maiores problemas e ações prioritárias"},
    "sm_loading":         {"EN": "Loading Smart Money Watch…",
                           "PT": "Carregando Smart Money Watch…"},
    "up_loading":         {"EN": "Checking your live positions…",
                           "PT": "Verificando suas posições ao vivo…"},

    # Wallet input section
    "wallet_section_title": {"EN": "Pull live SoDEX history",
                             "PT": "Buscar histórico ao vivo da SoDEX"},
    "wallet_section_sub":   {"EN": "Paste any wallet address that has traded perpetuals on SoDEX. Fetched directly from the public API — no auth required.",
                             "PT": "Cole qualquer endereço de carteira que tenha operado perps na SoDEX. Buscado direto da API pública — sem necessidade de login."},
    "wallet_fetch":         {"EN": "Fetch",          "PT": "Buscar"},
    "wallet_invalid":       {"EN": "That doesn't look like a valid EVM address. Expected format: `0x` followed by 40 hex characters.",
                             "PT": "Esse endereço não parece válido. Formato esperado: `0x` seguido de 40 caracteres hexadecimais."},

    # Metric row
    "m_total_trades":     {"EN": "Total Trades",        "PT": "Total de Trades"},
    "m_win_rate":         {"EN": "Win Rate",            "PT": "Taxa de Acerto"},
    "m_expectancy":       {"EN": "Expectancy / Trade",  "PT": "Expectativa / Trade"},
    "m_realized_pnl":     {"EN": "Realized PNL",        "PT": "PNL Realizado"},
    "m_closed_positions": {"EN": "closed positions",    "PT": "posições fechadas"},
    "m_of_wins":          {"EN": "{w:,} of {n:,} wins", "PT": "{w:,} de {n:,} ganhos"},
    "m_per_trade":        {"EN": "per trade avg",       "PT": "média por trade"},
    "m_all_closed":       {"EN": "all closed trades",   "PT": "todos os trades fechados"},

    # Secondary metric row (risk + fee decomposition)
    "m2_profit_factor":   {"EN": "PROFIT FACTOR",   "PT": "FATOR DE LUCRO"},
    "m2_pf_sub":          {"EN": "gross wins ÷ gross losses", "PT": "ganhos ÷ perdas brutas"},
    "m2_max_dd":          {"EN": "MAX DRAWDOWN",    "PT": "DRAWDOWN MÁXIMO"},
    "m2_dd_sub":          {"EN": "peak → trough",   "PT": "pico → fundo"},
    "m2_gross":           {"EN": "GROSS PNL",       "PT": "PNL BRUTO"},
    "m2_gross_sub":       {"EN": "before fees",     "PT": "antes das taxas"},
    "m2_fees":            {"EN": "FEES PAID",       "PT": "TAXAS PAGAS"},
    "m2_fees_sub":        {"EN": "{pct}% of gross profit", "PT": "{pct}% do lucro bruto"},
    "fee_flip":           {
        "EN": "Your trading is <strong>gross-profitable</strong> ({g}) — but fees ({f}) flip you to {n} net. The edge exists; execution costs are eating it. Fewer, larger entries beat many small ones.",
        "PT": "Seu trading é <strong>lucrativo no bruto</strong> ({g}) — mas as taxas ({f}) te viram para {n} líquido. O edge existe; os custos de execução estão comendo ele. Menos entradas, maiores, vencem muitas pequenas.",
    },

    # Rank banner
    "rank_top":           {"EN": "TOP {p}%",           "PT": "TOP {p}%"},
    "rank_ranked":        {"EN": 'Ranked <span class="rank">#{rank:,}</span> of <span class="total">{total:,}</span> traders',
                           "PT": 'Ranqueado <span class="rank">#{rank:,}</span> entre <span class="total">{total:,}</span> traders'},
    "rank_30d_volume":    {"EN": "30D VOLUME",         "PT": "VOLUME 30D"},
    "rank_sodex_30d_pnl": {"EN": "SODEX 30D PNL",      "PT": "PNL SODEX 30D"},
    "rank_dim_volume":    {"EN": "30D VOLUME",         "PT": "VOLUME 30D"},

    # TL;DR card
    "tldr_eyebrow":  {"EN": "10-SECOND READ", "PT": "LEITURA DE 10s"},
    "tldr_dataset":  {"EN": "{n} trades · {days}d", "PT": "{n} trades · {days}d"},
    "tldr_leak":     {"EN": "Biggest leak",  "PT": "Maior vazamento"},
    "tldr_edge":     {"EN": "Best edge",     "PT": "Melhor edge"},
    "tldr_fees":     {"EN": "Fees paid",     "PT": "Taxas pagas"},
    "tldr_net":      {"EN": "Net PNL",       "PT": "PNL líquido"},

    # Landing (elegant empty state)
    "land_eyebrow":  {"EN": "What you'll get", "PT": "O que você vai ver"},
    "land_f1_h":     {"EN": "Trade Check",       "PT": "Trade Check"},
    "land_f1_d":     {"EN": "Check any trade against your own history and the live smart-money book before you take it.",
                      "PT": "Cheque qualquer trade contra o seu histórico e o book do smart money antes de entrar."},
    "land_f2_h":     {"EN": "Smart Money Watch",  "PT": "Smart Money Watch"},
    "land_f2_d":     {"EN": "See where the top active + profitable SoDEX traders are positioned right now.",
                      "PT": "Veja onde os top traders ativos e lucrativos da SoDEX estão posicionados agora."},
    "land_f3_h":     {"EN": "AI Diagnostic",      "PT": "Diagnóstico IA"},
    "land_f3_d":     {"EN": "A full autopsy of your trading — the 5 biggest problems, each quantified in dollars.",
                      "PT": "Uma autópsia completa do seu trading — os 5 maiores problemas, cada um quantificado em dólares."},
    "land_t1":       {"EN": "Read-only",          "PT": "Somente leitura"},
    "land_t2":       {"EN": "Public API · no login", "PT": "API pública · sem login"},
    "land_t3":       {"EN": "No private key, ever", "PT": "Nunca pede chave privada"},

    # Edge Score card
    "eg_eyebrow":     {"EN": "EDGE SCORE", "PT": "EDGE SCORE"},
    "eg_pf":          {"EN": "Profit factor", "PT": "Fator de lucro"},
    "eg_consistency": {"EN": "Consistency",   "PT": "Consistência"},
    "eg_winrate":     {"EN": "Win rate",      "PT": "Taxa de acerto"},
    "eg_net":         {"EN": "Net PNL",       "PT": "PNL líquido"},
    "eg_download":    {"EN": "⬇ Download Edge Card (share on X)",
                       "PT": "⬇ Baixar Edge Card (compartilhar no X)"},
    "eg_verified":    {"EN": "VERIFIED", "PT": "VERIFICADO"},
    "eg_sub_hit":     {"EN": "Hit rate",   "PT": "Taxa de acerto"},
    "eg_sub_netp":    {"EN": "Net profit", "PT": "Lucro líquido"},
    "eg_sub_netn":    {"EN": "Net loss",   "PT": "Prejuízo líquido"},
    "eg_pf_exc":      {"EN": "Exceptional efficiency", "PT": "Eficiência excepcional"},
    "eg_pf_strong":   {"EN": "Strong efficiency",      "PT": "Eficiência forte"},
    "eg_pf_pos":      {"EN": "Net positive",           "PT": "Positivo no líquido"},
    "eg_pf_weak":     {"EN": "Losing more than winning", "PT": "Perde mais do que ganha"},
    "eg_badge_elite":  {"EN": "EXCEPTIONAL PERFORMANCE", "PT": "DESEMPENHO EXCEPCIONAL"},
    "eg_badge_strong": {"EN": "STRONG PERFORMANCE",      "PT": "DESEMPENHO FORTE"},
    "eg_badge_solid":  {"EN": "SOLID PERFORMANCE",       "PT": "DESEMPENHO SÓLIDO"},
    "eg_badge_dev":    {"EN": "DEVELOPING",              "PT": "EM DESENVOLVIMENTO"},
    "eg_badge_leak":   {"EN": "NEEDS WORK",              "PT": "PRECISA MELHORAR"},
    "eg_elite":   {"EN": "Elite edge",       "PT": "Edge de elite"},
    "eg_elite_d": {"EN": "Consistently profitable across conditions with a strong profit factor. This is a real, durable edge.",
                   "PT": "Consistentemente lucrativo em várias condições, com fator de lucro forte. Um edge real e durável."},
    "eg_strong":   {"EN": "Strong edge",     "PT": "Edge forte"},
    "eg_strong_d": {"EN": "You make more than you lose and it holds across most conditions — a genuine, repeatable edge.",
                    "PT": "Você ganha mais do que perde e isso se sustenta na maioria das condições — um edge genuíno e repetível."},
    "eg_solid":   {"EN": "Solid edge",       "PT": "Edge sólido"},
    "eg_solid_d": {"EN": "Positive overall, but the edge concentrates in some setups and leaks in others. Cut the leaks.",
                   "PT": "Positivo no geral, mas o edge se concentra em alguns setups e vaza em outros. Corte os vazamentos."},
    "eg_dev":   {"EN": "Developing",         "PT": "Em desenvolvimento"},
    "eg_dev_d": {"EN": "The pieces are there but inconsistent. Lean into your profitable buckets and drop the rest.",
                 "PT": "As peças existem, mas inconsistentes. Foque nos buckets lucrativos e largue o resto."},
    "eg_leak":   {"EN": "Leaking edge",      "PT": "Edge vazando"},
    "eg_leak_d": {"EN": "You're giving back more than you make. The diagnostic below shows exactly where.",
                  "PT": "Você está devolvendo mais do que ganha. O diagnóstico abaixo mostra exatamente onde."},

    # Sidebar
    "sb_data_source": {"EN": "Data source", "PT": "Fonte de dados"},
    "sb_footnote":    {"EN": "Peer benchmark vs top traders is fetched automatically — no manual input needed.",
                       "PT": "O benchmark vs top traders é buscado automaticamente — sem input manual."},

    # Anchor nav
    "nav_tradecheck":  {"EN": "Trade Check",  "PT": "Trade Check"},
    "nav_verdict":     {"EN": "Verdict",      "PT": "Veredito"},
    "nav_confront":    {"EN": "Belief check", "PT": "Crença×Dados"},
    "nav_waterfall":   {"EN": "Waterfall",    "PT": "Waterfall"},
    "nav_conditional": {"EN": "Performance",  "PT": "Performance"},
    "nav_peers":       {"EN": "Top traders",  "PT": "Top traders"},
    "nav_risk":        {"EN": "Risk filters", "PT": "Filtros de risco"},
    "nav_smartmoney":  {"EN": "Smart money",  "PT": "Smart money"},
    "nav_diagnostic":  {"EN": "AI diagnostic","PT": "Diagnóstico IA"},

    # Trade Check (Wave 3 — in-browser pre-trade verdict)
    "tc_title":   {"EN": "Trade Check", "PT": "Trade Check"},
    "tc_badge":   {"EN": "WAVE 3 · NEW", "PT": "WAVE 3 · NOVO"},
    "tc_sub":     {
        "EN": "Thinking about a trade? Check it against your own history and the live smart-money book — instantly, in your browser. No wallet to connect, nothing to install.",
        "PT": "Pensando em uma trade? Cheque contra o seu próprio histórico e o book do smart money ao vivo — na hora, no navegador. Sem conectar carteira, sem instalar nada.",
    },
    "tc_symbol":  {"EN": "Symbol", "PT": "Símbolo"},
    "tc_side":    {"EN": "Side",   "PT": "Lado"},
    "tc_your_history": {"EN": "Your history on this setup", "PT": "Seu histórico nesse setup"},
    "tc_smart_money":  {"EN": "Smart money right now",      "PT": "Smart money agora"},
    "tc_regime":       {"EN": "Current regime fit",         "PT": "Ajuste ao regime atual"},
    "tc_win":     {"EN": "win",    "PT": "acerto"},
    "tc_trades":  {"EN": "trades", "PT": "trades"},
    "tc_long":    {"EN": "long",   "PT": "long"},
    "tc_short":   {"EN": "short",  "PT": "short"},
    "tc_aligned":    {"EN": "aligned with you",  "PT": "alinhado com você"},
    "tc_contrarian": {"EN": "you'd be contrarian", "PT": "você estaria contra"},
    "tc_no_history": {"EN": "no closed trades on this symbol+side yet",
                     "PT": "nenhum trade fechado nesse símbolo+lado ainda"},
    "tc_sm_nosignal":{"EN": "no clear smart-money bias on this symbol",
                     "PT": "sem viés claro do smart money nesse símbolo"},
    "tc_regime_your":      {"EN": "your {regime} {side} edge", "PT": "seu edge {side} em {regime}"},
    "tc_regime_nodata":    {"EN": "not enough {regime} trades on this setup to read",
                            "PT": "poucos trades em {regime} nesse setup pra ler"},
    "tc_regime_unavailable": {"EN": "regime data unavailable right now",
                              "PT": "dados de regime indisponíveis agora"},
    "tc_v_strong_avoid": {"EN": "🛑 This {side} fights your history AND the smart-money book — strong skip.",
                          "PT": "🛑 Esse {side} briga com seu histórico E com o smart money — pule essa."},
    "tc_v_caution":      {"EN": "⚠ This {side} leans against you — cut size or wait for a better window.",
                          "PT": "⚠ Esse {side} pesa contra você — corte o tamanho ou espere uma janela melhor."},
    "tc_v_mixed":        {"EN": "~ Mixed signal on this {side} — no strong edge either way.",
                          "PT": "~ Sinal misto nesse {side} — sem edge forte pra nenhum lado."},
    "tc_v_favorable":    {"EN": "✓ This {side} is in your favor — the data backs it.",
                          "PT": "✓ Esse {side} está a seu favor — os dados apoiam."},
    "tc_v_strong_go":    {"EN": "✅ This {side} aligns with your edge AND the smart-money book — green light.",
                          "PT": "✅ Esse {side} bate com seu edge E com o smart money — sinal verde."},
    "tc_foot":    {"EN": "Read-only decision support — Edgework never places the order; it tells you whether to.",
                   "PT": "Suporte à decisão, somente leitura — o Edgework nunca envia a ordem; ele te diz se vale."},
    "tc_market":  {"EN": "Live market", "PT": "Mercado ao vivo"},
    "tc_mark":    {"EN": "mark",    "PT": "mark"},
    "tc_funding": {"EN": "funding", "PT": "funding"},
    "tc_fund_favors":  {"EN": "favors your side",  "PT": "a favor do seu lado"},
    "tc_fund_against": {"EN": "against your side",  "PT": "contra o seu lado"},
    "tc_vs_entry":     {"EN": "vs your median entry", "PT": "vs sua entrada mediana"},
    "tc_market_unavailable": {"EN": "price unavailable right now",
                              "PT": "preço indisponível agora"},
    "tc_size":         {"EN": "Suggested size", "PT": "Tamanho sugerido"},
    "tc_size_up":      {"EN": "Size up — full conviction",   "PT": "Aumente — convicção total"},
    "tc_size_normal":  {"EN": "Normal size",                 "PT": "Tamanho normal"},
    "tc_size_half":    {"EN": "Half size, or wait for a better setup", "PT": "Metade do tamanho, ou espere um setup melhor"},
    "tc_size_quarter": {"EN": "Quarter size, or stand aside", "PT": "Um quarto do tamanho, ou fique de fora"},
    "tc_size_skip":    {"EN": "Skip — no size here",         "PT": "Pule — sem tamanho aqui"},

    # One-click demo
    "demo_btn":      {"EN": "🎲 No wallet? Try a top trader's →",
                      "PT": "🎲 Sem carteira? Teste com um top trader →"},
    "demo_loading":  {"EN": "Loading a live top-trader demo…",
                      "PT": "Carregando demo com um top trader ao vivo…"},
    "demo_showing":  {"EN": "Live demo · top SoDEX trader",
                      "PT": "Demo ao vivo · top trader da SoDEX"},
    "demo_failed":   {"EN": "Couldn't fetch the leaderboard right now — paste a wallet instead.",
                      "PT": "Não consegui buscar o leaderboard agora — cole uma carteira manualmente."},

    # Term tooltips (title attributes)
    "tip_expectancy": {
        "EN": "Expectancy = average $ you make (or lose) per trade: winrate × avg win − loss rate × avg loss.",
        "PT": "Expectativa = quanto você ganha (ou perde) em média por trade: taxa de acerto × ganho médio − taxa de erro × perda média.",
    },
    "tip_pf": {
        "EN": "Profit factor = gross wins ÷ gross losses. Above 1.0 you make more than you lose; prop desks like ≥1.5.",
        "PT": "Fator de lucro = ganhos brutos ÷ perdas brutas. Acima de 1.0 você ganha mais do que perde; mesas proprietárias gostam de ≥1.5.",
    },
    "tip_dd": {
        "EN": "Max drawdown = the deepest peak-to-trough drop of your cumulative PNL. Your worst losing stretch in dollars.",
        "PT": "Drawdown máximo = a maior queda pico-a-fundo do seu PNL acumulado. Sua pior sequência perdedora em dólares.",
    },
    "tip_gross": {
        "EN": "What your trading made before trading fees were deducted.",
        "PT": "O que seu trading rendeu antes de descontar as taxas de negociação.",
    },
    "tip_fees": {
        "EN": "Total trading fees paid across all closed positions in this dataset.",
        "PT": "Total de taxas de negociação pagas em todas as posições fechadas deste dataset.",
    },
    "tip_confidence": {
        "EN": "Bootstrap probability: we resampled your trades 2,000 times; in this % of resamples the edge bucket beat the bleed bucket. Capped when samples are small.",
        "PT": "Probabilidade por bootstrap: reamostramos seus trades 2.000 vezes; nessa % das reamostragens o bucket de edge venceu o de ralo. Limitada quando a amostra é pequena.",
    },
    "tip_cf_actual": {
        "EN": "Your real cumulative PNL, as traded.",
        "PT": "Seu PNL acumulado real, como foi operado.",
    },
    "tip_cf_avoided": {
        "EN": "Simulated equity curve if the trades matching the risk-filter anti-patterns had been skipped.",
        "PT": "Curva simulada se os trades que caem nos anti-padrões dos filtros de risco tivessem sido evitados.",
    },
    "tip_cf_recovered": {
        "EN": "The dollar difference between the two curves — what those patterns cost you.",
        "PT": "A diferença em dólares entre as duas curvas — o que esses padrões te custaram.",
    },

    # Progressive-disclosure expander labels
    "exp_waterfall": {"EN": "03 · PNL Waterfall — which dimension bleeds most",
                      "PT": "03 · Waterfall de PNL — qual dimensão mais sangra"},
    "exp_risk":      {"EN": "06 · Risk filters — your worst 2-dimension combos",
                      "PT": "06 · Filtros de risco — seus piores combos de 2 dimensões"},

    # Contrarian track record (Wave 3 · Etapa D)
    "tr_title":      {"EN": "Your history vs the smart-money book",
                      "PT": "Seu histórico vs o book do smart money"},
    "tr_sub":        {
        "EN": "Every trade you opened in the last {days} days, classified by what the qualified top traders were holding <em>at that exact moment</em> — reconstructed from their position history. This is the evidence behind the divergence alert.",
        "PT": "Cada trade que você abriu nos últimos {days} dias, classificado pelo que os top traders qualificados seguravam <em>naquele exato momento</em> — reconstruído do histórico de posições deles. Essa é a evidência por trás do alerta de divergência.",
    },
    "tr_contrarian": {"EN": "⚠ Against the book", "PT": "⚠ Contra o book"},
    "tr_aligned":    {"EN": "✓ With the book",    "PT": "✓ Com o book"},
    "tr_nosignal":   {"EN": "— No clear signal",  "PT": "— Sem sinal claro"},
    "tr_trades":     {"EN": "trades",  "PT": "trades"},
    "tr_win":        {"EN": "win",     "PT": "acerto"},
    "tr_exp":        {"EN": "/trade",  "PT": "/trade"},
    "tr_total":      {"EN": "total",   "PT": "total"},
    "tr_verdict_bad": {
        "EN": "Fighting the book costs you <span class='neg'>{contr_exp}</span>/trade vs <span class='pos'>{alig_exp}</span>/trade with it — a <span class='neg'>{gap}</span> gap across {n} contrarian entries. The Discord alert would have pinged you on every one of them.",
        "PT": "Brigar com o book te custa <span class='neg'>{contr_exp}</span>/trade vs <span class='pos'>{alig_exp}</span>/trade a favor — um gap de <span class='neg'>{gap}</span> em {n} entradas contrárias. O alerta do Discord teria te avisado em cada uma delas.",
    },
    "tr_verdict_good": {
        "EN": "Interesting: your contrarian entries ({contr_exp}/trade) actually outperform your aligned ones ({alig_exp}/trade). You may have genuine fade-the-crowd edge — the alert still helps you take those consciously rather than by accident.",
        "PT": "Interessante: suas entradas contrárias ({contr_exp}/trade) na verdade superam as alinhadas ({alig_exp}/trade). Você pode ter edge genuíno de ir contra a multidão — o alerta ainda ajuda a tomar essas posições conscientemente, não por acidente.",
    },
    "tr_empty":      {
        "EN": "No trades in the last {days} days overlapped a clear smart-money bias — nothing to classify yet.",
        "PT": "Nenhum trade nos últimos {days} dias coincidiu com um viés claro do smart money — nada pra classificar ainda.",
    },
    "tr_loading":    {"EN": "Reconstructing the smart-money book at your entry times…",
                      "PT": "Reconstruindo o book do smart money nos seus horários de entrada…"},
    "tr_caveat":     {
        "EN": "Method: book reconstructed from the position history (≤1,000 most recent per trader) of today's qualified top traders ({n_traders}); their set may differ from who qualified at trade time. Your own wallet is excluded from the book. Same bias thresholds as the live watch (≥3 traders or 2× notional).",
        "PT": "Método: book reconstruído do histórico de posições (≤1.000 mais recentes por trader) dos top traders qualificados de hoje ({n_traders}); o conjunto pode diferir de quem qualificava na época do trade. Sua própria carteira é excluída do book. Mesmos limiares de viés do watch ao vivo (≥3 traders ou 2× notional).",
    },

    # Wave 3 execution layer (simulation)
    "w3_eyebrow":    {"EN": "⚡ Execution layer · Wave 3 preview · simulation only",
                      "PT": "⚡ Camada de execução · prévia Wave 3 · apenas simulação"},
    "w3_close_btn":  {"EN": "⚡ Close {symbol} · SIM", "PT": "⚡ Fechar {symbol} · SIM"},
    "w3_sim_tag":    {"EN": "SIGNED ORDER · SIMULATION — NOTHING WAS SENT",
                      "PT": "ORDEM ASSINADA · SIMULAÇÃO — NADA FOI ENVIADO"},
    "w3_action":     {"EN": "Action",           "PT": "Ação"},
    "w3_reduce_only":{"EN": "reduce-only",      "PT": "apenas redução"},
    "w3_signer":     {"EN": "Ephemeral signer", "PT": "Signatário efêmero"},
    "w3_signature":  {"EN": "Signature (0x01·r·s·v)", "PT": "Assinatura (0x01·r·s·v)"},
    "w3_digest":     {"EN": "EIP-712 digest",   "PT": "Digest EIP-712"},
    "w3_note":       {
        "EN": "<strong>How this works for real:</strong> this exact body, signed via the same EIP-712 pipeline, is what the local execution companion POSTs to SoDEX's /exchange. There it's signed with <strong>your own revocable SoDEX API key</strong> — from your machine, from your .env, never touching our servers. The hosted app only ever simulates with a throwaway key. Every close order is reduce-only by construction: it can shrink risk, never add it.",
        "PT": "<strong>Como funciona de verdade:</strong> esse body exato, assinado pelo mesmo pipeline EIP-712, é o que o companion local de execução envia pro /exchange da SoDEX. Lá ele é assinado com <strong>sua própria API key revogável da SoDEX</strong> — na sua máquina, do seu .env, sem nunca tocar nossos servidores. O app hospedado só simula com chave descartável. Toda ordem de fechamento é reduce-only por construção: só reduz risco, nunca adiciona.",
    },
    "w3_body_label": {"EN": "Exact POST body — what SoDEX /exchange would receive",
                      "PT": "Body POST exato — o que o /exchange da SoDEX receberia"},
    "w3_dismiss":    {"EN": "✕ Dismiss simulation", "PT": "✕ Fechar simulação"},

    # Discord divergence alerts wizard (Wave 3)
    "al_title":   {"EN": "Smart Money Divergence Alerts · Discord",
                   "PT": "Alertas de Divergência Smart Money · Discord"},
    "al_sub":     {
        "EN": "Get pinged the moment you open a position against the qualified smart-money book. Paste a Discord webhook to test it here; run the local bot to receive alerts continuously — read-only, no private key.",
        "PT": "Receba um ping no momento em que você abre uma posição contra o book dos top traders. Cole um webhook do Discord pra testar aqui; rode o bot local pra receber alertas continuamente — somente leitura, sem chave privada.",
    },
    "al_webhook_label": {"EN": "Discord webhook URL", "PT": "URL do webhook do Discord"},
    "al_test_btn":   {"EN": "Send test message", "PT": "Enviar mensagem de teste"},
    "al_test_ok":    {"EN": "✓ Test sent — check your Discord channel.",
                      "PT": "✓ Teste enviado — confira seu canal no Discord."},
    "al_test_fail":  {"EN": "Discord rejected the webhook (HTTP {code}). Double-check the URL.",
                      "PT": "O Discord rejeitou o webhook (HTTP {code}). Confira a URL."},
    "al_test_err":   {"EN": "Could not reach Discord: {err}", "PT": "Não consegui acessar o Discord: {err}"},
    "al_need_url":   {"EN": "Paste a webhook URL first.", "PT": "Cole uma URL de webhook primeiro."},
    "al_help":       {
        "EN": "Create one in Discord: Server Settings → Integrations → Webhooks → New Webhook → Copy URL.",
        "PT": "Crie um no Discord: Configurações do Servidor → Integrações → Webhooks → Novo Webhook → Copiar URL.",
    },
    "al_run_label":  {"EN": "Then run the watcher on your machine:",
                      "PT": "Depois rode o monitor na sua máquina:"},
    "al_run_note":   {
        "EN": "It polls your open positions every few minutes and posts a Discord alert on each new <strong>smart-money divergence</strong> and each position that matches one of your own losing <strong>2D risk patterns</strong> — deduped so the same position never double-pings.",
        "PT": "Ele verifica suas posições abertas a cada poucos minutos e posta um alerta no Discord a cada nova <strong>divergência do smart money</strong> e a cada posição que bate num dos seus <strong>padrões de risco 2D</strong> perdedores — com dedupe pra mesma posição nunca avisar duas vezes.",
    },

    # Tilt watch banner
    "tilt_tag":   {"EN": "TILT CHECK", "PT": "CHECAGEM DE TILT"},
    "tilt_body":  {
        "EN": "Your last <span class='hi'>{s}</span> trades were losses (most recent {ago}). Historically, your next trade after {bucket} runs <span class='neg'>{exp}</span>/trade across <span class='hi'>{n}</span> samples. Your own data says: step away or cut size.",
        "PT": "Seus últimos <span class='hi'>{s}</span> trades foram perdas (o mais recente {ago}). Historicamente, seu próximo trade após {bucket} roda <span class='neg'>{exp}</span>/trade em <span class='hi'>{n}</span> amostras. Seus próprios dados dizem: pause ou reduza o tamanho.",
    },
    "tilt_ago_h": {"EN": "{h}h ago", "PT": "há {h}h"},
    "tilt_ago_m": {"EN": "{m}min ago", "PT": "há {m}min"},

    # Verdict
    "v_eyebrow":          {"EN": "Verdict · {dim} · {conf}% confidence",
                           "PT": "Veredito · {dim} · {conf}% de confiança"},
    "v_is_your_edge":     {"EN": "is your",            "PT": "é seu"},
    "v_is_your_bleed":    {"EN": "is your",            "PT": "é seu"},
    "v_edge_word":        {"EN": "edge",               "PT": "edge"},
    "v_bleed_word":       {"EN": "bleed",              "PT": "ralo"},
    "v_arrow_advice":     {"EN": "Avoid {worst} {dim_word} — your edge is in {best}.",
                           "PT": "Evite {worst} {dim_word} — seu edge está em {best}."},
    "v_confidence":       {"EN": "Confidence · {conf}%", "PT": "Confiança · {conf}%"},
    "v_net_pnl":          {"EN": "Net PNL · 365d",      "PT": "PNL Líquido · 365d"},
    "v_edge_pnl":         {"EN": "Edge PNL · {best}",  "PT": "PNL do Edge · {best}"},
    "v_bleed_pnl":        {"EN": "Bleed PNL · {worst}","PT": "PNL do Ralo · {worst}"},
    "v_recovered":        {"EN": "Recovered if avoided","PT": "Recuperado se evitado"},
    "v_n_trades":         {"EN": "{n} trades",         "PT": "{n} trades"},
    "v_trades_win":       {"EN": "{n} trades · {w}% win", "PT": "{n} trades · {w}% acerto"},
    "v_vs_current":       {"EN": "+{p}% vs current",   "PT": "+{p}% vs atual"},
    "v_dim_hold":         {"EN": "hold-time",          "PT": "tempo de holding"},
    "v_dim_hold_word":    {"EN": "holds",              "PT": "holdings"},
    "v_dim_hour":         {"EN": "hour-of-day",        "PT": "hora-do-dia"},
    "v_dim_hour_word":    {"EN": "hours",              "PT": "horários"},
    "v_dim_size":         {"EN": "size",               "PT": "tamanho"},
    "v_dim_size_word":    {"EN": "sizes",              "PT": "tamanhos"},
    "v_dim_side":         {"EN": "side",               "PT": "lado"},
    "v_dim_side_word":    {"EN": "sides",              "PT": "lados"},
    "v_dim_streak":       {"EN": "loss-streak",        "PT": "sequência de perdas"},
    "v_dim_streak_word":  {"EN": "streaks",            "PT": "sequências"},
    "v_dim_symbol":       {"EN": "symbol",             "PT": "símbolo"},
    "v_dim_symbol_word":  {"EN": "symbols",            "PT": "símbolos"},
    "v_dim_regime":       {"EN": "BTC regime",         "PT": "regime BTC"},
    "v_dim_regime_word":  {"EN": "regimes",            "PT": "regimes"},

    # Confrontation block
    "c_what_you_believe": {"EN": "What you believe",   "PT": "O que você acha"},
    "c_what_pnl_says":    {"EN": "What your PNL says", "PT": "O que seu PNL diz"},
    "c_peak_edge":        {"EN": "Peak edge",          "PT": "Pico de edge"},
    "c_profit_hour":      {"EN": "Profit hour",        "PT": "Hora lucrativa"},
    "c_loss_hour":        {"EN": "Loss hour",          "PT": "Hora perdedora"},
    "c_edge_bleed":       {"EN": "Edge / bleed",       "PT": "Edge / ralo"},
    "c_pnl_usd_90d":      {"EN": "PNL · USD · 365D",    "PT": "PNL · USD · 365D"},
    "c_narrative":        {"EN": "You're most active at <strong>{busy_hour:02d}:00 UTC</strong> ({busy_n} trades), but most of your PNL is being made — and lost — in <strong>different hours</strong> entirely.",
                           "PT": "Você opera mais às <strong>{busy_hour:02d}:00 UTC</strong> ({busy_n} trades), mas a maior parte do seu PNL está sendo feito — e perdido — em <strong>horários diferentes</strong>."},

    # Waterfall
    "wf_eyebrow":         {"EN": "PNL waterfall · dimensional attribution",
                           "PT": "Cascata de PNL · atribuição dimensional"},
    "wf_interp":          {"EN": "<strong>{strongest}</strong> is your strongest axis ({strongest_v} best+worst signal). <strong>{worst}</strong> drags the most ({worst_v}). Each bar is the sum of that dimension's <em>best</em> and <em>worst</em> slice — a coarse but honest read on where edge and bleed concentrate.",
                           "PT": "<strong>{strongest}</strong> é seu eixo mais forte ({strongest_v} de sinal melhor+pior). <strong>{worst}</strong> puxa mais pra baixo ({worst_v}). Cada barra é a soma da fatia <em>melhor</em> e <em>pior</em> daquela dimensão — uma leitura grosseira mas honesta de onde edge e ralo se concentram."},
    "wf_dim_hour":        {"EN": "HOUR",     "PT": "HORA"},
    "wf_dim_side":        {"EN": "SIDE",     "PT": "LADO"},
    "wf_dim_symbol":      {"EN": "SYMBOL",   "PT": "SÍMBOLO"},
    "wf_dim_streak":      {"EN": "STREAK",   "PT": "STREAK"},
    "wf_dim_size":        {"EN": "SIZE",     "PT": "TAMANHO"},
    "wf_dim_hold":        {"EN": "HOLD",     "PT": "HOLD"},
    "wf_dim_regime":      {"EN": "REGIME",   "PT": "REGIME"},
    "wf_dim_net":         {"EN": "NET",      "PT": "LÍQUIDO"},

    # Conditional perf tabs
    "tab_hour_of_day":    {"EN": "Hour of day",  "PT": "Hora do dia"},
    "tab_loss_streak":    {"EN": "Loss streak",  "PT": "Streak de perdas"},
    "tab_size":           {"EN": "Size",         "PT": "Tamanho"},
    "tab_hold_time":      {"EN": "Hold time",    "PT": "Tempo de hold"},
    "tab_side":           {"EN": "Side",         "PT": "Lado"},
    "tab_symbol":         {"EN": "Symbol",       "PT": "Símbolo"},
    "tab_btc_regime":     {"EN": "BTC regime",   "PT": "Regime BTC"},

    # Cards/tables in conditional perf
    "cp_eyebrow":         {"EN": "{dim} · {n} buckets",    "PT": "{dim} · {n} buckets"},
    "cp_best":            {"EN": "Best",                    "PT": "Melhor"},
    "cp_worst":           {"EN": "Worst",                   "PT": "Pior"},
    "cp_expectancy_trade":{"EN": "expectancy / trade",      "PT": "expectativa / trade"},
    "cp_card_best":       {"EN": "BEST",                    "PT": "MELHOR"},
    "cp_card_worst":      {"EN": "WORST",                   "PT": "PIOR"},
    "cp_trades":          {"EN": "trades",                  "PT": "trades"},
    "cp_win":             {"EN": "win",                     "PT": "acerto"},
    "cp_total":           {"EN": "Total",                   "PT": "Total"},
    "cp_metric_pnl":      {"EN": "PNL",                     "PT": "PNL"},
    "cp_metric_exp":      {"EN": "Expectancy",              "PT": "Expectativa"},
    "cp_metric_wr":       {"EN": "Winrate",                 "PT": "Taxa de Acerto"},
    "cp_heatmap":         {"EN": "Heatmap · day-of-week × hour-of-day",
                           "PT": "Heatmap · dia-da-semana × hora-do-dia"},
    "cp_bar_view":        {"EN": "Bar view + full table",   "PT": "Visão em barras + tabela completa"},
    "dow_mon":            {"EN": "Mon",   "PT": "Seg"},
    "dow_tue":            {"EN": "Tue",   "PT": "Ter"},
    "dow_wed":            {"EN": "Wed",   "PT": "Qua"},
    "dow_thu":            {"EN": "Thu",   "PT": "Qui"},
    "dow_fri":            {"EN": "Fri",   "PT": "Sex"},
    "dow_sat":            {"EN": "Sat",   "PT": "Sáb"},
    "dow_sun":            {"EN": "Sun",   "PT": "Dom"},

    # Peer benchmark
    "pb_eyebrow":         {"EN": "Peer benchmark",   "PT": "Benchmark de pares"},
    "pb_vs":              {"EN": "vs top 5 by 30d PNL · {n_traders} traders · {n_trades:,} trades",
                           "PT": "vs top 5 por PNL 30d · {n_traders} traders · {n_trades:,} trades"},
    "pb_win_rate":        {"EN": "WIN RATE",         "PT": "TAXA DE ACERTO"},
    "pb_expectancy":      {"EN": "EXPECTANCY / TRADE","PT": "EXPECTATIVA / TRADE"},
    "pb_best_hour":       {"EN": "BEST HOUR",        "PT": "MELHOR HORA"},
    "pb_best_side":       {"EN": "BEST SIDE",        "PT": "MELHOR LADO"},
    "pb_you":             {"EN": "YOU",              "PT": "VOCÊ"},
    "pb_top5":            {"EN": "TOP 5",            "PT": "TOP 5"},

    # Risk filters / showing line
    "showing_label":      {"EN": "Showing",          "PT": "Mostrando"},
    "showing_positions":  {"EN": "{n} positions",    "PT": "{n} posições"},

    # Tab captions
    "tab_streak_caption":  {"EN": "Trades grouped by prior consecutive losses. If later buckets look much worse, that's a revenge-trading pattern.",
                            "PT": "Trades agrupados por perdas consecutivas anteriores. Se os buckets posteriores estiverem muito piores, é padrão de revenge-trading."},
    "tab_size_title":      {"EN": "Position Size",     "PT": "Tamanho da Posição"},
    "tab_size_caption":    {"EN": "Bucketed by your own size quartile (Q1 = smallest 25%, Q4 = largest 25%). Reveals whether you actually make money on big bets.",
                            "PT": "Agrupado pelo seu próprio quartil de tamanho (Q1 = 25% menor, Q4 = 25% maior). Revela se você realmente ganha dinheiro nas apostas grandes."},
    "tab_regime_unavail":  {"EN": "BTC regime data not available — either BTC kline fetch failed or your trades don't span enough history.",
                            "PT": "Dados de regime do BTC indisponíveis — ou a busca de klines do BTC falhou, ou seus trades não cobrem histórico suficiente."},
    "tab_regime_caption":  {"EN": "Each trade is tagged by the BTC market regime at the moment it was opened: **uptrend** / **chop** / **downtrend** (7-day vs 30-day SMA crossover, ±2% bands). Shows which regimes you actually make money in.",
                            "PT": "Cada trade é marcado pelo regime do BTC no momento da abertura: **alta** / **lateral** / **baixa** (cruzamento SMA 7d vs 30d, bandas ±2%). Mostra em quais regimes você realmente ganha dinheiro."},
    "expand_full_table":   {"EN": "Full table",        "PT": "Tabela completa"},

    # Topbar
    "tb_crumb":         {"EN": "autopsy",       "PT": "autópsia"},
    "tb_window":        {"EN": "WINDOW · 365D",  "PT": "JANELA · 365D"},
    "tb_live":          {"EN": "LIVE",          "PT": "AO VIVO"},

    # Filter status row
    "fs_count":         {"EN": "{n_filt:,} of {n_raw:,} trades",
                         "PT": "{n_filt:,} de {n_raw:,} trades"},
    "fs_active_one":    {"EN": "· 1 filter active ·",
                         "PT": "· 1 filtro ativo ·"},
    "fs_active_many":   {"EN": "· {n} filters active ·",
                         "PT": "· {n} filtros ativos ·"},

    # Risk filters
    "rf_title":         {"EN": "Risk filters",        "PT": "Filtros de risco"},
    "rf_avoid_tag":     {"EN": "⚠ Avoid",             "PT": "⚠ Evite"},
    "rf_edge_tag":      {"EN": "✓ Edge",              "PT": "✓ Edge"},
    "rf_per_trade":     {"EN": "/trade",              "PT": "/trade"},
    "rf_win":           {"EN": "win",                 "PT": "acerto"},
    "rf_trades":        {"EN": "trades",              "PT": "trades"},
    "rf_net":           {"EN": "net",                 "PT": "líquido"},
    "rf_anti_one":      {"EN": "1 anti-pattern",      "PT": "1 anti-padrão"},
    "rf_anti_many":     {"EN": "{n} anti-patterns",   "PT": "{n} anti-padrões"},
    "rf_edge_count":    {"EN": "{n} edge",            "PT": "{n} edge"},
    "rf_meta":          {"EN": "{summary} &nbsp;·&nbsp; 2-dim combos &nbsp;·&nbsp; min 5 trades",
                         "PT": "{summary} &nbsp;·&nbsp; combos de 2 dimensões &nbsp;·&nbsp; mín 5 trades"},
    "rf_footer":        {"EN": "Cross-dimensional setups where your historical expectancy is most extreme. <strong>Avoid</strong> = the worst combos in your sample; <strong>Edge</strong> = your strongest. Treat as a pre-trade checklist.",
                         "PT": "Setups cruzando dimensões onde sua expectativa histórica é mais extrema. <strong>Evite</strong> = os piores combos da sua amostra; <strong>Edge</strong> = os seus mais fortes. Trate como checklist pré-trade."},

    # Low-sample badge (statistical rigor)
    "cp_low_sample":       {"EN": "n<15", "PT": "n<15"},
    "cp_low_sample_tip":   {
        "EN": "Fewer than 15 trades in this bucket — expectancy is noisy. Treat as a hint, not a verdict.",
        "PT": "Menos de 15 trades nesse bucket — a expectativa é ruidosa. Trate como pista, não veredito.",
    },

    # Risk dim labels
    "rd_hour":     {"EN": "HOUR",    "PT": "HORA"},
    "rd_day":      {"EN": "DAY",     "PT": "DIA"},
    "rd_side":     {"EN": "SIDE",    "PT": "LADO"},
    "rd_symbol":   {"EN": "SYMBOL",  "PT": "SÍMBOLO"},
    "rd_streak":   {"EN": "STREAK",  "PT": "STREAK"},
    "rd_size":     {"EN": "SIZE",    "PT": "TAMANHO"},
    "rd_hold":     {"EN": "HOLD",    "PT": "HOLD"},
    "rd_regime":   {"EN": "REGIME",  "PT": "REGIME"},
}


def _current_lang() -> str:
    raw = st.session_state.get("lang", _LANG_DEFAULT)
    return raw if raw in _LANG_OPTIONS else _LANG_DEFAULT


def _t(key: str, **fmt) -> str:
    """Lookup a translation. Falls back gracefully to default lang then key."""
    lang = _current_lang()
    entry = _TRANSLATIONS.get(key) or {}
    s = entry.get(lang) or entry.get(_LANG_DEFAULT) or key
    if fmt:
        try:
            return s.format(**fmt)
        except (KeyError, IndexError):
            return s
    return s


# Seed lang from URL if present and supported.
_raw_lang = st.query_params.get("lang")
if isinstance(_raw_lang, list):
    _raw_lang = _raw_lang[0] if _raw_lang else None
if _raw_lang in _LANG_OPTIONS and "lang" not in st.session_state:
    st.session_state["lang"] = _raw_lang


# Language toggle — small, top-right of page (above the topbar).
_, _lang_col = st.columns([10, 1])
with _lang_col:
    _picked_lang = st.segmented_control(
        _t("lang_label"),
        options=_LANG_OPTIONS,
        default=_current_lang(),
        key="lang_toggle_widget",
        label_visibility="collapsed",
    )
if _picked_lang and _picked_lang != st.session_state.get("lang"):
    st.session_state["lang"] = _picked_lang
    st.rerun()


st.markdown(
    f"""
    <div class="ew-ambient" aria-hidden="true">
        <div class="ew-grid"></div>
        <div class="ew-spot"></div>
        <div class="ew-particles">{_particles_html}</div>
        <div class="ew-scan"></div>
    </div>

    <div class="ew-topbar">
        <span class="ew-brand">
            {_logo_html("sm")}
            <span class="ew-crumb">
                <span class="ew-topbar-sep">/</span>
                <span class="v">{_t("tb_crumb")}</span>
            </span>
        </span>
        <div class="ew-topbar-right">
            <span>{_t("tb_window")}</span>
            <span class="ew-pill"><span class="ew-pill-dot"></span>{_t("tb_live")}</span>
        </div>
    </div>

    <h1 class="ew-headline">{_t("headline_1")}<br><span class="accent">{_t("headline_2")}</span></h1>
    <p class="ew-sub">
        {_t("headline_sub")}
    </p>
    """,
    unsafe_allow_html=True,
)


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


# URL state must seed session_state BEFORE the data-source section below:
# the wallet auto-fetch trigger reads url_seed_wallet, and the empty-state
# st.stop() would otherwise end the script before seeding ever ran (which
# silently broke bookmarked ?w= links on cold sessions).
# --------------------------------------------------------------------------- #
# URL state — slicer filters + active wallet persist in query params so the
# whole view is shareable / bookmarkable.
# --------------------------------------------------------------------------- #

# Slicer filter values that go into the URL (?f_hour=14&f_side=long&…). The
# parser converts the URL string back to the type the slicer widget expects.
_URL_FILTER_PARSERS = {
    "hour":   int,
    "day":    int,
    "side":   str,
    "symbol": str,
    "streak": str,
    "size":   str,
    "hold":   str,
    "regime": str,
}


def _seed_state_from_url() -> None:
    """Populate session state from URL query params before widgets render.

    Runs once at the top of every script execution. Only seeds keys that
    don't already exist in session_state — that way user interactions
    (which write to session_state) always win over the URL.
    """
    qp = st.query_params

    # Wallet address (`?w=0x…`) — pre-fills the input + flags an auto-fetch
    raw_wallet = qp.get("w")
    if isinstance(raw_wallet, list):
        raw_wallet = raw_wallet[0] if raw_wallet else None
    if raw_wallet and _is_valid_evm_address(raw_wallet):
        if "active_address" not in st.session_state:
            st.session_state["active_address"] = raw_wallet
        if "url_seed_wallet" not in st.session_state:
            st.session_state["url_seed_wallet"] = raw_wallet

    # Slicer filters (`?f_hour=14&f_side=long&…`)
    for key, parser in _URL_FILTER_PARSERS.items():
        sess_key = f"slicer_{key}"
        if sess_key in st.session_state:
            continue
        raw = qp.get(f"f_{key}")
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        if raw is None or raw == "":
            continue
        try:
            st.session_state[sess_key] = parser(raw)
        except (ValueError, TypeError):
            continue


def _sync_state_to_url() -> None:
    """Write current slicer + wallet state back to URL query params.

    Only writes when the new state differs from what's currently in the
    URL — avoids triggering an unnecessary rerun loop.
    """
    new_qp: dict[str, str] = {}

    # Active wallet
    addr = (st.session_state.get("active_address") or "").strip()
    if addr:
        new_qp["w"] = addr

    # Filters
    for key in _URL_FILTER_PARSERS:
        val = st.session_state.get(f"slicer_{key}")
        if val is not None and val != "":
            new_qp[f"f_{key}"] = str(val)

    # UI language
    lang = st.session_state.get("lang")
    if lang and lang != _LANG_DEFAULT and lang in _LANG_OPTIONS:
        new_qp["lang"] = lang

    # Compare against current params (only the keys we manage).
    managed_keys = {"w", "lang", *(f"f_{k}" for k in _URL_FILTER_PARSERS)}
    current = {
        k: (v[0] if isinstance(v, list) else v)
        for k, v in st.query_params.items()
        if k in managed_keys
    }
    if current == new_qp:
        return

    # Preserve any unmanaged params (analytics, etc.) just in case.
    preserved = {
        k: (v[0] if isinstance(v, list) else v)
        for k, v in st.query_params.items()
        if k not in managed_keys
    }
    final = {**preserved, **new_qp}
    st.query_params.clear()
    for k, v in final.items():
        st.query_params[k] = v


_seed_state_from_url()




with st.sidebar:
    st.markdown(
        f'<div class="ew-sb-logo">{_logo_html("lg")}</div>'
        f'<div class="ew-sb-eyebrow">{_t("sb_data_source")}</div>',
        unsafe_allow_html=True,
    )

    parquet_path = Path("data/history.parquet")
    has_cached = parquet_path.exists()

    # Two clean choices only: analyze a real wallet, or explore with demo data.
    source = st.radio(
        "Data source",
        ["From wallet address", "Use demo data"],
        index=0,
        label_visibility="collapsed",
        help=(
            "Paste any SoDEX wallet address to pull its closed positions live "
            "from the public API. No login or signature required."
        ),
    )

    st.markdown("---")
    st.caption(
        "[GitHub ↗](https://github.com/nftradercrypto/edgework) · "
        "built by [@nftradercrypto](https://x.com/nftradercrypto)"
    )
    st.caption(_t("sb_footnote"))


# --------------------------------------------------------------------------- #
# Load data
# --------------------------------------------------------------------------- #

raw_orders: list[dict] = []
trades: pd.DataFrame | None = None

if "wallet_cache" not in st.session_state:
    st.session_state.wallet_cache = {}


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_demo_trader() -> tuple:
    """Pick an active + profitable top SoDEX trader and load their REAL
    history, so the demo shows the tool on real data (real symbols, working
    Trade Check + Smart Money comparison) rather than synthetic noise.

    Returns (address, trades_df) or (None, None) if the API is unavailable.
    """
    try:
        from edgework.sodex_client import SodexClient

        with SodexClient(
            user_address="0x0000000000000000000000000000000000000000"
        ) as dc:
            lb = dc.get_leaderboard(
                window_type="30d", sort_by="volume",
                sort_order="desc", page=1, page_size=10,
            )
        addr = None
        for it in (lb.get("items", []) or []):
            if it.get("wallet_address") and float(it.get("pnl_usd", 0) or 0) > 0:
                addr = it["wallet_address"]
                break
        if addr is None:
            for it in (lb.get("items", []) or []):
                if it.get("wallet_address"):
                    addr = it["wallet_address"]
                    break
        if not addr:
            return None, None
        end_ms = int(pd.Timestamp.now("UTC").value // 1_000_000)
        start_ms = end_ms - 365 * 86_400_000
        with SodexClient(user_address=addr) as c:
            positions = c.get_position_history_paginated(
                start_ms=start_ms, end_ms=end_ms, page_limit=500, max_pages=40,
            )
        if not positions:
            return None, None
        return addr, slicer.normalize_orders(positions)
    except Exception:  # noqa: BLE001 — fall back to synthetic demo
        return None, None


if source == "From wallet address":
    col_input, col_btn = st.columns([4, 1])
    with col_input:
        address = st.text_input(
            "Wallet address",
            value=st.session_state.get("active_address", ""),
            placeholder="0x…  paste any SoDEX wallet — read-only, no login",
            label_visibility="collapsed",
        )
    with col_btn:
        fetch_clicked = st.button(
            _t("wallet_fetch"), use_container_width=True, type="primary"
        )

    # Auto-trigger fetch when URL pre-loaded a wallet we don't have cached yet.
    # The seed flag is consumed on first use so reloads don't re-fetch.
    _url_seed = st.session_state.get("url_seed_wallet")
    if (
        _url_seed
        and _url_seed not in st.session_state.wallet_cache
        and not fetch_clicked
    ):
        fetch_clicked = True
        address = _url_seed
        st.session_state.pop("url_seed_wallet", None)

    if fetch_clicked:
        addr_clean = address.strip()
        if not _is_valid_evm_address(addr_clean):
            st.error(_t("wallet_invalid"))
        elif addr_clean in st.session_state.wallet_cache:
            st.session_state.active_address = addr_clean
            st.toast(f"Loaded cached history for {addr_clean[:10]}…")
        else:
            try:
                from edgework.sodex_client import SodexClient

                # 1-year window — paginated fetch covers the full window
                # in pages of up to 500 positions each.
                end_ms = int(pd.Timestamp.utcnow().value // 1_000_000)
                start_ms = end_ms - 365 * 86_400_000

                status_box = st.empty()
                status_box.info(f"Fetching positions for `{addr_clean[:10]}…`")

                def _on_page(page_idx: int, total: int) -> None:
                    status_box.info(
                        f"Fetched {total:,} positions (page {page_idx}) for "
                        f"`{addr_clean[:10]}…` — paginating…"
                    )

                with SodexClient(user_address=addr_clean) as c:
                    positions = c.get_position_history_paginated(
                        start_ms=start_ms,
                        end_ms=end_ms,
                        page_limit=500,
                        max_pages=40,
                        progress_cb=_on_page,
                    )

                status_box.empty()

                if not positions:
                    st.warning(
                        "No closed positions found for this address in "
                        "the last 365 days. The wallet may not have traded "
                        "on SoDEX, or the address is incorrect."
                    )
                else:
                    df = slicer.normalize_orders(positions)
                    st.session_state.wallet_cache[addr_clean] = df
                    st.session_state.active_address = addr_clean
                    st.success(
                        f"Loaded {len(df):,} closed positions "
                        f"(last 365 days)."
                    )
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not fetch history: {e}")

    active = st.session_state.get("active_address")
    if active and active in st.session_state.wallet_cache:
        trades = st.session_state.wallet_cache[active]
        st.caption(f"{_t('showing_label')} **`{active}`** · {_t('showing_positions', n=f'{len(trades):,}')}")

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

elif source == "Use demo data":
    # Load a real, active top trader so the demo shows the tool at its best.
    with st.spinner(_t("demo_loading")):
        _demo_addr, _demo_df = _fetch_demo_trader()
    if _demo_df is not None and not _demo_df.empty:
        trades = _demo_df
        st.session_state["active_address"] = _demo_addr
        st.caption(
            f"{_t('demo_showing')} · **`{_demo_addr}`** · "
            f"{_t('showing_positions', n=f'{len(trades):,}')}"
        )

if trades is None and source == "Use demo data":
    # Synthetic fallback — only if the live top-trader fetch was unavailable.
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
    # Convert tz-aware datetimes to int64 milliseconds robust to precision.
    # pandas 3.0 defaults pd.date_range to datetime64[us, UTC]; the legacy
    # `.astype("int64") // 1_000_000` trick produced seconds (not ms) and
    # normalize_orders then re-parsed those as ms → all trades landed in 1970.
    # Drop tz first (can't cast tz-aware → tz-naive precision), normalize to
    # ms precision, then to int64.
    opens_ms  = opens.tz_convert("UTC").tz_localize(None).astype("datetime64[ms]").astype("int64")
    closes_ms = closes.tz_convert("UTC").tz_localize(None).astype("datetime64[ms]").astype("int64")
    raw_orders = pd.DataFrame(
        {
            "createdAt": opens_ms,
            "updatedAt": closes_ms,
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
            _feat = (
                ("01", "⚡", _t("land_f1_h"), _t("land_f1_d")),
                ("02", "🎯", _t("land_f2_h"), _t("land_f2_d")),
                ("03", "🔬", _t("land_f3_h"), _t("land_f3_d")),
            )
            _cards = "".join(
                f'<div class="ew-feat-card"><span class="n">{n}</span>'
                f'<span class="ico">{ico}</span>'
                f'<div class="h">{h}</div><div class="d">{d}</div></div>'
                for n, ico, h, d in _feat
            )
            st.markdown(
                f'<div class="ew-land-eyebrow">{_t("land_eyebrow")}</div>'
                f'<div class="ew-feat-grid">{_cards}</div>'
                '<div class="ew-trust">'
                f'<span><span class="dot"></span>{_t("land_t1")}</span>'
                f'<span><span class="dot"></span>{_t("land_t2")}</span>'
                f'<span><span class="dot"></span>{_t("land_t3")}</span>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""
                <div class="ew-empty">
                    <div class="ew-empty-icon">[ — ]</div>
                    <div class="ew-empty-title">{_t("wallet_section_title")}</div>
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
# Phase 3 — Slicer bar (horizontal filters)
# --------------------------------------------------------------------------- #

_DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Static option lists for buckets that have known labels.
# Matches the exact bucketing rules in src/edgework/slicer.py.
_SIZE_BUCKETS  = ["Q1", "Q2", "Q3", "Q4"]
_HOLD_BUCKETS  = ["<5m", "5–30m", "30m–2h", "2–8h", "8–24h", ">24h"]
_STREAK_BUCKETS = ["fresh", "1L", "2L", "3L", "4L+"]


def _describe_tool_step(step_num: int, trace_entry: dict, n_trades_total: int) -> str:
    """Render one audit-trail entry as readable Markdown.

    Translates the technical tool name + JSON input into something a trader
    can scan. Used by the "Data sources" expander after the full diagnostic.
    """
    name = trace_entry.get("tool", "")
    inp  = trace_entry.get("input", {}) or {}
    out  = trace_entry.get("output", {}) or {}

    def _fmt_filters(filters: dict | None) -> str:
        if not filters:
            return ""
        labels = []
        for k, v in filters.items():
            if k == "hour":
                labels.append(f"HOUR={int(v):02d}:00")
            elif k == "day_of_week":
                labels.append(f"DAY={_DOW_LABELS[int(v)] if 0 <= int(v) < 7 else v}")
            elif k == "side":
                labels.append(f"SIDE={str(v).upper()}")
            elif k == "symbol":
                labels.append(f"SYMBOL={v}")
            elif k == "streak_bucket":
                labels.append(f"STREAK={v}")
            elif k == "size_quartile":
                labels.append(f"SIZE={v}")
            elif k == "hold_bucket":
                labels.append(f"HOLD={v}")
            elif k == "regime":
                labels.append(f"REGIME={str(v).upper()}")
        return " · ".join(labels)

    if name == "get_full_breakdown":
        filters = inp.get("filters") or {}
        n = out.get("overall", {}).get("n_trades", n_trades_total)
        bk = out.get("breakdowns", {})
        dims = ", ".join(bk.keys())
        f_label = _fmt_filters(filters)
        if f_label:
            return (
                f"**{step_num}. Full dataset breakdown**  \n"
                f"Pulled overall stats + every dimension breakdown ({dims}) "
                f"from your **{n:,} trades**, filtered to **{f_label}**."
            )
        return (
            f"**{step_num}. Full dataset breakdown**  \n"
            f"Pulled overall stats + per-bucket data across **8 dimensions** "
            f"({dims}) from your **{n:,} trades**."
        )

    if name == "get_slice_breakdown":
        dim = inp.get("dimension", "?")
        buckets = out.get("buckets") or []
        f_label = _fmt_filters(inp.get("filters"))
        suffix = f", filtered to {f_label}" if f_label else ""
        return (
            f"**{step_num}. Single-dimension breakdown — {dim}**  \n"
            f"Computed bucket-level stats across {len(buckets)} buckets{suffix}."
        )

    if name == "get_filtered_summary":
        f_label = _fmt_filters(inp.get("filters"))
        n = out.get("n_trades", 0)
        return (
            f"**{step_num}. Filtered summary**  \n"
            f"Aggregate stats for **{n:,} trades**"
            + (f" matching **{f_label}**." if f_label else " (whole dataset).")
        )

    if name == "list_top_trades":
        f_label = _fmt_filters(inp.get("filters"))
        sort_by = inp.get("sort_by", "pnl")
        ascending = bool(inp.get("ascending", True))
        n = len(out.get("trades") or [])
        order_label = (
            f"{'lowest' if ascending else 'highest'} {sort_by}"
        )
        suffix = f" matching **{f_label}**" if f_label else ""
        return (
            f"**{step_num}. Specific trade lookup**  \n"
            f"Listed **{n} trades** sorted by {order_label}{suffix}."
        )

    if name == "compare_subsets":
        a = inp.get("label_a") or "A"
        b = inp.get("label_b") or "B"
        return (
            f"**{step_num}. Head-to-head comparison**  \n"
            f"Compared **{a}** vs **{b}** on win rate, expectancy, and net PNL."
        )

    return f"**{step_num}. {name}**  \nNo description available."


def _format_slicer_value(slicer_key: str, value) -> str:
    """Format a filter value for display in the chip and the radio options."""
    if value is None:
        return "ALL"
    if slicer_key == "hour":
        return f"{int(value):02d}:00"
    if slicer_key == "day":
        d = int(value)
        return _DOW_LABELS[d] if 0 <= d < 7 else str(d)
    if slicer_key == "side":
        return str(value).upper()
    return str(value)


def _add_bucket_columns(raw_trades: pd.DataFrame) -> pd.DataFrame:
    """Attach the same bucket columns the slicer uses, so we can filter on them.

    Matches src/edgework/slicer.py exactly:
      - _size_q     : pd.qcut(size, 4) → Q1/Q2/Q3/Q4
      - _hold_b     : pd.cut(minutes, …) → <5m / 5–30m / 30m–2h / 2–8h / 8–24h / >24h
      - _streak_b   : sorted prior-loss count → fresh / 1L / 2L / 3L / 4L+
    """
    df = raw_trades.copy()

    # Size quartile
    if "size" in df.columns and df["size"].notna().any():
        try:
            df["_size_q"] = pd.qcut(df["size"], q=4, labels=_SIZE_BUCKETS)
        except (ValueError, TypeError):
            df["_size_q"] = pd.NA  # Not enough distinct values
    else:
        df["_size_q"] = pd.NA

    # Hold-duration bucket
    if "opened_at" in df.columns and "closed_at" in df.columns:
        hold_min = (df["closed_at"] - df["opened_at"]).dt.total_seconds() / 60.0
        df["_hold_b"] = pd.cut(
            hold_min,
            bins=[-1, 5, 30, 120, 480, 1_440, 1e9],
            labels=_HOLD_BUCKETS,
        )
    else:
        df["_hold_b"] = pd.NA

    # Streak bucket — requires sequential order
    if "opened_at" in df.columns and "pnl" in df.columns:
        ordered = df.sort_values("opened_at")
        running = []
        c = 0
        for pnl in ordered["pnl"]:
            running.append(c)
            c = c + 1 if pnl <= 0 else 0
        ordered["_streak_n"] = running
        ordered["_streak_b"] = pd.cut(
            ordered["_streak_n"],
            bins=[-1, 0, 1, 2, 3, 100],
            labels=_STREAK_BUCKETS,
        )
        # Map back to original row order via index.
        df["_streak_b"] = ordered["_streak_b"].reindex(df.index)
    else:
        df["_streak_b"] = pd.NA

    return df


# --------------------------------------------------------------------------- #
# Wave 2 Sprint 3 — BTC regime tagging (8th slicer dimension)
# --------------------------------------------------------------------------- #

_REGIME_BUCKETS = ["uptrend", "chop", "downtrend"]


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_btc_regime_map(start_ms: int, end_ms: int) -> dict:
    """Fetch daily BTC klines, compute a regime per day. Cached 1h.

    Classification uses the 7-day vs 30-day simple-moving-average ratio of
    BTC close:
        ratio > 1.02  → uptrend
        ratio < 0.98  → downtrend
        else          → chop

    Returns ``{ "YYYY-MM-DD": "uptrend"|"chop"|"downtrend" }``. Empty dict on
    any failure — caller should fall back gracefully.
    """
    from edgework.sodex_client import SodexClient

    with SodexClient(
        user_address="0x0000000000000000000000000000000000000000"
    ) as c:
        kl = c.get_perps_klines(
            symbol="BTC-USD",
            interval="1D",
            start_ms=start_ms,
            end_ms=end_ms,
            limit=500,
        )

    if not kl:
        return {}

    # SoDEX kline schema: t (ms), o, h, l, c, v, q — all strings except `t`.
    df = pd.DataFrame(kl)
    if "t" not in df.columns or "c" not in df.columns:
        return {}
    df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df["close"] = pd.to_numeric(df["c"], errors="coerce")
    df = df.dropna(subset=["close"]).sort_values("ts").reset_index(drop=True)
    if df.empty:
        return {}

    df["sma7"]  = df["close"].rolling(7,  min_periods=1).mean()
    df["sma30"] = df["close"].rolling(30, min_periods=1).mean()

    def _regime(r) -> str:
        if r["sma30"] == 0 or pd.isna(r["sma30"]):
            return "chop"
        ratio = r["sma7"] / r["sma30"]
        if ratio > 1.02:
            return "uptrend"
        if ratio < 0.98:
            return "downtrend"
        return "chop"

    df["regime"] = df.apply(_regime, axis=1)
    df["date_iso"] = df["ts"].dt.strftime("%Y-%m-%d")
    return dict(zip(df["date_iso"], df["regime"]))


# --------------------------------------------------------------------------- #
# Wallet rank on the SoDEX leaderboard
# --------------------------------------------------------------------------- #


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_wallet_rank(address: str, window: str = "30d") -> dict | None:
    """Return where a wallet stands on the public SoDEX leaderboard, ranked
    by VOLUME (not PNL).

    Why volume: the leaderboard has 100k+ rows but the vast majority are
    dormant / zero-PNL wallets. Ranking by PNL puts active traders near the
    bottom by sheer dilution. Volume rank is a much better proxy for "where
    do you stand among traders who actually trade".

    Cached 10 minutes — the leaderboard snapshot only updates a few times a
    day so a tighter TTL adds nothing.

    Returns ``{rank, total, percentile, pnl_usd, volume_usd, window}`` or
    ``None`` when the wallet hasn't traded in that window.
    """
    if not address or not address.startswith("0x"):
        return None
    try:
        from edgework.sodex_client import SodexClient

        with SodexClient(
            user_address="0x0000000000000000000000000000000000000000"
        ) as c:
            rank_data = c.get_leaderboard_rank(
                address=address, window_type=window, sort_by="volume",
            )
            lb_data = c.get_leaderboard(
                window_type=window,
                sort_by="volume",
                sort_order="desc",
                page=1,
                page_size=10,
            )
    except Exception:  # noqa: BLE001
        return None

    if not rank_data.get("found"):
        return None
    item = rank_data.get("item", {}) or {}
    total = int(lb_data.get("total", 0) or 0)
    rank = int(item.get("rank", 0) or 0)
    if rank <= 0 or total <= 0:
        return None
    return {
        "rank":       rank,
        "total":      total,
        "percentile": rank / total * 100,
        "pnl_usd":    float(item.get("pnl_usd", 0) or 0),
        "volume_usd": float(item.get("volume_usd", 0) or 0),
        "window":     window,
    }


def _attach_regime(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Add a ``regime`` column based on BTC market regime at trade open time."""
    if trades_df is None or trades_df.empty:
        return trades_df
    if "opened_at" not in trades_df.columns:
        return trades_df

    min_ts = trades_df["opened_at"].min()
    max_ts = trades_df["opened_at"].max()
    if pd.isna(min_ts) or pd.isna(max_ts):
        return trades_df

    # Pad start by 35 days so the 30-day SMA is valid for the earliest trades.
    # Use .timestamp() (POSIX seconds) instead of .value — pandas 2.0+ may
    # store datetimes at ms precision in which case .value is in ms, not ns,
    # and our division factor was off by 1000×.
    start_ms = int((min_ts - pd.Timedelta(days=35)).timestamp() * 1000)
    end_ms   = int(max_ts.timestamp() * 1000)

    regime_map = _fetch_btc_regime_map(start_ms, end_ms)
    if not regime_map:
        # Fail open — return df unchanged. Slicer's `by_regime` will simply
        # return an empty DataFrame downstream.
        return trades_df

    df = trades_df.copy()
    df["regime"] = (
        df["opened_at"].dt.strftime("%Y-%m-%d").map(regime_map).fillna("chop")
    )
    return df


def _build_filter_options(raw_trades: pd.DataFrame) -> dict:
    """Build available filter values from the full (bucket-tagged) dataset."""
    opts: dict[str, list] = {
        "hour": [], "day": [], "side": [], "symbol": [],
        "streak": [], "size": [], "hold": [], "regime": [],
    }
    if "opened_at" in raw_trades.columns:
        ts = raw_trades["opened_at"]
        opts["hour"] = sorted({int(h) for h in ts.dt.hour.unique()})
        opts["day"]  = sorted({int(d) for d in ts.dt.dayofweek.unique()})
    if "side" in raw_trades.columns:
        opts["side"] = sorted({
            str(s).lower() for s in raw_trades["side"].dropna().unique()
        })
    if "symbol" in raw_trades.columns:
        opts["symbol"] = sorted({
            str(s) for s in raw_trades["symbol"].dropna().unique()
        })

    # Bucket columns — preserve the canonical order from slicer.py,
    # but only show buckets that actually have trades.
    if "_streak_b" in raw_trades.columns:
        present = set(raw_trades["_streak_b"].dropna().astype(str).unique())
        opts["streak"] = [b for b in _STREAK_BUCKETS if b in present]
    if "_size_q" in raw_trades.columns:
        present = set(raw_trades["_size_q"].dropna().astype(str).unique())
        opts["size"] = [b for b in _SIZE_BUCKETS if b in present]
    if "_hold_b" in raw_trades.columns:
        present = set(raw_trades["_hold_b"].dropna().astype(str).unique())
        opts["hold"] = [b for b in _HOLD_BUCKETS if b in present]
    if "regime" in raw_trades.columns:
        present = set(raw_trades["regime"].dropna().astype(str).unique())
        opts["regime"] = [b for b in _REGIME_BUCKETS if b in present]

    return opts


def _apply_filters(raw_trades: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """Return a filtered view of trades. None values mean 'no filter'."""
    df = raw_trades
    if filters.get("hour") is not None and "opened_at" in df.columns:
        df = df[df["opened_at"].dt.hour == int(filters["hour"])]
    if filters.get("day") is not None and "opened_at" in df.columns:
        df = df[df["opened_at"].dt.dayofweek == int(filters["day"])]
    if filters.get("side") is not None and "side" in df.columns:
        df = df[df["side"].astype(str).str.lower() == str(filters["side"]).lower()]
    if filters.get("symbol") is not None and "symbol" in df.columns:
        df = df[df["symbol"].astype(str) == str(filters["symbol"])]
    if filters.get("streak") is not None and "_streak_b" in df.columns:
        df = df[df["_streak_b"].astype(str) == str(filters["streak"])]
    if filters.get("size") is not None and "_size_q" in df.columns:
        df = df[df["_size_q"].astype(str) == str(filters["size"])]
    if filters.get("hold") is not None and "_hold_b" in df.columns:
        df = df[df["_hold_b"].astype(str) == str(filters["hold"])]
    if filters.get("regime") is not None and "regime" in df.columns:
        df = df[df["regime"].astype(str) == str(filters["regime"])]
    return df


def _render_slicer_bar(raw_trades: pd.DataFrame):
    """Render slicer chips and return (filtered_trades, filters_dict).

    Seven dimensions, matching the Dashboard.html design (minus implicit
    quartile thresholds we re-compute on the raw set).
    """
    opts = _build_filter_options(raw_trades)

    slicers = [
        ("HOUR",   "hour",   opts["hour"]),
        ("DAY",    "day",    opts["day"]),
        ("SIDE",   "side",   opts["side"]),
        ("SYMBOL", "symbol", opts["symbol"]),
        ("STREAK", "streak", opts["streak"]),
        ("SIZE",   "size",   opts["size"]),
        ("HOLD",   "hold",   opts["hold"]),
        ("REGIME", "regime", opts["regime"]),
    ]

    st.markdown(
        f'<div class="ew-slicer-eyebrow">{_t("slicer_eyebrow")}</div>',
        unsafe_allow_html=True,
    )

    # 8 slicer chips + clear button, all in one row.
    cols = st.columns([1, 1, 1, 1, 1, 1, 1, 1, 0.6])
    filters: dict = {}

    for col, (label, key, options) in zip(cols[:8], slicers):
        if not options:
            with col:
                st.markdown(
                    f'<span style="color:{DIM};font-size:11px;'
                    f'font-family:Space Mono,monospace;letter-spacing:0.14em;'
                    f'text-transform:uppercase;padding:14px 16px;display:block;'
                    f'border:1px solid {BORDER};font-weight:700;">{label} · n/a</span>',
                    unsafe_allow_html=True,
                )
            filters[key] = None
            continue

        radio_opts = [None] + list(options)
        current = st.session_state.get(f"slicer_{key}", None)
        try:
            default_idx = radio_opts.index(current)
        except ValueError:
            default_idx = 0
            current = None
        display = _format_slicer_value(key, current)
        chip_label = f"{label} · {display}  ▾"

        with col:
            with st.popover(chip_label, use_container_width=True):
                selected = st.radio(
                    f"Filter {label.lower()}",
                    options=radio_opts,
                    format_func=lambda x, k=key: _format_slicer_value(k, x),
                    index=default_idx,
                    key=f"slicer_{key}",
                    label_visibility="collapsed",
                )
        filters[key] = selected

    with cols[8]:
        any_active = any(v is not None for v in filters.values())
        if any_active:
            if st.button("CLEAR", key="slicer_clear_btn", use_container_width=True):
                for _, key, _ in slicers:
                    skey = f"slicer_{key}"
                    if skey in st.session_state:
                        del st.session_state[skey]
                # Also drop the filter params from the URL so a reload
                # doesn't re-seed them.
                for key in list(_URL_FILTER_PARSERS.keys()):
                    url_key = f"f_{key}"
                    if url_key in st.query_params:
                        del st.query_params[url_key]
                st.rerun()

    return _apply_filters(raw_trades, filters), filters


def _render_filter_status(n_raw: int, n_filt: int, filters: dict) -> None:
    """Show how many trades remain after filters, with chip tags for each active filter."""
    active = {k: v for k, v in filters.items() if v is not None}
    if not active:
        return
    tags = " ".join(
        f"<span class='ew-fs-tag'>{k.upper()}={_format_slicer_value(k, v)}</span>"
        for k, v in active.items()
    )
    _n_active = len(active)
    _active_str = (
        _t("fs_active_one") if _n_active == 1
        else _t("fs_active_many", n=_n_active)
    )
    st.markdown(
        f"""
        <div class="ew-filter-status">
            <span class="ew-fs-count">{_t("fs_count", n_filt=n_filt, n_raw=n_raw)}</span>
            <span class="ew-fs-active">{_active_str}</span>
            {tags}
        </div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Slicer bar — narrow the dataset (Phase 3)
# --------------------------------------------------------------------------- #

# Attach BTC regime per trade (Wave 2 Sprint 3) so it becomes available as
# an 8th slicer dimension and shows up in the verdict / waterfall / risk
# filters / tabs.  Then pre-compute the slicer bucket columns (size quartile
# / hold / streak) so the slicer bar can offer them as filters.
_raw_trades = _attach_regime(trades)
_raw_trades = _add_bucket_columns(_raw_trades)
trades, _active_filters = _render_slicer_bar(_raw_trades)
_render_filter_status(len(_raw_trades), len(trades), _active_filters)

if trades.empty:
    st.warning(
        "No trades match the current filters. Clear filters above to see your data."
    )
    st.stop()


# --------------------------------------------------------------------------- #
# Compute stats
# --------------------------------------------------------------------------- #

overall = slicer.overall(trades)
slices = slicer.slice_all(trades)


# --------------------------------------------------------------------------- #
# Wallet rank banner (Wave 2) — only when a real wallet is loaded
# --------------------------------------------------------------------------- #

_active_addr_for_rank = st.session_state.get("active_address", "").strip()
if _active_addr_for_rank:
    _rank_data = _fetch_wallet_rank(_active_addr_for_rank, window="30d")
    if _rank_data:
        _rank = _rank_data["rank"]
        _total = _rank_data["total"]
        _pct = _rank_data["percentile"]
        _pnl = _rank_data["pnl_usd"]
        _vol = _rank_data["volume_usd"]

        # Top X% calculation — pct is rank/total*100, lower is better.
        _bottom_word = "ABAIXO" if _current_lang() == "PT" else "BOTTOM"
        if _pct <= 1:
            _tier_label, _tier_class = "TOP 1%", "elite"
        elif _pct <= 5:
            _tier_label, _tier_class = f"TOP {_pct:.1f}%", "elite"
        elif _pct <= 25:
            _tier_label, _tier_class = f"TOP {_pct:.1f}%", "good"
        elif _pct <= 50:
            _tier_label, _tier_class = f"TOP {_pct:.0f}%", "neutral"
        else:
            _tier_label, _tier_class = f"{_bottom_word} {100-_pct:.0f}%", "weak"

        _pnl_cls_rank = "pos" if _pnl >= 0 else "neg"
        _pnl_sign_rank = "+" if _pnl >= 0 else "−"
        _vol_str = (
            f"${_vol/1e6:.2f}M" if _vol >= 1e6
            else f"${_vol/1e3:.1f}k" if _vol >= 1e3
            else f"${_vol:,.0f}"
        )

        st.markdown(
            f"""
            <div class="ew-rank-banner">
                <div class="ew-rank-tier {_tier_class}">{_tier_label}</div>
                <div class="ew-rank-headline">
                    {_t("rank_ranked", rank=_rank, total=_total)}
                    <span class="window">· {_t("rank_dim_volume")}</span>
                </div>
                <div class="ew-rank-meta">
                    <span class="cell"><span class="k">{_t("rank_30d_volume")}</span>
                        <span class="v">{_vol_str}</span>
                    </span>
                    <span class="cell"><span class="k">{_t("rank_sodex_30d_pnl")}</span>
                        <span class="v {_pnl_cls_rank}">{_pnl_sign_rank}${abs(_pnl):,.0f}</span>
                    </span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# --------------------------------------------------------------------------- #
# Edge Score — a single 0-100 composite + a shareable branded Edge Card.
# --------------------------------------------------------------------------- #

def _compute_edge_score(ov, slices_dict: dict, trades_df: pd.DataFrame):
    """A single, defensible 0-100 read of how real a trader's edge is.

    Three components, all size-independent so they compare across wallets:
      · Profit factor (0-45): gross wins ÷ gross losses.
      · Consistency (0-30): share of well-sampled dimension buckets that are
        actually profitable — rewards an edge that holds across conditions,
        not one lucky bucket.
      · Edge quality (0-25): positive expectancy scaled by win rate.
    """
    pf = 1.0
    if trades_df is not None and "pnl" in getattr(trades_df, "columns", []):
        pnl = trades_df["pnl"].dropna()
        gw = float(pnl[pnl > 0].sum())
        gl = abs(float(pnl[pnl <= 0].sum()))
        pf = (gw / gl) if gl > 0 else 3.0
    pf_score = max(0.0, min(1.0, (pf - 1.0) / 2.0)) * 45.0

    prof = tot = 0
    for _k, df in (slices_dict or {}).items():
        if df is None or getattr(df, "empty", True):
            continue
        if "expectancy" not in df.columns or "n_trades" not in df.columns:
            continue
        for _, r in df[df["n_trades"] >= 5].iterrows():
            tot += 1
            if float(r["expectancy"]) > 0:
                prof += 1
    consistency = (prof / tot) if tot else 0.0
    cons_score = consistency * 30.0

    wr = float(ov.winrate)
    if ov.expectancy > 0:
        edge_q = (0.5 + 0.5 * min(wr / 0.55, 1.0)) * 25.0
    else:
        edge_q = 0.2 * wr * 25.0

    score = int(round(max(0.0, min(100.0, pf_score + cons_score + edge_q))))
    return score, {"pf": pf, "consistency": consistency, "wr": wr,
                   "expectancy": float(ov.expectancy)}


def _edge_grade(score: int) -> tuple[str, str, str]:
    """(grade label i18n-key, hex color, one-line description i18n-key)."""
    if score >= 80:
        return "eg_elite", GREEN, "eg_elite_d"
    if score >= 62:
        return "eg_strong", GREEN, "eg_strong_d"
    if score >= 45:
        return "eg_solid", ACCENT, "eg_solid_d"
    if score >= 28:
        return "eg_dev", ACCENT, "eg_dev_d"
    return "eg_leak", RED, "eg_leak_d"


def _edge_card_png(score: int, grade: str, color_hex: str, wallet: str,
                   stats: list[tuple], badge: str, verified: str) -> bytes:
    """Render the branded, share-ready Edge Card (16:9) as a PNG.

    stats: list of (icon_kind, label, value, subtitle) where icon_kind is
    one of {"pf", "wr", "net"}.
    """
    import math
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    def _font(size: int, bold: bool = False):
        cands = (
            ["C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
            if bold else
            ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
        )
        for c in cands:
            try:
                return ImageFont.truetype(c, size)
            except Exception:  # noqa: BLE001
                pass
        try:
            return ImageFont.load_default(size)
        except Exception:  # noqa: BLE001
            return ImageFont.load_default()

    def _hx(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def _tracked(dr, xy, text, font, fill, tr):
        x, y = xy
        for ch in text:
            dr.text((x, y), ch, font=font, fill=fill)
            x += dr.textlength(ch, font=font) + tr
        return x

    def _tracked_w(dr, text, font, tr):
        return sum(dr.textlength(ch, font=font) + tr for ch in text) - tr

    def _center(dr, xy, text, font, fill):
        b = dr.textbbox((0, 0), text, font=font)
        dr.text((xy[0]-(b[2]-b[0])/2, xy[1]-(b[3]-b[1])/2-b[1]), text, font=font, fill=fill)

    def _star(dr, cx, cy, r, fill):
        pts = []
        for i in range(10):
            ang = -math.pi/2 + i*math.pi/5
            rr = r if i % 2 == 0 else r*0.42
            pts.append((cx+rr*math.cos(ang), cy+rr*math.sin(ang)))
        dr.polygon(pts, fill=fill)

    def _stat_icon(dr, cx, cy, r, kind, gr):
        dr.ellipse([cx-r, cy-r, cx+r, cy+r], fill=_hx("#0f2418"))
        if kind == "pf":
            x0 = cx - 6.5
            for i, h in enumerate((8, 13, 18)):
                x = x0 + i*9
                dr.rounded_rectangle([x, cy+9-h, x+5, cy+9], radius=2, fill=gr)
        elif kind == "wr":
            dr.ellipse([cx-11, cy-11, cx+11, cy+11], outline=gr, width=3)
            dr.ellipse([cx-4, cy-4, cx+4, cy+4], fill=gr)
        else:
            _center(dr, (cx, cy), "$", _font(26, True), gr)

    W, H = 1600, 900
    green = _hx(color_hex)
    orange, txt, mut, dim = _hx("#f5841f"), _hx("#f5f5f5"), _hx("#a8a8a8"), _hx("#6f6f6f")

    img = Image.new("RGB", (W, H), _hx("#050506"))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([24, 24, W-24, H-24], radius=30, fill=_hx("#0e0e11"),
                        outline=_hx("#202024"), width=2)

    d.rounded_rectangle([92, 86, 103, 158], radius=5, fill=orange)
    d.text((124, 78), "Edgework", font=_font(66, True), fill=txt)
    _tracked(d, (126, 160), "TRADE ANALYTICS", _font(23), mut, 6)

    _tracked(d, (94, 266), "EDGE SCORE", _font(26, True), orange, 5)
    d.text((90, 298), grade, font=_font(104, True), fill=green)

    for (x0, x1), (kind, label, value, sub) in zip(
        [(90, 372), (392, 674), (694, 1012)], stats
    ):
        d.rounded_rectangle([x0, 500, x1, 700], radius=18, fill=_hx("#161619"),
                            outline=_hx("#26262c"), width=2)
        _stat_icon(d, x0+40, 548, 24, kind, green)
        _tracked(d, (x0+76, 538), label, _font(21), mut, 1)
        d.text((x0+28, 574), value, font=_font(46, True), fill=txt)
        d.text((x0+30, 642), sub, font=_font(20), fill=dim)

    # Ring with glow
    cx, cy, r, wd = 1250, 375, 168, 28
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    sweep = 360 * score / 100
    gd.arc([cx-r, cy-r, cx+r, cy+r], start=-90, end=-90+sweep, fill=green+(255,), width=wd+6)
    glow = glow.filter(ImageFilter.GaussianBlur(16))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    d = ImageDraw.Draw(img)
    d.arc([cx-r, cy-r, cx+r, cy+r], start=0, end=360, fill=_hx("#242428"), width=wd)
    d.arc([cx-r, cy-r, cx+r, cy+r], start=-90, end=-90+sweep, fill=green, width=wd)
    for ang in (-90, -90+sweep):
        a = math.radians(ang)
        ex, ey = cx+r*math.cos(a), cy+r*math.sin(a)
        d.ellipse([ex-wd/2, ey-wd/2, ex+wd/2, ey+wd/2], fill=green)
    _center(d, (cx, cy-18), str(score), _font(150, True), txt)
    _center(d, (cx, cy+92), "/ 100", _font(40), mut)

    # Badge pill under the ring
    bf = _font(22, True)
    bw = _tracked_w(d, badge, bf, 3) + 70
    bx0 = cx - bw/2
    d.rounded_rectangle([bx0, 668, bx0+bw, 726], radius=29,
                        fill=_hx("#0f2016"), outline=green, width=2)
    _star(d, bx0+32, 697, 11, green)
    _tracked(d, (bx0+52, 686), badge, bf, green, 3)

    # Footer
    d.line([90, 772, W-90, 772], fill=_hx("#202024"), width=1)
    gcx, gcy = 108, 812
    d.ellipse([gcx-13, gcy-13, gcx+13, gcy+13], outline=mut, width=2)
    d.ellipse([gcx-6, gcy-13, gcx+6, gcy+13], outline=mut, width=2)
    d.line([gcx-13, gcy, gcx+13, gcy], fill=mut, width=2)
    foot = (f"edgework.streamlit.app   ·   {wallet[:6]}…{wallet[-4:]}"
            if wallet else "edgework.streamlit.app")
    d.text((134, 798), foot, font=_font(24), fill=mut)
    vf = _font(24, True)
    vx = W - 90 - _tracked_w(d, verified, vf, 3)
    _tracked(d, (vx, 800), verified, vf, green, 3)
    sx, sy = vx-44, 812
    d.polygon([(sx, sy-14), (sx+13, sy-9), (sx+13, sy+3), (sx, sy+14),
               (sx-13, sy+3), (sx-13, sy-9)], outline=green, width=2)
    d.line([sx-5, sy, sx-1, sy+5], fill=green, width=2)
    d.line([sx-1, sy+5, sx+6, sy-5], fill=green, width=2)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _render_edge_card(trades_df: pd.DataFrame, slices_dict: dict, ov,
                      wallet: str) -> None:
    """The hero: a 0-100 Edge Score in an animated ring + a download button
    that exports a branded, share-ready card."""
    if trades_df is None or trades_df.empty or ov.n_trades == 0:
        return
    score, meta = _compute_edge_score(ov, slices_dict, trades_df)
    g_key, color, d_key = _edge_grade(score)
    grade = _t(g_key)

    import math
    r = 54
    circ = 2 * math.pi * r
    off = circ * (1 - score / 100)

    def _m(x):
        s = "−" if x < 0 else "+"
        return f"{s}${abs(x):,.0f}"

    net_cls = "pos" if ov.total_pnl >= 0 else "neg"
    pf = meta["pf"]

    st.markdown(
        f'<style>@keyframes ew-ec-{score} {{ to {{ --ew-ecn: {score}; }} }}'
        f'.ew-ec-num.s{score} {{ animation: ew-ec-{score} 1.35s ease-out forwards; }}</style>'
        '<div class="ew-edge">'
        '<div class="ew-edge-ring">'
        '<svg viewBox="0 0 128 128">'
        '<circle class="bg" cx="64" cy="64" r="54"/>'
        f'<circle class="arc" cx="64" cy="64" r="54" '
        f'style="--circ:{circ:.1f};--off:{off:.1f};stroke:{color}"/>'
        '</svg>'
        f'<div class="ew-edge-numwrap"><span class="ew-ec-num s{score}"></span>'
        '<span class="den">/100</span></div>'
        '</div>'
        '<div class="ew-edge-meta">'
        f'<div class="eyebrow">{_t("eg_eyebrow")}</div>'
        f'<div class="grade" style="color:{color}">{grade}</div>'
        f'<div class="desc">{_t(d_key)}</div>'
        '<div class="ew-edge-stats">'
        f'<div><span class="k">{_t("eg_pf")}</span>'
        f'<span class="v">{pf:.2f}</span></div>'
        f'<div><span class="k">{_t("eg_consistency")}</span>'
        f'<span class="v">{meta["consistency"]:.0%}</span></div>'
        f'<div><span class="k">{_t("eg_winrate")}</span>'
        f'<span class="v">{meta["wr"]:.0%}</span></div>'
        f'<div><span class="k">{_t("eg_net")}</span>'
        f'<span class="v {net_cls}">{_m(ov.total_pnl)}</span></div>'
        '</div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    try:
        # Subtitles for the card's stat tiles.
        pf_sub = ("eg_pf_exc" if pf >= 2 else "eg_pf_strong" if pf >= 1.5
                  else "eg_pf_pos" if pf >= 1 else "eg_pf_weak")
        net_sub = "eg_sub_netp" if ov.total_pnl >= 0 else "eg_sub_netn"
        badge_key = ("eg_badge_elite" if score >= 80 else "eg_badge_strong" if score >= 62
                     else "eg_badge_solid" if score >= 45 else "eg_badge_dev"
                     if score >= 28 else "eg_badge_leak")
        png = _edge_card_png(
            score, grade, color, wallet or "",
            [
                ("pf",  _t("eg_pf").upper(),      f"{pf:.2f}",        _t(pf_sub)),
                ("wr",  _t("eg_winrate").upper(), f"{meta['wr']:.0%}", _t("eg_sub_hit")),
                ("net", _t("eg_net").upper(),     _m(ov.total_pnl),   _t(net_sub)),
            ],
            _t(badge_key), _t("eg_verified"),
        )
        st.download_button(
            _t("eg_download"), data=png,
            file_name=f"edgework-edge-score-{score}.png",
            mime="image/png", key="edge_card_dl",
        )
    except Exception:  # noqa: BLE001 — the on-screen card is the primary deliverable
        pass


# --------------------------------------------------------------------------- #
# TL;DR card — the 10-second read. Deterministic, computed from slices.
# --------------------------------------------------------------------------- #

def _render_tldr(trades_df: pd.DataFrame, slices_dict: dict, ov) -> None:
    """First thing a new visitor reads: dataset size, biggest leak, best edge,
    fees. No AI, no scroll required — the page's thesis in one strip."""
    if trades_df is None or trades_df.empty or ov.n_trades == 0:
        return

    # Self-contained label formatters (the verdict's _DIM_VERDICT lives
    # further down the script; Streamlit executes top-down).
    _fmt_by_dim = {
        "hour_of_day":        ("hour",          lambda v: f"{int(v):02d}:00 UTC"),
        "consecutive_losses": ("streak_bucket", lambda v: str(v).upper()),
        "size_quartile":      ("size_quartile", lambda v: str(v).upper()),
        "hold_duration":      ("hold_bucket",   lambda v: str(v).upper()),
        "side":               ("side",          lambda v: str(v).upper()),
        "symbol":             ("symbol",        str),
        "regime":             ("regime",        lambda v: str(v).upper()),
    }

    leak = edge = None  # (label, total_pnl, n)
    # A bucket that contains nearly the whole dataset (e.g. "DOWNTREND" when
    # 100% of trades happened in a downtrend) isn't an actionable edge — it's
    # just the dataset. Only consider buckets below this share of all trades.
    _max_share = 0.8 * ov.n_trades
    for dim_key, df in (slices_dict or {}).items():
        cfg = _fmt_by_dim.get(dim_key)
        if cfg is None or df is None or df.empty:
            continue
        key_col, fmt = cfg
        if key_col not in df.columns or "total_pnl" not in df.columns:
            continue
        sig = df[(df["n_trades"] >= 5) & (df["n_trades"] <= _max_share)]
        if sig.empty:
            continue
        lo = sig.loc[sig["total_pnl"].idxmin()]
        hi = sig.loc[sig["total_pnl"].idxmax()]
        if float(lo["total_pnl"]) < 0 and (leak is None or float(lo["total_pnl"]) < leak[1]):
            leak = (fmt(lo[key_col]), float(lo["total_pnl"]), int(lo["n_trades"]))
        if float(hi["total_pnl"]) > 0 and (edge is None or float(hi["total_pnl"]) > edge[1]):
            edge = (fmt(hi[key_col]), float(hi["total_pnl"]), int(hi["n_trades"]))

    span_days = 0
    if "closed_at" in trades_df.columns and trades_df["closed_at"].notna().any():
        span = trades_df["closed_at"].max() - trades_df["closed_at"].min()
        span_days = max(1, int(span.days))

    has_fees = "fees" in trades_df.columns and trades_df["fees"].notna().any()
    fees_total = float(trades_df["fees"].fillna(0).sum()) if has_fees else 0.0

    def _m(x: float) -> str:
        sign = "−" if x < 0 else "+"
        return f"{sign}${abs(x):,.0f}"

    leak_html = (
        f'<span class="neg">{leak[0]} → {_m(leak[1])}</span><small>{leak[2]:,} trades</small>'
        if leak else "—"
    )
    edge_html = (
        f'<span class="pos">{edge[0]} → {_m(edge[1])}</span><small>{edge[2]:,} trades</small>'
        if edge else "—"
    )
    # 4th cell: fees when available, net PNL otherwise.
    if has_fees and fees_total > 0:
        last_k, last_v = _t("tldr_fees"), f'<span class="neg">−${fees_total:,.0f}</span>'
    else:
        net = float(ov.total_pnl)
        cls = "pos" if net >= 0 else "neg"
        last_k, last_v = _t("tldr_net"), f'<span class="{cls}">{_m(net)}</span>'

    st.markdown(
        '<div class="ew-tldr">'
        '<div class="cell">'
        f'<span class="k">— {_t("tldr_eyebrow")}</span>'
        f'<span class="v">{_t("tldr_dataset", n=f"{ov.n_trades:,}", days=span_days)}</span>'
        '</div>'
        '<div class="cell">'
        f'<span class="k">{_t("tldr_leak")}</span>'
        f'<span class="v">{leak_html}</span>'
        '</div>'
        '<div class="cell">'
        f'<span class="k">{_t("tldr_edge")}</span>'
        f'<span class="v">{edge_html}</span>'
        '</div>'
        '<div class="cell">'
        f'<span class="k">{last_k}</span>'
        f'<span class="v">{last_v}</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def _render_anchor_nav() -> None:
    """Numbered jump-links that give the long page a navigable spine."""
    items = [
        ("sec-tradecheck",  "01", _t("nav_tradecheck")),
        ("sec-verdict",     "02", _t("nav_verdict")),
        ("sec-confront",    "03", _t("nav_confront")),
        ("sec-waterfall",   "04", _t("nav_waterfall")),
        ("sec-conditional", "05", _t("nav_conditional")),
        ("sec-peers",       "06", _t("nav_peers")),
        ("sec-risk",        "07", _t("nav_risk")),
        ("sec-smartmoney",  "08", _t("nav_smartmoney")),
        ("sec-diagnostic",  "09", _t("nav_diagnostic")),
    ]
    links = "".join(
        f'<a href="#{anchor}"><span class="n">{num}</span>{label}</a>'
        for anchor, num, label in items
    )
    st.markdown(f'<div class="ew-nav">{links}</div>', unsafe_allow_html=True)


@st.cache_data(ttl=900, show_spinner=False)
def _consensus_cached() -> dict:
    """Smart-money consensus via the pure module. Shared by Trade Check (top)
    and the Smart Money Watch (bottom) so the leaderboard + position fetches
    happen once per 15 min."""
    from edgework.smart_money import fetch_consensus
    try:
        return fetch_consensus(n_top=20, window="30d")
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "traders": [], "consensus_per_symbol": {}}


@st.cache_data(ttl=3600, show_spinner=False)
def _current_btc_regime() -> str | None:
    """Today's BTC regime (uptrend / chop / downtrend), or None if unavailable."""
    end_ms = int(pd.Timestamp.now("UTC").value // 1_000_000)
    start_ms = end_ms - 45 * 86_400_000
    regime_map = _fetch_btc_regime_map(start_ms, end_ms)
    if not regime_map:
        return None
    return regime_map[max(regime_map)]


def _sm_bias_for(cs: dict | None) -> tuple[str | None, str]:
    """(bias_side, strength) for a symbol's consensus — same thresholds as the
    live watch and the divergence engine."""
    if not cs:
        return None, ""
    lc, sc = int(cs.get("long_count", 0)), int(cs.get("short_count", 0))
    ln, sn = float(cs.get("long_notional", 0)), float(cs.get("short_notional", 0))
    if lc - sc >= 3:
        return "long", "strong"
    if sc - lc >= 3:
        return "short", "strong"
    if ln > sn * 2 and lc > 0:
        return "long", "weak"
    if sn > ln * 2 and sc > 0:
        return "short", "weak"
    return None, ""


@st.cache_data(ttl=120, show_spinner=False)
def _symbol_market(symbol: str) -> dict:
    """Current mark price + funding rate for a symbol (cached 2 min)."""
    try:
        from edgework.sodex_client import SodexClient

        with SodexClient(
            user_address="0x0000000000000000000000000000000000000000"
        ) as c:
            rows = c.get_perps_mark_prices(symbol)
        if not rows:
            return {}
        r = rows[0]
        return {
            "mark": float(r.get("markPrice") or 0) or None,
            "funding": float(r.get("fundingRate") or 0),
        }
    except Exception:  # noqa: BLE001
        return {}


def _size_suggestion(score: int) -> tuple[str, str]:
    """(i18n key, css class) for the position-size hint, driven by the verdict."""
    if score >= 2:
        return "tc_size_up", "pos"
    if score == 1:
        return "tc_size_normal", "pos"
    if score == 0:
        return "tc_size_half", "neutral"
    if score == -1:
        return "tc_size_quarter", "neg"
    return "tc_size_skip", "neg"


def _render_trade_check(raw_trades_df: pd.DataFrame, smart_money: dict,
                        current_regime: str | None) -> None:
    """Pre-trade verdict: check a hypothetical trade against your own history
    AND the live smart-money book, before you take it. 100% in-browser."""
    if raw_trades_df is None or raw_trades_df.empty or "symbol" not in raw_trades_df.columns:
        return
    symbols = raw_trades_df["symbol"].value_counts().index.tolist()
    if not symbols:
        return

    # Local formatter — _money_signed is defined further down the script and
    # Streamlit executes top-down, so referencing it here would NameError.
    def _money_signed(x):
        if x is None or pd.isna(x):
            return "—"
        sign = "−" if x < 0 else ("+" if x > 0 else "")
        return f"{sign}${abs(x):,.2f}"

    st.markdown(
        '<div class="ew-tc-banner ew-anchor" id="sec-tradecheck">'
        '<div class="ew-tc-banner-top">'
        f'<span class="title">⚡ {_t("tc_title")}</span>'
        f'<span class="badge">{_t("tc_badge")}</span>'
        '</div>'
        f'<div class="sub">{_t("tc_sub")}</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns([2, 2])
    with c1:
        symbol = st.selectbox(_t("tc_symbol"), symbols, key="tc_symbol",
                              label_visibility="collapsed")
    with c2:
        side = st.segmented_control(
            _t("tc_side"), options=["long", "short"], default="long",
            key="tc_side", label_visibility="collapsed",
        ) or "long"

    # 1 — your history on this exact setup
    sub = raw_trades_df[
        (raw_trades_df["symbol"] == symbol)
        & (raw_trades_df["side"].astype(str).str.lower() == side)
    ]
    n = len(sub)
    hist_exp = hist_wr = hist_total = None
    hist_score = 0
    if n >= 1:
        pnl = sub["pnl"].dropna()
        if len(pnl):
            wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
            hist_wr = len(wins) / len(pnl)
            aw = float(wins.mean()) if len(wins) else 0.0
            al = abs(float(losses.mean())) if len(losses) else 0.0
            hist_exp = aw * hist_wr - al * (1 - hist_wr)
            hist_total = float(pnl.sum())
            if n >= 5:
                hist_score = 1 if hist_exp > 0 else (-1 if hist_exp < 0 else 0)

    # 2 — smart-money book right now
    consensus = (smart_money or {}).get("consensus_per_symbol", {}) or {}
    cs = consensus.get(symbol)
    bias, strength = _sm_bias_for(cs)
    sm_score = 0
    if bias is not None:
        sm_score = 1 if bias == side else -1

    # 3 — your edge in the current regime, same symbol+side
    reg_exp = None
    if current_regime and "regime" in sub.columns and not sub.empty:
        reg_sub = sub[sub["regime"].astype(str) == current_regime]
        if len(reg_sub) >= 3:
            rp = reg_sub["pnl"].dropna()
            if len(rp):
                rwins, rlosses = rp[rp > 0], rp[rp <= 0]
                rwr = len(rwins) / len(rp)
                raw_ = float(rwins.mean()) if len(rwins) else 0.0
                ral = abs(float(rlosses.mean())) if len(rlosses) else 0.0
                reg_exp = raw_ * rwr - ral * (1 - rwr)

    # Verdict
    score = hist_score + sm_score
    if score <= -2:
        v_cls, v_key = "bad", "tc_v_strong_avoid"
    elif score == -1:
        v_cls, v_key = "warn", "tc_v_caution"
    elif score >= 2:
        v_cls, v_key = "good", "tc_v_strong_go"
    elif score == 1:
        v_cls, v_key = "ok", "tc_v_favorable"
    else:
        v_cls, v_key = "neutral", "tc_v_mixed"
    verdict_txt = _t(v_key, symbol=symbol, side=side.upper())

    # ── signal rows ──
    def _exp_cls(x):
        return "pos" if (x is not None and x >= 0) else "neg"

    if hist_exp is None:
        hist_val = _t("tc_no_history")
    else:
        low = ' <span class="lown">⚠ n&lt;5</span>' if n < 5 else ""
        hist_val = (
            f'<span class="{_exp_cls(hist_exp)}">{_money_signed(hist_exp)}</span>/trade'
            f' · {hist_wr:.0%} {_t("tc_win")} · {n} {_t("tc_trades")}{low}'
        )

    if bias is None:
        sm_val = _t("tc_sm_nosignal")
        sm_row_cls = "neutral"
    else:
        lc, sc = int(cs.get("long_count", 0)), int(cs.get("short_count", 0))
        align = _t("tc_aligned") if bias == side else _t("tc_contrarian")
        sm_row_cls = "pos" if bias == side else "neg"
        sm_val = (
            f'{lc} {_t("tc_long")} · {sc} {_t("tc_short")} → '
            f'<span class="{sm_row_cls}">{align}</span>'
        )

    if current_regime:
        if reg_exp is None:
            reg_val = _t("tc_regime_nodata", regime=current_regime.upper())
        else:
            reg_val = (
                f'{_t("tc_regime_your", regime=current_regime.upper(), side=side)}: '
                f'<span class="{_exp_cls(reg_exp)}">{_money_signed(reg_exp)}</span>/trade'
            )
    else:
        reg_val = _t("tc_regime_unavailable")

    # 4 — live market: mark price, funding, and distance from your median entry.
    mkt = _symbol_market(symbol)
    mkt_val = _t("tc_market_unavailable")
    if mkt.get("mark"):
        mark = mkt["mark"]
        fund = mkt.get("funding", 0.0)
        # Funding > 0 → longs pay shorts. So it's a cost for longs, income for shorts.
        fund_pct = fund * 100
        if abs(fund) < 1e-9:
            fund_txt = f'{_t("tc_funding")} {fund_pct:+.4f}%'
        else:
            favors = (fund > 0 and side == "short") or (fund < 0 and side == "long")
            fcls = "pos" if favors else "neg"
            fword = _t("tc_fund_favors") if favors else _t("tc_fund_against")
            fund_txt = (f'{_t("tc_funding")} <span class="{fcls}">{fund_pct:+.4f}%</span> '
                        f'({fword})')
        # Distance from the trader's own median entry on this symbol+side.
        dist_txt = ""
        if not sub.empty and "entry_price" in sub.columns:
            med_entry = float(sub["entry_price"].dropna().median() or 0)
            if med_entry > 0:
                dpct = (mark - med_entry) / med_entry * 100
                arrow = "↑" if dpct >= 0 else "↓"
                dcls = "neg" if abs(dpct) > 3 else "neutral"
                dist_txt = (f' · <span class="{dcls}">{arrow}{abs(dpct):.1f}%</span> '
                            f'{_t("tc_vs_entry")}')
        mkt_val = f'{_t("tc_mark")} ${mark:,.4g} · {fund_txt}{dist_txt}'

    # Position-size suggestion driven by the verdict score.
    sz_key, sz_cls = _size_suggestion(score)
    size_html = (
        f'<div class="tc-size"><span class="k">{_t("tc_size")}</span>'
        f'<span class="v {sz_cls}">{_t(sz_key)}</span></div>'
    )

    rows = (
        f'<div class="tc-row"><span class="i">1</span>'
        f'<span class="k">{_t("tc_your_history")}</span>'
        f'<span class="v">{hist_val}</span></div>'
        f'<div class="tc-row"><span class="i">2</span>'
        f'<span class="k">{_t("tc_smart_money")}</span>'
        f'<span class="v">{sm_val}</span></div>'
        f'<div class="tc-row"><span class="i">3</span>'
        f'<span class="k">{_t("tc_regime")}</span>'
        f'<span class="v">{reg_val}</span></div>'
        f'<div class="tc-row"><span class="i">4</span>'
        f'<span class="k">{_t("tc_market")}</span>'
        f'<span class="v">{mkt_val}</span></div>'
    )

    st.markdown(
        f'<div class="ew-tc {v_cls}">'
        f'<div class="tc-verdict">{verdict_txt}</div>'
        f'<div class="tc-rows">{rows}</div>'
        f'{size_html}'
        f'<div class="tc-foot">{_t("tc_foot")}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


_render_edge_card(trades, slices, overall,
                  st.session_state.get("active_address") or "")
_render_tldr(trades, slices, overall)
_render_anchor_nav()

# Trade Check — the in-browser pre-trade verdict (Wave 3). Uses the full
# (unfiltered) history so the verdict ignores the slicer selection.
_tc_consensus = _consensus_cached()
_render_trade_check(_raw_trades, _tc_consensus, _current_btc_regime())


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
            <div class="ew-metric-label">{_t("m_total_trades")}</div>
            <div class="ew-metric-value">{overall.n_trades:,}</div>
            <div class="ew-metric-sub">{_t("m_closed_positions")}</div>
            <div class="ew-metric-glow"></div>
        </div>
        <div class="ew-metric">
            <div class="ew-metric-label">{_t("m_win_rate")}</div>
            <div class="ew-metric-value">{overall.winrate:.1%}</div>
            <div class="ew-metric-sub">{_t("m_of_wins", w=n_wins, n=overall.n_trades)}</div>
            <div class="ew-metric-glow"></div>
        </div>
        <div class="ew-metric">
            <div class="ew-metric-label"><span class="ew-tip" title="{_t('tip_expectancy')}">{_t("m_expectancy")}</span></div>
            <div class="ew-metric-value {exp_cls}">{exp_sign}${overall.expectancy:,.2f}</div>
            <div class="ew-metric-sub">{_t("m_per_trade")}</div>
            <div class="ew-metric-glow"></div>
        </div>
        <div class="ew-metric">
            <div class="ew-metric-label">{_t("m_realized_pnl")}</div>
            <div class="ew-metric-value {pnl_cls}">{pnl_sign}${overall.total_pnl:,.0f}</div>
            <div class="ew-metric-sub">{_t("m_all_closed")}</div>
            <div class="ew-metric-glow"></div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ── Secondary metric row: profit factor · max drawdown · gross PNL · fees ──
def _render_risk_metrics_row(trades_df: pd.DataFrame) -> None:
    """Prop-desk numbers the headline row doesn't show.

    Profit factor and max drawdown are the first two numbers any prop firm
    checks. The gross/fees split surfaces the cost of execution — many
    high-frequency accounts are gross-profitable and net-negative, which is
    invisible when you only show realized (net) PNL.
    """
    if trades_df is None or trades_df.empty or "pnl" not in trades_df.columns:
        return

    # Local formatter — _money_int is defined further down the script and
    # Streamlit executes top-down, so referencing it here would NameError.
    def _fmt_signed(x: float) -> str:
        sign = "−" if x < 0 else ("+" if x > 0 else "")
        return f"{sign}${abs(x):,.0f}"

    pnl = trades_df["pnl"].dropna()
    if pnl.empty:
        return

    wins_sum = float(pnl[pnl > 0].sum())
    losses_sum = abs(float(pnl[pnl <= 0].sum()))
    if losses_sum > 0:
        pf_str = f"{wins_sum / losses_sum:.2f}"
        pf_cls = "pos" if wins_sum / losses_sum >= 1 else "neg"
    else:
        pf_str, pf_cls = "∞", "pos"

    # Max drawdown on the chronological cumulative PNL curve.
    if "closed_at" in trades_df.columns:
        eq = trades_df.sort_values("closed_at")["pnl"].cumsum()
    else:
        eq = pnl.cumsum()
    dd = float((eq.cummax() - eq).max()) if len(eq) else 0.0
    dd_cls = "neg" if dd > 0 else ""

    # Fees decomposition — only when the fees column made it through.
    has_fees = "fees" in trades_df.columns and trades_df["fees"].notna().any()
    fees_total = float(trades_df["fees"].fillna(0).sum()) if has_fees else 0.0
    net_total = float(pnl.sum())
    gross_total = net_total + fees_total
    gross_cls = "pos" if gross_total >= 0 else "neg"
    fee_pct = (fees_total / gross_total * 100) if gross_total > 0 else None

    if has_fees and fees_total > 0:
        gross_cell = (
            '<div class="ew-metric2">'
            f'<span class="k ew-tip" title="{_t("tip_gross")}">{_t("m2_gross")}</span>'
            f'<span class="v {gross_cls}">{_fmt_signed(gross_total)}</span>'
            f'<span class="s">{_t("m2_gross_sub")}</span>'
            '</div>'
        )
        fee_sub = _t("m2_fees_sub", pct=f"{fee_pct:.0f}") if fee_pct is not None else ""
        fees_cell = (
            '<div class="ew-metric2">'
            f'<span class="k ew-tip" title="{_t("tip_fees")}">{_t("m2_fees")}</span>'
            f'<span class="v neg">−${fees_total:,.0f}</span>'
            f'<span class="s">{fee_sub}</span>'
            '</div>'
        )
    else:
        gross_cell = fees_cell = '<div class="ew-metric2"></div>'

    st.markdown(
        '<div class="ew-metrics2">'
        '<div class="ew-metric2">'
        f'<span class="k ew-tip" title="{_t("tip_pf")}">{_t("m2_profit_factor")}</span>'
        f'<span class="v {pf_cls}">{pf_str}</span>'
        f'<span class="s">{_t("m2_pf_sub")}</span>'
        '</div>'
        '<div class="ew-metric2">'
        f'<span class="k ew-tip" title="{_t("tip_dd")}">{_t("m2_max_dd")}</span>'
        f'<span class="v {dd_cls}">−${dd:,.0f}</span>'
        f'<span class="s">{_t("m2_dd_sub")}</span>'
        '</div>'
        f'{gross_cell}{fees_cell}'
        '</div>',
        unsafe_allow_html=True,
    )

    # The killer insight: gross-profitable but net-negative.
    if has_fees and gross_total > 0 and net_total < 0:
        st.markdown(
            '<div class="ew-fee-flip">⚠ '
            + _t(
                "fee_flip",
                g=_fmt_signed(gross_total),
                f=f"−${fees_total:,.0f}",
                n=_fmt_signed(net_total),
            )
            + '</div>',
            unsafe_allow_html=True,
        )


_render_risk_metrics_row(trades)


# ── Tilt check: current loss streak × your own historical streak stats ──────
def _render_tilt_banner(trades_df: pd.DataFrame, slices_dict: dict) -> None:
    """One-line, data-only warning when the trader is in a live loss streak.

    Deliberately conservative — fires only when ALL hold:
      - the most recent 2+ closed trades are consecutive losses,
      - the latest loss closed within the last 24h (a stale streak is noise),
      - the trader's own history has n>=5 trades in the matching streak
        bucket AND negative expectancy there.
    No moralizing: it cites the trader's own numbers and stops. Positive
    or unsupported streak stats render nothing.
    """
    if trades_df is None or trades_df.empty:
        return
    if "pnl" not in trades_df.columns or "closed_at" not in trades_df.columns:
        return

    recent = trades_df.dropna(subset=["pnl", "closed_at"]).sort_values("closed_at")
    if recent.empty:
        return

    # Current streak: walk back from the most recent close.
    streak = 0
    for pnl in recent["pnl"].iloc[::-1]:
        if pnl <= 0:
            streak += 1
        else:
            break
    if streak < 2:
        return

    last_close = recent["closed_at"].iloc[-1]
    now = pd.Timestamp.now(tz="UTC")
    if last_close.tzinfo is None:
        last_close = last_close.tz_localize("UTC")
    age = now - last_close
    if age > pd.Timedelta(hours=24):
        return  # stale streak — not a live session signal

    bucket = "2L" if streak == 2 else ("3L" if streak == 3 else "4L+")

    streak_df = slices_dict.get("consecutive_losses")
    if streak_df is None or streak_df.empty or "streak_bucket" not in streak_df.columns:
        return
    row = streak_df[streak_df["streak_bucket"].astype(str) == bucket]
    if row.empty:
        return
    row = row.iloc[0]
    n_hist = int(row["n_trades"])
    exp_hist = float(row["expectancy"])
    if n_hist < 5 or exp_hist >= 0:
        return  # not statistically supported, or streaks aren't a problem for them

    mins = int(age.total_seconds() // 60)
    ago = _t("tilt_ago_m", m=mins) if mins < 60 else _t("tilt_ago_h", h=mins // 60)

    st.markdown(
        '<div class="ew-tilt">'
        f'<span class="tag">⚠ {_t("tilt_tag")}</span>'
        '<span>'
        + _t(
            "tilt_body",
            s=streak,
            ago=ago,
            bucket=bucket,
            exp=f"−${abs(exp_hist):,.2f}",
            n=n_hist,
        )
        + '</span>'
        '</div>',
        unsafe_allow_html=True,
    )


_render_tilt_banner(trades, slices)


# --------------------------------------------------------------------------- #
# Equity curve + counterfactual ("recovered if anti-patterns avoided")
# --------------------------------------------------------------------------- #

# Map slice-dict key → (slice df column with the value, formatter).
_SLICE_KEY_COL = {
    "hour_of_day":        "hour",
    "consecutive_losses": "streak_bucket",
    "size_quartile":      "size_quartile",
    "hold_duration":      "hold_bucket",
    "side":               "side",
    "symbol":             "symbol",
    "regime":             "regime",
}


def _slice_value_label(dim_key: str, value) -> str:
    """Human-readable label for a slice value, used in the counterfactual caption."""
    if dim_key == "hour_of_day":
        return f"HOUR={int(value):02d}:00"
    if dim_key == "side":
        return f"SIDE={str(value).upper()}"
    if dim_key == "symbol":
        return f"SYMBOL={value}"
    if dim_key == "consecutive_losses":
        return f"STREAK={value}"
    if dim_key == "size_quartile":
        return f"SIZE={value}"
    if dim_key == "hold_duration":
        return f"HOLD={value}"
    if dim_key == "regime":
        return f"REGIME={str(value).upper()}"
    return f"{dim_key}={value}"


def _slice_to_trade_mask(dim_key: str, value, trades_df: pd.DataFrame) -> pd.Series:
    """Boolean mask: which trades fall into the (dim_key, value) slice."""
    idx = trades_df.index
    if dim_key == "hour_of_day" and "opened_at" in trades_df.columns:
        return trades_df["opened_at"].dt.hour == int(value)
    if dim_key == "side" and "side" in trades_df.columns:
        return trades_df["side"].astype(str).str.lower() == str(value).lower()
    if dim_key == "symbol" and "symbol" in trades_df.columns:
        return trades_df["symbol"].astype(str) == str(value)
    if dim_key == "consecutive_losses" and "_streak_b" in trades_df.columns:
        return trades_df["_streak_b"].astype(str) == str(value)
    if dim_key == "size_quartile" and "_size_q" in trades_df.columns:
        return trades_df["_size_q"].astype(str) == str(value)
    if dim_key == "hold_duration" and "_hold_b" in trades_df.columns:
        return trades_df["_hold_b"].astype(str) == str(value)
    if dim_key == "regime" and "regime" in trades_df.columns:
        return trades_df["regime"].astype(str) == str(value)
    return pd.Series(False, index=idx)


def _find_worst_slices(
    slices_dict: dict,
    top_n: int = 6,
    min_n: int = 5,
) -> list[tuple[str, object, float, float, int]]:
    """Across ALL dimensions, return the top-N slices with worst expectancy
    (must be negative + meet ``min_n`` sample size).

    Returns list of (dim_key, slice_value, expectancy, total_pnl, n_trades),
    worst expectancy first. We rank by expectancy (not total_pnl) so the
    counterfactual surfaces *surgical* anti-patterns — high per-trade bleed
    on a smallish sample — rather than broad slices that just happen to
    contain most of the trader's volume.
    """
    candidates: list[tuple[str, object, float, float, int]] = []
    for dim_key, df in slices_dict.items():
        if df is None or df.empty:
            continue
        if dim_key not in _SLICE_KEY_COL:
            continue
        key_col = _SLICE_KEY_COL[dim_key]
        if key_col not in df.columns:
            continue
        if not {"expectancy", "total_pnl", "n_trades"}.issubset(df.columns):
            continue
        sig = df[df["n_trades"] >= min_n]
        for _, row in sig.iterrows():
            exp = float(row["expectancy"])
            tpnl = float(row["total_pnl"])
            n = int(row["n_trades"])
            if exp < 0:
                candidates.append((dim_key, row[key_col], exp, tpnl, n))
    candidates.sort(key=lambda x: x[2])  # most negative expectancy first
    return candidates[:top_n]


def _compute_avoid_mask_from_slices(
    trades_df: pd.DataFrame,
    slices_dict: dict,
    top_n: int = 3,
    max_slice_share: float = 0.40,
    max_total_share: float = 0.50,
) -> tuple[pd.Series, list[tuple[str, object, float, float, int]]]:
    """Union mask of trades falling into surgical worst-expectancy slices.

    Selection rules:
      - Each slice individually must cover <= ``max_slice_share`` of trades
        (default 40%). Broader slices ("you trade BTC, BTC bleeds") aren't
        actionable — drop them.
      - Total mask coverage capped at ``max_total_share`` (default 50%).
      - We rank by per-trade expectancy so the worst contexts are surgical
        rather than just high-volume.
    """
    if trades_df is None or trades_df.empty:
        return pd.Series(False, index=trades_df.index if trades_df is not None else []), []

    candidates = _find_worst_slices(slices_dict, top_n=top_n * 4)
    if not candidates:
        return pd.Series(False, index=trades_df.index), []

    n_total = max(len(trades_df), 1)
    mask = pd.Series(False, index=trades_df.index)
    selected: list[tuple[str, object, float, float, int]] = []

    for dim_key, val, exp, tpnl, n in candidates:
        if len(selected) >= top_n:
            break
        m = _slice_to_trade_mask(dim_key, val, trades_df).fillna(False)
        share = m.sum() / n_total
        # Reject any single slice that's too broad to be a useful rule.
        if share > max_slice_share:
            continue
        new_mask = mask | m
        # Cap total coverage.
        if new_mask.sum() / n_total > max_total_share:
            if not selected:
                # Edge case: even the narrowest worst slice already overflows.
                # Take it anyway — the trader has very concentrated trading.
                mask = m
                selected.append((dim_key, val, exp, tpnl, n))
            break
        mask = new_mask
        selected.append((dim_key, val, exp, tpnl, n))

    return mask, selected


def _equity_curve(
    df: pd.DataFrame,
    avoid_mask: pd.Series | None = None,
    avoid_label: str | None = None,
) -> None:
    """Render the equity curve. If ``avoid_mask`` is provided, overlay a
    counterfactual line showing what cumulative PNL would have been with
    those trades dropped (PNL set to 0)."""
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

    eq = df[[close_col, pnl_col]].copy().dropna(subset=[close_col, pnl_col])
    eq = eq.sort_values(close_col).reset_index(drop=False)  # keep original index
    eq["cum"] = eq[pnl_col].cumsum()
    final = eq["cum"].iloc[-1]
    line_color = GREEN if final >= 0 else RED
    fill_color = GREEN_DIM if final >= 0 else RED_DIM

    # Counterfactual series (same x, different y) — zero out PNL of "avoid" trades.
    cf_eq = None
    cf_final = None
    if avoid_mask is not None and avoid_mask.any():
        cf_pnl_col = eq[pnl_col].copy()
        # Map the boolean mask (indexed by original df) onto the eq dataframe.
        cf_pnl_col[avoid_mask.reindex(eq["index"], fill_value=False).values] = 0.0
        cf_eq = eq.copy()
        cf_eq["cum_cf"] = cf_pnl_col.cumsum()
        cf_final = float(cf_eq["cum_cf"].iloc[-1])

    fig = go.Figure()

    # Actual: filled area
    fig.add_trace(
        go.Scatter(
            x=eq[close_col], y=eq["cum"],
            fill="tozeroy",
            fillcolor=fill_color,
            line=dict(color="rgba(0,0,0,0)", width=0),
            showlegend=False, hoverinfo="skip",
        )
    )

    # Counterfactual line (dashed amber) — added BEFORE the solid line so
    # the solid actual line stays visually dominant.
    if cf_eq is not None:
        fig.add_trace(
            go.Scatter(
                x=cf_eq[close_col], y=cf_eq["cum_cf"],
                mode="lines",
                line=dict(color=ACCENT, width=2, dash="dash"),
                showlegend=False,
                hovertemplate=(
                    "<b>%{x|%b %d, %H:%M}</b><br>"
                    "If avoided: $%{y:,.0f}<extra></extra>"
                ),
            )
        )

    # Actual line (solid, on top)
    fig.add_trace(
        go.Scatter(
            x=eq[close_col], y=eq["cum"],
            mode="lines",
            line=dict(color=line_color, width=2),
            showlegend=False,
            hovertemplate="<b>%{x|%b %d, %H:%M}</b><br>Actual: $%{y:,.0f}<extra></extra>",
        )
    )

    # Annotations — actual final, then counterfactual final (offset)
    fig.add_annotation(
        x=eq[close_col].iloc[-1], y=final,
        text=f"  {'+' if final>=0 else ''}${final:,.0f}",
        showarrow=False,
        font=dict(color=line_color, family="IBM Plex Mono, monospace", size=12, weight=600),
        xanchor="left",
    )
    if cf_eq is not None and cf_final is not None:
        fig.add_annotation(
            x=cf_eq[close_col].iloc[-1], y=cf_final,
            text=f"  {'+' if cf_final>=0 else ''}${cf_final:,.0f} (if avoided)",
            showarrow=False,
            font=dict(color=ACCENT, family="IBM Plex Mono, monospace", size=12, weight=600),
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
        margin=dict(l=10, r=170, t=10, b=10),
        height=220,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=PANEL, bordercolor=BORDER,
            font=dict(family="IBM Plex Mono, monospace", size=11),
        ),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# Compute the counterfactual mask BEFORE rendering the equity curve.
_avoid_mask, _avoided_slices = _compute_avoid_mask_from_slices(
    trades, slices, top_n=3
)

# Stat strip above the equity curve: actual / counterfactual / recovered.
_close_col = next(
    (c for c in ("closed_at", "close_time", "updatedAt") if c in trades.columns),
    None,
)
_pnl_col = next(
    (c for c in ("pnl", "realizedPnL", "realized_pnl") if c in trades.columns),
    None,
)

if _close_col is not None and _pnl_col is not None:
    _actual_total = float(trades[_pnl_col].sum())

    if _avoid_mask is not None and _avoid_mask.any():
        _cf_pnl = trades[_pnl_col].copy()
        _cf_pnl[_avoid_mask] = 0.0
        _cf_total = float(_cf_pnl.sum())
        _delta = _cf_total - _actual_total
        _n_avoided = int(_avoid_mask.sum())
        _avoided_labels = " · ".join(
            _slice_value_label(d, v) for (d, v, *_rest) in _avoided_slices
        )

        _actual_cls = "pos" if _actual_total >= 0 else "neg"
        _cf_cls = "pos" if _cf_total >= 0 else "neg"
        _delta_cls = "pos" if _delta >= 0 else "neg"

        st.markdown(
            f"""
            <div class="ew-chart-label">{_t("eq_label_with_cf")}</div>
            <div class="ew-cf-strip">
                <span class="cell">
                    <span class="k ew-tip" title="{_t('tip_cf_actual')}">{_t("cf_actual")}</span>
                    <span class="v {_actual_cls}">{'+' if _actual_total>=0 else '−'}${abs(_actual_total):,.0f}</span>
                </span>
                <span class="cell">
                    <span class="k ew-tip" title="{_t('tip_cf_avoided')}">{_t("cf_if_avoided")} · {_avoided_labels}</span>
                    <span class="v {_cf_cls}">{'+' if _cf_total>=0 else '−'}${abs(_cf_total):,.0f}</span>
                </span>
                <span class="cell">
                    <span class="k ew-tip" title="{_t('tip_cf_recovered')}">{_t("cf_recovered")} ({_n_avoided} {_t("cf_trades_skipped")})</span>
                    <span class="v {_delta_cls}">{'+' if _delta>=0 else '−'}${abs(_delta):,.0f}</span>
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="ew-chart-label">{_t("eq_label")}</div>',
            unsafe_allow_html=True,
        )

_equity_curve(trades, avoid_mask=_avoid_mask)

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


LOW_SAMPLE_N = 15  # below this, bucket expectancy is treated as noisy


def _stat_card(
    tag: str, label: str, value: float, n_trades: int,
    winrate: float, total_pnl: float, *, kind: str,
) -> str:
    kind_class = kind if kind in ("win", "loss") else ""
    value_class = kind if kind in ("win", "loss") else ""
    total_class = "pos" if total_pnl >= 0 else "neg"
    wr_class = "pos" if winrate >= 0.5 else "neg"
    wr_width = f"{winrate * 100:.1f}"
    low_badge = (
        f'<span class="ew-card-lown" title="{_t("cp_low_sample_tip")}">⚠ {_t("cp_low_sample")}</span>'
        if n_trades < LOW_SAMPLE_N else ""
    )
    return (
        f'<div class="ew-card {kind_class}">'
        f'  <div class="ew-card-tag">{tag}{low_badge}</div>'
        f'  <div class="ew-card-label">{label}</div>'
        f'  <div class="ew-card-value {value_class}">{_money(value)}</div>'
        f'  <div class="ew-wr-track">'
        f'    <div class="ew-wr-fill" style="width:{wr_width}%"></div>'
        f'  </div>'
        f'  <div class="ew-card-meta">'
        f'    <span class="hi">{n_trades:,}</span> {_t("cp_trades")}'
        f'    &nbsp;·&nbsp;'
        f'    <span class="{wr_class}">{winrate:.0%}</span> {_t("cp_win")}'
        f'    <br>'
        f'    {_t("cp_total")}: <span class="{total_class}">{_money_int(total_pnl)}</span>'
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
        st.caption(
            "Todas as fatias têm menos de 5 trades — sinal insuficiente."
            if _current_lang() == "PT"
            else "All slices have fewer than 5 trades — not enough signal."
        )
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
    _pt = _current_lang() == "PT"
    _w_worst = "Pior" if _pt else "Worst"
    _w_best = "Melhor" if _pt else "Best"
    _w_least_bad = "Menos pior" if _pt else "Least bad"
    rows: list[tuple[str, str, dict]] = []
    for _, row in worst.iterrows():
        kind = "loss" if row["expectancy"] < 0 else "neutral"
        rows.append((_w_worst, kind, row.to_dict()))
    for _, row in best.iterrows():
        if row["expectancy"] > 0:
            tag, kind = _w_best, "win"
        else:
            tag, kind = _w_least_bad, "neutral"
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
    _buckets_w = "buckets"
    st.markdown(
        f"""
        <div class="ew-panel-head">
            <span class="ew-panel-title">{title} · {len(df)} {_buckets_w}</span>
            <span class="ew-panel-meta">
                {_t("cp_best")} <span class="pos">{best_pnl}</span>
                &nbsp;·&nbsp;
                {_t("cp_worst")} <span class="neg">{worst_pnl}</span>
                &nbsp;·&nbsp;
                {_t("cp_expectancy_trade")}
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
# Phase 2 — Autopsy narrative blocks
# --------------------------------------------------------------------------- #

# Dimension → (display label, key column name, value formatter)
_DIM_VERDICT = {
    "hour_of_day":        ("v_dim_hour",   "hour",          lambda v: f"{int(v):02d}:00 UTC"),
    "consecutive_losses": ("v_dim_streak", "streak_bucket", lambda v: str(v).upper()),
    "size_quartile":      ("v_dim_size",   "size_quartile", lambda v: str(v).upper()),
    "hold_duration":      ("v_dim_hold",   "hold_bucket",   lambda v: str(v).upper()),
    "side":               ("v_dim_side",   "side",          lambda v: str(v).upper()),
    "symbol":             ("v_dim_symbol", "symbol",        lambda v: str(v)),
    "regime":             ("v_dim_regime", "regime",        lambda v: str(v).upper()),
}


def _money_signed(x: float) -> str:
    """Money formatter with explicit +/− sign (no decimals)."""
    if x is None or pd.isna(x):
        return "—"
    if x > 0:
        return f"+${x:,.0f}"
    if x < 0:
        return f"−${abs(x):,.0f}"
    return "$0"


# Dimension → trades-DataFrame column holding the per-trade bucket value.
# hour_of_day is derived from opened_at; the _-prefixed columns come from
# _add_bucket_columns; regime from _attach_regime.
_DIM_TRADE_COL = {
    "consecutive_losses": "_streak_b",
    "size_quartile":      "_size_q",
    "hold_duration":      "_hold_b",
    "side":               "side",
    "symbol":             "symbol",
    "regime":             "regime",
}


def _bucket_pnls(trades_df: pd.DataFrame, dim_key: str, bucket_value) -> np.ndarray | None:
    """Per-trade PNLs of one bucket of one dimension, or None if unavailable."""
    if trades_df is None or trades_df.empty or "pnl" not in trades_df.columns:
        return None
    if dim_key == "hour_of_day":
        if "opened_at" not in trades_df.columns:
            return None
        mask = trades_df["opened_at"].dt.hour == int(bucket_value)
    else:
        col = _DIM_TRADE_COL.get(dim_key)
        if col is None or col not in trades_df.columns:
            return None
        mask = trades_df[col].astype(str) == str(bucket_value)
    pnls = trades_df.loc[mask, "pnl"].dropna().to_numpy(dtype=float)
    return pnls if len(pnls) >= 2 else None


def _bootstrap_confidence(
    pnl_best: np.ndarray,
    pnl_worst: np.ndarray,
    n_iter: int = 2000,
) -> int:
    """Bootstrap probability (%) that the edge bucket genuinely beats the bleed.

    Resamples each bucket's trades with replacement n_iter times and measures
    how often the edge bucket's mean PNL exceeds the bleed bucket's. This is a
    real statistical statement — "in X% of resamples the edge held" — unlike a
    sample-size heuristic. Seeded for reproducibility.

    Small-sample honesty cap: a bootstrap only resamples the observed points,
    so with tiny buckets it can't see how noisy the sample mean itself is and
    will overstate certainty. We cap the reported confidence by the smaller
    bucket's size — n=5 caps at 80%, n=10 at 90%, n≥15 uncapped (max 99%).
    """
    rng = np.random.default_rng(42)
    b = rng.choice(pnl_best, size=(n_iter, len(pnl_best)), replace=True).mean(axis=1)
    w = rng.choice(pnl_worst, size=(n_iter, len(pnl_worst)), replace=True).mean(axis=1)
    prob = float((b > w).mean())
    cap = min(99, 70 + 2 * min(len(pnl_best), len(pnl_worst)))
    return min(cap, max(50, round(prob * 100)))


def _verdict_dimension(slices_dict: dict, trades_df: pd.DataFrame | None = None):
    """Find the dimension with the strongest expectancy spread.

    Returns (dim_key, best_row, worst_row, spread, confidence_pct) or None
    if no dimension has at least 2 slices with n_trades >= 5.

    Confidence is a bootstrap probability computed from the winning
    dimension's raw per-trade PNLs (see _bootstrap_confidence). Falls back
    to a sample-size heuristic only when raw trades aren't available.
    """
    winner = None
    for dim_key, df in slices_dict.items():
        if dim_key not in _DIM_VERDICT or df is None or df.empty:
            continue
        if "expectancy" not in df.columns or "n_trades" not in df.columns:
            continue
        sig = df[df["n_trades"] >= 5]
        if len(sig) < 2:
            continue
        best  = sig.loc[sig["expectancy"].idxmax()]
        worst = sig.loc[sig["expectancy"].idxmin()]
        spread = float(best["expectancy"]) - float(worst["expectancy"])
        if winner is None or spread > winner[3]:
            winner = (dim_key, best, worst, spread, None)

    if winner is None:
        return None

    dim_key, best, worst, spread, _ = winner
    _, key_col, _fmt = _DIM_VERDICT[dim_key]
    conf = None
    if trades_df is not None:
        pnl_best = _bucket_pnls(trades_df, dim_key, best[key_col])
        pnl_worst = _bucket_pnls(trades_df, dim_key, worst[key_col])
        if pnl_best is not None and pnl_worst is not None:
            conf = _bootstrap_confidence(pnl_best, pnl_worst)
    if conf is None:
        # Heuristic fallback (no raw trades) — sample-size based.
        n_combined = int(best["n_trades"]) + int(worst["n_trades"])
        conf = min(96, 50 + n_combined // 2)
    return (dim_key, best, worst, spread, conf)


def _verdict_instruction(dim_key: str, best, worst) -> str:
    _, key_col, fmt = _DIM_VERDICT[dim_key]
    worst_label = fmt(worst[key_col])
    best_label  = fmt(best[key_col])
    pt = _current_lang() == "PT"
    if dim_key == "hour_of_day":
        return f"Não opere {worst_label}." if pt else f"Don't trade {worst_label}."
    if dim_key == "consecutive_losses":
        return (
            f"Pare após {worst_label} — sua pior expectativa." if pt
            else f"Walk away after {worst_label} — your worst expectancy."
        )
    if dim_key == "size_quartile":
        return (
            f"Limite o tamanho — {worst_label} sangra." if pt
            else f"Cap your size — {worst_label} bleeds."
        )
    if dim_key == "hold_duration":
        return (
            f"Evite holdings {worst_label} — seu edge está em {best_label}." if pt
            else f"Avoid {worst_label} holds — your edge is in {best_label}."
        )
    if dim_key == "side":
        return (
            f"Evite {worst_label}s — favoreça {best_label}s." if pt
            else f"Skip {worst_label}s — bias toward {best_label}s."
        )
    if dim_key == "symbol":
        return (
            f"Tire {worst_label} do seu book." if pt
            else f"Drop {worst_label} from your book."
        )
    return f"Evite {worst_label}." if pt else f"Avoid {worst_label}."


def _render_verdict(slices_dict, overall, trades_df: pd.DataFrame | None = None) -> None:
    v = _verdict_dimension(slices_dict, trades_df)
    if v is None:
        st.markdown(
            f"""
            <section id="sec-verdict" class="ew-verdict ew-anchor">
                <div class="ew-verdict-eyebrow">
                    {("VEREDITO" if _current_lang() == "PT" else "VERDICT")} · <span class="v">{("sinal insuficiente" if _current_lang() == "PT" else "not enough signal")}</span>
                </div>
                <p style="color:{MUTED};font-family:'Outfit',sans-serif;font-size:15px;">
                    {("São necessários ao menos 5 trades em duas ou mais buckets de qualquer dimensão para renderizar um veredito. Carregue mais histórico para desbloquear." if _current_lang() == "PT" else "Need at least 5 trades in two or more buckets of any dimension to render a verdict. Load more history to unlock.")}
                </p>
            </section>
            """,
            unsafe_allow_html=True,
        )
        return

    dim_key, best, worst, _, conf = v
    dim_label_key, key_col, fmt = _DIM_VERDICT[dim_key]
    dim_label   = _t(dim_label_key)
    best_label  = fmt(best[key_col])
    worst_label = fmt(worst[key_col])
    best_pnl    = float(best["total_pnl"])
    worst_pnl   = float(worst["total_pnl"])
    n_best      = int(best["n_trades"])
    n_worst     = int(worst["n_trades"])
    best_wr     = float(best["winrate"])
    worst_wr    = float(worst["winrate"])
    instruction = _verdict_instruction(dim_key, best, worst)

    overall_pnl = float(overall.total_pnl)
    # "Recovered if avoided" — counterfactual PNL if worst slice were skipped.
    recovered   = -worst_pnl if worst_pnl < 0 else 0.0
    if overall_pnl != 0:
        lift_pct = recovered / abs(overall_pnl) * 100
        _pt = _current_lang() == "PT"
        lift_text = f"{lift_pct:+.0f}% {('vs atual' if _pt else 'vs current')}"
    else:
        lift_text = "n/a"

    overall_pnl_class = "pos" if overall_pnl >= 0 else "neg"
    _verdict_word = "VEREDITO" if _current_lang() == "PT" else "VERDICT"
    _conf_word = "CONFIANÇA" if _current_lang() == "PT" else "CONFIDENCE"

    html = f"""
    <section id="sec-verdict" class="ew-verdict ew-anchor">
        <div class="ew-verdict-eyebrow">
            {_verdict_word} · <span class="v">{dim_label}</span> · <span class="ew-tip" title="{_t('tip_confidence')}">{conf}% {_conf_word}</span>
        </div>
        <div class="ew-verdict-grid">
            <div class="ew-verdict-col">
                <div class="ew-verdict-label">{best_label} {_t("v_is_your_edge")} <span class="em edge">{_t("v_edge_word")}</span>.</div>
                <div class="ew-verdict-num pos">{_money_signed(best_pnl)}</div>
            </div>
            <div class="ew-verdict-col">
                <div class="ew-verdict-label">{worst_label} {_t("v_is_your_bleed")} <span class="em bleed">{_t("v_bleed_word")}</span>.</div>
                <div class="ew-verdict-num neg">{_money_signed(worst_pnl)}</div>
            </div>
        </div>
        <div class="ew-verdict-rule">
            <span class="arrow">→</span>
            <span class="text">{instruction}</span>
            <span class="conf">{_conf_word}<span class="ew-conf-meter"><span class="fill" style="width:{conf}%"></span></span><span class="v">{conf}%</span></span>
        </div>
        <div class="ew-verdict-meta">
            <div class="cell">
                <span class="k">{_t("v_net_pnl")}</span>
                <span class="val {overall_pnl_class}">{_money_signed(overall_pnl)}</span>
                <span class="delta neu">{_t("v_n_trades", n=overall.n_trades)}</span>
            </div>
            <div class="cell">
                <span class="k">{_t("v_edge_pnl", best=best_label)}</span>
                <span class="val pos">{_money_signed(best_pnl)}</span>
                <span class="delta">{_t("v_trades_win", n=n_best, w=int(round(best_wr*100)))}</span>
            </div>
            <div class="cell">
                <span class="k">{_t("v_bleed_pnl", worst=worst_label)}</span>
                <span class="val neg">{_money_signed(worst_pnl)}</span>
                <span class="delta neg">{_t("v_trades_win", n=n_worst, w=int(round(worst_wr*100)))}</span>
            </div>
            <div class="cell">
                <span class="k">{_t("v_recovered")}</span>
                <span class="val">{_money_signed(recovered)}</span>
                <span class="delta">{lift_text}</span>
            </div>
        </div>
    </section>
    """
    st.markdown(html, unsafe_allow_html=True)


def _render_confrontation(slices_dict) -> None:
    """Left: belief narrative · Right: hour-of-day histogram with peak/trough."""
    hod = slices_dict.get("hour_of_day")
    if hod is None or hod.empty:
        return

    hours, counts = {h: 0.0 for h in range(24)}, {h: 0 for h in range(24)}
    for _, row in hod.iterrows():
        h = int(row["hour"])
        hours[h]  = float(row["total_pnl"])
        counts[h] = int(row["n_trades"])

    vals    = list(hours.values())
    max_abs = max((abs(v) for v in vals), default=1.0) or 1.0
    peak_h   = max(hours, key=lambda h: hours[h])
    trough_h = min(hours, key=lambda h: hours[h])
    most_active_h = max(counts, key=lambda h: counts[h])
    n_active = counts[most_active_h]
    active_pnl = hours[most_active_h]

    # Pick the most damning belief to surface
    _pt = _current_lang() == "PT"
    if most_active_h == trough_h and active_pnl < 0:
        if _pt:
            belief = (
                f"Você passa a maior parte do tempo de tela às <span class='em'>{most_active_h:02d}:00 UTC</span> — "
                f"<span class='em'>{n_active} trades</span> em 365 dias.<br><br>"
                f"A fita parece rápida. Você se sente afiado.<br><br>"
                f"Essa hora te custa <span class='neg'>{_money_signed(active_pnl)}</span>."
            )
        else:
            belief = (
                f"You spend most of your screen-time at <span class='em'>{most_active_h:02d}:00 UTC</span> — "
                f"<span class='em'>{n_active} trades</span> in 365 days.<br><br>"
                f"The tape feels fast. You feel sharp.<br><br>"
                f"That hour costs you <span class='neg'>{_money_signed(active_pnl)}</span>."
            )
    elif active_pnl > 0:
        if _pt:
            belief = (
                f"Sua hora mais ativa é <span class='em'>{most_active_h:02d}:00 UTC</span> — "
                f"<span class='em'>{n_active} trades</span>.<br><br>"
                f"Pela primeira vez seu instinto e seus dados concordam: essa hora retorna "
                f"<span class='pos'>{_money_signed(active_pnl)}</span>.<br><br>"
                f"A pergunta é: o que acontece no resto do dia?"
            )
        else:
            belief = (
                f"Your most active hour is <span class='em'>{most_active_h:02d}:00 UTC</span> — "
                f"<span class='em'>{n_active} trades</span>.<br><br>"
                f"For once your gut and your data agree: that hour returns "
                f"<span class='pos'>{_money_signed(active_pnl)}</span>.<br><br>"
                f"The question is what happens the rest of the day."
            )
    else:
        if _pt:
            belief = (
                f"Você opera mais às <span class='em'>{most_active_h:02d}:00 UTC</span> "
                f"({n_active} trades), mas a maior parte do seu PNL está sendo feito — e perdido — "
                f"em <span class='em'>horários diferentes</span>."
            )
        else:
            belief = (
                f"You're most active at <span class='em'>{most_active_h:02d}:00 UTC</span> "
                f"({n_active} trades), but most of your PNL is being made — and lost — "
                f"in <span class='em'>different hours</span> entirely."
            )

    bars_html = ""
    for h in range(24):
        v = hours[h]
        n = counts[h]
        pct = abs(v) / max_abs * 48  # up to 48% of total height (half-axis)
        classes = "ew-hod-bar"
        if h == peak_h and v > 0:
            classes += " peak"
        if h == trough_h and v < 0:
            classes += " trough"
        if v >= 0:
            up_h, down_h = pct, 0
        else:
            up_h, down_h = 0, pct
        tooltip = f"{h:02d}:00 · {n} trades · {_money_signed(v)}"
        bars_html += (
            f'<div class="{classes}" title="{tooltip}">'
            f'<span class="up" style="height:{up_h}%"></span>'
            f'<span class="down" style="height:{down_h}%"></span>'
            "</div>"
        )

    axis_html = "".join(
        f'<span>{h:02d}</span>' if h % 3 == 0 else "<span></span>"
        for h in range(24)
    )
    _pt = _current_lang() == "PT"
    if hours[peak_h] > 0:
        callout_text = (
            f"↓ {'PICO DE EDGE' if _pt else 'PEAK EDGE'} · {peak_h:02d}:00"
        )
    else:
        callout_text = (
            f"↑ {'MAIOR RALO' if _pt else 'DEEPEST BLEED'} · {trough_h:02d}:00"
        )

    html = f"""
    <section id="sec-confront" class="ew-confront ew-anchor">
        <div class="left">
            <h3>{_t("c_what_you_believe")}</h3>
            <div class="ew-conf-stmt">{belief}</div>
        </div>
        <div class="right">
            <h3>{_t("c_what_pnl_says")}<span class="ew-callout">{callout_text}</span></h3>
            <div class="ew-hod">
                <div class="ew-hod-baseline"></div>
                {bars_html}
            </div>
            <div class="ew-hod-axis">{axis_html}</div>
            <div class="ew-hod-legend">
                <span><span class="sw pos"></span>{_t("c_profit_hour")}</span>
                <span><span class="sw neg"></span>{_t("c_loss_hour")}</span>
                <span><span class="sw peak"></span>{_t("c_edge_bleed")}</span>
                <span style="margin-left:auto">{_t("c_pnl_usd_90d")}</span>
            </div>
        </div>
    </section>
    """
    st.markdown(html, unsafe_allow_html=True)


def _render_waterfall(slices_dict, overall) -> None:
    """Dimensional attribution: each dim's best+worst slice as a coarse signal.

    Not a true PNL decomposition — the same money lives in every slice. This
    is a *narrative* chart that says \"this axis helps, that one hurts.\"
    """
    dim_order = [
        ("hour_of_day",        _t("wf_dim_hour")),
        ("side",               _t("wf_dim_side")),
        ("symbol",             _t("wf_dim_symbol")),
        ("consecutive_losses", _t("wf_dim_streak")),
        ("size_quartile",      _t("wf_dim_size")),
        ("hold_duration",      _t("wf_dim_hold")),
        ("regime",             _t("wf_dim_regime")),
    ]
    bars = []  # (label, value, kind: "pos"|"neg")
    for dim_key, lbl in dim_order:
        df = slices_dict.get(dim_key)
        if df is None or df.empty or "total_pnl" not in df.columns:
            continue
        sig = df[df["n_trades"] >= 5] if "n_trades" in df.columns else df
        if len(sig) < 2:
            continue
        best_pnl  = float(sig["total_pnl"].max())
        worst_pnl = float(sig["total_pnl"].min())
        signal = best_pnl + worst_pnl
        bars.append((lbl, signal, "pos" if signal >= 0 else "neg"))

    if not bars:
        return

    # NET bar = realized PNL
    bars.append((_t("wf_dim_net"), float(overall.total_pnl), "total"))

    # Determine scale
    abs_values = [abs(v) for _, v, _ in bars]
    max_abs = max(abs_values) or 1.0
    half_h = 46  # half of the chart, in percent — leave room for labels

    n = len(bars)
    bars_html = ""
    for label, val, kind in bars:
        # Bar geometry — anchored to the baseline (50% of container height)
        bar_h = abs(val) / max_abs * half_h  # percent of container
        if val >= 0:
            bottom = 50  # baseline
        else:
            bottom = 50 - bar_h
        num_class = "acc" if kind == "total" else ("pos" if val >= 0 else "neg")
        bar_class = "neg" if kind == "neg" else ("total" if kind == "total" else "")
        bars_html += (
            f'<div class="ew-wf-bar {bar_class}">'
            f'<span class="num {num_class}">{_money_signed(val)}</span>'
            f'<span class="body" style="bottom:{bottom}%;height:{max(bar_h,1.5)}%"></span>'
            f'<span class="lbl">{label}</span>'
            "</div>"
        )

    # Narrative — pick the strongest positive and negative contributors.
    contribs = [(lbl, val) for lbl, val, kind in bars if kind != "total"]
    if contribs:
        contribs.sort(key=lambda x: x[1])
        worst_lbl, worst_val = contribs[0]
        best_lbl, best_val   = contribs[-1]
        if _current_lang() == "PT":
            note = (
                f"<span class='em'>{best_lbl}</span> é seu eixo mais forte "
                f"(<span class='pos'>{_money_signed(best_val)}</span> de sinal melhor+pior). "
                f"<span class='em'>{worst_lbl}</span> puxa mais pra baixo "
                f"(<span class='neg'>{_money_signed(worst_val)}</span>). "
                "Cada barra é a soma da fatia <span class='em'>melhor e pior</span> "
                "daquela dimensão — uma leitura grosseira mas honesta de onde edge e ralo se concentram."
            )
        else:
            note = (
                f"<span class='em'>{best_lbl}</span> is your strongest axis "
                f"(<span class='pos'>{_money_signed(best_val)}</span> best+worst signal). "
                f"<span class='em'>{worst_lbl}</span> drags the most "
                f"(<span class='neg'>{_money_signed(worst_val)}</span>). "
                "Each bar is the sum of that dimension's <span class='em'>best and worst</span> "
                "slice — a coarse but honest read on where edge and bleed concentrate."
            )
    else:
        note = ""

    grid_style = f"grid-template-columns: repeat({n}, 1fr);"
    html = f"""
    <section class="ew-waterfall-section">
        <div class="ew-waterfall-header">{_t("wf_eyebrow")}</div>
        <div class="ew-waterfall-wrap">
            <div class="ew-waterfall" style="{grid_style}">
                {bars_html}
            </div>
        </div>
        <div class="ew-waterfall-note">{note}</div>
    </section>
    """
    st.markdown(html, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Wave 2 — Benchmark contrast
# --------------------------------------------------------------------------- #


def _delta_text(you: float, them: float, *, money: bool = True) -> str:
    """Format the diff between you and them with sign + color class hint."""
    if pd.isna(you) or pd.isna(them):
        return ""
    diff = you - them
    if money:
        sign = "+" if diff >= 0 else "−"
        return f"{sign}${abs(diff):,.0f}"
    sign = "+" if diff >= 0 else "−"
    return f"{sign}{abs(diff):.1%}"


def _best_hour_label(slices_d: dict) -> tuple[str, float]:
    """(label, expectancy) of best hour with n>=5 — or (None, nan) if absent."""
    hod = slices_d.get("hour_of_day")
    if hod is None or hod.empty or "expectancy" not in hod.columns:
        return (None, float("nan"))
    sig = hod[hod["n_trades"] >= 5]
    if sig.empty:
        return (None, float("nan"))
    best = sig.loc[sig["expectancy"].idxmax()]
    return (f"{int(best['hour']):02d}:00", float(best["expectancy"]))


def _best_side_label(slices_d: dict) -> tuple[str, float]:
    """(label, expectancy) of best side — or (None, nan)."""
    sd = slices_d.get("side")
    if sd is None or sd.empty or "expectancy" not in sd.columns:
        return (None, float("nan"))
    sig = sd[sd["n_trades"] >= 5]
    if sig.empty:
        sig = sd
    best = sig.loc[sig["expectancy"].idxmax()]
    return (str(best["side"]).upper(), float(best["expectancy"]))


def _render_benchmark(you_overall, you_slices, them_overall, them_slices, them_addr: str) -> None:
    """Side-by-side comparison of you vs a benchmark wallet."""
    short_id = f"{them_addr[:6]}…{them_addr[-4:]}"

    # 4 contrast cells: Win Rate · Expectancy · Best Hour · Best Side
    your_wr = float(you_overall.winrate)
    their_wr = float(them_overall.winrate)
    your_exp = float(you_overall.expectancy)
    their_exp = float(them_overall.expectancy)

    your_hour, your_hour_exp = _best_hour_label(you_slices)
    their_hour, their_hour_exp = _best_hour_label(them_slices)

    your_side, your_side_exp = _best_side_label(you_slices)
    their_side, their_side_exp = _best_side_label(them_slices)

    def _cls(x: float) -> str:
        if x is None or pd.isna(x):
            return ""
        return "pos" if x >= 0 else "neg"

    def _pct(x: float) -> str:
        return "—" if pd.isna(x) else f"{x:.1%}"

    def _money_compact(x: float) -> str:
        if pd.isna(x):
            return "—"
        sign = "+" if x > 0 else ("−" if x < 0 else "")
        return f"{sign}${abs(x):,.2f}"

    # Diff lines
    wr_gap = your_wr - their_wr
    exp_gap = your_exp - their_exp
    gap_money = lambda d: ("+" if d >= 0 else "−") + f"${abs(d):,.2f}"

    # Narrative insights — pick the most asymmetric finding
    insights: list[str] = []
    if your_hour and their_hour and your_hour != their_hour:
        insights.append(
            f"Your edge hour is <span class='em'>{your_hour}</span> "
            f"({'+'if your_hour_exp>0 else '−'}${abs(your_hour_exp):.2f}/trade). "
            f"Theirs is <span class='em'>{their_hour}</span> "
            f"({'+'if their_hour_exp>0 else '−'}${abs(their_hour_exp):.2f}/trade) — "
            f"you're optimizing for <span class='neg'>different hours of the day</span>."
        )
    if your_side and their_side and your_side != their_side:
        insights.append(
            f"You make money on <span class='em'>{your_side}s</span> while they make it on "
            f"<span class='em'>{their_side}s</span>. Worth interrogating whether your bias is "
            f"<span class='em'>structural</span> or just <span class='neg'>habitual</span>."
        )
    if exp_gap < 0:
        insights.append(
            f"Your expectancy per trade trails by <span class='neg'>{gap_money(exp_gap)}</span>. "
            f"Over {you_overall.n_trades:,} trades that's "
            f"<span class='neg'>{gap_money(exp_gap * you_overall.n_trades)}</span> of missed PNL "
            f"at their per-trade rate."
        )
    elif exp_gap > 0:
        insights.append(
            f"You actually <span class='pos'>beat the benchmark</span> by "
            f"<span class='pos'>{gap_money(exp_gap)}</span>/trade. The contrast below shows "
            f"which dimensions to lean into."
        )
    if not insights:
        insights.append(
            "The benchmark's profile is similar to yours on the dimensions we can see. "
            "Dig into the conditional performance tabs for finer contrasts."
        )

    insights_html = "".join(f"<p>{i}</p>" for i in insights)

    html = f"""
    <div class="ew-bench">
        <div class="ew-bench-header">
            <div class="ew-bench-title">Benchmark contrast</div>
            <div class="ew-bench-id">vs <span class="v">{short_id}</span>
                · {them_overall.n_trades:,} trades</div>
        </div>
        <div class="ew-bench-grid">
            <div class="ew-bench-cell">
                <div class="ew-bench-cell-label">Win Rate</div>
                <div class="ew-bench-cell-row">
                    <span class="who you">YOU</span>
                    <span class="v">{_pct(your_wr)}</span>
                </div>
                <div class="ew-bench-cell-row">
                    <span class="who">BENCH</span>
                    <span class="v">{_pct(their_wr)}</span>
                </div>
                <div class="ew-bench-diff">
                    Gap: <span class="em {_cls(wr_gap)}">{'+' if wr_gap>=0 else '−'}{abs(wr_gap):.1%}</span>
                </div>
            </div>
            <div class="ew-bench-cell">
                <div class="ew-bench-cell-label">Expectancy / Trade</div>
                <div class="ew-bench-cell-row">
                    <span class="who you">YOU</span>
                    <span class="v {_cls(your_exp)}">{_money_compact(your_exp)}</span>
                </div>
                <div class="ew-bench-cell-row">
                    <span class="who">BENCH</span>
                    <span class="v {_cls(their_exp)}">{_money_compact(their_exp)}</span>
                </div>
                <div class="ew-bench-diff">
                    Gap: <span class="em {_cls(exp_gap)}">{gap_money(exp_gap)}</span> / trade
                </div>
            </div>
            <div class="ew-bench-cell">
                <div class="ew-bench-cell-label">Best Hour</div>
                <div class="ew-bench-cell-row">
                    <span class="who you">YOU</span>
                    <span class="v">{your_hour or '—'}</span>
                </div>
                <div class="ew-bench-cell-row">
                    <span class="who">BENCH</span>
                    <span class="v">{their_hour or '—'}</span>
                </div>
                <div class="ew-bench-diff">
                    {('Same hour.' if your_hour == their_hour else 'Different hours of edge.') if your_hour and their_hour else 'Insufficient data.'}
                </div>
            </div>
            <div class="ew-bench-cell">
                <div class="ew-bench-cell-label">Best Side</div>
                <div class="ew-bench-cell-row">
                    <span class="who you">YOU</span>
                    <span class="v">{your_side or '—'}</span>
                </div>
                <div class="ew-bench-cell-row">
                    <span class="who">BENCH</span>
                    <span class="v">{their_side or '—'}</span>
                </div>
                <div class="ew-bench-diff">
                    {('Same directional bias.' if your_side == their_side else 'Opposing bias.') if your_side and their_side else 'Insufficient data.'}
                </div>
            </div>
        </div>
        <div class="ew-bench-insights">{insights_html}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Wave 2 — Peer Benchmark (zero-input, auto-fetched cohort)
# --------------------------------------------------------------------------- #


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_cohort_benchmark(window_type: str = "30d", n_traders: int = 5) -> dict:
    """Fetch top N traders from leaderboard, then their 30-day position history.

    Returns aggregated cohort stats. Cached for 1 hour.
    """
    from edgework.sodex_client import SodexClient

    end_ms = int(pd.Timestamp.utcnow().value // 1_000_000)
    days = 30 if window_type == "30d" else 7
    start_ms = end_ms - days * 86_400_000

    result = {
        "cohort": [],
        "leaderboard": [],
        "window": window_type,
        "days": days,
        "error": None,
    }

    try:
        with SodexClient(
            user_address="0x0000000000000000000000000000000000000000"
        ) as c:
            lb = c.get_leaderboard(
                window_type=window_type,
                sort_by="pnl",
                sort_order="desc",
                page=1,
                page_size=10,
            )
            result["leaderboard"] = lb.get("items", [])
    except Exception as e:  # noqa: BLE001
        result["error"] = f"leaderboard fetch: {e}"
        return result

    # Parallel history fetch — 5 paginated pulls in series is the slowest
    # part of the page on a cold cache. Aggregation keeps leaderboard order.
    from concurrent.futures import ThreadPoolExecutor as _TPE

    def _fetch_history(addr: str):
        try:
            with SodexClient(user_address=addr) as cc:
                return addr, cc.get_position_history_paginated(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    page_limit=500,
                    max_pages=3,
                )
        except Exception:  # noqa: BLE001
            return addr, None

    _lb_addrs = [
        it.get("wallet_address")
        for it in result["leaderboard"][:n_traders]
        if it.get("wallet_address")
    ]
    _hist_by_addr: dict[str, object] = {}
    if _lb_addrs:
        with _TPE(max_workers=min(5, len(_lb_addrs))) as _pool:
            for _addr, _hist in _pool.map(_fetch_history, _lb_addrs):
                _hist_by_addr[_addr] = _hist

    for item in result["leaderboard"][:n_traders]:
        addr = item.get("wallet_address")
        if not addr:
            continue
        try:
            positions = _hist_by_addr.get(addr)
            if not positions:
                continue
            df = slicer.normalize_orders(positions)
            if df.empty:
                continue
            ov = slicer.overall(df)
            sl = slicer.slice_all(df)
            best_hour, best_hour_exp = _best_hour_label(sl)
            best_side, best_side_exp = _best_side_label(sl)
            # Median position size in USD = size * entry_price.
            # Used for the scale caveat at the bottom of the card.
            try:
                pos_usd = (
                    df["size"].astype(float) * df["entry_price"].astype(float)
                ).dropna()
                med_size_usd = float(pos_usd.median()) if not pos_usd.empty else 0.0
            except Exception:  # noqa: BLE001
                med_size_usd = 0.0

            result["cohort"].append({
                "addr": addr,
                "rank": item.get("rank"),
                "lb_pnl_usd": float(item.get("pnl_usd", 0) or 0),
                "lb_volume_usd": float(item.get("volume_usd", 0) or 0),
                "n_trades": int(ov.n_trades),
                "winrate": float(ov.winrate),
                "expectancy": float(ov.expectancy),
                "total_pnl": float(ov.total_pnl),
                "avg_hold_min": float(ov.avg_hold_minutes),
                "median_pos_usd": med_size_usd,
                "best_hour": best_hour,
                "best_hour_exp": best_hour_exp,
                "best_side": best_side,
                "best_side_exp": best_side_exp,
            })
        except Exception:  # noqa: BLE001
            continue

    return result


# --------------------------------------------------------------------------- #
# Smart Money Watch — top traders' current open positions, in real-time
# --------------------------------------------------------------------------- #


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_smart_money_consensus(n_top: int = 20, window: str = "30d") -> dict:
    """Fetch the open positions of the top active+profitable SoDEX traders.

    Two-step selection so we get *actively trading winners* — not lucky
    one-shots:

      1. Pull top 50 by 30d VOLUME (= guaranteed active, lots of trades).
      2. Filter to profitable in window (PNL > 0).
      3. Sort by PNL desc, take top N.

    For each qualified trader, fetch their currently-open positions and
    aggregate per (symbol, side). Returns a dict keyed by symbol with
    counts + combined notional + combined trader-PNL.

    Cached 15min — top traders' open positions don't churn second-by-second.
    """
    from edgework.sodex_client import SodexClient

    result: dict = {
        "traders":             [],
        "consensus_per_symbol": {},
        "total_volume_leaders": 0,
        "fetched_at":           pd.Timestamp.now(tz="UTC").isoformat(),
        "error":                None,
    }

    try:
        with SodexClient(
            user_address="0x0000000000000000000000000000000000000000"
        ) as c:
            lb = c.get_leaderboard(
                window_type=window,
                sort_by="volume",
                sort_order="desc",
                page=1,
                page_size=50,
            )
        items = lb.get("items", []) or []
        result["total_volume_leaders"] = int(lb.get("total", 0) or 0)

        # Active + profitable, ranked by PNL.
        winners = [x for x in items if float(x.get("pnl_usd", 0) or 0) > 0]
        winners.sort(key=lambda x: float(x.get("pnl_usd", 0)), reverse=True)
        qualified = winners[:n_top]
    except Exception as e:  # noqa: BLE001
        result["error"] = f"leaderboard fetch failed: {e}"
        return result

    consensus: dict[str, dict] = {}
    trader_infos: list[dict] = []

    # Fan the per-trader open-position fetches out in parallel — 20 wallets
    # sequentially is 8-15s of cold-cache spinner; parallel it's ~1.5s.
    # Results land in a dict keyed by addr so aggregation below stays in
    # deterministic `qualified` order.
    from concurrent.futures import ThreadPoolExecutor

    def _fetch_open(addr: str):
        try:
            with SodexClient(user_address=addr) as cc:
                return addr, cc.get_open_positions()
        except Exception:  # noqa: BLE001 — one bad wallet must not kill the watch
            return addr, None

    addrs = [it.get("wallet_address") for it in qualified if it.get("wallet_address")]
    open_by_addr: dict[str, object] = {}
    if addrs:
        with ThreadPoolExecutor(max_workers=min(8, len(addrs))) as pool:
            for addr, data in pool.map(_fetch_open, addrs):
                open_by_addr[addr] = data

    for item in qualified:
        addr = item.get("wallet_address")
        if not addr:
            continue
        trader = {
            "addr":          addr,
            "rank_volume":   item.get("rank"),
            "pnl_usd":       float(item.get("pnl_usd", 0) or 0),
            "volume_usd":    float(item.get("volume_usd", 0) or 0),
        }
        trader_infos.append(trader)

        open_data = open_by_addr.get(addr)
        if open_data is None:
            continue

        # Open positions can come as {positions: [...]} or just [...] depending
        # on SoDEX gateway shape — handle both.
        if isinstance(open_data, list):
            positions = open_data
        elif isinstance(open_data, dict):
            positions = open_data.get("positions") or open_data.get("data") or []
        else:
            positions = []

        for p in positions:
            symbol = p.get("symbol")
            if not symbol:
                continue

            # SoDEX uses position_side="BOTH" (one-way mode) — direction is
            # encoded in the SIGN of `size`. Positive = long, negative = short.
            try:
                raw_size = float(p.get("size") or 0)
            except (ValueError, TypeError):
                raw_size = 0.0
            if raw_size == 0:
                continue  # closed, lingering in response

            side_raw = (p.get("positionSide") or p.get("side") or "").lower()
            if "long" in side_raw:
                side = "long"
            elif "short" in side_raw:
                side = "short"
            else:
                # BOTH or empty → infer from size sign.
                side = "long" if raw_size > 0 else "short"

            size = abs(raw_size)
            try:
                entry = float(p.get("avgEntryPrice") or p.get("entry_price") or 0)
            except (ValueError, TypeError):
                entry = 0.0
            notional = size * entry if entry else 0.0

            cs = consensus.setdefault(symbol, {
                "long_count":         0,
                "short_count":        0,
                "long_notional":      0.0,
                "short_notional":     0.0,
                "long_pnl_combined":  0.0,
                "short_pnl_combined": 0.0,
                "long_traders":       [],
                "short_traders":      [],
            })
            entry_info = {
                "addr":            addr,
                "size":            size,
                "entry_price":     entry,
                "notional":        notional,
                "trader_pnl_30d":  trader["pnl_usd"],
                "trader_vol_30d":  trader["volume_usd"],
            }
            cs[f"{side}_count"]        += 1
            cs[f"{side}_notional"]     += notional
            cs[f"{side}_pnl_combined"] += trader["pnl_usd"]
            cs[f"{side}_traders"].append(entry_info)

    result["traders"]              = trader_infos
    result["consensus_per_symbol"] = consensus
    return result


def _fmt_money_compact(x: float) -> str:
    """$X / $Xk / $X.XM compact formatting for sizes."""
    if x is None:
        return "—"
    ax = abs(x)
    sign = "" if x >= 0 else "−"
    if ax >= 1e6:
        return f"{sign}${ax/1e6:.1f}M"
    if ax >= 1e3:
        return f"{sign}${ax/1e3:.1f}k"
    return f"{sign}${ax:,.0f}"


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_user_open_positions(address: str) -> list[dict]:
    """Fetch a wallet's currently open positions. Cached 10 min.

    Returns a list of normalized dicts ``{symbol, side, size, entry_price,
    notional, unrealized_pnl}``. Empty list on no positions / fetch error.
    """
    if not address or not address.startswith("0x"):
        return []
    try:
        from edgework.sodex_client import SodexClient

        with SodexClient(user_address=address) as c:
            raw = c.get_open_positions()
    except Exception:  # noqa: BLE001
        return []

    if isinstance(raw, list):
        positions = raw
    elif isinstance(raw, dict):
        positions = raw.get("positions") or raw.get("data") or []
    else:
        return []

    out: list[dict] = []
    for p in positions:
        symbol = p.get("symbol")
        if not symbol:
            continue
        try:
            size_raw = float(p.get("size") or 0)
        except (ValueError, TypeError):
            size_raw = 0.0
        if size_raw == 0:
            continue  # already closed, lingering in response

        # SoDEX "ONE-WAY" mode: positionSide == "BOTH" and the sign of
        # `size` encodes direction (positive = long, negative = short).
        # "HEDGE" mode: positionSide is explicitly "LONG" or "SHORT".
        side_raw = (p.get("positionSide") or p.get("side") or "").lower()
        if "long" in side_raw:
            side = "long"
        elif "short" in side_raw:
            side = "short"
        else:
            side = "long" if size_raw > 0 else "short"

        size = abs(size_raw)
        try:
            entry = float(p.get("avgEntryPrice") or p.get("entry_price") or 0)
        except (ValueError, TypeError):
            entry = 0.0
        notional = size * entry if entry else 0.0
        try:
            upnl = float(p.get("unrealizedPnL") or p.get("unrealized_pnl") or 0)
        except (ValueError, TypeError):
            upnl = 0.0
        out.append({
            "symbol":         symbol,
            "side":           side,
            "size":           size,
            "entry_price":    entry,
            "notional":       notional,
            "unrealized_pnl": upnl,
        })
    return out


def _classify_user_vs_smart_money(
    user_pos: dict,
    consensus: dict | None,
) -> tuple[str, str, str]:
    """Return (status_label, status_class, narrative_html)."""
    if consensus is None:
        return (
            "— no consensus",
            "neutral",
            "No qualified top trader has an open position in this symbol.",
        )

    lc = int(consensus.get("long_count", 0))
    sc = int(consensus.get("short_count", 0))
    ln = float(consensus.get("long_notional", 0))
    sn = float(consensus.get("short_notional", 0))
    user_side = user_pos["side"]

    # Determine smart-money directional bias.
    #   - "strong": ≥3 trader gap (alert-worthy)
    #   - "weak": notional 2× one side and at least 1 trader (informational)
    sm_dir, sm_strength = None, None
    if lc - sc >= 3:
        sm_dir, sm_strength = "long", "strong"
    elif sc - lc >= 3:
        sm_dir, sm_strength = "short", "strong"
    elif ln > sn * 2 and lc > 0:
        sm_dir, sm_strength = "long", "weak"
    elif sn > ln * 2 and sc > 0:
        sm_dir, sm_strength = "short", "weak"

    _long_w = _t("up_long_word")
    _short_w = _t("up_short_word")
    _traders_w = _t("up_traders_word")
    _user_side_w = _long_w if user_side == "long" else _short_w

    if sm_dir is None:
        return (
            _t("up_status_mixed"),
            "neutral",
            f"{_t('up_split_word')}: {lc} {_long_w} ({_fmt_money_compact(ln)}) vs "
            f"{sc} {_short_w} ({_fmt_money_compact(sn)}).",
        )

    side_notional = ln if sm_dir == "long" else sn
    side_count = lc if sm_dir == "long" else sc
    _sm_side_w = _long_w if sm_dir == "long" else _short_w

    if user_side == sm_dir:
        return (
            _t("up_status_aligned"),
            "aligned",
            f"{_t('up_you')} {_user_side_w}, smart money {_sm_side_w} {_t('up_too_word')} "
            f"({side_count} {_traders_w}, {_fmt_money_compact(side_notional)}).",
        )
    return (
        _t("up_status_contrarian") if sm_strength == "strong" else _t("up_status_weak_contrarian"),
        "contrarian" if sm_strength == "strong" else "weak-contrarian",
        f"{_t('up_you')} {_user_side_w} {_t('up_but_word')} {_sm_side_w} "
        f"({side_count} {_traders_w}, {_fmt_money_compact(side_notional)}).",
    )


def _render_user_positions_vs_smart_money(
    user_positions: list[dict],
    consensus: dict,
) -> None:
    """Section comparing user's open positions to the smart-money book."""
    if not user_positions:
        st.markdown(
            (
                '<div class="ew-section">'
                f'<div class="ew-section-title">{_t("sec_your_positions")}</div>'
                f'<div class="ew-section-sub">{_t("up_no_open")}</div>'
                '</div>'
            ),
            unsafe_allow_html=True,
        )
        return

    rows_html = ""
    n_contrarian = 0
    for pos in user_positions:
        symbol = pos["symbol"]
        sm = consensus.get(symbol)
        status_label, status_cls, narrative = _classify_user_vs_smart_money(pos, sm)
        if status_cls in ("contrarian", "weak-contrarian"):
            n_contrarian += 1

        side_label = pos["side"].upper()
        side_cls = "long" if pos["side"] == "long" else "short"
        notional_str = _fmt_money_compact(pos["notional"])
        upnl = pos.get("unrealized_pnl", 0.0)
        upnl_str = ""
        if abs(upnl) >= 1:
            upnl_cls = "pos" if upnl >= 0 else "neg"
            upnl_str = (
                f' <small class="upnl {upnl_cls}">'
                f'uPNL {"+" if upnl >= 0 else "−"}{_fmt_money_compact(abs(upnl))}'
                f'</small>'
            )

        if sm:
            lc, sc = int(sm.get("long_count", 0)), int(sm.get("short_count", 0))
            ln, sn = float(sm.get("long_notional", 0)), float(sm.get("short_notional", 0))
            sm_str = (
                f'<span class="sm-long">{lc} {_t("up_long_word")} ({_fmt_money_compact(ln)})</span>'
                f' <span class="sm-sep">vs</span> '
                f'<span class="sm-short">{sc} {_t("up_short_word")} ({_fmt_money_compact(sn)})</span>'
            )
        else:
            sm_str = f'<span class="sm-empty">{_t("up_sm_no_qualified")}</span>'

        rows_html += (
            '<div class="ew-up-row">'
            f'<span class="sym">{symbol}</span>'
            f'<span class="my-side {side_cls}">{side_label} {notional_str}{upnl_str}</span>'
            f'<span class="sm-detail">{sm_str}</span>'
            f'<span class="status {status_cls}">{status_label}</span>'
            '</div>'
        )

    header_html = (
        '<div class="ew-up-row header">'
        f'<span>{_t("up_h_symbol")}</span>'
        f'<span>{_t("up_h_your_pos")}</span>'
        f'<span>{_t("up_h_smart_money")}</span>'
        f'<span>{_t("up_h_status")}</span>'
        '</div>'
    )

    warning_html = ""
    if n_contrarian:
        _lang = _current_lang()
        if _lang == "PT":
            _s_be = "estão" if n_contrarian != 1 else "está"
            _s_pl = "s" if n_contrarian != 1 else ""
        else:
            _s_be = "s are" if n_contrarian != 1 else " is"
            _s_pl = ""
        warning_html = (
            '<div class="ew-up-warning">'
            + _t("up_warning", n=n_contrarian, s_be=_s_be, s_pl=_s_pl)
            + '</div>'
        )

    _n = len(user_positions)
    _sub = _t("up_subtitle", n=_n, s="s" if _n != 1 else "")
    section_html = (
        '<div class="ew-section">'
        f'<div class="ew-section-title">{_t("sec_your_positions")}</div>'
        f'<div class="ew-section-sub">{_sub}</div>'
        '</div>'
    )

    grid_html = f'<div class="ew-up-grid">{header_html}{rows_html}</div>'
    st.markdown(section_html + warning_html + grid_html, unsafe_allow_html=True)


def _render_smart_money_watch(data: dict) -> None:
    """Live snapshot of top-trader positions, with consensus per symbol."""
    if data.get("error"):
        st.caption(_t("sm_unavailable", err=data['error']))
        return

    consensus = data.get("consensus_per_symbol", {}) or {}
    traders = data.get("traders", []) or []
    if not traders:
        st.caption(_t("sm_no_traders"))
        return
    if not consensus:
        st.markdown(
            (
                '<div class="ew-section">'
                f'<div class="ew-section-title ew-anchor" id="sec-smartmoney">{_t("sec_smart_money")}</div>'
                f'<div class="ew-section-sub">{_t("sm_no_pos", n=len(traders))}</div>'
                '</div>'
            ),
            unsafe_allow_html=True,
        )
        return

    n_traders = len(traders)
    n_in_market = len({
        p["addr"]
        for cs in consensus.values()
        for p in (cs.get("long_traders", []) + cs.get("short_traders", []))
    })

    fetched_at = data.get("fetched_at", "")
    fetched_short = fetched_at[11:16] + " UTC" if fetched_at else ""

    # Sort symbols by absolute consensus strength.
    def _strength(kv):
        cs = kv[1]
        return abs(cs["long_count"] - cs["short_count"])
    sorted_symbols = sorted(consensus.items(), key=_strength, reverse=True)

    rows_html = ""
    for symbol, cs in sorted_symbols[:12]:
        lc, sc = int(cs["long_count"]), int(cs["short_count"])
        ln, sn = float(cs["long_notional"]), float(cs["short_notional"])
        net_notional = ln - sn

        _long_up = _t("up_long_word").upper()
        _short_up = _t("up_short_word").upper()
        if lc - sc >= 3:
            bias_label, bias_cls = f"↑ {_long_up} · {lc}v{sc}", "long"
        elif sc - lc >= 3:
            bias_label, bias_cls = f"↓ {_short_up} · {sc}v{lc}", "short"
        elif lc + sc <= 1:
            _single = "único" if _current_lang() == "PT" else "single"
            bias_label, bias_cls = f"·  {_single}", "neutral"
        else:
            _mixed = "MISTO" if _current_lang() == "PT" else "MIXED"
            bias_label, bias_cls = f"~ {_mixed} · {lc}v{sc}", "neutral"

        total_notional = ln + sn
        long_pct = (ln / total_notional * 100) if total_notional > 0 else 50
        short_pct = 100 - long_pct
        bar_html = (
            '<div class="ew-sm-bar">'
            f'<div class="long" style="width:{long_pct:.0f}%"></div>'
            f'<div class="short" style="width:{short_pct:.0f}%"></div>'
            '</div>'
        )
        long_cell  = f'{_fmt_money_compact(ln) if lc else "—"} <small>({lc})</small>'
        short_cell = f'{_fmt_money_compact(sn) if sc else "—"} <small>({sc})</small>'

        # NET column: self-explanatory "$X long" / "$X short" / "flat".
        if abs(net_notional) < 1:
            net_str, net_cls = _t("sm_flat"), "neutral"
        elif net_notional > 0:
            net_str = f'{_fmt_money_compact(net_notional)} <small>{_t("sm_long_word")}</small>'
            net_cls = "pos"
        else:
            net_str = f'{_fmt_money_compact(abs(net_notional))} <small>{_t("sm_short_word")}</small>'
            net_cls = "neg"

        # Single-line HTML (no leading whitespace) so the Markdown parser
        # doesn't mistake indented HTML for a code block.
        rows_html += (
            '<div class="ew-sm-row">'
            f'<span class="sym">{symbol}</span>'
            f'<span class="bias {bias_cls}">{bias_label}</span>'
            f'<span class="size pos">{long_cell}</span>'
            f'<span class="size neg">{short_cell}</span>'
            f'{bar_html}'
            f'<span class="net {net_cls}">{net_str}</span>'
            '</div>'
        )

    header_html = (
        '<div class="ew-sm-row header">'
        f'<span>{_t("sm_h_symbol")}</span>'
        f'<span>{_t("sm_h_bias")}</span>'
        f'<span>{_t("sm_h_long")}</span>'
        f'<span>{_t("sm_h_short")}</span>'
        f'<span class="bar-col">{_t("sm_h_split")}</span>'
        f'<span>{_t("sm_h_net")}</span>'
        '</div>'
    )

    section_html = (
        '<div class="ew-section">'
        f'<div class="ew-section-title ew-anchor" id="sec-smartmoney">{_t("sec_smart_money")}</div>'
        '<div class="ew-section-sub">'
        + _t("sm_subtitle", n_traders=n_traders, n_in_market=n_in_market, fetched=fetched_short)
        + '<br><br>'
        + _t("sm_how_to_read")
        + '</div>'
        '</div>'
    )

    watch_html = (
        f'<div class="ew-sm-watch">{header_html}{rows_html}</div>'
    )

    st.markdown(section_html + watch_html, unsafe_allow_html=True)


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_smartmoney_intervals(addrs: tuple, days: int = 30) -> dict:
    """Reconstruct when each qualified top trader held what.

    Pulls every trader's position history for the window and converts each
    closed position into an interval (open_ms, close_ms, side, notional,
    addr). Looking up which intervals contain a timestamp = what the
    smart-money book looked like at that moment.
    """
    from concurrent.futures import ThreadPoolExecutor

    from edgework.sodex_client import SodexClient

    if not addrs:
        return {}

    end_ms = int(pd.Timestamp.utcnow().value // 1_000_000)
    start_ms = end_ms - days * 86_400_000

    def _hist(addr: str):
        try:
            with SodexClient(user_address=addr) as c:
                return addr, c.get_position_history_paginated(
                    start_ms=start_ms, end_ms=end_ms,
                    page_limit=500, max_pages=2,
                )
        except Exception:  # noqa: BLE001 — one bad wallet must not kill the card
            return addr, None

    intervals: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(addrs))) as pool:
        for addr, hist in pool.map(_hist, addrs):
            for p in hist or []:
                symbol = p.get("symbol")
                if not symbol:
                    continue
                try:
                    o_ms = int(p.get("createdAt") or 0)
                    c_ms = int(p.get("updatedAt") or 0)
                except (TypeError, ValueError):
                    continue
                if not o_ms or not c_ms or c_ms < o_ms:
                    continue
                side_raw = str(p.get("positionSide") or "").lower()
                if "long" in side_raw:
                    side = "long"
                elif "short" in side_raw:
                    side = "short"
                else:
                    continue  # direction undeterminable for closed one-way rows
                try:
                    entry = float(p.get("avgEntryPrice") or 0)
                    qty = abs(float(p.get("cumClosedSize") or p.get("maxSize") or 0))
                except (TypeError, ValueError):
                    entry = qty = 0.0
                notional = entry * qty
                intervals.setdefault(symbol, []).append(
                    (o_ms, c_ms, side, notional, addr.lower())
                )
    return intervals


@st.cache_data(ttl=1800, show_spinner=False)
def _compute_contrarian_track_record(
    trades_df: pd.DataFrame,
    addrs: tuple,
    self_addr: str,
    days: int = 30,
) -> dict:
    """Classify the user's recent entries against the reconstructed book.

    Same bias thresholds as the live classifier: strong = count diff ≥3,
    weak = 2× notional dominance with at least one trader on that side.
    The user's own wallet is excluded from the book (a top-volume wallet
    analysing itself must not count as its own smart money).
    """
    intervals = _fetch_smartmoney_intervals(addrs, days)

    now_ms = int(pd.Timestamp.utcnow().value // 1_000_000)
    start_ms = now_ms - days * 86_400_000
    self_l = (self_addr or "").lower()

    buckets: dict[str, list[float]] = {"contrarian": [], "aligned": [], "nosignal": []}
    df = trades_df.dropna(subset=["opened_at", "pnl"])

    for t in df.itertuples():
        try:
            t_ms = int(t.opened_at.timestamp() * 1000)
        except (AttributeError, ValueError, OSError):
            continue
        if t_ms < start_ms:
            continue
        pnl = float(t.pnl)
        iv = intervals.get(t.symbol)
        if not iv:
            buckets["nosignal"].append(pnl)
            continue

        lc = sc = 0
        ln = sn = 0.0
        for (o_ms, c_ms, side_i, notional_i, addr_i) in iv:
            if addr_i == self_l:
                continue
            if o_ms <= t_ms <= c_ms:
                if side_i == "long":
                    lc += 1
                    ln += notional_i
                else:
                    sc += 1
                    sn += notional_i

        if lc - sc >= 3 or (ln > sn * 2 and lc > 0):
            bias = "long"
        elif sc - lc >= 3 or (sn > ln * 2 and sc > 0):
            bias = "short"
        else:
            buckets["nosignal"].append(pnl)
            continue

        user_side = str(t.side).lower()
        if user_side == bias:
            buckets["aligned"].append(pnl)
        else:
            buckets["contrarian"].append(pnl)

    def _bstats(pnls: list[float]) -> dict:
        if not pnls:
            return {"n": 0, "wr": None, "exp": None, "total": 0.0}
        a = np.array(pnls, dtype=float)
        return {
            "n": int(len(a)),
            "wr": float((a > 0).mean()),
            "exp": float(a.mean()),
            "total": float(a.sum()),
        }

    return {
        "contrarian": _bstats(buckets["contrarian"]),
        "aligned":    _bstats(buckets["aligned"]),
        "nosignal":   _bstats(buckets["nosignal"]),
        "days":       days,
        "n_traders":  len(addrs),
    }


def _render_contrarian_track_record(
    trades_df: pd.DataFrame,
    smart_money: dict,
    self_addr: str,
) -> None:
    """Etapa D — the evidence card behind the divergence alert."""
    traders = smart_money.get("traders") or []
    addrs = tuple(t["addr"] for t in traders if t.get("addr"))
    if not addrs or trades_df is None or trades_df.empty:
        return

    with st.spinner(_t("tr_loading")):
        try:
            data = _compute_contrarian_track_record(
                trades_df, addrs, self_addr or ""
            )
        except Exception:  # noqa: BLE001 — evidence card is optional, never fatal
            return

    days = data["days"]
    c, a, ns = data["contrarian"], data["aligned"], data["nosignal"]

    section_html = (
        '<div class="ew-section">'
        f'<div class="ew-section-title">{_t("tr_title")}</div>'
        f'<div class="ew-section-sub">{_t("tr_sub", days=days)}</div>'
        '</div>'
    )

    if c["n"] == 0 and a["n"] == 0:
        st.markdown(
            section_html
            + f'<div class="ew-track-caveat">{_t("tr_empty", days=days)}</div>',
            unsafe_allow_html=True,
        )
        return

    def _money2(x: float) -> str:
        """Signed money with cents — per-trade expectancies here are often
        single-digit dollars, where integer rounding hides the real gap."""
        sign = "−" if x < 0 else "+"
        return f"{sign}${abs(x):,.2f}"

    def _cell(kind: str, label: str, s: dict) -> str:
        if s["n"] == 0:
            body = '<span class="big">0</span><div class="sub">—</div>'
        else:
            wr_cls = "pos" if s["wr"] >= 0.5 else "neg"
            exp_cls = "pos" if s["exp"] >= 0 else "neg"
            tot_cls = "pos" if s["total"] >= 0 else "neg"
            body = (
                f'<span class="big">{s["n"]:,}</span>'
                '<div class="sub">'
                f'<span class="{wr_cls}">{s["wr"]:.0%}</span> {_t("tr_win")}'
                f' · <span class="{exp_cls}">{_money2(s["exp"])}</span>{_t("tr_exp")}'
                f'<br>{_t("tr_total")}: <span class="{tot_cls}">{_money_signed(s["total"])}</span>'
                '</div>'
            )
        return (
            f'<div class="ew-track-cell {kind}">'
            f'<span class="k">{label}</span>{body}</div>'
        )

    cells = (
        _cell("contrarian", _t("tr_contrarian"), c)
        + _cell("aligned", _t("tr_aligned"), a)
        + _cell("nosignal", _t("tr_nosignal"), ns)
    )

    verdict_html = ""
    if c["n"] >= 3 and a["n"] >= 3:
        gap = a["exp"] - c["exp"]
        key = "tr_verdict_bad" if gap > 0 else "tr_verdict_good"
        verdict_html = (
            '<div class="ew-track-verdict">'
            + _t(
                key,
                contr_exp=_money2(c["exp"]),
                alig_exp=_money2(a["exp"]),
                gap=_money2(abs(gap)),
                n=c["n"],
            )
            + '</div>'
        )

    caveat_html = (
        f'<div class="ew-track-caveat">{_t("tr_caveat", n_traders=data["n_traders"])}</div>'
    )

    st.markdown(
        section_html
        + f'<div class="ew-track"><div class="ew-track-grid">{cells}</div>'
        + verdict_html
        + caveat_html
        + '</div>',
        unsafe_allow_html=True,
    )


def _render_cohort_benchmark(you_overall, you_slices, you_trades) -> None:
    """Auto-comparison: you vs top-5 SoDEX traders. Renders just before briefing."""
    # Fetch (cached) — show spinner during cold load.
    with st.spinner("Loading peer benchmark — top 5 SoDEX traders (cached 1h)…"):
        try:
            data = _fetch_cohort_benchmark(window_type="30d", n_traders=5)
        except Exception as e:  # noqa: BLE001
            st.warning(f"Peer benchmark unavailable: {e}")
            return

    if data.get("error"):
        st.caption(f"Peer benchmark unavailable: {data['error']}")
        return
    cohort: list[dict] = data.get("cohort", [])
    if len(cohort) < 2:
        return  # Not enough data for a benchmark

    # Your median position size (USD) — for scale caveat
    try:
        your_pos_usd = (
            you_trades["size"].astype(float) * you_trades["entry_price"].astype(float)
        ).dropna()
        your_med_size = float(your_pos_usd.median()) if not your_pos_usd.empty else 0.0
    except Exception:  # noqa: BLE001
        your_med_size = 0.0

    import statistics as stats

    # Peer medians
    med_wr = stats.median(c["winrate"] for c in cohort)
    med_exp = stats.median(c["expectancy"] for c in cohort)
    med_n = stats.median(c["n_trades"] for c in cohort)
    med_pnl = stats.median(c["total_pnl"] for c in cohort)
    med_hold = stats.median(c["avg_hold_min"] for c in cohort)
    med_size = stats.median(
        c["median_pos_usd"] for c in cohort if c.get("median_pos_usd", 0) > 0
    ) if any(c.get("median_pos_usd", 0) > 0 for c in cohort) else 0.0

    # Most common best hour / side across the peers
    hours = [c["best_hour"] for c in cohort if c["best_hour"]]
    sides = [c["best_side"] for c in cohort if c["best_side"]]
    peers_hour = max(set(hours), key=hours.count) if hours else None
    peers_side = max(set(sides), key=sides.count) if sides else None

    you_wr = float(you_overall.winrate)
    you_exp = float(you_overall.expectancy)
    you_n = int(you_overall.n_trades)
    you_pnl = float(you_overall.total_pnl)

    your_hour, your_hour_exp = _best_hour_label(you_slices)
    your_side, _ = _best_side_label(you_slices)

    # Ranking: where would your PNL land if dropped into the top-5 list?
    sorted_pnls = sorted(
        [c["total_pnl"] for c in cohort] + [you_pnl], reverse=True
    )
    your_rank = sorted_pnls.index(you_pnl) + 1
    rank_of = len(cohort) + 1

    # Scale ratio (peers' median position size vs yours) — drives the caveat.
    scale_ratio = (med_size / your_med_size) if (med_size and your_med_size) else None

    # Format helpers
    def _cls(x: float) -> str:
        if x is None or pd.isna(x):
            return ""
        return "pos" if x >= 0 else "neg"

    def _pct(x: float) -> str:
        return "—" if x is None or pd.isna(x) else f"{x:.1%}"

    def _money_compact(x: float) -> str:
        if x is None or pd.isna(x):
            return "—"
        sign = "+" if x > 0 else ("−" if x < 0 else "")
        return f"{sign}${abs(x):,.2f}"

    wr_gap = you_wr - med_wr
    exp_gap = you_exp - med_exp
    gap_money = lambda d: ("+" if d >= 0 else "−") + f"${abs(d):,.2f}"

    # Insights
    _pt_ins = _current_lang() == "PT"
    insights: list[str] = []
    if _pt_ins:
        insights.append(
            f"Seu PNL de <span class='em'>{_money_compact(you_pnl)}</span> ficaria em "
            f"<span class='em'>#{your_rank}</span> de <span class='em'>{rank_of}</span> "
            f"se entrasse junto com o top 5."
        )
    else:
        insights.append(
            f"Your <span class='em'>{_money_compact(you_pnl)}</span> PNL would rank "
            f"<span class='em'>#{your_rank}</span> of <span class='em'>{rank_of}</span> "
            f"if dropped in alongside the top 5."
        )

    if exp_gap < 0:
        deficit_total = exp_gap * you_n
        if _pt_ins:
            insights.append(
                f"A expectativa mediana dos top traders é <span class='em'>"
                f"{_money_compact(med_exp)}</span>/trade vs sua "
                f"<span class='{_cls(you_exp)}'>{_money_compact(you_exp)}</span>. "
                f"Com sua quantidade de trades, igualar a taxa deles mudaria seu PNL em "
                f"<span class='neg'>{gap_money(deficit_total)}</span>."
            )
        else:
            insights.append(
                f"Top traders' median expectancy is <span class='em'>"
                f"{_money_compact(med_exp)}</span>/trade vs your "
                f"<span class='{_cls(you_exp)}'>{_money_compact(you_exp)}</span>. "
                f"At your trade count, matching their rate would shift PNL by "
                f"<span class='neg'>{gap_money(deficit_total)}</span>."
            )
    elif exp_gap > 0:
        if _pt_ins:
            insights.append(
                f"Você está <span class='pos'>batendo os pares</span> em expectativa por "
                f"<span class='pos'>{gap_money(exp_gap)}</span>/trade. Seja lá o que você "
                f"está fazendo certo, o top 5 não está conseguindo igualar."
            )
        else:
            insights.append(
                f"You're <span class='pos'>beating the peers</span> on expectancy by "
                f"<span class='pos'>{gap_money(exp_gap)}</span>/trade. Whatever you're "
                f"doing right, the top 5 aren't matching it."
            )

    if med_n > 0:
        ratio = you_n / med_n
        if ratio > 2:
            if _pt_ins:
                insights.append(
                    f"Você faz <span class='em'>{ratio:.1f}×</span> mais trades que a "
                    f"mediana dos top ({you_n:,} vs {int(med_n):,}). Eles são "
                    f"<span class='em'>mais seletivos</span> — menos tiros, filtros mais apertados."
                )
            else:
                insights.append(
                    f"You take <span class='em'>{ratio:.1f}×</span> as many trades as the "
                    f"top traders' median ({you_n:,} vs {int(med_n):,}). They're "
                    f"<span class='em'>more selective</span> — fewer shots, tighter filters."
                )
        elif ratio < 0.5:
            if _pt_ins:
                insights.append(
                    f"Você faz <span class='em'>{1/ratio:.1f}× menos</span> trades que a "
                    f"mediana dos top. Seletividade é positiva — mas confirme que sua "
                    f"amostra é grande o bastante pra confiar no veredito."
                )
            else:
                insights.append(
                    f"You take <span class='em'>{1/ratio:.1f}× fewer</span> trades than "
                    f"the top traders' median. Selectivity is a plus — but make sure your "
                    f"sample is large enough to trust the verdict."
                )

    if your_hour and peers_hour and your_hour != peers_hour:
        if _pt_ins:
            insights.append(
                f"Os top traders concentram seu edge às <span class='em'>{peers_hour}</span>; "
                f"o seu é às <span class='em'>{your_hour}</span>. Vocês otimizam para "
                f"<span class='em'>horários diferentes</span> do dia."
            )
        else:
            insights.append(
                f"Top traders cluster their edge at <span class='em'>{peers_hour}</span>; "
                f"yours is at <span class='em'>{your_hour}</span>. You're optimizing for "
                f"<span class='em'>different hours</span> of the day."
            )

    if your_side and peers_side and your_side != peers_side:
        if _pt_ins:
            insights.append(
                f"Top 5 tendem a <span class='em'>{peers_side}</span>; você tende a "
                f"<span class='em'>{your_side}</span>. Vale checar se seu viés é "
                f"<span class='em'>estrutural</span> ou só <span class='neg'>de hábito</span>."
            )
        else:
            insights.append(
                f"Top 5 lean <span class='em'>{peers_side}</span>; you lean "
                f"<span class='em'>{your_side}</span>. Worth checking if your bias is "
                f"<span class='em'>structural</span> or just <span class='neg'>habitual</span>."
            )

    insights_html = "".join(f"<p>{ins}</p>" for ins in insights)
    total_trades = sum(c["n_trades"] for c in cohort)

    # Scale caveat — only shown when peers trade noticeably bigger size.
    def _fmt_size(usd: float) -> str:
        if usd >= 1e6:
            return f"${usd/1e6:.1f}M"
        if usd >= 1e3:
            return f"${usd/1e3:.1f}k"
        return f"${usd:,.0f}"

    caveat_html = ""
    _pt_cav = _current_lang() == "PT"
    _caveat_k = "Ressalva de escala:" if _pt_cav else "Scale caveat:"
    if scale_ratio and scale_ratio >= 2:
        if _pt_cav:
            caveat_html = (
                "<div class='ew-bench-caveat'>"
                f"<span class='k'>{_caveat_k}</span> "
                f"a posição mediana dos top traders é <span class='em'>{_fmt_size(med_size)}</span> "
                f"vs a sua <span class='em'>{_fmt_size(your_med_size)}</span> "
                f"(<span class='em'>~{scale_ratio:.0f}×</span> maior). "
                "Os gaps em dólares acima são absolutos, não normalizados por tamanho — "
                "copie o <strong>processo</strong> deles, não os números por trade."
                "</div>"
            )
        else:
            caveat_html = (
                "<div class='ew-bench-caveat'>"
                f"<span class='k'>{_caveat_k}</span> "
                f"top traders' median position size is <span class='em'>{_fmt_size(med_size)}</span> "
                f"vs your <span class='em'>{_fmt_size(your_med_size)}</span> "
                f"(<span class='em'>~{scale_ratio:.0f}×</span> larger). "
                "Dollar gaps above are absolute, not size-normalized — "
                "match their <strong>process</strong>, not their per-trade numbers."
                "</div>"
            )
    elif scale_ratio and scale_ratio <= 0.5:
        if _pt_cav:
            caveat_html = (
                "<div class='ew-bench-caveat'>"
                f"<span class='k'>{_caveat_k}</span> "
                f"você opera <span class='em'>~{1/scale_ratio:.0f}× maior</span> "
                "que a posição mediana desse grupo de pares. Os gaps em dólares podem "
                "subestimar a eficiência deles por dólar arriscado."
                "</div>"
            )
        else:
            caveat_html = (
                "<div class='ew-bench-caveat'>"
                f"<span class='k'>{_caveat_k}</span> "
                f"you trade <span class='em'>~{1/scale_ratio:.0f}× larger</span> "
                "than this peer group's median position. The dollar gaps may "
                "understate their efficiency on a per-dollar-risked basis."
                "</div>"
            )

    _pt = _current_lang() == "PT"
    _gap_w = "Diferença" if _pt else "Gap"
    _same_hour = "Mesma hora." if _pt else "Same hour."
    _diff_hour = "Horários de edge diferentes." if _pt else "Different hours of edge."
    _same_side = "Mesmo viés direcional." if _pt else "Same directional bias."
    _opp_side = "Viés oposto." if _pt else "Opposing bias."
    _insuf = "Dados insuficientes." if _pt else "Insufficient data."
    _per_trade = "/ trade"
    html = f"""
    <div class="ew-bench">
        <div class="ew-bench-header">
            <div class="ew-bench-title ew-anchor" id="sec-peers">{_t("pb_eyebrow")}</div>
            <div class="ew-bench-id">{_t("pb_vs", n_traders=len(cohort), n_trades=total_trades)}</div>
        </div>
        <div class="ew-bench-grid">
            <div class="ew-bench-cell">
                <div class="ew-bench-cell-label">{_t("pb_win_rate")}</div>
                <div class="ew-bench-cell-row">
                    <span class="who you">{_t("pb_you")}</span>
                    <span class="v">{_pct(you_wr)}</span>
                </div>
                <div class="ew-bench-cell-row">
                    <span class="who">{_t("pb_top5")}</span>
                    <span class="v">{_pct(med_wr)}</span>
                </div>
                <div class="ew-bench-diff">
                    {_gap_w}: <span class="em {_cls(wr_gap)}">{'+' if wr_gap>=0 else '−'}{abs(wr_gap):.1%}</span>
                </div>
            </div>
            <div class="ew-bench-cell">
                <div class="ew-bench-cell-label">{_t("pb_expectancy")}</div>
                <div class="ew-bench-cell-row">
                    <span class="who you">{_t("pb_you")}</span>
                    <span class="v {_cls(you_exp)}">{_money_compact(you_exp)}</span>
                </div>
                <div class="ew-bench-cell-row">
                    <span class="who">{_t("pb_top5")}</span>
                    <span class="v {_cls(med_exp)}">{_money_compact(med_exp)}</span>
                </div>
                <div class="ew-bench-diff">
                    {_gap_w}: <span class="em {_cls(exp_gap)}">{gap_money(exp_gap)}</span> {_per_trade}
                </div>
            </div>
            <div class="ew-bench-cell">
                <div class="ew-bench-cell-label">{_t("pb_best_hour")}</div>
                <div class="ew-bench-cell-row">
                    <span class="who you">{_t("pb_you")}</span>
                    <span class="v">{your_hour or '—'}</span>
                </div>
                <div class="ew-bench-cell-row">
                    <span class="who">{_t("pb_top5")}</span>
                    <span class="v">{peers_hour or '—'}</span>
                </div>
                <div class="ew-bench-diff">
                    {(_same_hour if your_hour == peers_hour else _diff_hour) if your_hour and peers_hour else _insuf}
                </div>
            </div>
            <div class="ew-bench-cell">
                <div class="ew-bench-cell-label">{_t("pb_best_side")}</div>
                <div class="ew-bench-cell-row">
                    <span class="who you">{_t("pb_you")}</span>
                    <span class="v">{(your_side or '—').upper()}</span>
                </div>
                <div class="ew-bench-cell-row">
                    <span class="who">{_t("pb_top5")}</span>
                    <span class="v">{(peers_side or '—').upper()}</span>
                </div>
                <div class="ew-bench-diff">
                    {(_same_side if your_side == peers_side else _opp_side) if your_side and peers_side else _insuf}
                </div>
            </div>
        </div>
        <div class="ew-bench-insights">{insights_html}</div>
        {caveat_html}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Wave 2 Sprint 2 — Risk filters (2D anti-pattern detector)
# --------------------------------------------------------------------------- #


_RISK_DIM_FORMATTERS = {
    "hour":   lambda v: (_t("rd_hour"),   f"{int(v):02d}:00 UTC"),
    "day":    lambda v: (_t("rd_day"),    _DOW_LABELS[int(v)] if 0 <= int(v) < 7 else str(v)),
    "side":   lambda v: (_t("rd_side"),   str(v).upper()),
    "symbol": lambda v: (_t("rd_symbol"), str(v)),
    "streak": lambda v: (_t("rd_streak"), str(v)),
    "size":   lambda v: (_t("rd_size"),   str(v)),
    "hold":   lambda v: (_t("rd_hold"),   str(v)),
    "regime": lambda v: (_t("rd_regime"), str(v).upper()),
}


def _compute_risk_contexts(trades_df: pd.DataFrame, min_n: int = 5) -> list[dict]:
    """Cross every pair of dimensions and find combinations by expectancy.

    Returns sorted list (worst first) of:
        {"dims": ((dim_a, val_a), (dim_b, val_b)),
         "n": int, "wr": float, "expectancy": float, "total_pnl": float,
         "avg_pnl": float}

    Same expectancy formula as slicer.py:
        expectancy = avg_win * winrate − avg_loss_mag * (1 − winrate)
    """
    if trades_df is None or trades_df.empty or "pnl" not in trades_df.columns:
        return []

    # Build the dim columns (skip any that aren't available on this df)
    dim_cols: dict = {}
    if "opened_at" in trades_df.columns:
        try:
            dim_cols["hour"] = trades_df["opened_at"].dt.hour.astype("Int64")
            dim_cols["day"]  = trades_df["opened_at"].dt.dayofweek.astype("Int64")
        except Exception:  # noqa: BLE001
            pass
    if "side" in trades_df.columns:
        dim_cols["side"] = trades_df["side"].astype(str).str.lower()
    if "symbol" in trades_df.columns:
        dim_cols["symbol"] = trades_df["symbol"].astype(str)
    if "_streak_b" in trades_df.columns:
        dim_cols["streak"] = trades_df["_streak_b"].astype(str)
    if "_size_q" in trades_df.columns:
        dim_cols["size"] = trades_df["_size_q"].astype(str)
    if "_hold_b" in trades_df.columns:
        dim_cols["hold"] = trades_df["_hold_b"].astype(str)
    if "regime" in trades_df.columns:
        dim_cols["regime"] = trades_df["regime"].astype(str)

    dim_names = list(dim_cols.keys())
    if len(dim_names) < 2:
        return []

    results: list[dict] = []
    pnl_series = trades_df["pnl"]

    for i in range(len(dim_names)):
        for j in range(i + 1, len(dim_names)):
            a = dim_names[i]
            b = dim_names[j]
            col_a = dim_cols[a]
            col_b = dim_cols[b]

            tmp = pd.DataFrame({"_a": col_a, "_b": col_b, "_pnl": pnl_series})
            tmp = tmp.dropna(subset=["_a", "_b", "_pnl"])
            if tmp.empty:
                continue

            for (val_a, val_b), grp in tmp.groupby(["_a", "_b"]):
                pnl = grp["_pnl"]
                n = len(pnl)
                if n < min_n:
                    continue
                wins = pnl[pnl > 0]
                losses = pnl[pnl <= 0]
                wr = len(wins) / n
                avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
                avg_loss_mag = abs(float(losses.mean())) if len(losses) > 0 else 0.0
                expectancy = avg_win * wr - avg_loss_mag * (1 - wr)
                results.append({
                    "dims": ((a, val_a), (b, val_b)),
                    "n": n,
                    "wr": wr,
                    "expectancy": expectancy,
                    "total_pnl": float(pnl.sum()),
                    "avg_pnl": float(pnl.mean()),
                })

    results.sort(key=lambda x: x["expectancy"])
    return results


def _fmt_risk_label(dims: tuple) -> str:
    """Render combo as styled HTML: 'HOUR 18:00 + SIDE SHORT'."""
    parts = []
    for dim, val in dims:
        fmt = _RISK_DIM_FORMATTERS.get(dim)
        if fmt is None:
            label, value = dim.upper(), str(val)
        else:
            label, value = fmt(val)
        parts.append(f'<span class="k">{label}</span> <span class="v">{value}</span>')
    return '<span class="plus">+</span>'.join(parts)


def _render_risk_filters(trades_df: pd.DataFrame) -> None:
    """Top-3 anti-patterns (worst expectancy) + 1 strongest edge context."""
    contexts = _compute_risk_contexts(trades_df, min_n=5)
    if not contexts:
        return  # no 2D combos with enough sample

    worst = [c for c in contexts if c["expectancy"] < 0][:3]
    best  = [c for c in contexts if c["expectancy"] > 0]
    best  = sorted(best, key=lambda c: c["expectancy"], reverse=True)[:1]

    if not worst and not best:
        return

    # Build each item as a single concatenated HTML string — no internal
    # newlines or indentation, so st.markdown doesn't mistake the inter-item
    # whitespace for a paragraph break / code block.
    def _item_html(c: dict, kind: str) -> str:
        tag = _t("rf_avoid_tag") if kind == "warn" else _t("rf_edge_tag")
        cls = "neg" if kind == "warn" else "pos"
        return (
            f'<div class="ew-risk-item {kind}">'
            f'<div class="ew-risk-tag">{tag}</div>'
            f'<div class="ew-risk-label">{_fmt_risk_label(c["dims"])}</div>'
            f'<div class="ew-risk-stats">'
            f'<span class="{cls}">{_money_signed(c["expectancy"])}</span>{_t("rf_per_trade")}'
            f' &nbsp;·&nbsp; <span class="v">{c["wr"]:.0%}</span> {_t("rf_win")}'
            f' &nbsp;·&nbsp; <span class="v">{c["n"]}</span> {_t("rf_trades")}'
            f' &nbsp;·&nbsp; {_t("rf_net")} <span class="{cls}">{_money_signed(c["total_pnl"])}</span>'
            f'</div>'
            f'</div>'
        )

    items_html = "".join(_item_html(c, "warn") for c in worst) + "".join(
        _item_html(c, "edge") for c in best
    )

    n_w, n_e = len(worst), len(best)
    summary_bits = []
    if n_w:
        summary_bits.append(
            _t("rf_anti_one") if n_w == 1 else _t("rf_anti_many", n=n_w)
        )
    if n_e:
        summary_bits.append(_t("rf_edge_count", n=n_e))
    summary = " · ".join(summary_bits)

    # Single-line HTML to avoid st.markdown's indented-block / code-block quirks.
    html = (
        '<div class="ew-risk">'
        '<div class="ew-risk-header">'
        f'<div class="ew-risk-title">{_t("rf_title")}</div>'
        f'<div class="ew-risk-id">{_t("rf_meta", summary=summary)}</div>'
        '</div>'
        f'<div class="ew-risk-list">{items_html}</div>'
        f'<div class="ew-risk-footer">{_t("rf_footer")}</div>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Autopsy narrative — Verdict, Confrontation, Waterfall
# --------------------------------------------------------------------------- #

_render_verdict(slices, overall, trades)
_render_confrontation(slices)

# Secondary depth: collapsed by default so first-time visitors aren't hit
# with every chart at once. The anchor div sits outside the expander so the
# top-nav jump still lands here when collapsed.
st.markdown('<div id="sec-waterfall" class="ew-anchor"></div>', unsafe_allow_html=True)
with st.expander(_t("exp_waterfall"), expanded=False):
    _render_waterfall(slices, overall)


# --------------------------------------------------------------------------- #
# Conditional performance section
# --------------------------------------------------------------------------- #

st.markdown(
    f"""
    <div class="ew-section">
        <div class="ew-section-title ew-anchor" id="sec-conditional">{_t("sec_conditional")}</div>
        <div class="ew-section-sub">{_t("sec_conditional_sub")}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_hour, tab_streak, tab_size, tab_hold, tab_side, tab_symbol, tab_regime = st.tabs(
    [_t("tab_hour_of_day"), _t("tab_loss_streak"), _t("tab_size"),
     _t("tab_hold_time"), _t("tab_side"), _t("tab_symbol"), _t("tab_btc_regime")]
)


with tab_hour:
    _panel_header(_t("tab_hour_of_day"), slices["hour_of_day"])
    metric = _metric_pills("m_hour")
    _render_cards(
        slices["hour_of_day"], key_col="hour",
        key_label_fn=lambda h: f"{int(h):02d}:00 UTC",
    )
    st.markdown(
        f'<div class="ew-chart-label">{_t("cp_heatmap")}</div>',
        unsafe_allow_html=True,
    )
    _hour_dow_heatmap(trades, metric)
    with st.expander(_t("cp_bar_view")):
        _bar_chart(
            slices["hour_of_day"], key_col="hour", metric_key=metric,
            sort_by_key=True, key_label_fn=lambda h: f"{int(h):02d}h",
        )
        st.dataframe(
            _format_slice_table(slices["hour_of_day"]),
            use_container_width=True, hide_index=True,
        )


with tab_streak:
    _panel_header(_t("tab_loss_streak"), slices["consecutive_losses"])
    metric = _metric_pills("m_streak")
    st.caption(_t("tab_streak_caption"))
    _render_cards(slices["consecutive_losses"], key_col="streak_bucket")
    _bar_chart(
        slices["consecutive_losses"], key_col="streak_bucket", metric_key=metric,
    )
    with st.expander(_t("expand_full_table")):
        st.dataframe(
            _format_slice_table(slices["consecutive_losses"]),
            use_container_width=True, hide_index=True,
        )


with tab_size:
    _panel_header(_t("tab_size_title"), slices["size_quartile"])
    metric = _metric_pills("m_size")
    st.caption(_t("tab_size_caption"))
    _render_cards(slices["size_quartile"], key_col="size_quartile")
    _bar_chart(
        slices["size_quartile"], key_col="size_quartile",
        metric_key=metric, sort_by_key=True,
    )
    with st.expander(_t("expand_full_table")):
        st.dataframe(
            _format_slice_table(slices["size_quartile"]),
            use_container_width=True, hide_index=True,
        )


with tab_hold:
    _panel_header(_t("tab_hold_time"), slices["hold_duration"])
    metric = _metric_pills("m_hold")
    _render_cards(slices["hold_duration"], key_col="hold_bucket")
    _bar_chart(
        slices["hold_duration"], key_col="hold_bucket", metric_key=metric,
    )
    with st.expander(_t("expand_full_table")):
        st.dataframe(
            _format_slice_table(slices["hold_duration"]),
            use_container_width=True, hide_index=True,
        )


with tab_side:
    _panel_header(_t("tab_side"), slices["side"])
    metric = _metric_pills("m_side")
    _render_cards(
        slices["side"], key_col="side", key_label_fn=lambda s: str(s).upper(),
    )
    _bar_chart(
        slices["side"], key_col="side", metric_key=metric,
        key_label_fn=lambda s: str(s).upper(),
    )
    with st.expander(_t("expand_full_table")):
        st.dataframe(
            _format_slice_table(slices["side"]),
            use_container_width=True, hide_index=True,
        )


with tab_symbol:
    _panel_header(_t("tab_symbol"), slices["symbol"])
    metric = _metric_pills("m_symbol")
    _render_cards(slices["symbol"], key_col="symbol")
    _bar_chart(slices["symbol"], key_col="symbol", metric_key=metric)
    with st.expander(_t("expand_full_table")):
        st.dataframe(
            _format_slice_table(slices["symbol"]),
            use_container_width=True, hide_index=True,
        )


with tab_regime:
    regime_df = slices.get("regime")
    if regime_df is None or regime_df.empty:
        st.caption(_t("tab_regime_unavail"))
    else:
        _panel_header(_t("tab_btc_regime"), regime_df)
        metric = _metric_pills("m_regime")
        st.caption(_t("tab_regime_caption"))
        _render_cards(
            regime_df, key_col="regime",
            key_label_fn=lambda v: str(v).upper(),
        )
        _bar_chart(
            regime_df, key_col="regime", metric_key=metric,
            sort_by_key=True,
            key_label_fn=lambda v: str(v).upper(),
        )
        with st.expander(_t("expand_full_table")):
            st.dataframe(
                _format_slice_table(regime_df),
                use_container_width=True, hide_index=True,
            )


st.divider()


# --------------------------------------------------------------------------- #
# Peer Benchmark (Wave 2) — zero-input vs top SoDEX traders
# --------------------------------------------------------------------------- #

_render_cohort_benchmark(overall, slices, trades)


# --------------------------------------------------------------------------- #
# Risk Filters (Wave 2 · Sprint 2) — 2D anti-pattern detector
# --------------------------------------------------------------------------- #

st.markdown('<div id="sec-risk" class="ew-anchor"></div>', unsafe_allow_html=True)
with st.expander(_t("exp_risk"), expanded=False):
    _render_risk_filters(trades)


# --------------------------------------------------------------------------- #
# Smart Money Watch — live snapshot of top active SoDEX winners' positions.
# Zero-input, cached 15 min. The setup for divergence alerts builds on this.
# --------------------------------------------------------------------------- #

with st.spinner(_t("sm_loading")):
    # Reuse the Trade Check's cached consensus so the leaderboard + position
    # fetches happen once per 15 min for the whole page.
    _smart_money = _tc_consensus if isinstance(_tc_consensus, dict) else _consensus_cached()

# Your positions vs Smart Money — only when a real wallet is loaded.
_active_addr_for_open = (st.session_state.get("active_address") or "").strip()
if _active_addr_for_open:
    with st.spinner(_t("up_loading")):
        try:
            _your_open = _fetch_user_open_positions(_active_addr_for_open)
        except Exception:  # noqa: BLE001
            _your_open = []
    _render_user_positions_vs_smart_money(
        _your_open, _smart_money.get("consensus_per_symbol", {}) or {}
    )

_render_smart_money_watch(_smart_money)

# Etapa D — historical evidence: how the trader's past entries fared against
# the reconstructed smart-money book. Only meaningful with a real wallet.
if _active_addr_for_open:
    _render_contrarian_track_record(trades, _smart_money, _active_addr_for_open)

# --------------------------------------------------------------------------- #
# Full Diagnostic — single AI-powered consolidated analysis. Replaces the old
# "Pre-Session Briefing" + "Ask Edgework" sections with one canonical CTA.
# --------------------------------------------------------------------------- #

st.markdown(
    f"""
    <div class="ew-section">
        <div class="ew-section-title ew-anchor" id="sec-diagnostic">{_t("sec_diagnostic")}</div>
        <div class="ew-section-sub">{_t("sec_diagnostic_sub")}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

_diag_run = st.button(
    _t("btn_diagnostic"),
    type="primary",
    use_container_width=False,
    key="diag_run_btn",
)

if _diag_run:
    _s = get_settings()
    if not _s.anthropic_api_key:
        st.warning(
            "**Anthropic API key not configured.** Add it in one of:\n\n"
            "- **Streamlit Cloud:** *Manage app → Settings → Secrets* and paste:\n"
            "  ```\n"
            "  ANTHROPIC_API_KEY = \"sk-ant-...\"\n"
            "  ```\n"
            "- **Local:** same key in your `.env` file.\n\n"
            "The dashboard above works without it."
        )
    else:
        # Cache by dataset signature so re-clicks on the same data cost nothing.
        _dataset_key = f"{len(trades)}_{int(trades['pnl'].sum())}"

        @st.cache_data(ttl=3600, show_spinner=False)
        def _cached_diagnostic(dataset_key: str, lang: str):
            from edgework import qna as _qna
            return _qna.full_diagnostic(trades, slices, lang=lang)

        try:
            with st.spinner(_t("diag_running")):
                _answer, _trace, _usage = _cached_diagnostic(_dataset_key, _current_lang())

            # Header bar above the rendered markdown.
            st.markdown(
                f"""
                <div class="ew-qna-answer">
                    <div class="ew-qna-question">
                        <span class="prompt">›</span> {_t("diag_header")}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.container(border=False):
                st.markdown(_answer)

            # ── Cost strip: dev-only. Pass ?debug=1 in the URL to reveal.
            _debug_mode = str(
                st.query_params.get("debug", "")
            ).lower() in ("1", "true", "yes", "on")

            if _debug_mode:
                _input_tokens = (
                    _usage.get("input_tokens", 0)
                    + _usage.get("cache_creation_input", 0)
                    + _usage.get("cache_read_input", 0)
                )
                _output_tokens = _usage.get("output_tokens", 0)
                _calls         = _usage.get("api_calls", 0)
                _cached        = _usage.get("cache_read_input", 0)
                # Sonnet 4.6 pricing: $3/MTok in, $15/MTok out, $3.75 cache
                # write, $0.30 cache read.
                _est_cost = (
                    (_usage.get("input_tokens", 0)           * 3.0
                     + _usage.get("cache_creation_input", 0) * 3.75
                     + _usage.get("cache_read_input", 0)     * 0.30
                     + _output_tokens                        * 15.0)
                    / 1_000_000
                )
                st.markdown(
                    f"""
                    <div class="ew-qna-cost">
                        <span class="k">API USAGE · DEBUG</span>
                        <span>{_calls} call{'s' if _calls != 1 else ''}</span>
                        ·
                        <span>{_input_tokens:,} in / {_output_tokens:,} out tokens</span>
                        ·
                        <span>{_cached:,} cached</span>
                        ·
                        <span class="cost">≈ ${_est_cost:.4f}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            # ── Audit trail — polished, user-facing.
            if _trace:
                with st.expander(
                    f"Data sources · how we computed this  ({len(_trace)} step"
                    f"{'s' if len(_trace) > 1 else ''})",
                    expanded=False,
                ):
                    n_trades_total = len(trades)
                    for i, t in enumerate(_trace, 1):
                        st.markdown(_describe_tool_step(i, t, n_trades_total))
        except Exception as e:  # noqa: BLE001
            st.error(f"Diagnostic failed: {e}")


# Bottombar — matches Dashboard.html design footer.
_active_addr = st.session_state.get("active_address")
_wallet_display = (
    f"{_active_addr[:6]}…{_active_addr[-4:]}" if _active_addr else "DEMO"
)
st.markdown(
    f"""
    <div class="ew-bottombar">
        <div class="left">
            <span>// {_t("bb_wallet")} <span class="v">{_wallet_display}</span></span>
            <span>// {_t("bb_readonly")}</span>
        </div>
        <div class="right">
            <span><span class="k">{_t("bb_build")}</span><span class="v">1.0.0-rc.4</span></span>
            <span><span class="k">{_t("bb_built_by")}</span><span class="v">@nftradercrypto</span></span>
            <span><a href="https://github.com/nftradercrypto/edgework" target="_blank">GITHUB ↗</a></span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Persist slicer + wallet state in the URL — runs once at the end of every
# script execution so the URL is always a bookmarkable snapshot of the view.
# --------------------------------------------------------------------------- #
_sync_state_to_url()
