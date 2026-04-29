"""Conditional Performance Mapping.

Given a normalized DataFrame of closed trades, compute winrate, expectancy,
and time-in-trade across every dimension a trader doesn't normally see.

This is the heart of Edgework. The output of `slice_all()` is what feeds
the Streamlit dashboard and the AI Briefing prompt.

Schema of the input `trades` DataFrame:
    - opened_at      : datetime64[ns, UTC]
    - closed_at      : datetime64[ns, UTC]
    - symbol         : str   (e.g. "BTC-USD")
    - side           : str   ("long" | "short")
    - entry_price    : float
    - exit_price     : float
    - size           : float (notional in USD)
    - pnl            : float (realized PNL, fees included)
    - leverage       : float (optional)

Anything else is enriched downstream (regime, news sentiment, etc).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #

REQUIRED_COLS = [
    "opened_at",
    "closed_at",
    "symbol",
    "side",
    "entry_price",
    "exit_price",
    "size",
    "pnl",
]


def normalize_orders(raw_orders: list[dict]) -> pd.DataFrame:
    """Best-effort normalize raw SoDEX order/fill dicts into the slicer schema.

    SoDEX's exact schema may vary; this function is intentionally tolerant.
    Any field it can't infer is set to NaN — the slicer skips slices that
    would be all-NaN.
    """
    if not raw_orders:
        return pd.DataFrame(columns=REQUIRED_COLS)

    df = pd.DataFrame(raw_orders)

    # Map common alternate names.
    rename_map = {
        "openTime": "opened_at",
        "createTime": "opened_at",
        "closeTime": "closed_at",
        "updateTime": "closed_at",
        "avgPrice": "entry_price",
        "price": "entry_price",
        "closePrice": "exit_price",
        "qty": "size",
        "quantity": "size",
        "realizedPnl": "pnl",
        "realizedProfit": "pnl",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Coerce timestamps (assume ms epoch if int).
    for col in ("opened_at", "closed_at"):
        if col not in df.columns:
            df[col] = pd.NaT
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = pd.to_datetime(df[col], unit="ms", utc=True)
        else:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    # Side normalization.
    if "side" in df.columns:
        df["side"] = df["side"].astype(str).str.lower().str.replace("buy", "long").str.replace(
            "sell", "short"
        )
    else:
        df["side"] = np.nan

    # Numeric coercion.
    for col in ("entry_price", "exit_price", "size", "pnl", "leverage"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif col != "leverage":
            df[col] = np.nan

    # Drop trades with no PNL — they're open positions or failed entries.
    df = df.dropna(subset=["pnl", "closed_at"]).reset_index(drop=True)

    # Ensure all required columns exist.
    for col in REQUIRED_COLS:
        if col not in df.columns:
            df[col] = np.nan

    return df[REQUIRED_COLS + (["leverage"] if "leverage" in df.columns else [])]


# --------------------------------------------------------------------------- #
# Slice computation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SliceStats:
    """Summary stats for a single slice of trades."""

    n_trades: int
    winrate: float          # 0.0 – 1.0
    avg_pnl: float          # mean realized PNL per trade
    expectancy: float       # avg_win * winrate - avg_loss * (1 - winrate)
    total_pnl: float
    avg_hold_minutes: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "n_trades": self.n_trades,
            "winrate": round(self.winrate, 4),
            "avg_pnl": round(self.avg_pnl, 4),
            "expectancy": round(self.expectancy, 4),
            "total_pnl": round(self.total_pnl, 2),
            "avg_hold_minutes": round(self.avg_hold_minutes, 1),
        }


def _stats(group: pd.DataFrame) -> SliceStats:
    """Compute SliceStats for a sub-DataFrame of trades."""
    n = len(group)
    if n == 0:
        return SliceStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)

    pnl = group["pnl"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]

    winrate = len(wins) / n
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = abs(losses.mean()) if len(losses) else 0.0
    expectancy = avg_win * winrate - avg_loss * (1 - winrate)

    hold = (group["closed_at"] - group["opened_at"]).dt.total_seconds() / 60.0
    avg_hold = hold.mean() if len(hold) else 0.0

    return SliceStats(
        n_trades=n,
        winrate=winrate,
        avg_pnl=pnl.mean(),
        expectancy=expectancy,
        total_pnl=pnl.sum(),
        avg_hold_minutes=avg_hold,
    )


# --------------------------------------------------------------------------- #
# Dimensions
# --------------------------------------------------------------------------- #


def by_hour_of_day(trades: pd.DataFrame) -> pd.DataFrame:
    """Slice by hour the trade was opened (UTC)."""
    df = trades.copy()
    df["hour"] = df["opened_at"].dt.hour
    return _aggregate(df, "hour")


def by_day_of_week(trades: pd.DataFrame) -> pd.DataFrame:
    """Slice by day of week (0 = Monday)."""
    df = trades.copy()
    df["dow"] = df["opened_at"].dt.dayofweek
    return _aggregate(df, "dow")


def by_side(trades: pd.DataFrame) -> pd.DataFrame:
    """Slice by long vs short."""
    return _aggregate(trades, "side")


def by_symbol(trades: pd.DataFrame) -> pd.DataFrame:
    """Slice by trading pair."""
    return _aggregate(trades, "symbol")


def by_consecutive_losses(trades: pd.DataFrame) -> pd.DataFrame:
    """Slice by how many consecutive losses preceded each trade.

    This is the 'revenge trading' detector: traders typically have very
    different stats on the trade right after 2+ losses than on a fresh trade.
    """
    df = trades.sort_values("opened_at").reset_index(drop=True).copy()
    streak: list[int] = []
    current = 0
    for pnl in df["pnl"]:
        streak.append(current)
        current = current + 1 if pnl <= 0 else 0
    df["consec_losses_before"] = streak
    df["streak_bucket"] = pd.cut(
        df["consec_losses_before"],
        bins=[-1, 0, 1, 2, 3, 100],
        labels=["fresh", "1L", "2L", "3L", "4L+"],
    )
    return _aggregate(df, "streak_bucket")


def by_size_quartile(trades: pd.DataFrame) -> pd.DataFrame:
    """Slice by position size relative to your own distribution.

    Bucketing by quartile (Q1 = smallest 25%, Q4 = largest 25%) reveals
    if you actually make money on your big bets or only on the small ones.
    """
    df = trades.copy()
    df["size_quartile"] = pd.qcut(df["size"], q=4, labels=["Q1", "Q2", "Q3", "Q4"])
    return _aggregate(df, "size_quartile")


def by_hold_duration(trades: pd.DataFrame) -> pd.DataFrame:
    """Slice by how long you held the trade."""
    df = trades.copy()
    hold_min = (df["closed_at"] - df["opened_at"]).dt.total_seconds() / 60.0
    df["hold_bucket"] = pd.cut(
        hold_min,
        bins=[-1, 5, 30, 120, 480, 1_440, 1e9],
        labels=["<5m", "5–30m", "30m–2h", "2–8h", "8–24h", ">24h"],
    )
    return _aggregate(df, "hold_bucket")


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _aggregate(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Group `df` by `by` and compute SliceStats per group."""
    if df.empty or by not in df.columns:
        return pd.DataFrame()
    rows = []
    for key, sub in df.groupby(by, observed=True, dropna=False):
        s = _stats(sub).as_dict()
        s[by] = key
        rows.append(s)
    out = pd.DataFrame(rows)
    cols = [by] + [c for c in out.columns if c != by]
    return out[cols].sort_values(by).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Top-level
# --------------------------------------------------------------------------- #


def slice_all(trades: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Run every dimension. Returns a dict of slice-name → DataFrame.

    This is what the Streamlit app calls once and renders into multiple
    charts, and what the AI Briefing summarizes into a paragraph.
    """
    return {
        "hour_of_day": by_hour_of_day(trades),
        "day_of_week": by_day_of_week(trades),
        "side": by_side(trades),
        "symbol": by_symbol(trades),
        "consecutive_losses": by_consecutive_losses(trades),
        "size_quartile": by_size_quartile(trades),
        "hold_duration": by_hold_duration(trades),
    }


def overall(trades: pd.DataFrame) -> SliceStats:
    """Single-line summary across all trades (the headline number)."""
    return _stats(trades)
