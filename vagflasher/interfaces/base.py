"""
Hardware interface layer.

Each interface wraps the physical transport (J2534 DLL, WebSocket to ESP32,
SocketCAN) and exposes a single async method:

    async def transact(request: bytes, timeout_ms: int) -> bytes

The platform layer never talks to hardware directly — it only calls transact().
This means swapping cables (J2534 → FunkBridge → SocketCAN) requires changing
exactly one line in the CLI.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class InterfaceError(Exception):
    pass


class BaseInterface(ABC):
    """Abstract base for all hardware interfaces."""

    @abstractmethod
    async def open(self) -> None:
        """Open the interface and connect to the vehicle."""

    @abstractmethod
    async def close(self) -> None:
        """Disconnect cleanly."""

    @abstractmethod
    async def transact(self, request: bytes, timeout_ms: int = 2000) -> bytes:
        """
        Send a UDS request and receive the response.
        Handles ISO-TP framing internally.
        Raises InterfaceError on timeout or transport error.
        """

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, *_):
        await self.close()
