"""Smart Money Divergence alerts (Wave 3).

The marquee Wave 3 deliverable: notify a trader the moment they open a
position that fights the qualified smart-money book. Pure logic here —
detection, Discord formatting, sending, and dedupe state. The poller
(``scripts/alert_bot.py``) wires it to a live loop; the Streamlit app uses
``classify_divergence`` for the on-screen comparison.

The bias thresholds match the in-app classifier exactly:
  - strong bias : one side outnumbers the other by >= 3 traders
  - weak bias   : one side's notional is >= 2x the other (and non-empty)
A position is a divergence when the trader sits opposite a clear bias.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Same thresholds as streamlit_app._classify_user_vs_smart_money.
STRONG_COUNT_DIFF = 3
WEAK_NOTIONAL_RATIO = 2.0


@dataclass
class DivergenceAlert:
    symbol: str
    user_side: str          # "long" | "short"
    user_notional: float
    smart_side: str         # the dominant smart-money side (opposite user_side)
    strength: str           # "strong" | "weak"
    long_count: int
    short_count: int
    long_notional: float
    short_notional: float

    @property
    def key(self) -> str:
        """Stable identity for dedupe: one alert per (symbol, side) entry."""
        return f"{self.symbol}:{self.user_side}"


def _smart_bias(cs: dict) -> tuple[str | None, str]:
    """Return (bias_side, strength) for one symbol's consensus, or (None, '')."""
    lc, sc = int(cs.get("long_count", 0)), int(cs.get("short_count", 0))
    ln, sn = float(cs.get("long_notional", 0)), float(cs.get("short_notional", 0))
    if lc - sc >= STRONG_COUNT_DIFF:
        return "long", "strong"
    if sc - lc >= STRONG_COUNT_DIFF:
        return "short", "strong"
    if ln > sn * WEAK_NOTIONAL_RATIO and lc > 0:
        return "long", "weak"
    if sn > ln * WEAK_NOTIONAL_RATIO and sc > 0:
        return "short", "weak"
    return None, ""


def classify_divergence(user_pos: dict, consensus_sym: dict | None) -> DivergenceAlert | None:
    """Return a DivergenceAlert iff the position is contrarian to a clear bias.

    Aligned, mixed, or no-consensus positions return None.
    """
    if not consensus_sym:
        return None
    bias, strength = _smart_bias(consensus_sym)
    if bias is None:
        return None
    user_side = str(user_pos.get("side", "")).lower()
    if user_side not in ("long", "short") or user_side == bias:
        return None
    return DivergenceAlert(
        symbol=user_pos["symbol"],
        user_side=user_side,
        user_notional=float(user_pos.get("notional", 0) or 0),
        smart_side=bias,
        strength=strength,
        long_count=int(consensus_sym.get("long_count", 0)),
        short_count=int(consensus_sym.get("short_count", 0)),
        long_notional=float(consensus_sym.get("long_notional", 0)),
        short_notional=float(consensus_sym.get("short_notional", 0)),
    )


def detect_divergences(
    open_positions: list[dict],
    consensus_per_symbol: dict[str, dict],
) -> list[DivergenceAlert]:
    """All contrarian positions in the current book."""
    alerts = []
    for pos in open_positions or []:
        a = classify_divergence(pos, (consensus_per_symbol or {}).get(pos.get("symbol")))
        if a is not None:
            alerts.append(a)
    return alerts


# --------------------------------------------------------------------------- #
# Discord formatting + send
# --------------------------------------------------------------------------- #

_COLOR_STRONG = 0xE53935  # red
_COLOR_WEAK = 0xF5841F    # accent orange


def _fmt_usd(x: float) -> str:
    ax = abs(x)
    if ax >= 1e6:
        return f"${ax / 1e6:.1f}M"
    if ax >= 1e3:
        return f"${ax / 1e3:.1f}k"
    return f"${ax:,.0f}"


def format_discord(alert: DivergenceAlert, *, wallet: str | None = None,
                   app_url: str | None = None) -> dict:
    """Build a Discord webhook payload (rich embed) for one divergence."""
    lc, sc = alert.long_count, alert.short_count
    ln, sn = alert.long_notional, alert.short_notional
    smart_label = (
        f"{lc} long ({_fmt_usd(ln)}) vs {sc} short ({_fmt_usd(sn)})"
    )
    title = f"⚠ Divergence — {alert.symbol}"
    desc = (
        f"You are **{alert.user_side.upper()}** {_fmt_usd(alert.user_notional)} "
        f"on **{alert.symbol}**, against a {alert.strength} smart-money "
        f"**{alert.smart_side.upper()}** bias.\n\n"
        f"**Smart-money book:** {smart_label}"
    )
    fields = [
        {"name": "Your side", "value": alert.user_side.upper(), "inline": True},
        {"name": "Smart money", "value": alert.smart_side.upper(), "inline": True},
        {"name": "Strength", "value": alert.strength, "inline": True},
    ]
    embed: dict[str, Any] = {
        "title": title,
        "description": desc,
        "color": _COLOR_STRONG if alert.strength == "strong" else _COLOR_WEAK,
        "fields": fields,
        "footer": {"text": "Edgework · Smart Money Divergence"},
    }
    if wallet:
        embed["footer"]["text"] += f" · {wallet[:6]}…{wallet[-4:]}"
    if app_url:
        url = app_url
        if wallet:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}w={wallet}"
        embed["url"] = url
    return {"embeds": [embed]}


def send_discord(webhook_url: str, payload: dict, *, timeout: float = 8.0) -> int:
    """POST a payload to a Discord webhook. Returns the HTTP status code.

    Discord returns 204 on success for webhook posts.
    """
    import httpx

    with httpx.Client(timeout=timeout) as client:
        r = client.post(webhook_url, json=payload)
    return r.status_code


def send_test(webhook_url: str, *, timeout: float = 8.0) -> int:
    """Send a harmless connectivity check to the webhook."""
    payload = {
        "embeds": [{
            "title": "✓ Edgework alerts connected",
            "description": (
                "This channel will receive **Smart Money Divergence** alerts "
                "when you open a position against the qualified top-trader book."
            ),
            "color": 0x4CAF50,
            "footer": {"text": "Edgework · test message"},
        }]
    }
    return send_discord(webhook_url, payload, timeout=timeout)


# --------------------------------------------------------------------------- #
# Dedupe state — don't re-fire the same open position every poll
# --------------------------------------------------------------------------- #


@dataclass
class AlertState:
    """Tracks which (symbol, side) entries have already been alerted.

    Persisted as JSON: ``{key: first_alerted_unix_ms}``. A key is cleared
    once the position is no longer open, so re-opening the same contrarian
    position later legitimately re-alerts.
    """

    path: Path
    fired: dict[str, int]

    @classmethod
    def load(cls, path: str | Path) -> AlertState:
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (FileNotFoundError, ValueError, OSError):
            data = {}
        return cls(path=p, fired={str(k): int(v) for k, v in data.items()})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.fired, indent=2), encoding="utf-8")

    def select_new(self, alerts: list[DivergenceAlert]) -> list[DivergenceAlert]:
        """Return alerts not already fired; mark them fired (in memory)."""
        now_ms = int(time.time() * 1000)
        fresh = [a for a in alerts if a.key not in self.fired]
        for a in fresh:
            self.fired[a.key] = now_ms
        return fresh

    def prune(self, live_keys: set[str]) -> None:
        """Drop fired keys whose positions are no longer open."""
        self.fired = {k: v for k, v in self.fired.items() if k in live_keys}
