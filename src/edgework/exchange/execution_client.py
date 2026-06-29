"""LOCAL-ONLY live execution client.

This is the only module that transmits a real, key-signed order to SoDEX.
It is deliberately NOT used by the hosted app. The trader runs it on their
own machine; the API key comes from the local environment and is sent only
to SoDEX's official gateway — the same trust model as using the SoDEX
frontend yourself.

The hosted app uses order_builder.simulate() instead, which signs with an
ephemeral key and sends nothing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
from eth_utils import to_checksum_address as _to_checksum

from .constants import DOMAIN_PERPS, NETWORK_CONFIG
from .signing import normalize_orders_in_params, sign_action


@dataclass
class ExecutionConfig:
    api_private_key: str    # hex (with/without 0x) — the SoDEX API key, NOT a wallet seed
    user_address: str       # main wallet address (0x...)
    account_id: int         # numeric SoDEX account id
    network: str = "mainnet"
    timeout_s: float = 8.0


class LocalExecutionClient:
    """Signs and submits a single action to SoDEX /exchange. Local use only."""

    def __init__(self, cfg: ExecutionConfig):
        if cfg.network not in NETWORK_CONFIG:
            raise ValueError(f"Invalid network: {cfg.network}")
        net = NETWORK_CONFIG[cfg.network]
        self.cfg = cfg
        self.chain_id = net["chain_id"]
        self.perps_url = net["perps"]
        self.user_address = _to_checksum(cfg.user_address)

    def submit(self, action_type: str, params: dict, *, domain: str = DOMAIN_PERPS) -> dict:
        """Sign `params` with the real API key and POST to /exchange.

        Returns the parsed JSON response, or a status/text dict on non-JSON.
        """
        signed = sign_action(
            action_type, params, self.cfg.api_private_key,
            self.chain_id, domain_name=domain,
        )
        normalized_params = json.loads(signed.payload_json)["params"]
        full_body = {
            "type": action_type,
            "params": normalized_params,
            "nonce": signed.nonce,
            "signature": signed.typed_signature,
        }
        body_json = json.dumps(full_body, separators=(",", ":"), sort_keys=False)
        with httpx.Client(timeout=self.cfg.timeout_s) as client:
            r = client.post(
                f"{self.perps_url}/exchange",
                content=body_json,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        try:
            return r.json()
        except Exception:  # noqa: BLE001 — surface raw text on non-JSON
            return {"_status": r.status_code, "_text": r.text[:500]}
