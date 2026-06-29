#!/usr/bin/env python
"""Edgework alert bot — Smart Money Divergence alerts to Discord (LOCAL).

Watches your open SoDEX positions and pings a Discord channel the moment you
open one that fights the qualified smart-money book (the same top active+
profitable traders the app's Smart Money Watch tracks). Runs entirely on your
machine; the only thing it talks to is SoDEX's public read API and your own
Discord webhook. No private keys, read-only.

Setup (.env in the repo root, or exported env vars):
    SODEX_USER_ADDRESS=0x...                 # the wallet to watch (public)
    EDGEWORK_DISCORD_WEBHOOK=https://discord.com/api/webhooks/...

Usage:
    python scripts/alert_bot.py --test
        Send a connectivity test to the webhook and exit.

    python scripts/alert_bot.py --once
        Run a single check, fire any new divergence alerts, exit.

    python scripts/alert_bot.py
        Loop forever, checking every --interval seconds (default 300).

    python scripts/alert_bot.py --interval 600 --dry-run
        Loop every 10 min; --dry-run prints alerts instead of sending them.

State (so the same open position isn't re-alerted every cycle) lives in
~/.edgework/alert_state.json by default; override with --state.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

from edgework.alerts import (  # noqa: E402
    AlertState,
    detect_divergences,
    format_discord,
    send_discord,
    send_test,
)
from edgework.smart_money import fetch_consensus, fetch_open_positions  # noqa: E402

APP_URL = "https://edgework.streamlit.app"
DEFAULT_STATE = Path.home() / ".edgework" / "alert_state.json"


def _log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _check_once(address: str, webhook: str, state: AlertState, *, dry_run: bool) -> int:
    """One poll cycle. Returns the number of new alerts fired."""
    positions = fetch_open_positions(address)
    if not positions:
        _log("no open positions")
        state.prune(set())
        state.save()
        return 0

    sm = fetch_consensus(n_top=20, window="30d")
    if sm.get("error"):
        _log(f"smart-money fetch error: {sm['error']}")
        return 0

    consensus = sm.get("consensus_per_symbol", {}) or {}
    alerts = detect_divergences(positions, consensus)

    # Keep state in step with reality: forget positions that are closed now.
    live_keys = {f"{p['symbol']}:{p['side']}" for p in positions}
    state.prune(live_keys)

    new_alerts = state.select_new(alerts)
    _log(
        f"{len(positions)} positions · {len(alerts)} contrarian · "
        f"{len(new_alerts)} new"
    )

    for a in new_alerts:
        payload = format_discord(a, wallet=address, app_url=APP_URL)
        if dry_run:
            _log(f"  DRY-RUN would alert: {a.symbol} {a.user_side.upper()} "
                 f"vs smart {a.smart_side.upper()} ({a.strength})")
        else:
            try:
                code = send_discord(webhook, payload)
                _log(f"  alerted {a.symbol} {a.user_side.upper()} → Discord {code}")
            except Exception as e:  # noqa: BLE001 — keep the loop alive
                _log(f"  send failed for {a.symbol}: {e}")

    state.save()
    return len(new_alerts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="alert_bot")
    ap.add_argument("--test", action="store_true",
                    help="send a webhook connectivity test and exit")
    ap.add_argument("--once", action="store_true",
                    help="run a single check and exit")
    ap.add_argument("--interval", type=int, default=300,
                    help="seconds between checks in loop mode (default 300)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print alerts instead of sending them")
    ap.add_argument("--state", default=str(DEFAULT_STATE),
                    help=f"dedupe state file (default {DEFAULT_STATE})")
    args = ap.parse_args(argv)

    load_dotenv()
    address = os.environ.get("SODEX_USER_ADDRESS", "").strip()
    webhook = os.environ.get("EDGEWORK_DISCORD_WEBHOOK", "").strip()

    if not webhook:
        raise SystemExit("EDGEWORK_DISCORD_WEBHOOK not set in .env")

    if args.test:
        code = send_test(webhook)
        _log(f"test message → Discord HTTP {code}")
        return 0 if code in (200, 204) else 1

    if not address:
        raise SystemExit("SODEX_USER_ADDRESS not set in .env")

    state = AlertState.load(args.state)

    if args.once:
        _check_once(address, webhook, state, dry_run=args.dry_run)
        return 0

    _log(f"watching {address[:6]}…{address[-4:]} every {args.interval}s "
         f"(state: {args.state}){' · DRY-RUN' if args.dry_run else ''}")
    try:
        while True:
            try:
                _check_once(address, webhook, state, dry_run=args.dry_run)
            except Exception as e:  # noqa: BLE001 — never let one cycle kill the loop
                _log(f"cycle error: {e}")
            time.sleep(max(30, args.interval))
    except KeyboardInterrupt:
        _log("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
