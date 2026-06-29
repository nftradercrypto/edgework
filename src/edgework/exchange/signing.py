"""EIP-712 signing pipeline for SoDEX.

Reproduces the SoDEX Go SDK flow (eip712.go):
  1. payloadHash = keccak256(compact JSON of the ActionPayload)
  2. structHash  = keccak256(ActionTypeHash | payloadHash | nonce_bytes)
  3. digest      = keccak256(0x19 0x01 | domainSeparator | structHash)
  4. signature   = 0x01 | r | s | v  (66 bytes total)

`sign_action` returns a SignedAction with the typed signature, nonce, and
each intermediate hash (hex) for debugging.

Ported verbatim from the production SoDEX trading client — this is the
battle-tested implementation. No dependency on the HTTP client (importable
standalone for tests).

Uses eth_keys + eth_utils.keccak rather than web3 to keep the dependency
footprint small (web3 drags in native ckzg/cytoolz).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from eth_keys.datatypes import PrivateKey as _PrivateKey
from eth_utils import keccak as _keccak

from .constants import DOMAIN_PERPS, FIELD_ORDER


def _keccak256(data: bytes) -> bytes:
    """keccak256 — identical output to Web3.keccak."""
    return _keccak(data)


# ── Pre-computed type hashes ────────────────────────────────────────────────
DOMAIN_TYPEHASH = _keccak256(
    b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
)
ACTION_TYPEHASH = _keccak256(
    b"ExchangeAction(bytes32 payloadHash,uint64 nonce)"
)


@dataclass
class SignedAction:
    typed_signature: str   # "0x01" + 130 hex chars (134 chars total)
    nonce: int             # ms timestamp, same value goes in the body
    payload_json: str      # exact JSON used for payloadHash (debug)
    payload_hash: str      # hex
    struct_hash: str       # hex
    digest: str            # hex


def compute_domain_separator(domain_name: str, chain_id: int) -> bytes:
    """Compute the EIP-712 domainSeparator.

    verifyingContract = address(0) (SoDEX uses the zero address).
    """
    return _keccak256(
        DOMAIN_TYPEHASH
        + _keccak256(domain_name.encode())
        + _keccak256(b"1")
        + chain_id.to_bytes(32, "big")
        + b"\x00" * 32
    )


def order_raw_order_fields(order: dict) -> dict:
    """Reorder an order's fields per FIELD_ORDER (Go struct order).

    omitempty fields (price, quantity, funds, stopPrice, stopType,
    triggerType) are dropped when the key is absent from the input.
    Required fields are always present (even when 0/false).
    """
    OMIT_IF_MISSING = {"price", "quantity", "funds", "stopPrice", "stopType", "triggerType"}
    out: dict = {}
    for key in FIELD_ORDER:
        if key in order:
            out[key] = order[key]
        elif key not in OMIT_IF_MISSING:
            # Required fields must be present — defensive fallback.
            if key == "reduceOnly":
                out[key] = False
            elif key == "positionSide":
                out[key] = 1
    unknown = set(order.keys()) - set(FIELD_ORDER)
    if unknown:
        raise ValueError(f"Unknown fields in order: {unknown}")
    return out


def normalize_orders_in_params(params: dict) -> dict:
    """Apply order_raw_order_fields to each order in params.orders[]."""
    if "orders" not in params:
        return params
    out = dict(params)
    out["orders"] = [order_raw_order_fields(o) for o in params["orders"]]
    return out


def build_payload_json(action_type: str, params: dict) -> str:
    """Build the exact JSON that gets hashed.

    Format: {"type":"<action>","params":{...}}
    Compact (no spaces), sort_keys=False (preserve defined order).
    """
    payload = {"type": action_type, "params": params}
    return json.dumps(payload, separators=(",", ":"), sort_keys=False)


def sign_action(
    action_type: str,
    params: dict,
    api_private_key: str,
    chain_id: int,
    domain_name: str = DOMAIN_PERPS,
    nonce_ms: int | None = None,
) -> SignedAction:
    """Full EIP-712 pipeline.

    Args:
        action_type: "newOrder", "cancelOrder", etc.
        params: request dict (orders[] is re-ordered when applicable)
        api_private_key: hex string of the API private key (with or without 0x)
        chain_id: 286623 mainnet, 138565 testnet
        domain_name: "futures" (perps) or "spot"
        nonce_ms: optional, default = int(time.time() * 1000)

    Returns:
        SignedAction with typed_signature + nonce + intermediate hashes (debug)
    """
    pk_hex = api_private_key[2:] if api_private_key.startswith("0x") else api_private_key
    pk_obj = _PrivateKey(bytes.fromhex(pk_hex))

    if nonce_ms is None:
        nonce_ms = int(time.time() * 1000)

    # Normalize orders (Go struct order)
    params = normalize_orders_in_params(params)

    # Step 1: payloadHash
    payload_json = build_payload_json(action_type, params)
    payload_hash = _keccak256(payload_json.encode("utf-8"))

    # Step 2: structHash
    nonce_bytes = b"\x00" * 24 + nonce_ms.to_bytes(8, "big")
    struct_hash = _keccak256(ACTION_TYPEHASH + payload_hash + nonce_bytes)

    # Step 3: EIP-712 digest
    domain_sep = compute_domain_separator(domain_name, chain_id)
    digest = _keccak256(b"\x19\x01" + domain_sep + struct_hash)

    # Step 4: ECDSA sign + wire format (0x01 prefix)
    # eth_keys.sign_msg_hash returns v ∈ {0,1} and to_bytes() = r‖s‖v —
    # exactly what SoDEX expects.
    sig = pk_obj.sign_msg_hash(digest)
    sig_bytes = sig.to_bytes()
    typed_sig = "0x01" + sig_bytes.hex()

    return SignedAction(
        typed_signature=typed_sig,
        nonce=nonce_ms,
        payload_json=payload_json,
        payload_hash="0x" + payload_hash.hex(),
        struct_hash="0x" + struct_hash.hex(),
        digest="0x" + digest.hex(),
    )


def derive_address(api_private_key: str) -> str:
    """Return the checksummed address of a private key.

    Useful to verify the API private key matches the registered public key.
    """
    pk_hex = api_private_key[2:] if api_private_key.startswith("0x") else api_private_key
    return _PrivateKey(bytes.fromhex(pk_hex)).public_key.to_checksum_address()
