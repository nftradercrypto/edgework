"""SoDEX API client (read-only).

Wave 1 only needs read access:
- account order history (your trades)
- public leaderboard (for benchmarking)
- public market data (for slicing context)

Order placement / signing (EIP-712) is intentionally out of scope here.
That belongs in Wave 2+ when execution is added.

Authentication uses the documented header trio:
    X-API-Key, X-API-Sign, X-API-Nonce
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import get_settings


@dataclass
class SodexAuth:
    """Build the auth headers for a SoDEX request.

    Sign = HMAC-SHA256(secret, f"{nonce}{method}{path}{body}")  # hex
    Adjust if/when the official docs say otherwise.
    """

    api_key: str
    api_secret: str

    def headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        nonce = str(int(time.time() * 1000))
        message = f"{nonce}{method.upper()}{path}{body}"
        sign = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-API-Key": self.api_key,
            "X-API-Sign": sign,
            "X-API-Nonce": nonce,
            "Content-Type": "application/json",
        }


class SodexClient:
    """Thin async-friendly wrapper for the SoDEX REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        s = get_settings()
        self.api_key = api_key or s.sodex_api_key
        self.api_secret = api_secret or s.sodex_api_secret
        self.base_url = (base_url or s.sodex_base_url).rstrip("/")
        self._auth = SodexAuth(self.api_key, self.api_secret) if self.api_key else None
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SodexClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Low-level
    # ------------------------------------------------------------------ #

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        headers = self._auth.headers("GET", path) if self._auth else {}
        r = self._client.get(url, headers=headers, params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        body_str = json.dumps(body, separators=(",", ":"))
        headers = self._auth.headers("POST", path, body_str) if self._auth else {}
        r = self._client.post(url, headers=headers, content=body_str)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------ #
    # High-level (read-only — Wave 1)
    # ------------------------------------------------------------------ #

    def get_account(self) -> dict[str, Any]:
        """Account summary (balances, tier, fee schedule)."""
        return self._get("/api/v1/perps/account")

    def get_order_history(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Pull historical orders for the authenticated account."""
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if start_ms:
            params["startTime"] = start_ms
        if end_ms:
            params["endTime"] = end_ms
        data = self._get("/api/v1/perps/trade/orders/history", params=params)
        if isinstance(data, dict) and "data" in data:
            return list(data["data"])
        return list(data)

    def get_fills(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Pull historical fills (executed trades) for the account."""
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if start_ms:
            params["startTime"] = start_ms
        if end_ms:
            params["endTime"] = end_ms
        data = self._get("/api/v1/perps/trade/fills", params=params)
        if isinstance(data, dict) and "data" in data:
            return list(data["data"])
        return list(data)

    def get_leaderboard(
        self,
        period: str = "weekly",
        sort_by: str = "volume",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Public leaderboard snapshot."""
        params = {"period": period, "sortBy": sort_by, "limit": limit}
        data = self._get("/api/v1/leaderboard", params=params)
        if isinstance(data, dict) and "data" in data:
            return list(data["data"])
        return list(data)

    def get_klines(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Public OHLCV candles for a perps market (regime context).

        Confirmed endpoint shape (per Buildathon API channel):
            GET /api/v1/perps/markets/{symbol}/klines?interval=&limit=
        """
        path = f"/api/v1/perps/markets/{symbol}/klines"
        params = {"interval": interval, "limit": limit}
        data = self._get(path, params=params)
        if isinstance(data, dict) and "data" in data:
            return list(data["data"])
        return list(data)

    def get_perps_symbols(self) -> list[dict[str, Any]]:
        """List all perps markets available on SoDEX."""
        data = self._get("/api/v1/perps/markets/symbols")
        if isinstance(data, dict) and "data" in data:
            return list(data["data"])
        return list(data)

    def get_spot_klines(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Public OHLCV candles for a spot market.

        Spot uses virtual/wrapped naming (e.g. "vBTC_vUSDC", "wSOSO").
        """
        path = f"/api/v1/spot/markets/{symbol}/klines"
        params = {"interval": interval, "limit": limit}
        data = self._get(path, params=params)
        if isinstance(data, dict) and "data" in data:
            return list(data["data"])
        return list(data)

    def get_spot_symbols(self) -> list[dict[str, Any]]:
        """List all spot markets (uses v-prefix / w-prefix naming)."""
        data = self._get("/api/v1/spot/markets/symbols")
        if isinstance(data, dict) and "data" in data:
            return list(data["data"])
        return list(data)
