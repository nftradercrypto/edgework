"""Insight → action: build signed SoDEX orders from Edgework insights.

This is the Edgework-specific layer on top of the raw signing pipeline.
It turns a *reason to act* — "this position is contrarian to the
smart-money book", "this position is in your bleed zone" — into a concrete,
signed SoDEX order.

Safety by construction:
  - Every order this module builds is a **reduce-only close**. It can only
    *decrease* risk, never open new exposure or flip you net-short/long.
    A bug here cannot blow up an account.
  - `simulate()` signs with a throwaway ephemeral key and returns the exact
    body that *would* be POSTed — but sends nothing. This is what the hosted
    app uses. No real key is ever required or touched.
  - Real submission lives in `execution_client.py` and is local-only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

from eth_keys.datatypes import PrivateKey as _PrivateKey

from .constants import (
    DOMAIN_PERPS,
    NETWORK_CONFIG,
    OrderModifier,
    OrderSide,
    OrderType,
    PositionSide,
    TimeInForce,
)
from .signing import build_payload_json, normalize_orders_in_params, sign_action

CloseReason = Literal[
    "contrarian_to_smart_money",
    "bleed_zone_timestop",
    "manual_close",
]

_REASON_LABEL = {
    "contrarian_to_smart_money": "Close position contrarian to smart-money book",
    "bleed_zone_timestop": "Time-stop: position in your bleed zone",
    "manual_close": "Manual close",
}


@dataclass
class ClosePlan:
    """A fully-described intent to close (reduce) a position.

    Built from an open position + a reason. Carries everything needed to
    construct the SoDEX order params, plus human-readable context for the UI.
    """

    symbol: str                 # "BTC-USD"
    symbol_id: int              # numeric SoDEX symbolID
    position_side: str          # current position: "long" | "short"
    quantity: str               # absolute size to close, as a string
    reason: CloseReason
    order_type: int = OrderType.MARKET
    price: str | None = None    # required only for LIMIT
    account_id: int | None = None

    @property
    def close_side(self) -> int:
        """The order side that *reduces* this position."""
        # Long position is closed by SELLing; short by BUYing.
        return OrderSide.SELL if self.position_side == "long" else OrderSide.BUY

    @property
    def reason_label(self) -> str:
        return _REASON_LABEL.get(self.reason, self.reason)

    def to_order_params(self) -> tuple[str, dict]:
        """Return ("newOrder", params) ready for signing.

        Always reduceOnly=True — this order can only shrink the position.
        """
        if self.account_id is None:
            raise ValueError("account_id is required to build order params")
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("LIMIT close requires a price")

        import time as _t
        nonce_ms = int(_t.time() * 1000)
        cl_ord_id = f"{self.account_id}-edgework-{nonce_ms}"

        order: dict = {
            "clOrdID":     cl_ord_id,
            "modifier":    int(OrderModifier.NORMAL),
            "side":        int(self.close_side),
            "type":        int(self.order_type),
            # MARKET → IOC (fill what you can now); LIMIT → GTC.
            "timeInForce": int(
                TimeInForce.IOC if self.order_type == OrderType.MARKET
                else TimeInForce.GTC
            ),
            "reduceOnly":  True,
            "positionSide": int(PositionSide.BOTH),
        }
        if self.order_type == OrderType.LIMIT:
            order["price"] = str(self.price)
        order["quantity"] = str(self.quantity)

        params = {
            "accountID": self.account_id,
            "symbolID":  int(self.symbol_id),
            "orders":    [order],
        }
        return "newOrder", params


def plan_close_from_position(
    position: dict,
    *,
    symbol_id: int,
    account_id: int | None = None,
    reason: CloseReason = "manual_close",
    order_type: int = OrderType.MARKET,
    price: str | None = None,
) -> ClosePlan:
    """Build a ClosePlan from an Edgework open-position dict.

    `position` is the shape produced by sodex_client.get_open_positions /
    the UI's _fetch_user_open_positions: it has at least
    {"symbol", "side", "size"|"quantity"}.
    """
    symbol = position["symbol"]
    side = position["side"]  # "long" | "short"
    # Size may arrive as "size", "quantity", or a signed number.
    raw_qty = (
        position.get("quantity")
        if position.get("quantity") is not None
        else position.get("size", 0)
    )
    qty = abs(float(raw_qty))
    return ClosePlan(
        symbol=symbol,
        symbol_id=symbol_id,
        position_side=side,
        quantity=_fmt_qty(qty),
        reason=reason,
        order_type=order_type,
        price=price,
        account_id=account_id,
    )


def _fmt_qty(qty: float) -> str:
    """Format a quantity to a clean string (no trailing float noise)."""
    s = f"{qty:.8f}".rstrip("0").rstrip(".")
    return s if s else "0"


@dataclass
class SimulatedOrder:
    """The result of simulating an order: everything that *would* be sent,
    plus the signed EIP-712 fields — but nothing was transmitted.
    """

    action_type: str
    body: dict                  # exact POST body /exchange would receive
    payload_json: str
    payload_hash: str
    struct_hash: str
    digest: str
    typed_signature: str
    nonce: int
    ephemeral_signer: str       # checksummed address of the throwaway key
    network: str
    sent: bool = field(default=False, init=False)


def simulate(
    action_type: str,
    params: dict,
    *,
    network: str = "mainnet",
    domain: str = DOMAIN_PERPS,
) -> SimulatedOrder:
    """Build and sign an order with a throwaway ephemeral key. Sends NOTHING.

    This is what the hosted app calls. It proves the full EIP-712 pipeline
    end-to-end — payload hashing, struct hashing, domain separation, ECDSA
    signing, wire format — without requiring or touching any real key.

    The signature is real and valid (it just belongs to a random key SoDEX
    has never seen, so it would be rejected if actually submitted). That's
    the point: the trader sees the exact mechanics with zero risk.
    """
    if network not in NETWORK_CONFIG:
        raise ValueError(f"Invalid network: {network}")
    chain_id = NETWORK_CONFIG[network]["chain_id"]

    # Fresh random key, used once, never persisted.
    ephemeral_pk = _PrivateKey(os.urandom(32))
    ephemeral_hex = ephemeral_pk.to_bytes().hex()

    signed = sign_action(
        action_type, params, ephemeral_hex, chain_id, domain_name=domain,
    )

    normalized_params = normalize_orders_in_params(params)
    body = {
        "type": action_type,
        "params": normalized_params,
        "nonce": signed.nonce,
        "signature": signed.typed_signature,
    }

    return SimulatedOrder(
        action_type=action_type,
        body=body,
        payload_json=signed.payload_json,
        payload_hash=signed.payload_hash,
        struct_hash=signed.struct_hash,
        digest=signed.digest,
        typed_signature=signed.typed_signature,
        nonce=signed.nonce,
        ephemeral_signer=ephemeral_pk.public_key.to_checksum_address(),
        network=network,
    )
