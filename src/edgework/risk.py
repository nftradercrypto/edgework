"""2D risk-pattern detection — the engine behind the in-app risk filter and
the Wave 3 risk-control hook.

Crosses every pair of dimensions on a trader's history and ranks the
combinations by expectancy (worst first). The "avoid" patterns (negative
expectancy, enough sample) are the ones the risk-control hook fires on when a
newly-opened position matches one of them.

Self-contained: derives its dimension columns (hour, day, side, symbol, size
quartile) directly from a normalized trades DataFrame, so the standalone alert
poller can use it without the Streamlit app's bucket-column helpers.
"""
from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

# Dimensions evaluable both historically AND for a live open position.
# (streak / hold / regime are richer app-only dims; omitted here so an open
# position can actually be matched against every context this produces.)
_DEFAULT_DIMS = ("hour", "day", "side", "symbol", "size")

_SIZE_LABELS = ["Q1", "Q2", "Q3", "Q4"]


def _size_bins(trades_df: pd.DataFrame) -> list[float] | None:
    """Quartile edges of the size distribution, for placing a new position."""
    if "size" not in trades_df.columns:
        return None
    s = pd.to_numeric(trades_df["size"], errors="coerce").dropna()
    if s.empty:
        return None
    try:
        edges = list(np.quantile(s, [0.0, 0.25, 0.5, 0.75, 1.0]))
    except (ValueError, IndexError):
        return None
    return edges


def size_quartile(size: float, bins: list[float] | None) -> str | None:
    """Which quartile label a given size falls into, given the history bins."""
    if bins is None or size is None:
        return None
    for i in range(4):
        lo, hi = bins[i], bins[i + 1]
        if size <= hi or i == 3:
            if size >= lo or i == 0:
                return _SIZE_LABELS[i]
    return _SIZE_LABELS[-1]


def _dim_columns(trades_df: pd.DataFrame, dims: tuple[str, ...]) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    if "opened_at" in trades_df.columns:
        try:
            if "hour" in dims:
                out["hour"] = trades_df["opened_at"].dt.hour.astype("Int64")
            if "day" in dims:
                out["day"] = trades_df["opened_at"].dt.dayofweek.astype("Int64")
        except Exception:  # noqa: BLE001
            pass
    if "side" in dims and "side" in trades_df.columns:
        out["side"] = trades_df["side"].astype(str).str.lower()
    if "symbol" in dims and "symbol" in trades_df.columns:
        out["symbol"] = trades_df["symbol"].astype(str)
    if "size" in dims and "size" in trades_df.columns:
        bins = _size_bins(trades_df)
        if bins is not None:
            out["size"] = trades_df["size"].map(lambda x: size_quartile(float(x), bins)
                                                if pd.notna(x) else None)
    return out


def compute_risk_contexts(
    trades_df: pd.DataFrame,
    min_n: int = 5,
    dims: tuple[str, ...] = _DEFAULT_DIMS,
) -> list[dict[str, Any]]:
    """All 2D dimension combos ranked worst-expectancy first.

    Each: ``{"dims": ((dim_a, val_a), (dim_b, val_b)), "n", "wr",
    "expectancy", "total_pnl", "avg_pnl"}``. Same expectancy formula as the
    slicer: ``avg_win*wr - avg_loss_mag*(1-wr)``.
    """
    if trades_df is None or trades_df.empty or "pnl" not in trades_df.columns:
        return []
    dim_cols = _dim_columns(trades_df, dims)
    names = list(dim_cols.keys())
    if len(names) < 2:
        return []

    pnl_series = trades_df["pnl"]
    results: list[dict] = []
    for a, b in combinations(names, 2):
        tmp = pd.DataFrame({"_a": dim_cols[a], "_b": dim_cols[b], "_pnl": pnl_series})
        tmp = tmp.dropna(subset=["_a", "_b", "_pnl"])
        if tmp.empty:
            continue
        for (val_a, val_b), grp in tmp.groupby(["_a", "_b"]):
            pnl = grp["_pnl"]
            n = len(pnl)
            if n < min_n:
                continue
            wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
            wr = len(wins) / n
            avg_win = float(wins.mean()) if len(wins) else 0.0
            avg_loss_mag = abs(float(losses.mean())) if len(losses) else 0.0
            results.append({
                "dims": ((a, val_a), (b, val_b)),
                "n": n, "wr": wr,
                "expectancy": avg_win * wr - avg_loss_mag * (1 - wr),
                "total_pnl": float(pnl.sum()), "avg_pnl": float(pnl.mean()),
            })
    results.sort(key=lambda x: x["expectancy"])
    return results


def position_open_context(
    position: dict,
    trades_df: pd.DataFrame,
    *,
    regime: str | None = None,
) -> dict[str, Any]:
    """Derive the evaluable attributes of a live open position.

    Always: side, symbol. Plus size quartile (vs history) and hour/day when
    the position carries an open timestamp (``opened_at_ms``). Returns a dict
    of {dim: value} usable by match_antipatterns.
    """
    ctx: dict[str, Any] = {}
    side = str(position.get("side", "")).lower()
    if side in ("long", "short"):
        ctx["side"] = side
    if position.get("symbol"):
        ctx["symbol"] = str(position["symbol"])

    bins = _size_bins(trades_df)
    size = position.get("size")
    if size is not None and bins is not None:
        q = size_quartile(float(size), bins)
        if q:
            ctx["size"] = q

    o_ms = position.get("opened_at_ms")
    if o_ms:
        try:
            ts = pd.Timestamp(int(o_ms), unit="ms", tz="UTC")
            ctx["hour"] = int(ts.hour)
            ctx["day"] = int(ts.dayofweek)
        except (ValueError, TypeError, OSError):
            pass

    if regime:
        ctx["regime"] = str(regime)
    return ctx


def match_antipatterns(
    pos_ctx: dict[str, Any],
    contexts: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Avoid-patterns (expectancy < 0) whose BOTH dims match the position.

    A context only matches if every one of its two dimensions is present in
    pos_ctx and equal — so we never fire on a dimension we couldn't evaluate.
    Worst expectancy first, capped at ``limit``.
    """
    matched: list[dict] = []
    for c in contexts:
        if c["expectancy"] >= 0:
            continue
        ok = True
        for dim, val in c["dims"]:
            have = pos_ctx.get(dim)
            if have is None or str(have) != str(val):
                ok = False
                break
        if ok:
            matched.append(c)
    matched.sort(key=lambda x: x["expectancy"])
    return matched[:limit]
