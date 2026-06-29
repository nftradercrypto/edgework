"""2D risk-pattern engine + risk-control hook detection."""
from __future__ import annotations

import numpy as np
import pandas as pd

from edgework.alerts import detect_risk_alerts
from edgework.risk import (
    compute_risk_contexts,
    match_antipatterns,
    position_open_context,
    size_quartile,
)


def _history():
    """Synthetic history where SHORT BTC-USD is a clear, well-sampled loser
    and LONG ETH-USD is a clear winner."""
    rows = []
    base = pd.Timestamp("2026-05-01T12:00:00Z")
    for i in range(40):
        rows.append({
            "opened_at": base + pd.Timedelta(hours=i),
            "closed_at": base + pd.Timedelta(hours=i, minutes=30),
            "symbol": "BTC-USD", "side": "short",
            "entry_price": 100.0, "exit_price": 101.0,
            "size": 10.0, "pnl": -50.0,            # consistent loser
        })
    for i in range(40):
        rows.append({
            "opened_at": base + pd.Timedelta(hours=i),
            "closed_at": base + pd.Timedelta(hours=i, minutes=30),
            "symbol": "ETH-USD", "side": "long",
            "entry_price": 50.0, "exit_price": 52.0,
            "size": 5.0, "pnl": +40.0,             # consistent winner
        })
    return pd.DataFrame(rows)


def test_size_quartile_edges():
    bins = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert size_quartile(0.5, bins) == "Q1"
    assert size_quartile(3.5, bins) == "Q4"
    assert size_quartile(10.0, bins) == "Q4"   # above max clamps to top
    assert size_quartile(1.0, None) is None


def test_compute_risk_contexts_ranks_loser_worst():
    ctx = compute_risk_contexts(_history(), min_n=5)
    assert ctx, "expected some 2D combos"
    worst = ctx[0]
    # the worst combo should involve the losing BTC short
    dims = dict(worst["dims"])
    assert worst["expectancy"] < 0
    assert dims.get("symbol") == "BTC-USD" or dims.get("side") == "short"


def test_match_antipatterns_only_when_both_dims_present():
    contexts = compute_risk_contexts(_history(), min_n=5)
    # A position with symbol+side matching the loser should match a pattern.
    pos_ctx = {"symbol": "BTC-USD", "side": "short"}
    matched = match_antipatterns(pos_ctx, contexts)
    assert any(
        dict(m["dims"]).get("symbol") == "BTC-USD"
        or dict(m["dims"]).get("side") == "short"
        for m in matched
    )
    # A winning-side position should not match an avoid-pattern.
    assert match_antipatterns({"symbol": "ETH-USD", "side": "long"}, contexts) == []


def test_position_open_context_derives_fields():
    df = _history()
    pos = {"symbol": "BTC-USD", "side": "short", "size": 10.0,
           "opened_at_ms": int(pd.Timestamp("2026-05-02T07:00:00Z").timestamp() * 1000)}
    ctx = position_open_context(pos, df)
    assert ctx["symbol"] == "BTC-USD" and ctx["side"] == "short"
    assert ctx["hour"] == 7 and "size" in ctx


def test_detect_risk_alerts_fires_on_losing_setup():
    df = _history()
    positions = [
        {"symbol": "BTC-USD", "side": "short", "size": 10.0, "notional": 1000},  # bad
        {"symbol": "ETH-USD", "side": "long", "size": 5.0, "notional": 500},     # good
    ]
    alerts = detect_risk_alerts(positions, df)
    symbols = {a.symbol for a in alerts}
    assert "BTC-USD" in symbols
    assert "ETH-USD" not in symbols
    btc = next(a for a in alerts if a.symbol == "BTC-USD")
    assert btc.expectancy < 0 and btc.key.startswith("risk:")


def test_detect_risk_alerts_empty_without_history():
    positions = [{"symbol": "BTC-USD", "side": "short", "size": 1, "notional": 1}]
    assert detect_risk_alerts(positions, None) == []
    assert detect_risk_alerts(positions, pd.DataFrame()) == []
