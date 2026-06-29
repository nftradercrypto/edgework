#!/usr/bin/env python
"""Edgework execution companion — LOCAL-ONLY live order execution for SoDEX.

The hosted Edgework app never touches a real key: its execution layer runs in
simulation. This companion is the real half of the loop. It runs on YOUR
machine, signs with YOUR revocable SoDEX API key from YOUR .env, and talks
only to SoDEX's official gateway — the same trust model as using the SoDEX
frontend yourself.

Setup (.env in the repo root, or exported env vars):
    SODEX_USER_ADDRESS=0x...          # your wallet (public)
    SODEX_ACCOUNT_ID=12345            # numeric account id
    SODEX_API_PRIVATE_KEY=0x...       # API key private key — NOT your seed.
                                      # Create/revoke it on SoDEX at any time.

Usage:
    python scripts/edgework_exec.py positions
        List your open positions (public read — needs only the address).

    python scripts/edgework_exec.py close BTC-USD
        DRY-RUN (default): build + sign the reduce-only close and print the
        exact body that WOULD be posted. Nothing is sent.

    python scripts/edgework_exec.py close BTC-USD --qty 0.05
        Partial close (still reduce-only).

    python scripts/edgework_exec.py close BTC-USD --live
        Actually submit. Asks for confirmation unless --yes.

Safety by construction:
    - every order is reduce-only — this tool can only SHRINK risk;
    - quantity is capped at your current position size;
    - live mode requires an interactive YES (or explicit --yes).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make src/ importable when running from the repo root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

from edgework.exchange.constants import OrderType  # noqa: E402
from edgework.exchange.execution_client import (  # noqa: E402
    ExecutionConfig,
    LocalExecutionClient,
)
from edgework.exchange.order_builder import (  # noqa: E402
    plan_close_from_position,
    simulate,
)
from edgework.exchange.signing import derive_address, sign_action  # noqa: E402
from edgework.exchange.constants import NETWORK_CONFIG  # noqa: E402
from edgework.sodex_client import SodexClient  # noqa: E402


def _mask(s: str, keep: int = 6) -> str:
    """Never print key material — show just enough to recognize it."""
    if not s:
        return "(not set)"
    return s[:keep] + "…" + s[-4:] if len(s) > keep + 4 else "***"


def _load_env() -> dict:
    load_dotenv()
    return {
        "address":    os.environ.get("SODEX_USER_ADDRESS", "").strip(),
        "account_id": os.environ.get("SODEX_ACCOUNT_ID", "").strip(),
        "api_key":    os.environ.get("SODEX_API_PRIVATE_KEY", "").strip(),
        "network":    os.environ.get("SODEX_NETWORK", "mainnet").strip() or "mainnet",
    }


def _fetch_open_positions(address: str) -> list[dict]:
    """Normalized open positions (same rules as the app: one-way mode sign)."""
    with SodexClient(user_address=address) as c:
        raw = c.get_open_positions()
    if isinstance(raw, dict):
        raw = raw.get("positions") or raw.get("data") or []
    out = []
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
            entry = float(p.get("avgEntryPrice") or 0)
        except (TypeError, ValueError):
            entry = 0.0
        out.append({
            "symbol": symbol,
            "side": side,
            "size": abs(size_raw),
            "entry_price": entry,
            "notional": abs(size_raw) * entry,
        })
    return out


def _fetch_symbol_id(symbol: str) -> int:
    """name → numeric id, from the live symbols list."""
    with SodexClient(
        user_address="0x0000000000000000000000000000000000000000"
    ) as c:
        for s in c.get_perps_symbols() or []:
            name = s.get("name") or s.get("symbol") or s.get("displayName")
            sid = s.get("id") or s.get("symbolID") or s.get("symbolId")
            if name == symbol and sid is not None:
                return int(sid)
    raise SystemExit(f"Symbol {symbol!r} not found on SoDEX.")


def cmd_positions(env: dict) -> int:
    if not env["address"]:
        raise SystemExit("SODEX_USER_ADDRESS not set in .env")
    positions = _fetch_open_positions(env["address"])
    if not positions:
        print("No open positions.")
        return 0
    print(f"{'SYMBOL':<14} {'SIDE':<6} {'SIZE':>14} {'ENTRY':>14} {'NOTIONAL':>14}")
    for p in positions:
        print(
            f"{p['symbol']:<14} {p['side']:<6} {p['size']:>14,.6f} "
            f"{p['entry_price']:>14,.2f} {p['notional']:>14,.2f}"
        )
    return 0


def cmd_close(env: dict, symbol: str, qty: float | None, live: bool, yes: bool) -> int:
    if not env["address"]:
        raise SystemExit("SODEX_USER_ADDRESS not set in .env")

    positions = [
        p for p in _fetch_open_positions(env["address"]) if p["symbol"] == symbol
    ]
    if not positions:
        raise SystemExit(f"No open position in {symbol}.")
    pos = positions[0]

    # Cap at position size — this tool can only shrink risk.
    if qty is not None:
        qty = min(abs(qty), pos["size"])
        pos = dict(pos, size=qty)

    account_id = int(env["account_id"]) if env["account_id"] else 0
    symbol_id = _fetch_symbol_id(symbol)
    plan = plan_close_from_position(
        pos, symbol_id=symbol_id, account_id=account_id,
        reason="manual_close", order_type=OrderType.MARKET,
    )
    action_type, params = plan.to_order_params()

    print(f"\n  {plan.reason_label}")
    print(f"  {symbol}: {pos['side'].upper()} {plan.quantity} → "
          f"close via {plan.close_side.name} (reduce-only)\n")

    if not live:
        # Dry run. With a real key: sign exactly what live mode would sign.
        # Without one: ephemeral simulation (same as the hosted app).
        if env["api_key"]:
            chain_id = NETWORK_CONFIG[env["network"]]["chain_id"]
            signed = sign_action(
                action_type, params, env["api_key"], chain_id,
            )
            body = {
                "type": action_type,
                "params": json.loads(signed.payload_json)["params"],
                "nonce": signed.nonce,
                "signature": signed.typed_signature,
            }
            print(f"  DRY-RUN · signed with YOUR key "
                  f"({_mask(derive_address(env['api_key']))}) · NOT sent")
        else:
            sim = simulate(action_type, params, network=env["network"])
            body = sim.body
            print(f"  DRY-RUN · no SODEX_API_PRIVATE_KEY set — signed with an "
                  f"ephemeral key ({_mask(sim.ephemeral_signer)}) · NOT sent")
        print("\n  POST body for /exchange:")
        print(json.dumps(body, indent=2))
        print("\n  Re-run with --live to submit.")
        return 0

    # ── Live submission ──
    if not env["api_key"] or not env["account_id"]:
        raise SystemExit(
            "Live mode needs SODEX_API_PRIVATE_KEY and SODEX_ACCOUNT_ID in .env"
        )
    if not yes:
        answer = input(
            f"  Submit LIVE reduce-only {plan.close_side.name} {plan.quantity} "
            f"{symbol}? Type YES to confirm: "
        )
        if answer.strip() != "YES":
            print("  Aborted.")
            return 1

    client = LocalExecutionClient(ExecutionConfig(
        api_private_key=env["api_key"],
        user_address=env["address"],
        account_id=int(env["account_id"]),
        network=env["network"],
    ))
    resp = client.submit(action_type, params)
    print("  SoDEX response:")
    print(json.dumps(resp, indent=2)[:2000])
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="edgework_exec",
        description="Edgework local execution companion (SoDEX, reduce-only).",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("positions", help="list your open positions")

    ap_close = sub.add_parser("close", help="close (reduce) a position")
    ap_close.add_argument("symbol", help="e.g. BTC-USD")
    ap_close.add_argument("--qty", type=float, default=None,
                          help="partial size to close (default: full position)")
    ap_close.add_argument("--live", action="store_true",
                          help="actually submit (default: dry-run)")
    ap_close.add_argument("--yes", action="store_true",
                          help="skip the interactive confirmation in live mode")

    args = ap.parse_args(argv)
    env = _load_env()

    if args.cmd == "positions":
        return cmd_positions(env)
    if args.cmd == "close":
        return cmd_close(env, args.symbol, args.qty, args.live, args.yes)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
