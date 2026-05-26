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
        """Closed positions — single page (≤500).

        For complete history, use :meth:`get_position_history_paginated`,
        which slides ``endTime`` backwards until the window is exhausted.

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

    def get_position_history_paginated(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        page_limit: int = 500,
        max_pages: int = 40,
        account_id: int | None = None,
        progress_cb=None,
    ) -> list[dict[str, Any]]:
        """Fetch ALL closed positions in [start_ms, end_ms] via sliding-window pagination.

        SoDEX returns positions newest-first within a [startTime, endTime] window
        with a hard cap of ``limit`` per request. To collect everything, we keep
        the same ``startTime`` but slide ``endTime`` back to the oldest position
        seen on each page, then re-request.

        ``progress_cb(page_idx, total_so_far)`` is called after each page if
        provided — useful for showing a live progress message.

        Stops when:
          - A page returns fewer than ``page_limit`` rows (end of history), OR
          - ``max_pages`` reached (safety cap, default 40 → up to 20k positions), OR
          - The oldest position on a page is at-or-before ``start_ms``.
        """
        out: list[dict[str, Any]] = []
        seen_keys: set = set()
        current_end = end_ms

        for page_idx in range(max_pages):
            page = self.get_position_history(
                symbol=symbol,
                start_ms=start_ms,
                end_ms=current_end,
                limit=page_limit,
                account_id=account_id,
            )
            if not page:
                break

            # Deduplicate as we go — the boundary timestamp might be inclusive
            # on both sides, causing one repeated row between pages.
            for p in page:
                k = (
                    p.get("symbol"),
                    p.get("positionSide") or p.get("side"),
                    p.get("createdAt"),
                    p.get("updatedAt"),
                    p.get("realizedPnL") or p.get("pnl"),
                )
                if k not in seen_keys:
                    seen_keys.add(k)
                    out.append(p)

            if progress_cb is not None:
                progress_cb(page_idx + 1, len(out))

            # End of history if the page is short.
            if len(page) < page_limit:
                break

            # Slide endTime to the oldest createdAt seen on this page.
            ts_field = "createdAt" if "createdAt" in page[0] else "updatedAt"
            try:
                oldest = min(
                    int(p[ts_field])
                    for p in page
                    if p.get(ts_field) is not None
                )
            except (ValueError, TypeError):
                break

            # Stop if we've reached past the user's startTime.
            if start_ms is not None and oldest <= start_ms:
                break

            # Subtract 1 ms so we don't refetch the boundary row.
            current_end = oldest - 1

        return out

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

    # ------------------------------------------------------------------ #
    # Public leaderboard (served from mainnet-data, NOT mainnet-gw)
    # ------------------------------------------------------------------ #

    LEADERBOARD_BASE = "https://mainnet-data.sodex.dev/api/v1"

    def get_leaderboard_rank(
        self,
        address: str,
        window_type: str = "30d",
        sort_by: str = "volume",
    ) -> dict[str, Any]:
        """Lookup a single wallet's leaderboard rank.

        Args:
            address     : EVM wallet address.
            window_type : "7d" or "30d".
            sort_by     : "volume" (default) or "pnl". Volume rank is the more
                          meaningful signal — the leaderboard includes ~100k+
                          dormant wallets, so PNL rank skews toward "bottom".

        Response shape::

            { "window_type": "30D",
              "wallet_address": "0x…",
              "found": true | false,
              "snapshot_ts": int,
              "item": {                                # absent when found=false
                "wallet_address": "0x…", "account_id": int,
                "pnl_usd": str, "volume_usd": str, "rank": int
              } }

        ``found=false`` when the wallet has no closed positions in the window.
        """
        url = f"{self.LEADERBOARD_BASE}/leaderboard/rank"
        params = {
            "window_type": window_type,
            "wallet_address": address,
            "sort_by": sort_by,
            "sort_order": "desc",
        }
        r = self._client.get(url, params=params, headers={"Accept": "application/json"})
        r.raise_for_status()
        return self._unwrap(r.json()) or {}

    def get_leaderboard(
        self,
        window_type: str = "30d",
        sort_by: str = "pnl",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """SoDEX public leaderboard.

        Discovered by inspecting the sodex.com frontend JS bundle. Served from
        a different gateway than the per-account endpoints (`mainnet-data`
        instead of `mainnet-gw`). No auth required.

        Args:
            window_type : "7d" or "30d". Other windows return 400.
            sort_by     : "pnl" or "volume".
            sort_order  : "desc" or "asc".
            page        : 1-based.
            page_size   : one of 10, 20, 50.

        Returns:
            ``{"window_type": "30D", "page": 1, "page_size": 50, "total": int,
               "snapshot_ts": ms, "items": [
                   {"wallet_address": "0x…", "account_id": int,
                    "pnl_usd": str, "volume_usd": str, "rank": int}, …]}``
        """
        url = f"{self.LEADERBOARD_BASE}/leaderboard"
        params = {
            "window_type": window_type,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "page": page,
            "page_size": page_size,
        }
        r = self._client.get(url, params=params, headers={"Accept": "application/json"})
        r.raise_for_status()
        return self._unwrap(r.json()) or {}
