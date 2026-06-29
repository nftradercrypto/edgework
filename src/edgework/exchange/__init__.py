"""Edgework execution layer (Wave 3).

The *insight → action* bridge. Edgework's analytics surface (Wave 1/2) is
read-only. This subpackage adds the ability to turn a diagnostic insight
(e.g. "you're contrarian to the smart-money book", "this position is in
your bleed zone") into a real, signed SoDEX order.

Custody model — deliberately local-first:
  - The hosted app (edgework.streamlit.app) NEVER asks for a private key.
    It runs every action in SIMULATION mode: it builds and signs the
    EIP-712 order with an ephemeral demo key and shows you the exact
    payload/signature/digest, but sends nothing.
  - Real execution runs in a LOCAL companion the trader runs on their own
    machine. The SoDEX API key lives in the local .env and is transmitted
    only to SoDEX's own API — identical trust model to using the SoDEX
    frontend yourself. The code is open-source and auditable.

SoDEX uses a delegated, revocable API key (NOT your wallet seed) signed via
a custom EIP-712 scheme. The signing pipeline is ported verbatim from the
battle-tested implementation used in production trading.
"""

from .constants import (
    DOMAIN_PERPS,
    DOMAIN_SPOT,
    MarginMode,
    NETWORK_CONFIG,
    OrderModifier,
    OrderSide,
    OrderType,
    PositionSide,
    TimeInForce,
)
from .signing import SignedAction, derive_address, sign_action

__all__ = [
    "DOMAIN_PERPS",
    "DOMAIN_SPOT",
    "MarginMode",
    "NETWORK_CONFIG",
    "OrderModifier",
    "OrderSide",
    "OrderType",
    "PositionSide",
    "TimeInForce",
    "SignedAction",
    "derive_address",
    "sign_action",
]
