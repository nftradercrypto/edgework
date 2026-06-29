"""Divergence detection, Discord formatting, and dedupe state."""
from __future__ import annotations

from edgework.alerts import (
    AlertState,
    DivergenceAlert,
    classify_divergence,
    detect_divergences,
    format_discord,
)


def _consensus(lc, sc, ln, sn):
    return {
        "long_count": lc, "short_count": sc,
        "long_notional": ln, "short_notional": sn,
    }


# ── classify_divergence ─────────────────────────────────────────────────────

def test_strong_long_bias_user_short_is_divergence():
    pos = {"symbol": "BTC-USD", "side": "short", "notional": 1000}
    a = classify_divergence(pos, _consensus(4, 0, 100_000, 0))
    assert a is not None
    assert a.smart_side == "long" and a.user_side == "short"
    assert a.strength == "strong"


def test_aligned_position_is_not_divergence():
    pos = {"symbol": "BTC-USD", "side": "long", "notional": 1000}
    assert classify_divergence(pos, _consensus(4, 0, 100_000, 0)) is None


def test_weak_notional_bias_triggers():
    # counts tied, but long notional > 2x short → weak long bias
    pos = {"symbol": "ETH-USD", "side": "short", "notional": 500}
    a = classify_divergence(pos, _consensus(1, 1, 30_000, 10_000))
    assert a is not None and a.strength == "weak" and a.smart_side == "long"


def test_mixed_book_no_divergence():
    pos = {"symbol": "ETH-USD", "side": "short", "notional": 500}
    # counts tied, notionals within 2x → no clear bias
    assert classify_divergence(pos, _consensus(2, 2, 12_000, 10_000)) is None


def test_no_consensus_no_divergence():
    pos = {"symbol": "DOGE-USD", "side": "long", "notional": 100}
    assert classify_divergence(pos, None) is None


def test_detect_divergences_filters_to_contrarian_only():
    positions = [
        {"symbol": "BTC-USD", "side": "short", "notional": 1000},  # contrarian
        {"symbol": "ETH-USD", "side": "long", "notional": 1000},   # aligned
        {"symbol": "SOL-USD", "side": "long", "notional": 1000},   # no consensus
    ]
    consensus = {
        "BTC-USD": _consensus(5, 0, 200_000, 0),
        "ETH-USD": _consensus(5, 0, 200_000, 0),
    }
    out = detect_divergences(positions, consensus)
    assert [a.symbol for a in out] == ["BTC-USD"]


# ── Discord formatting ──────────────────────────────────────────────────────

def test_format_discord_embed_shape():
    a = DivergenceAlert(
        symbol="BTC-USD", user_side="short", user_notional=2100,
        smart_side="long", strength="strong",
        long_count=4, short_count=0, long_notional=150_000, short_notional=0,
    )
    payload = format_discord(a, wallet="0x1234567890abcdef", app_url="https://x.app")
    assert "embeds" in payload and len(payload["embeds"]) == 1
    embed = payload["embeds"][0]
    assert "BTC-USD" in embed["title"]
    assert embed["url"].endswith("w=0x1234567890abcdef")
    assert embed["color"] == 0xE53935  # strong → red


# ── dedupe state ────────────────────────────────────────────────────────────

def _alert(symbol, side):
    return DivergenceAlert(
        symbol=symbol, user_side=side, user_notional=100,
        smart_side="long" if side == "short" else "short", strength="strong",
        long_count=4, short_count=0, long_notional=1, short_notional=0,
    )


def test_state_select_new_dedupes(tmp_path):
    st = AlertState.load(tmp_path / "s.json")
    a = _alert("BTC-USD", "short")
    assert len(st.select_new([a])) == 1      # first time fires
    assert len(st.select_new([a])) == 0      # same key suppressed


def test_state_persists_and_reloads(tmp_path):
    p = tmp_path / "s.json"
    st = AlertState.load(p)
    st.select_new([_alert("BTC-USD", "short")])
    st.save()
    st2 = AlertState.load(p)
    assert "BTC-USD:short" in st2.fired
    assert len(st2.select_new([_alert("BTC-USD", "short")])) == 0


def test_state_prune_reopens_alert(tmp_path):
    p = tmp_path / "s.json"
    st = AlertState.load(p)
    st.select_new([_alert("BTC-USD", "short")])
    st.prune(set())                          # position closed → forget it
    assert len(st.select_new([_alert("BTC-USD", "short")])) == 1  # re-alerts
