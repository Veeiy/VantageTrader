"""Tests for OAuth refresh-token auth in TastytradeClient.

Uses httpx.MockTransport to drive the client through token exchange,
authenticated calls, near-expiry preemptive refresh, and 401-triggered
refresh-and-retry.
"""
from __future__ import annotations

import time

import httpx
import pytest

from vantage_trader.tastytrade.client import TastytradeClient, TastytradeError


def _build_client(handler) -> TastytradeClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        base_url="https://api.cert.tastyworks.com",
        transport=transport,
    )
    return TastytradeClient(
        client_secret="secret-xyz",
        refresh_token="refresh-abc",
        environment="sandbox",
        client=http,
    )


@pytest.mark.asyncio
async def test_login_exchanges_refresh_token_for_access_token():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/oauth/token"
        assert request.method == "POST"
        body = dict(p.split("=") for p in request.content.decode().split("&"))
        assert body["grant_type"] == "refresh_token"
        assert body["client_secret"] == "secret-xyz"
        assert body["refresh_token"] == "refresh-abc"
        return httpx.Response(200, json={"access_token": "atk-1", "expires_in": 900})

    client = _build_client(handler)
    await client.login()
    assert client._access_token == "atk-1"
    assert client._access_expires_at > time.monotonic()
    await client.close()


@pytest.mark.asyncio
async def test_authenticated_call_sends_bearer_header():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "atk-1", "expires_in": 900})
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"data": {"items": []}})

    client = _build_client(handler)
    await client.login()
    await client.list_accounts()
    assert seen["auth"] == "Bearer atk-1"
    await client.close()


@pytest.mark.asyncio
async def test_preemptive_refresh_when_token_near_expiry():
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path == "/oauth/token":
            token_calls += 1
            return httpx.Response(
                200,
                json={"access_token": f"atk-{token_calls}", "expires_in": 900},
            )
        return httpx.Response(200, json={"data": {"items": []}})

    client = _build_client(handler)
    await client.login()
    assert token_calls == 1

    # Force expiry into the leeway window so the next call must refresh.
    client._access_expires_at = time.monotonic() + 10  # < REFRESH_LEEWAY_SECONDS (60)

    await client.list_accounts()
    assert token_calls == 2
    assert client._access_token == "atk-2"
    await client.close()


@pytest.mark.asyncio
async def test_401_triggers_refresh_and_retries_once():
    token_calls = 0
    accounts_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, accounts_calls
        if request.url.path == "/oauth/token":
            token_calls += 1
            return httpx.Response(
                200,
                json={"access_token": f"atk-{token_calls}", "expires_in": 900},
            )
        # First call with atk-1 returns 401; second call succeeds.
        accounts_calls += 1
        if accounts_calls == 1:
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(200, json={"data": {"items": []}})

    client = _build_client(handler)
    await client.login()
    await client.list_accounts()
    assert token_calls == 2  # initial + refresh after 401
    assert accounts_calls == 2  # original + retry
    await client.close()


@pytest.mark.asyncio
async def test_oauth_failure_raises_tastytrade_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = _build_client(handler)
    with pytest.raises(TastytradeError, match="OAuth refresh failed"):
        await client.login()
    await client.close()


@pytest.mark.asyncio
async def test_missing_access_token_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"expires_in": 900})  # no access_token

    client = _build_client(handler)
    with pytest.raises(TastytradeError, match="no access_token"):
        await client.login()
    await client.close()
