"""Async REST client for tastytrade.

Docs: https://developer.tastytrade.com/open-api-spec/
Sandbox:    https://api.cert.tastyworks.com
Production: https://api.tastyworks.com

This is intentionally a slim, hand-rolled client covering only what the bot
needs: session auth, account discovery, positions, order placement, and
fetching the DXLink quote-streamer token. If you need broader coverage,
swap in the community `tastytrade` SDK.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import OrderRequest, Position

log = logging.getLogger(__name__)

SANDBOX_BASE_URL = "https://api.cert.tastyworks.com"
LIVE_BASE_URL = "https://api.tastyworks.com"


class TastytradeError(Exception):
    pass


class TastytradeClient:
    def __init__(
        self,
        username: str,
        password: str,
        environment: str = "sandbox",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if environment == "sandbox":
            self.base_url = SANDBOX_BASE_URL
        elif environment == "live":
            self.base_url = LIVE_BASE_URL
        else:
            raise ValueError(f"Unknown environment: {environment}")
        self._username = username
        self._password = password
        self._session_token: str | None = None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": "vantage-trader/0.1"},
        )

    async def __aenter__(self) -> "TastytradeClient":
        await self.login()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # ---- auth -------------------------------------------------------------

    async def login(self) -> None:
        resp = await self._client.post(
            "/sessions",
            json={"login": self._username, "password": self._password},
        )
        self._raise_for_status(resp)
        data = resp.json().get("data", {})
        token = data.get("session-token")
        if not token:
            raise TastytradeError("Login succeeded but no session-token returned")
        self._session_token = token
        log.info("Authenticated to %s as %s", self.base_url, self._username)

    @property
    def _auth_headers(self) -> dict[str, str]:
        if not self._session_token:
            raise TastytradeError("Not logged in. Call login() first.")
        return {"Authorization": self._session_token}

    # ---- accounts ---------------------------------------------------------

    async def list_accounts(self) -> list[dict[str, Any]]:
        resp = await self._client.get(
            "/customers/me/accounts", headers=self._auth_headers
        )
        self._raise_for_status(resp)
        items = resp.json().get("data", {}).get("items", [])
        return [item.get("account", item) for item in items]

    async def get_balances(self, account_number: str) -> dict[str, Any]:
        resp = await self._client.get(
            f"/accounts/{account_number}/balances", headers=self._auth_headers
        )
        self._raise_for_status(resp)
        return resp.json().get("data", {})

    async def get_positions(self, account_number: str) -> list[Position]:
        resp = await self._client.get(
            f"/accounts/{account_number}/positions", headers=self._auth_headers
        )
        self._raise_for_status(resp)
        items = resp.json().get("data", {}).get("items", [])
        positions = []
        for raw in items:
            positions.append(
                Position(
                    symbol=raw.get("symbol", ""),
                    quantity=int(float(raw.get("quantity", 0))),
                    direction=raw.get("quantity-direction", "Zero"),
                    average_open_price=float(raw.get("average-open-price", 0) or 0),
                    raw=raw,
                )
            )
        return positions

    # ---- orders -----------------------------------------------------------

    async def dry_run_order(
        self, account_number: str, order: OrderRequest
    ) -> dict[str, Any]:
        """Validate an order without submitting it. Returns buying-power effect."""
        resp = await self._client.post(
            f"/accounts/{account_number}/orders/dry-run",
            headers=self._auth_headers,
            json=order.to_payload(),
        )
        self._raise_for_status(resp)
        return resp.json().get("data", {})

    async def place_order(
        self, account_number: str, order: OrderRequest
    ) -> dict[str, Any]:
        resp = await self._client.post(
            f"/accounts/{account_number}/orders",
            headers=self._auth_headers,
            json=order.to_payload(),
        )
        self._raise_for_status(resp)
        return resp.json().get("data", {})

    async def list_live_orders(self, account_number: str) -> list[dict[str, Any]]:
        resp = await self._client.get(
            f"/accounts/{account_number}/orders/live", headers=self._auth_headers
        )
        self._raise_for_status(resp)
        return resp.json().get("data", {}).get("items", [])

    # ---- option chains & market metrics ----------------------------------

    async def get_option_chain_nested(self, underlying: str) -> dict[str, Any]:
        """Returns expirations -> strikes -> {call, put} OCC symbols.

        Endpoint: /option-chains/{symbol}/nested
        """
        resp = await self._client.get(
            f"/option-chains/{underlying}/nested", headers=self._auth_headers
        )
        self._raise_for_status(resp)
        return resp.json().get("data", {})

    async def get_market_metrics(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Returns IV rank, IV percentile, earnings date, etc. per underlying.

        Endpoint: /market-metrics?symbols=SPY,QQQ,...
        """
        if not symbols:
            return []
        resp = await self._client.get(
            "/market-metrics",
            headers=self._auth_headers,
            params={"symbols": ",".join(symbols)},
        )
        self._raise_for_status(resp)
        return resp.json().get("data", {}).get("items", [])

    async def get_option_quotes(
        self, occ_symbols: list[str]
    ) -> list[dict[str, Any]]:
        """Bulk snapshot of bid/ask/OI/etc. for option symbols.

        Endpoint: /market-data/by-type?equity-option=...
        Note: greeks (theta, delta, IV) are not on this REST endpoint; for
        those subscribe to the DXLink 'Greeks' event on the streamer symbol.
        """
        if not occ_symbols:
            return []
        # tastytrade caps URL length; chunk to be safe.
        out: list[dict[str, Any]] = []
        chunk = 90
        for i in range(0, len(occ_symbols), chunk):
            batch = occ_symbols[i : i + chunk]
            resp = await self._client.get(
                "/market-data/by-type",
                headers=self._auth_headers,
                params={"equity-option": ",".join(batch)},
            )
            self._raise_for_status(resp)
            items = resp.json().get("data", {}).get("items", [])
            out.extend(items)
        return out

    async def get_equity_quote(self, symbol: str) -> dict[str, Any]:
        """REST snapshot via /market-data/{symbol}. For streaming use DXLink."""
        resp = await self._client.get(
            f"/market-data/{symbol}", headers=self._auth_headers
        )
        self._raise_for_status(resp)
        return resp.json().get("data", {})

    # ---- streamer token ---------------------------------------------------

    async def get_quote_streamer_token(self) -> dict[str, Any]:
        """Returns { token, dxlink-url, level } used to connect to DXLink."""
        resp = await self._client.get(
            "/api-quote-tokens", headers=self._auth_headers
        )
        self._raise_for_status(resp)
        return resp.json().get("data", {})

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.is_success:
            return
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        raise TastytradeError(
            f"HTTP {resp.status_code} on {resp.request.method} "
            f"{resp.request.url.path}: {body}"
        )
