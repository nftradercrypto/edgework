"""SoSoValue API client.

Wraps the public read-only endpoints we need for Edgework:
- news feed (sentiment context for trades)
- SSI indexes (market regime)
- ETF flows (institutional flow context)
- macro indicators (optional regime context)

Auth is API key in header. The exact endpoint paths follow the
SoSoValue OpenAPI doc; if a path returns 404 in practice, adjust here.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import get_settings


class SoSoValueClient:
    """Thin wrapper for SoSoValue OpenAPI read endpoints."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        s = get_settings()
        self.api_key = api_key or s.sosovalue_api_key
        self.base_url = (base_url or s.sosovalue_base_url).rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SoSoValueClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["x-soso-api-key"] = self.api_key
        return h

    def _post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        r = self._client.post(url, headers=self._headers(), json=body or {})
        r.raise_for_status()
        return r.json()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        r = self._client.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------ #
    # News
    # ------------------------------------------------------------------ #

    def get_news(self, limit: int = 50, lang: str = "en") -> list[dict[str, Any]]:
        """Latest crypto news items, AI-tagged with sentiment."""
        data = self._get("/openapi/v1/news/list", params={"limit": limit, "lang": lang})
        return _unwrap(data)

    # ------------------------------------------------------------------ #
    # ETF flows
    # ------------------------------------------------------------------ #

    def get_etf_flows(self, asset: str = "btc") -> dict[str, Any]:
        """Latest daily ETF flow snapshot for BTC or ETH."""
        return self._get(f"/openapi/v1/etf/{asset.lower()}/currentEtfDataMetrics")

    def get_etf_flow_history(self, asset: str = "btc", days: int = 30) -> list[dict[str, Any]]:
        """Historical daily ETF net flows."""
        data = self._get(
            f"/openapi/v1/etf/{asset.lower()}/historicalInflowChart",
            params={"days": days},
        )
        return _unwrap(data)

    # ------------------------------------------------------------------ #
    # SSI indexes
    # ------------------------------------------------------------------ #

    def list_indexes(self) -> list[dict[str, Any]]:
        """List available SSI indexes (e.g., MAG7.ssi, DEFI.ssi)."""
        data = self._get("/openapi/v1/indices/list")
        return _unwrap(data)

    def get_index_detail(self, symbol: str) -> dict[str, Any]:
        """Index details: composition, returns, signal."""
        return self._get(f"/openapi/v1/indices/{symbol}")

    def get_index_history(self, symbol: str, days: int = 30) -> list[dict[str, Any]]:
        """Historical daily values of an index."""
        data = self._get(
            f"/openapi/v1/indices/{symbol}/history",
            params={"days": days},
        )
        return _unwrap(data)

    # ------------------------------------------------------------------ #
    # Sectors (market regime proxy)
    # ------------------------------------------------------------------ #

    def get_sectors(self) -> list[dict[str, Any]]:
        """Sector performance breakdown (BTC, ETH, L1, DeFi, AI, etc)."""
        data = self._get("/openapi/v1/sectors/list")
        return _unwrap(data)


def _unwrap(payload: Any) -> list[dict[str, Any]]:
    """Most SoSoValue endpoints wrap data in {code, msg, data: [...]}.

    This handles either shape uniformly.
    """
    if isinstance(payload, dict) and "data" in payload:
        inner = payload["data"]
        if isinstance(inner, list):
            return inner
        if isinstance(inner, dict) and "list" in inner and isinstance(inner["list"], list):
            return inner["list"]
        return [inner]
    if isinstance(payload, list):
        return payload
    return [payload] if payload else []
