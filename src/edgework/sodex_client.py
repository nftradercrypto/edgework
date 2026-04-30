"""SoDEX REST API client.

Wave 1 scope: read-only endpoints, which on SoDEX are fully public —
they take `userAddress` (your EVM public address) as part of the URL
and require no auth headers at all. Confirmed by the official docs:

    curl -X GET "${PERPS_ENDPOINT}/accounts/{userAddress}/positions/history" \\
      -H 'Accept: application/json'

This is by design: API keys on SoDEX exist only to *sign write actions*
(EIP-712 typed signatures for new orders, cancels, leverage changes,
transfers, etc). Querying account data needs neither the API key
nor any signing.

Write endpoints (out of scope for Wave 1, planned for Wave 2+) use
EIP-712 signing per the Go SDK at sodex-tech/sodex-go-sdk-public.

Endpoints implemented here:

    Markets (no auth, no address)
      GET /perps/markets/symbols
      GET /perps/markets/{symbol}/klines
      GET /perps/markets/tickers
      GET /perps/markets/{symbol}/orderbook
      GET /perps/markets/mark-prices

    Account (no auth, address in URL)
      GET /perps/accounts/{userAddress}/positions
      GET /perps/accounts/{userAddress}/positions/history    ← Edgework's primary source
      GET /perps/accounts/{userAddress}/orders/history
      GET /perps/accounts/{userAddress}/trades
      GET /perps/accounts/{userAddress}/balances
      GET /perps/accounts/{userAddress}/fee-rate
      GET /perps/accounts/{userAddress}/state
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import get_settings


class SodexAPIError(RuntimeError):
    """Raised when SoDEX returns code != 0 in an otherwise-200 response body."""

    def __init__(self, code: int | None, message: str) -> None:
        super().__init__(f"SoDEX error {code}: {message}")
        self.code = code
        self.message = message


class SodexClient:
    """Read-only SoDEX REST API client.

    No private key required. Pass your wallet's public address
    (the one you use to log into SoDEX) and you can query everything
    Edgework needs.

    Example:
        with SodexClient(user_address="0xe5a7...f935") as client:
            history = client.get_position_history(symbol="BTC-USD")
    """

    def __init__(
        self,
        user_address: str | None = None,
        base_url: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        s = get_settings()
        self.user_address = user_address or s.sodex_user_address
        # base_url is .../api/v1; we append /perps or /spot per call
        self.base_url = (base_url or s.sodex_base_url).rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SodexClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Internal HTTP
    # ------------------------------------------------------------------ #

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Issue a GET to {base_url}{path}. No auth headers."""
        url = f"{self.base_url}{path}"
        r = self._client.get(url, params=params, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        """SoDEX wraps successful responses as {code: 0, data: <...>, timestamp}.

        On error: {code: <negative>, error: <str>, timestamp} — raise.
        """
        if isinstance(payload, dict) and "code" in payload:
            if payload["code"] != 0:
                raise SodexAPIError(payload.get("code"), payload.get("error", "unknown"))
            return payload.get("data")
        return payload

    def _require_address(self) -> str:
        if not self.user_address:
            raise ValueError(
                "user_address is required for account endpoints. "
                "Set SODEX_USER_ADDRESS in .env or pass it to SodexClient(...)."
            )
        return self.user_address

    # ------------------------------------------------------------------ #
    # Market endpoints (perps)
    # ------------------------------------------------------------------ #

    def get_perps_symbols(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """List perpetual symbols (e.g. BTC-USD, ETH-USD)."""
        params = {"symbol": symbol} if symbol else None
        data = self._unwrap(self._get("/perps/markets/symbols", params=params))
        return list(data or [])

    def get_perps_tickers(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """24h ticker stats for perps."""
        params = {"symbol": symbol} if symbol else None
        data = self._unwrap(self._get("/perps/markets/tickers", params=params))
        return list(data or [])

    def get_perps_mark_prices(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Mark price + funding rate snapshot."""
        params = {"symbol": symbol} if symbol else None
        data = self._unwrap(self._get("/perps/markets/mark-prices", params=params))
        return list(data or [])

    def get_perps_klines(
        self,
        symbol: str,
        interval: str = "1h",
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Candles for a perps symbol.

        interval: 1m | 5m | 15m | 30m | 1h | 4h | 1D | 1W | 1M
        """
        params: dict[str, Any] = {"interval": interval, "limit": limit}
        if start_ms:
            params["startTime"] = start_ms
        if end_ms:
            params["endTime"] = end_ms
        data = self._unwrap(self._get(f"/perps/markets/{symbol}/klines", params=params))
        return list(data or [])

    def get_perps_orderbook(self, symbol: str, limit: int = 50) -> dict[str, Any]:
        """L2 order book snapshot."""
        data = self._unwrap(
            self._get(f"/perps/markets/{symbol}/orderbook", params={"limit": limit})
        )
        return data or {}

    # ------------------------------------------------------------------ #
    # Account endpoints (perps) — public, address in URL
    # ------------------------------------------------------------------ #

    def get_balances(self, account_id: int | None = None) -> dict[str, Any]:
        """Current account balances (perps wallet)."""
        addr = self._require_address()
        params = {"accountID": account_id} if account_id else None
        data = self._unwrap(
            self._get(f"/perps/accounts/{addr}/balances", params=params)
        )
        return data or {}

    def get_open_positions(self, account_id: int | None = None) -> dict[str, Any]:
        """Currently open positions."""
        addr = self._require_address()
        params = {"accountID": account_id} if account_id else None
        data = self._unwrap(
            self._get(f"/perps/accounts/{addr}/positions", params=params)
        )
        return data or {}

    def get_position_history(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
        account_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Closed positions — Edgework's primary data source.

        Each entry is a `Position` (see schema): includes avgEntryPrice,
        avgClosePrice, realizedPnL (already net of fees + liquidation),
        cumTradingFee, size (signed: + long, - short), createdAt, updatedAt.
        """
        addr = self._require_address()
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if start_ms:
            params["startTime"] = start_ms
        if end_ms:
            params["endTime"] = end_ms
        if account_id:
            params["accountID"] = account_id
        data = self._unwrap(
            self._get(f"/perps/accounts/{addr}/positions/history", params=params)
        )
        return list(data or [])

    def get_order_history(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
        account_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Historical orders (filled, canceled, expired)."""
        addr = self._require_address()
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if start_ms:
            params["startTime"] = start_ms
        if end_ms:
            params["endTime"] = end_ms
        if account_id:
            params["accountID"] = account_id
        data = self._unwrap(
            self._get(f"/perps/accounts/{addr}/orders/history", params=params)
        )
        return list(data or [])

    def get_user_trades(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
        account_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Historical fill-level trade executions."""
        addr = self._require_address()
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if start_ms:
            params["startTime"] = start_ms
        if end_ms:
            params["endTime"] = end_ms
        if account_id:
            params["accountID"] = account_id
        data = self._unwrap(
            self._get(f"/perps/accounts/{addr}/trades", params=params)
        )
        return list(data or [])

    def get_fee_rate(
        self,
        symbol: str | None = None,
        account_id: int | None = None,
    ) -> dict[str, Any]:
        """Effective maker/taker fee rates and tier breakdown."""
        addr = self._require_address()
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        if account_id:
            params["accountID"] = account_id
        data = self._unwrap(
            self._get(f"/perps/accounts/{addr}/fee-rate", params=params)
        )
        return data or {}

    def get_account_state(self, account_id: int | None = None) -> dict[str, Any]:
        """Comprehensive account snapshot (balances + positions + open orders)."""
        addr = self._require_address()
        params = {"accountID": account_id} if account_id else None
        data = self._unwrap(
            self._get(f"/perps/accounts/{addr}/state", params=params)
        )
        return data or {}
