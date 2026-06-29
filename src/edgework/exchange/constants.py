"""SoDEX API constants: URLs, enums, the critical signing field order.

FIELD_ORDER is captured verbatim from the SoDEX platform — changing the
order breaks the EIP-712 signature. Ported from the production trading
client (confirmed against live platform capture).
"""
from __future__ import annotations

from enum import IntEnum


# ── Network configuration ───────────────────────────────────────────────────
NETWORK_CONFIG = {
    "mainnet": {
        "chain_id": 286623,
        "gateway":  "https://mainnet-gw.sodex.dev",
        "perps":    "https://mainnet-gw.sodex.dev/api/v1/perps",
        "spot":     "https://mainnet-gw.sodex.dev/api/v1/spot",
        "ws_perps": "wss://mainnet-gw.sodex.dev/ws/perps",
        "ws_spot":  "wss://mainnet-gw.sodex.dev/ws/spot",
    },
    "testnet": {
        "chain_id": 138565,
        "gateway":  "https://testnet-gw.sodex.dev",
        "perps":    "https://testnet-gw.sodex.dev/api/v1/perps",
        "spot":     "https://testnet-gw.sodex.dev/api/v1/spot",
        "ws_perps": "wss://testnet-gw.sodex.dev/ws/perps",
        "ws_spot":  "wss://testnet-gw.sodex.dev/ws/spot",
    },
}


# ── CRITICAL: RawOrder field order (Go struct order) ────────────────────────
# Changing this order breaks the signature. The omitempty fields (price,
# quantity, funds, stopPrice, stopType, triggerType) only enter the JSON when
# a value is supplied.
FIELD_ORDER = [
    "clOrdID",       # always present
    "modifier",      # always present
    "side",          # always present
    "type",          # always present
    "timeInForce",   # always present
    "price",         # omitempty
    "quantity",      # omitempty
    "funds",         # omitempty
    "stopPrice",     # omitempty
    "stopType",      # omitempty
    "triggerType",   # omitempty
    "reduceOnly",    # always present (bool, default false)
    "positionSide",  # always present
]


# ── Enums ───────────────────────────────────────────────────────────────────
class OrderSide(IntEnum):
    BUY = 1
    SELL = 2


class OrderType(IntEnum):
    LIMIT = 1
    MARKET = 2


class TimeInForce(IntEnum):
    GTC = 1
    IOC = 3
    GTX = 4   # post-only / maker — never executes immediately (safe to test)


class OrderModifier(IntEnum):
    NORMAL = 1
    STOP = 2
    BRACKET = 3
    ATTACHED_STOP = 4


class PositionSide(IntEnum):
    BOTH = 1   # only value currently supported (one-way mode)


class MarginMode(IntEnum):
    ISOLATED = 1
    CROSS = 2


class StopType(IntEnum):
    STOP_LOSS = 1
    TAKE_PROFIT = 2


class TriggerType(IntEnum):
    MARK_PRICE = 1
    LAST_PRICE = 2


# ── Action type names (go in ActionPayload.Type) ────────────────────────────
ACTION_TYPES = {
    "newOrder":       "NewOrderRequest",
    "cancelOrder":    "CancelOrderRequest",
    "replaceOrder":   "ReplaceOrderRequest",
    "updateLeverage": "UpdateLeverageRequest",
    "updateMargin":   "UpdateMarginRequest",
    "scheduleCancel": "ScheduleCancelRequest",
    "transferAsset":  "TransferAssetRequest",
}


# ── EIP-712 domain names per engine ─────────────────────────────────────────
DOMAIN_PERPS = "futures"
DOMAIN_SPOT = "spot"
