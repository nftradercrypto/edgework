"""AI Briefing layer.

Composes a single-paragraph pre-session briefing that combines:
- the trader's own conditional edge (from `slicer`)
- today's market regime (SoSoValue indexes, ETF flows, news sentiment)

Output is intentionally NOT a dashboard. It's a paragraph the trader
can read in 30 seconds. The whole point of Edgework is condensing
conditional intelligence into actionable language, not adding another
panel to look at.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from anthropic import Anthropic

from .config import get_settings
from .slicer import SliceStats


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


@dataclass
class TraderEdge:
    """The minimal slice of trader history needed for a briefing.

    We don't shove every slice into the prompt — we extract the most
    actionable signals (best/worst hour, streak penalty, side bias) so the
    prompt stays tight and the LLM stays focused.
    """

    overall: SliceStats
    best_hour_utc: int | None
    worst_hour_utc: int | None
    best_hour_expectancy: float | None
    worst_hour_expectancy: float | None
    side_bias: str | None       # "long" if longs work better, else "short"
    revenge_penalty: float | None  # expectancy difference: fresh - after 2L
    favorite_symbol: str | None


@dataclass
class MarketContext:
    """Today's market regime snapshot (compact)."""

    btc_dominance: float | None
    btc_etf_net_flow_usd: float | None     # latest daily ETF net flow
    eth_etf_net_flow_usd: float | None
    top_sector_24h: str | None              # leading sector by 24h return
    bottom_sector_24h: str | None
    news_sentiment: str | None              # "bullish" | "bearish" | "mixed"
    notable_news: list[str] | None          # 1–3 headlines
    btc_regime: str | None                  # "uptrend" | "downtrend" | "chop"


# --------------------------------------------------------------------------- #
# Edge extraction from slicer output
# --------------------------------------------------------------------------- #


def extract_trader_edge(
    overall: SliceStats,
    slices: dict[str, pd.DataFrame],
) -> TraderEdge:
    """Distill the slicer output down to the few facts the briefing needs."""

    best_h = worst_h = None
    best_e = worst_e = None
    hod = slices.get("hour_of_day")
    if hod is not None and not hod.empty and "expectancy" in hod.columns:
        # only consider hours with at least 5 trades, so we don't anchor
        # on noisy single-trade slices
        signal = hod[hod["n_trades"] >= 5]
        if not signal.empty:
            best_row = signal.loc[signal["expectancy"].idxmax()]
            worst_row = signal.loc[signal["expectancy"].idxmin()]
            best_h = int(best_row["hour"])
            worst_h = int(worst_row["hour"])
            best_e = float(best_row["expectancy"])
            worst_e = float(worst_row["expectancy"])

    side_bias = None
    side_df = slices.get("side")
    if side_df is not None and not side_df.empty and "expectancy" in side_df.columns:
        ranked = side_df.sort_values("expectancy", ascending=False)
        if len(ranked) >= 1:
            top = ranked.iloc[0]
            if pd.notna(top["side"]):
                side_bias = str(top["side"])

    revenge = None
    streak_df = slices.get("consecutive_losses")
    if streak_df is not None and not streak_df.empty:
        try:
            fresh = streak_df.loc[streak_df["streak_bucket"] == "fresh", "expectancy"].iloc[0]
            after_2l = streak_df.loc[streak_df["streak_bucket"] == "2L", "expectancy"].iloc[0]
            revenge = float(fresh - after_2l)
        except (IndexError, KeyError):
            pass

    fav_symbol = None
    sym_df = slices.get("symbol")
    if sym_df is not None and not sym_df.empty:
        signal = sym_df[sym_df["n_trades"] >= 5]
        if not signal.empty:
            fav_symbol = str(signal.loc[signal["total_pnl"].idxmax(), "symbol"])

    return TraderEdge(
        overall=overall,
        best_hour_utc=best_h,
        worst_hour_utc=worst_h,
        best_hour_expectancy=best_e,
        worst_hour_expectancy=worst_e,
        side_bias=side_bias,
        revenge_penalty=revenge,
        favorite_symbol=fav_symbol,
    )


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #


SYSTEM_PROMPT = """You are Edgework's pre-session briefing engine.

Your job: write one tight paragraph (90–140 words) that helps a serious \
perpetuals trader decide whether today is a day to size up, size down, \
or stay flat.

Rules:
- Refer to the trader as "you", direct second person.
- Combine THEIR historical edge with TODAY's market regime. Both matter.
- Be specific: cite the trader's worst hour, side bias, or revenge \
penalty when relevant. Cite ETF flow direction or sector rotation when \
relevant. Don't list everything — pick what matters today.
- No hype, no emojis, no "as an AI". Trader-to-trader voice.
- End with one concrete instruction (e.g., "Avoid shorts before 14:00 \
UTC", "Skip leveraged BTC longs today", "Half size until 16:00").
- Never invent stats. If you don't have data for something, omit it."""


