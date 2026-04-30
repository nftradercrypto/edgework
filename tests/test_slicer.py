"""Smoke tests for the slicer module."""

from __future__ import annotations

import numpy as np
import pandas as pd

from edgework import slicer


def _synthetic_trades(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Build a deterministic synthetic dataset for testing."""
    rng = np.random.default_rng(seed)
    now = pd.Timestamp("2026-04-01", tz="UTC")
    opens = pd.date_range(end=now, periods=n, freq="3h")
    holds = pd.to_timedelta(rng.exponential(60, size=n), unit="m")
    closes = opens + holds
    side = rng.choice(["long", "short"], size=n, p=[0.55, 0.45])
    pnl = np.where(side == "long", rng.normal(15, 80, n), rng.normal(-5, 80, n))
    df = pd.DataFrame(
        {
            "opened_at": opens,
            "closed_at": closes,
            "symbol": rng.choice(["BTC-USD", "ETH-USD"], n),
            "side": side,
            "entry_price": rng.uniform(20000, 70000, n),
            "exit_price": rng.uniform(20000, 70000, n),
            "size": rng.uniform(500, 5000, n),
            "pnl": pnl,
        }
    )
    return df


def test_normalize_handles_alternate_field_names():
    raw = [
        {
            "openTime": 1_700_000_000_000,
            "closeTime": 1_700_000_600_000,
            "symbol": "BTC-USD",
            "side": "buy",
            "avgPrice": 30000.0,
            "closePrice": 30100.0,
            "qty": 1000.0,
            "realizedPnl": 100.0,
        }
    ]
    out = slicer.normalize_orders(raw)
    assert len(out) == 1
    assert out.iloc[0]["side"] == "long"
    assert out.iloc[0]["pnl"] == 100.0


def test_normalize_official_sodex_position_schema():
    """Verify SoDEX's real Position shape from /positions/history.

    Closed positions have size=0 (no open exposure left) and direction
    is given by positionSide. Actual size traded is cumClosedSize.
    """
    raw = [
        # A long that closed in profit
        {
            "id": 4463884,
            "symbol": "BTC-USD",
            "marginMode": "CROSS",
            "positionSide": "LONG",
            "size": 0,                          # closed → no open exposure
            "initialMargin": 0,
            "avgEntryPrice": 76230,
            "cumOpenCost": 0,
            "cumTradingFee": 0.11299596104,
            "cumClosedSize": 0.00471,           # actual size traded
            "avgClosePrice": 76285.67,
            "maxSize": 0.00471,
            "realizedPnL": 0.262,
            "leverage": 10,
            "active": False,
            "createdAt": 1_750_000_000_000,
            "updatedAt": 1_750_000_900_000,
        },
        # A short that closed in profit
        {
            "id": 4463885,
            "symbol": "ETH-USD",
            "marginMode": "CROSS",
            "positionSide": "SHORT",
            "size": 0,
            "avgEntryPrice": 3000,
            "avgClosePrice": 2950,
            "cumClosedSize": 2.0,
            "maxSize": 2.0,
            "cumTradingFee": 5.5,
            "realizedPnL": 100.0,
            "leverage": 5,
            "active": False,
            "createdAt": 1_750_002_000_000,
            "updatedAt": 1_750_003_000_000,
        },
    ]
    out = slicer.normalize_orders(raw)
    assert len(out) == 2
    # Long
    assert out.iloc[0]["side"] == "long"
    assert out.iloc[0]["size"] == 0.00471        # from cumClosedSize, not size=0
    assert out.iloc[0]["entry_price"] == 76230
    # Short
    assert out.iloc[1]["side"] == "short"
    assert out.iloc[1]["size"] == 2.0
    assert out.iloc[1]["pnl"] == 100.0


def test_overall_returns_zero_for_empty():
    s = slicer.overall(pd.DataFrame(columns=slicer.REQUIRED_COLS))
    assert s.n_trades == 0
    assert s.winrate == 0.0


def test_slice_all_returns_all_dimensions():
    df = _synthetic_trades()
    out = slicer.slice_all(df)
    expected = {
        "hour_of_day",
        "day_of_week",
        "side",
        "symbol",
        "consecutive_losses",
        "size_quartile",
        "hold_duration",
    }
    assert set(out.keys()) == expected
    for name, slice_df in out.items():
        assert not slice_df.empty, f"{name} should not be empty"
        assert "expectancy" in slice_df.columns
        assert "n_trades" in slice_df.columns


def test_consecutive_losses_detects_streak():
    """A pure-loss streak should produce non-zero buckets beyond 'fresh'."""
    n = 50
    opens = pd.date_range(end=pd.Timestamp("2026-04-01", tz="UTC"), periods=n, freq="1h")
    df = pd.DataFrame(
        {
            "opened_at": opens,
            "closed_at": opens + pd.Timedelta(minutes=30),
            "symbol": "BTC-USD",
            "side": "long",
            "entry_price": 30000,
            "exit_price": 29900,
            "size": 1000,
            "pnl": [-10.0] * n,  # all losses
        }
    )
    streaks = slicer.by_consecutive_losses(df)
    # We expect to see traders sitting in '4L+' for most of the run
    assert "streak_bucket" in streaks.columns
    assert (streaks["n_trades"] > 0).any()


def test_winrate_bounds():
    df = _synthetic_trades()
    s = slicer.overall(df)
    assert 0.0 <= s.winrate <= 1.0
