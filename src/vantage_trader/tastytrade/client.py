"""Async REST client for tastytrade.

Auth: OAuth2 refresh-token grant (Personal OAuth Grant).
    Session-token auth (POST /sessions with username+password) was
    discontinued by tastytrade on 2025-12-01. This client exchanges a
    long-lived refresh_token for a short-lived (~15 min) access_token
    via POST /oauth/token, then sends `Authorization: Bearer <access>`
    on every API call. The token is refreshed automatically when it's
    within `REFRESH_LEEWAY_SECONDS` of expiry, or on a 401 response.

How to get the credentials (one-time, via tastytrade web UI):
    1. Manage > API > Open API access -> agree to terms (account-level)
    2. Manage > API > OAuth application -> create app (records client_id,
       client_secret)
    3. Inside the app -> New Personal OAuth Grant (check the scopes you
       need: read, trade, openid, etc.) -> copy the refresh_token

Docs:
    - https://developer.tastytrade.com/api-guides/oauth/
    - https://developer.tastytrade.com/open-api-spec/

Sandbox:    https://api.cert.tastyworks.com  (OAuth flow identical)
Production: https://api.tastyworks.com
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .models import OrderRequest, Position

log = logging.getLogger(__name__)

SANDBOX_BASE_URL = "https://api.cert.tastyworks.com"
LIVE_BASE_URL = "https://api.tastyworks.com"

OAUTH_TOKEN_PATH = "/oauth/token"
REFRESH_LEEWAY_SECONDS = 60   # refresh when this close to expiry
DEFAULT_TOKEN_LIFETIME = 900  # tastytrade default; only used if expires_in is missing


class TastytradeError(Exception):
    pass


class TastytradeClient:
    def __init__(
        self,
        client_secret: str,
        refresh_token: str,
        environment: str = "sandbox",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if environment == "sandbox":
            self.base_url = SANDBOX_BASE_URL
        elif environment == "live":
            self.base_url = LIVE_BASE_URL
        else:
            raise ValueError(f"Unknown environment: {environment}")
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._access_expires_at: float = 0.0
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
        """Initial token exchange. Identical to refresh; kept as a public alias."""
        await self._refresh_access_token()
        log.info("OAuth: authenticated to %s", self.base_url)

    async def _refresh_access_token(self) -> None:
        resp = await self._client.post(
            OAUTH_TOKEN_PATH,
            data={
                "grant_type": "refresh_token",
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if not resp.is_success:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise TastytradeError(
                f"OAuth refresh failed (HTTP {resp.status_code}): {body}"
            )
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise TastytradeError(f"OAuth refresh returned no access_token: {data}")
        lifetime = int(data.get("expires_in") or DEFAULT_TOKEN_LIFETIME)
        self._access_token = token
        self._access_expires_at = time.monotonic() + lifetime
        log.debug("OAuth: new access_token, lifetime=%ds", lifetime)

    async def _ensure_token(self) -> None:
        if self._access_token is None:
            await self._refresh_access_token()
            return
        if time.monotonic() >= self._access_expires_at - REFRESH_LEEWAY_SECONDS:
            await self._refresh_access_token()

    async def _auth_header(self) -> dict[str, str]:
        await self._ensure_token()
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        """One request layer: ensures token, retries once on 401 after forced refresh."""
        headers = await self._auth_header()
        resp = await self._client.request(
            method, path, headers=headers, params=params, json=json
        )
        if resp.status_code == 401:
            log.info("OAuth: 401 on %s %s, refreshing and retrying", method, path)
            await self._refresh_access_token()
            headers = await self._auth_header()
            resp = await self._client.request(
                method, path, headers=headers, params=params, json=json
            )
        self._raise_for_status(resp)
        return resp

    # ---- accounts ---------------------------------------------------------

    async def list_accounts(self) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/customers/me/accounts")
        items = resp.json().get("data", {}).get("items", [])
        return [item.get("account", item) for item in items]

    async def get_balances(self, account_number: str) -> dict[str, Any]:
        resp = await self._request("GET", f"/accounts/{account_number}/balances")
        return resp.json().get("data", {})

    async def get_positions(self, account_number: str) -> list[Position]:
        resp = await self._request("GET", f"/accounts/{account_number}/positions")
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
        resp = await self._request(
            "POST",
            f"/accounts/{account_number}/orders/dry-run",
            json=order.to_payload(),
        )
        return resp.json().get("data", {})

    async def place_order(
        self, account_number: str, order: OrderRequest
    ) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            f"/accounts/{account_number}/orders",
            json=order.to_payload(),
        )
        return resp.json().get("data", {})

    async def list_live_orders(self, account_number: str) -> list[dict[str, Any]]:
        resp = await self._request("GET", f"/accounts/{account_number}/orders/live")
        return resp.json().get("data", {}).get("items", [])

    # ---- option chains & market metrics ----------------------------------

    async def get_option_chain_nested(self, underlying: str) -> dict[str, Any]:
        resp = await self._request("GET", f"/option-chains/{underlying}/nested")
        return resp.json().get("data", {})

    async def get_market_metrics(self, symbols: list[str]) -> list[dict[str, Any]]:
        if not symbols:
            return []
        resp = await self._request(
            "GET", "/market-metrics", params={"symbols": ",".join(symbols)}
        )
        return resp.json().get("data", {}).get("items", [])

    async def get_option_quotes(
        self, occ_symbols: list[str]
    ) -> list[dict[str, Any]]:
        """Bulk snapshot of bid/ask/OI/etc. for option symbols.

        Greeks (theta, delta, IV) are not on this REST endpoint; for those
        subscribe to the DXLink 'Greeks' event on the streamer symbol.
        """
        if not occ_symbols:
            return []
        out: list[dict[str, Any]] = []
        chunk = 90
        for i in range(0, len(occ_symbols), chunk):
            batch = occ_symbols[i : i + chunk]
            resp = await self._request(
                "GET", "/market-data/by-type",
                params={"equity-option": ",".join(batch)},
            )
            items = resp.json().get("data", {}).get("items", [])
            out.extend(items)
        return out

    async def get_equity_quote(self, symbol: str) -> dict[str, Any]:
        resp = await self._request("GET", f"/market-data/{symbol}")
        return resp.json().get("data", {})

    # ---- streamer token ---------------------------------------------------

    async def get_quote_streamer_token(self) -> dict[str, Any]:
        """Returns { token, dxlink-url, level } used to connect to DXLink."""
        resp = await self._request("GET", "/api-quote-tokens")
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
