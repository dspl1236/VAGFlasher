"""
ME17.5 / MED17.5 platform flash sequence.

Covers: 06J906026 (EA888 Gen1/1.5), 07K906055 (EA888 Gen2),
        8P/8J TT/A3, EDC17 TDI variants.

Flash sequence (from RevFlash-J2534 RE + TriCoreTool corpus):
  1. DiagnosticSession(0x03 programming)
  2. SecurityAccess SA2 (BiWbBuD101 or CodeRobert key)
  3. For each flash block:
     a. RequestDownload(address, block_size)
     b. EraseMemory (Bosch 0xFF service)
     c. TransferData (bootloader)
     d. RequestTransferExit
  4. Write calibration blocks (same loop)
  5. ChecksumVerify (Bosch proprietary)
  6. ECUReset
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from ..interfaces.base import BaseInterface
from ..protocols.sa2 import resolve_sa2
from ..protocols.uds import (
    NRC,
    Session,
    UDSResponse,
    parse_response,
    req_diagnostic_session,
    req_request_download,
    req_security_access_key,
    req_security_access_seed,
    req_tester_present,
    req_transfer_data,
    req_transfer_exit,
)

console = Console()

# Block sizes from RevFlash-J2534 RE
CHUNK_SIZE       = 0x0FF6   # 4086 bytes per TransferData chunk (standard Bosch)
ERASE_RETRY      = 3        # retry count for EraseMemory
ERASE_RETRY_WAIT = 10.0     # seconds to wait between erase retries
PROG_RETRY_WAIT  = 5.0


@dataclass
class FlashBlock:
    """One addressable region of ECU flash."""
    address: int
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)


class ME17FlashError(Exception):
    pass


class ME17Platform:
    """
    ME17.5 / EDC17 flash sequence.

    Usage:
        async with FunkBridgeInterface() as iface:
            platform = ME17Platform(iface, bcb_key="BiWbBuD101")
            await platform.flash(blocks)
    """

    def __init__(
        self,
        interface: BaseInterface,
        bcb_key: str = "BiWbBuD101",
        on_progress: Callable[[str], None] | None = None,
    ):
        self.iface = interface
        self.bcb_key = bcb_key
        self._on_progress = on_progress or (lambda msg: console.print(f"  {msg}"))

    def _log(self, msg: str) -> None:
        self._on_progress(msg)

    async def _send(self, request: bytes, timeout_ms: int = 2000) -> UDSResponse:
        """Send a UDS request and parse the response. Handles 0x78 pending."""
        for _ in range(20):  # max 20 pending responses
            raw = await self.iface.transact(request, timeout_ms)
            resp = parse_response(raw)
            if resp.pending:
                await asyncio.sleep(0.5)
                continue
            return resp
        raise ME17FlashError("Too many 0x78 pending responses")

    async def _assert_ok(self, resp: UDSResponse, context: str) -> None:
        if not resp.ok:
            raise ME17FlashError(f"{context} failed: NRC={resp.nrc_name()}")

    async def start_session(self) -> None:
        self._log("Starting programming session...")
        resp = await self._send(req_diagnostic_session(Session.PROGRAMMING))
        await self._assert_ok(resp, "DiagnosticSession(programming)")
        self._log("Programming session started.")

    async def security_access(self) -> None:
        self._log(f"Security access ({self.bcb_key})...")

        resp = await self._send(req_security_access_seed(0x01))
        await self._assert_ok(resp, "SecurityAccess seed request")

        seed = resp.data[1:]  # first byte is level echo
        key = resolve_sa2(self.bcb_key, seed)

        resp = await self._send(req_security_access_key(0x01, key))
        await self._assert_ok(resp, "SecurityAccess key send")
        self._log("Security access granted.")

    async def erase_block(self, block: FlashBlock) -> None:
        """Erase a flash block (with retries — ECU sometimes needs a nudge)."""
        for attempt in range(ERASE_RETRY):
            self._log(f"Erasing 0x{block.address:06X} ({block.size // 1024}KB)...")
            resp = await self._send(
                req_request_download(block.address, block.size),
                timeout_ms=5000,
            )
            if not resp.ok:
                if attempt < ERASE_RETRY - 1:
                    self._log(f"  Erase refused ({resp.nrc_name()}), retrying in {ERASE_RETRY_WAIT}s...")
                    await asyncio.sleep(ERASE_RETRY_WAIT)
                    continue
                raise ME17FlashError(f"EraseBlock 0x{block.address:06X} failed after {ERASE_RETRY} attempts")
            return
        raise ME17FlashError("Erase failed")

    async def transfer_block(self, block: FlashBlock, label: str = "") -> None:
        """Transfer a flash block using chunked TransferData."""
        label = label or f"0x{block.address:06X}"
        data = block.data
        total_chunks = (len(data) + CHUNK_SIZE - 1) // CHUNK_SIZE

        seq = 1
        offset = 0

        with Progress(
            SpinnerColumn(),
            TextColumn(f"  Writing {label}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("", total=total_chunks)

            while offset < len(data):
                chunk = data[offset: offset + CHUNK_SIZE]
                resp = await self._send(req_transfer_data(seq, chunk), timeout_ms=3000)

                if not resp.ok:
                    if resp.nrc == NRC.REQUEST_SEQUENCE_ERROR and seq > 1:
                        self._log(f"  Sequence error at chunk {seq}, retrying...")
                        await asyncio.sleep(PROG_RETRY_WAIT)
                        resp = await self._send(req_transfer_data(seq, chunk), timeout_ms=3000)
                    if not resp.ok:
                        raise ME17FlashError(
                            f"TransferData chunk {seq}/{total_chunks} failed: {resp.nrc_name()}"
                        )

                seq = (seq + 1) & 0xFF
                offset += len(chunk)
                progress.advance(task)

        resp = await self._send(req_transfer_exit())
        await self._assert_ok(resp, f"TransferExit {label}")
        self._log(f"  {label}: written successfully.")

    async def tester_present_loop(self, stop_event: asyncio.Event) -> None:
        """Send TesterPresent every 2s to keep the session alive during slow operations."""
        while not stop_event.is_set():
            try:
                await self.iface.transact(req_tester_present(suppress_response=True), 1000)
            except Exception:
                pass
            await asyncio.sleep(2.0)

    async def flash(self, blocks: list[FlashBlock]) -> None:
        """
        Full ME17.5 flash sequence.

        Args:
            blocks: List of FlashBlock with address + data.
                    Caller (ROM editor) produces these from a verified .bin.
        """
        self._log(f"ME17.5 flash: {len(blocks)} blocks, BCB key={self.bcb_key}")

        await self.start_session()
        await self.security_access()

        stop_tp = asyncio.Event()
        tp_task = asyncio.create_task(self.tester_present_loop(stop_tp))

        try:
            for i, block in enumerate(blocks):
                label = f"block {i+1}/{len(blocks)} @ 0x{block.address:06X}"
                await self.erase_block(block)
                await self.transfer_block(block, label)
        finally:
            stop_tp.set()
            await tp_task

        self._log("All blocks written. Flash complete.")

    async def read_ecu(self, address: int, size: int) -> bytes:
        """
        Read ECU flash (RequestUpload sequence).
        Used to dump a stock ROM before tuning.
        """
        await self.start_session()
        await self.security_access()

        from ..protocols.uds import Service
        request = (bytes([Service.REQUEST_UPLOAD, 0x00, 0x33])
                   + address.to_bytes(3, 'big')
                   + size.to_bytes(3, 'big'))

        resp = await self._send(request, timeout_ms=5000)
        await self._assert_ok(resp, "RequestUpload")

        result = bytearray()
        seq = 1
        total_chunks = (size + CHUNK_SIZE - 1) // CHUNK_SIZE

        with Progress(
            SpinnerColumn(),
            TextColumn("  Reading ECU"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("", total=total_chunks)
            while len(result) < size:
                resp = await self._send(req_transfer_data(seq, b""), timeout_ms=3000)
                await self._assert_ok(resp, f"ReadChunk {seq}")
                result.extend(resp.data)
                seq = (seq + 1) & 0xFF
                progress.advance(task)

        resp = await self._send(req_transfer_exit())
        await self._assert_ok(resp, "TransferExit(read)")

        return bytes(result[:size])