def _build_user_prompt(edge: TraderEdge, market: MarketContext) -> str:
    """Compose the user-facing prompt for the briefing model."""
    o = edge.overall
    lines: list[str] = []

    lines.append("TRADER EDGE PROFILE")
    lines.append(
        f"- Overall: {o.n_trades} closed trades, "
        f"winrate {o.winrate:.1%}, expectancy ${o.expectancy:.2f}, "
        f"avg hold {o.avg_hold_minutes:.0f} min"
    )
    if edge.best_hour_utc is not None and edge.best_hour_expectancy is not None:
        lines.append(
            f"- Best hour (UTC): {edge.best_hour_utc:02d}:00 "
            f"(expectancy ${edge.best_hour_expectancy:.2f})"
        )
    if edge.worst_hour_utc is not None and edge.worst_hour_expectancy is not None:
        lines.append(
            f"- Worst hour (UTC): {edge.worst_hour_utc:02d}:00 "
            f"(expectancy ${edge.worst_hour_expectancy:.2f})"
        )
    if edge.side_bias:
        lines.append(f"- Side bias: {edge.side_bias}s perform better")
    if edge.revenge_penalty is not None:
        lines.append(
            f"- Revenge-trading penalty: expectancy drops "
            f"${edge.revenge_penalty:.2f} after 2 consecutive losses"
        )
    if edge.favorite_symbol:
        lines.append(f"- Best symbol by total PNL: {edge.favorite_symbol}")

    lines.append("")
    lines.append("TODAY'S MARKET REGIME")
    if market.btc_regime:
        lines.append(f"- BTC regime: {market.btc_regime}")
    if market.btc_dominance is not None:
        lines.append(f"- BTC dominance: {market.btc_dominance:.2f}%")
    if market.btc_etf_net_flow_usd is not None:
        lines.append(
            f"- BTC ETF net flow (latest day): "
            f"${market.btc_etf_net_flow_usd / 1e6:+.1f}M"
        )
    if market.eth_etf_net_flow_usd is not None:
        lines.append(
            f"- ETH ETF net flow (latest day): "
            f"${market.eth_etf_net_flow_usd / 1e6:+.1f}M"
        )
    if market.top_sector_24h:
        lines.append(f"- Leading sector 24h: {market.top_sector_24h}")
    if market.bottom_sector_24h:
        lines.append(f"- Lagging sector 24h: {market.bottom_sector_24h}")
    if market.news_sentiment:
        lines.append(f"- News sentiment: {market.news_sentiment}")
    if market.notable_news:
        lines.append("- Notable headlines:")
        for h in market.notable_news[:3]:
            lines.append(f"  • {h}")

    lines.append("")
    lines.append(
        f"Now: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
        "Write the briefing paragraph."
    )

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Generator
# --------------------------------------------------------------------------- #


def generate_briefing(
    edge: TraderEdge,
    market: MarketContext,
    *,
    client: Anthropic | None = None,
    model: str | None = None,
    max_tokens: int = 400,
) -> str:
    """Generate a pre-session briefing paragraph.

    Returns the paragraph text. On API failure, raises — let the caller
    decide whether to fall back to a static template.
    """
    s = get_settings()
    client = client or Anthropic(api_key=s.anthropic_api_key)
    model = model or s.anthropic_model

    user_prompt = _build_user_prompt(edge, market)

    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()


def build_market_context_from_sosovalue(client: Any) -> MarketContext:
    """Best-effort assemble a MarketContext from a live SoSoValueClient.

    Tolerant to partial data — any field the API doesn't return stays None.
    """
    btc_etf = eth_etf = None
    try:
        btc_etf = float(
            (client.get_etf_flows("btc") or {}).get("dailyNetInflow") or 0
        ) or None
    except Exception:  # noqa: BLE001 — partial data is OK
        pass
    try:
        eth_etf = float(
            (client.get_etf_flows("eth") or {}).get("dailyNetInflow") or 0
        ) or None
    except Exception:  # noqa: BLE001
        pass

    top_sec = bottom_sec = None
    try:
        sectors = client.get_sectors() or []
        if sectors:
            sectors_sorted = sorted(
                sectors, key=lambda s: s.get("change24h", 0) or 0, reverse=True
            )
            top_sec = sectors_sorted[0].get("name")
            bottom_sec = sectors_sorted[-1].get("name")
    except Exception:  # noqa: BLE001
        pass

    headlines: list[str] = []
    sentiment = None
    try:
        news = client.get_news(limit=10) or []
        sentiments = [n.get("sentiment", "").lower() for n in news if n.get("sentiment")]
        if sentiments:
            bull = sum(1 for s in sentiments if "bull" in s or "positive" in s)
            bear = sum(1 for s in sentiments if "bear" in s or "negative" in s)
            if bull > bear * 1.5:
                sentiment = "bullish"
            elif bear > bull * 1.5:
                sentiment = "bearish"
            else:
                sentiment = "mixed"
        headlines = [n.get("title", "") for n in news[:3] if n.get("title")]
    except Exception:  # noqa: BLE001
        pass

    return MarketContext(
        btc_dominance=None,
        btc_etf_net_flow_usd=btc_etf,
        eth_etf_net_flow_usd=eth_etf,
        top_sector_24h=top_sec,
        bottom_sector_24h=bottom_sec,
        news_sentiment=sentiment,
        notable_news=headlines or None,
        btc_regime=None,
    )
