"""Smart-money book: who the qualified top traders are and what they hold.

Pure, importable logic shared by the Streamlit app (which wraps these in
``st.cache_data``) and the standalone alert poller (``scripts/alert_bot.py``),
so both compute the consensus exactly the same way.

"Qualified" = actively trading AND profitable: top 50 by 30-day volume,
filtered to positive PNL, then the top ``n_top`` by PNL. This deliberately
excludes lucky one-shot wallets — the consensus reflects traders with a real,
active edge.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .sodex_client import SodexClient

_ZERO_ADDR = "0x0000000000000000000000000000000000000000"


def normalize_open_positions(raw: Any) -> list[dict]:
    """Normalize a raw get_open_positions payload into a clean position list.

    Each item: ``{symbol, side, size, entry_price, notional, unrealized_pnl}``.
    Handles both ``{positions: [...]}`` / ``{data: [...]}`` and bare lists, and
    SoDEX one-way mode where direction is the sign of ``size``.
    """
    if isinstance(raw, dict):
        raw = raw.get("positions") or raw.get("data") or []
    out: list[dict] = []
    for p in raw or []:
        symbol = p.get("symbol")
        try:
            size_raw = float(p.get("size") or 0)
        except (TypeError, ValueError):
            size_raw = 0.0
        if not symbol or size_raw == 0:
            continue
        side_raw = str(p.get("positionSide") or p.get("side") or "").lower()
        if "long" in side_raw:
            side = "long"
        elif "short" in side_raw:
            side = "short"
        else:
            side = "long" if size_raw > 0 else "short"
        try:
            entry = float(p.get("avgEntryPrice") or p.get("entry_price") or 0)
        except (TypeError, ValueError):
            entry = 0.0
        try:
            upnl = float(p.get("unrealizedPnL") or p.get("unrealized_pnl") or 0)
        except (TypeError, ValueError):
            upnl = 0.0
        size = abs(size_raw)
        try:
            opened_ms = int(p.get("createdAt") or 0) or None
        except (TypeError, ValueError):
            opened_ms = None
        out.append({
            "symbol": symbol,
            "side": side,
            "size": size,
            "entry_price": entry,
            "notional": size * entry if entry else 0.0,
            "unrealized_pnl": upnl,
            "opened_at_ms": opened_ms,
        })
    return out


def fetch_open_positions(address: str) -> list[dict]:
    """Normalized open positions for a wallet (public read; no auth)."""
    if not address or not address.startswith("0x"):
        return []
    try:
        with SodexClient(user_address=address) as c:
            raw = c.get_open_positions()
    except Exception:  # noqa: BLE001 — caller treats missing data as "no positions"
        return []
    return normalize_open_positions(raw)


@dataclass
class SmartMoney:
    """The smart-money snapshot the rest of the app reasons about."""

    traders: list[dict] = field(default_factory=list)
    consensus_per_symbol: dict[str, dict] = field(default_factory=dict)
    fetched_at: str = ""
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "traders": self.traders,
            "consensus_per_symbol": self.consensus_per_symbol,
            "fetched_at": self.fetched_at,
            "error": self.error,
        }


def fetch_consensus(n_top: int = 20, window: str = "30d", max_workers: int = 8) -> dict:
    """Aggregate the open positions of the top active+profitable traders.

    Returns the same dict shape the app has always used:
    ``{traders, consensus_per_symbol, fetched_at, error}`` where each
    consensus entry has long/short counts, combined notional, combined
    trader-PNL, and the contributing traders.
    """
    import pandas as pd  # local import keeps module import cheap for the CLI

    sm = SmartMoney(fetched_at=pd.Timestamp.now(tz="UTC").isoformat())

    try:
        with SodexClient(user_address=_ZERO_ADDR) as c:
            lb = c.get_leaderboard(
                window_type=window, sort_by="volume",
                sort_order="desc", page=1, page_size=50,
            )
        items = lb.get("items", []) or []
        winners = [x for x in items if float(x.get("pnl_usd", 0) or 0) > 0]
        winners.sort(key=lambda x: float(x.get("pnl_usd", 0)), reverse=True)
        qualified = winners[:n_top]
    except Exception as e:  # noqa: BLE001
        sm.error = f"leaderboard fetch failed: {e}"
        return sm.as_dict()

    def _fetch(addr: str):
        try:
            with SodexClient(user_address=addr) as cc:
                return addr, cc.get_open_positions()
        except Exception:  # noqa: BLE001
            return addr, None

    addrs = [it.get("wallet_address") for it in qualified if it.get("wallet_address")]
    open_by_addr: dict[str, Any] = {}
    if addrs:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(addrs))) as pool:
            for addr, data in pool.map(_fetch, addrs):
                open_by_addr[addr] = data

    consensus: dict[str, dict] = {}
    traders: list[dict] = []
    for item in qualified:
        addr = item.get("wallet_address")
        if not addr:
            continue
        pnl_usd = float(item.get("pnl_usd", 0) or 0)
        vol_usd = float(item.get("volume_usd", 0) or 0)
        traders.append({
            "addr": addr, "rank_volume": item.get("rank"),
            "pnl_usd": pnl_usd, "volume_usd": vol_usd,
        })
        for pos in normalize_open_positions(open_by_addr.get(addr)):
            symbol, side = pos["symbol"], pos["side"]
            cs = consensus.setdefault(symbol, {
                "long_count": 0, "short_count": 0,
                "long_notional": 0.0, "short_notional": 0.0,
                "long_pnl_combined": 0.0, "short_pnl_combined": 0.0,
                "long_traders": [], "short_traders": [],
            })
            cs[f"{side}_count"] += 1
            cs[f"{side}_notional"] += pos["notional"]
            cs[f"{side}_pnl_combined"] += pnl_usd
            cs[f"{side}_traders"].append({
                "addr": addr, "size": pos["size"],
                "entry_price": pos["entry_price"], "notional": pos["notional"],
                "trader_pnl_30d": pnl_usd, "trader_vol_30d": vol_usd,
            })

    sm.traders = traders
    sm.consensus_per_symbol = consensus
    return sm.as_dict()
