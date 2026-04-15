"""
FunkBridge WebSocket interface.

Connects to the esp32-isotp-ble-bridge-c7vag over WebSocket (WiFi AP or Station
mode). The ESP32 handles all ISO-TP framing in firmware — we just send raw UDS
payloads and receive raw UDS responses.

WebSocket endpoint: ws://<host>/ws  (default host: funkbridge.local or 192.168.4.1)

Wire protocol: binary frames
  TX: raw UDS request bytes (no framing — ESP32 wraps in ISO-TP)
  RX: raw UDS response bytes (ESP32 unwraps ISO-TP)
"""
from __future__ import annotations

import asyncio

import aiohttp

from .base import BaseInterface, InterfaceError

DEFAULT_HOST = "funkbridge.local"
DEFAULT_PORT = 80
CONNECT_TIMEOUT = 10.0


class FunkBridgeInterface(BaseInterface):
    """
    FunkBridge WebSocket interface for ESP32 ISO-TP CAN bridge.

    The ESP32 firmware handles:
      - ISO-TP (ISO 15765-2) framing and flow control
      - CAN bus timing
      - TX/RX ID management

    We just push and pull raw UDS payloads.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._url = f"ws://{host}:{port}/ws"
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    async def open(self) -> None:
        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(
                self._url,
                timeout=aiohttp.ClientTimeout(total=CONNECT_TIMEOUT),
                heartbeat=5.0,
            )
        except Exception as e:
            await self._session.close()
            raise InterfaceError(f"FunkBridge: cannot connect to {self._url}: {e}") from e

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._session:
            await self._session.close()
            self._session = None

    async def transact(self, request: bytes, timeout_ms: int = 2000) -> bytes:
        if not self._ws:
            raise InterfaceError("FunkBridge: not connected (call open() first)")

        await self._ws.send_bytes(request)

        try:
            msg = await asyncio.wait_for(
                self._ws.receive(),
                timeout=timeout_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            raise InterfaceError(
                f"FunkBridge: timeout after {timeout_ms}ms "
                f"waiting for response to {request[:4].hex()}"
            )

        if msg.type == aiohttp.WSMsgType.BINARY:
            return msg.data
        if msg.type == aiohttp.WSMsgType.ERROR:
            raise InterfaceError(f"FunkBridge: WebSocket error: {msg.data}")
        if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING):
            raise InterfaceError("FunkBridge: connection closed by peer")

        raise InterfaceError(f"FunkBridge: unexpected message type {msg.type}")

    def __repr__(self) -> str:
        status = "connected" if self._ws else "disconnected"
        return f"FunkBridgeInterface({self.host}:{self.port} [{status}])"
