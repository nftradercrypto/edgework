"""Filter normalization in the AI tool layer.

The hold-duration bucket labels use en-dash ("5–30m") because pd.cut
produces them that way. The model routinely sends a plain hyphen
("5-30m"). Without dash-folding the filter silently matches nothing and
the diagnostic reasons over missing data.
"""
from __future__ import annotations

import sys
import types

import pandas as pd
import pytest

# qna imports anthropic + pydantic_settings at module level; neither is
# needed for the filter functions under test. Stub them so the test runs
# in a minimal environment.
if "pydantic_settings" not in sys.modules:
    fake_ps = types.ModuleType("pydantic_settings")

    class _BS:  # noqa: D401
        def __init__(self, **kw):
            pass

    fake_ps.BaseSettings = _BS
    fake_ps.SettingsConfigDict = dict
    sys.modules["pydantic_settings"] = fake_ps

if "anthropic" not in sys.modules:
    fake_an = types.ModuleType("anthropic")
    fake_an.Anthropic = object
    sys.modules["anthropic"] = fake_an

from edgework.qna import _apply_filters, _norm_label  # noqa: E402


def test_norm_label_folds_dash_variants():
    assert _norm_label("5–30m") == _norm_label("5-30m")          # en-dash
    assert _norm_label("5—30m") == _norm_label("5-30m")          # em-dash
    assert _norm_label("5−30m") == _norm_label("5-30m")          # minus sign
    assert _norm_label(" 5–30M ") == _norm_label("5-30m")        # space + case


@pytest.fixture
def trades_df():
    return pd.DataFrame({
        "pnl": [10.0, -5.0, 3.0, -2.0],
        "_hold_b": ["5–30m", "5–30m", ">24h", "<5m"],   # en-dash, as pd.cut emits
        "_size_q": ["Q1", "Q4", "Q2", "Q4"],
        "symbol": ["BTC-USD", "ETH-USD", "BTC-USD", "SOL-USD"],
        "side": ["long", "short", "long", "long"],
        "opened_at": pd.to_datetime(["2026-01-01T03:00:00Z"] * 4, utc=True),
    })


def test_hyphen_filter_matches_en_dash_bucket(trades_df):
    out = _apply_filters(trades_df, {"hold_bucket": "5-30m"})
    assert len(out) == 2


def test_exact_en_dash_still_matches(trades_df):
    out = _apply_filters(trades_df, {"hold_bucket": "5–30m"})
    assert len(out) == 2


def test_symbol_filter_case_insensitive(trades_df):
    out = _apply_filters(trades_df, {"symbol": "btc-usd"})
    assert len(out) == 2


def test_side_filter_case_insensitive(trades_df):
    out = _apply_filters(trades_df, {"side": "LONG"})
    assert len(out) == 3


def test_combined_filters(trades_df):
    out = _apply_filters(trades_df, {"size_quartile": "Q4", "side": "long"})
    assert len(out) == 1
    assert out.iloc[0]["symbol"] == "SOL-USD"


def test_no_filters_returns_original(trades_df):
    out = _apply_filters(trades_df, None)
    assert len(out) == len(trades_df)
