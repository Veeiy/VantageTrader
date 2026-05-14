"""DXLink websocket streamer for tastytrade market data.

We only consume the Greeks event here — that's what the calendar strategy
needs (theta, delta, IV per option streamer symbol). Quote/Trade events can
be added later if the strategy needs live underlying ticks.

Protocol summary (from tastytrade DXLink docs):
    1. WS connect to the url returned by /api-quote-tokens (data.dxlink-url).
    2. SETUP   -> server replies AUTH_STATE: UNAUTHORIZED
    3. AUTH    -> server replies AUTH_STATE: AUTHORIZED
    4. CHANNEL_REQUEST (channel=1, service=FEED, contract=AUTO)
    5. FEED_SETUP (declare which event fields we want in COMPACT form)
    6. FEED_SUBSCRIPTION { add: [{type:"Greeks", symbol:".SPY240614C500"}] }
    7. Receive FEED_DATA messages -> decode COMPACT array into dicts.

COMPACT format:
    data = [ "Greeks", [ <field0_value>, <field1_value>, ..., <eventSymbol>, ... ] ]
The fields are in the order we declared in `acceptEventFields`.
Server may concatenate multiple event records in the inner array; we slice it
into chunks of len(fields).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

import websockets
from websockets.exceptions import ConnectionClosed

log = logging.getLogger(__name__)

GREEKS_FIELDS = [
    "eventSymbol",
    "price",
    "volatility",
    "delta",
    "gamma",
    "theta",
    "vega",
    "rho",
]


@dataclass
class Greeks:
    symbol: str
    price: float | None = None
    volatility: float | None = None  # IV as decimal (0.20 = 20%)
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None       # daily theta per share (negative for long options)
    vega: float | None = None
    rho: float | None = None

    @classmethod
    def from_row(cls, fields: list[str], row: list[Any]) -> "Greeks":
        kwargs: dict[str, Any] = {"symbol": ""}
        for fname, value in zip(fields, row):
            if fname == "eventSymbol":
                kwargs["symbol"] = value
            elif fname in {"price", "volatility", "delta", "gamma", "theta", "vega", "rho"}:
                try:
                    kwargs[fname] = float(value) if value not in ("NaN", None, "") else None
                except (TypeError, ValueError):
                    kwargs[fname] = None
        return cls(**kwargs)


class DXLinkStreamer:
    """Async DXLink client. Maintains the latest Greeks per subscribed symbol.

    Usage:
        async with DXLinkStreamer(url, token) as s:
            await s.subscribe_greeks([".SPY240614C500", ...])
            g = s.latest_greeks(".SPY240614C500")
    """

    KEEPALIVE_INTERVAL = 30

    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._greeks: dict[str, Greeks] = {}
        self._subscribed: set[str] = set()
        self._reader_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._channel_ready = asyncio.Event()
        self._auth_ok = asyncio.Event()
        self._closed = False

    async def __aenter__(self) -> "DXLinkStreamer":
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def connect(self) -> None:
        log.info("DXLink: connecting to %s", self.url)
        self._ws = await websockets.connect(self.url, max_size=2**22)
        self._reader_task = asyncio.create_task(self._reader_loop(), name="dxlink-reader")
        await self._send({
            "type": "SETUP",
            "channel": 0,
            "version": "0.1-vantage-trader",
            "keepaliveTimeout": 60,
            "acceptKeepaliveTimeout": 60,
        })
        await self._send({"type": "AUTH", "channel": 0, "token": self.token})
        await asyncio.wait_for(self._auth_ok.wait(), timeout=15)

        await self._send({
            "type": "CHANNEL_REQUEST",
            "channel": 1,
            "service": "FEED",
            "parameters": {"contract": "AUTO"},
        })
        await asyncio.wait_for(self._channel_ready.wait(), timeout=15)

        await self._send({
            "type": "FEED_SETUP",
            "channel": 1,
            "acceptAggregationPeriod": 1.0,
            "acceptDataFormat": "COMPACT",
            "acceptEventFields": {"Greeks": GREEKS_FIELDS},
        })
        self._keepalive_task = asyncio.create_task(self._keepalive_loop(), name="dxlink-keepalive")
        log.info("DXLink: ready")

    async def close(self) -> None:
        self._closed = True
        for task in (self._reader_task, self._keepalive_task):
            if task is not None:
                task.cancel()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()

    # ---- subscriptions ---------------------------------------------------

    async def subscribe_greeks(self, symbols: Iterable[str]) -> None:
        new_syms = [s for s in symbols if s not in self._subscribed]
        if not new_syms:
            return
        await self._send({
            "type": "FEED_SUBSCRIPTION",
            "channel": 1,
            "add": [{"type": "Greeks", "symbol": s} for s in new_syms],
        })
        self._subscribed.update(new_syms)
        log.debug("DXLink: subscribed greeks for %d new symbols", len(new_syms))

    async def unsubscribe_greeks(self, symbols: Iterable[str]) -> None:
        rm = [s for s in symbols if s in self._subscribed]
        if not rm:
            return
        await self._send({
            "type": "FEED_SUBSCRIPTION",
            "channel": 1,
            "remove": [{"type": "Greeks", "symbol": s} for s in rm],
        })
        for s in rm:
            self._subscribed.discard(s)
            self._greeks.pop(s, None)

    async def wait_for_greeks(
        self, symbols: list[str], timeout: float = 5.0
    ) -> dict[str, Greeks]:
        """Wait up to `timeout` seconds for at least one greeks message for each symbol."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            present = {s: self._greeks[s] for s in symbols if s in self._greeks}
            if len(present) == len(symbols):
                return present
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return present
            await asyncio.sleep(0.1)

    def latest_greeks(self, symbol: str) -> Greeks | None:
        return self._greeks.get(symbol)

    # ---- internals -------------------------------------------------------

    async def _send(self, message: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("websocket not connected")
        await self._ws.send(json.dumps(message))

    async def _reader_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning("DXLink: non-JSON frame ignored: %r", raw[:200])
                    continue
                self._handle_message(msg)
        except ConnectionClosed:
            if not self._closed:
                log.warning("DXLink: connection closed unexpectedly")
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("DXLink: reader loop error")

    async def _keepalive_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.KEEPALIVE_INTERVAL)
                await self._send({"type": "KEEPALIVE", "channel": 0})
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("DXLink: keepalive error")

    def _handle_message(self, msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype == "AUTH_STATE":
            state = msg.get("state")
            if state == "AUTHORIZED":
                self._auth_ok.set()
            elif state == "UNAUTHORIZED":
                log.debug("DXLink: AUTH_STATE UNAUTHORIZED (awaiting auth)")
        elif mtype == "CHANNEL_OPENED":
            if msg.get("channel") == 1:
                self._channel_ready.set()
        elif mtype == "FEED_DATA":
            self._handle_feed_data(msg)
        elif mtype == "KEEPALIVE":
            pass
        elif mtype == "ERROR":
            log.error("DXLink ERROR: %s", msg)
        else:
            log.debug("DXLink: unhandled message type=%s", mtype)

    def _handle_feed_data(self, msg: dict[str, Any]) -> None:
        # data shape: ["Greeks", [val1, val2, ..., valN, val1, val2, ...]]
        data = msg.get("data", [])
        if len(data) < 2 or data[0] != "Greeks":
            return
        flat = data[1]
        n = len(GREEKS_FIELDS)
        if not flat or len(flat) % n != 0:
            log.debug("DXLink: malformed Greeks row, len=%d expect multiple of %d", len(flat), n)
            return
        for i in range(0, len(flat), n):
            row = flat[i : i + n]
            g = Greeks.from_row(GREEKS_FIELDS, row)
            if g.symbol:
                self._greeks[g.symbol] = g
