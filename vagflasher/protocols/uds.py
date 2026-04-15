"""
UDS (ISO 14229) service layer.

Stateless helpers — each takes raw bytes in, returns raw bytes out.
The interface layer handles transport; this layer handles meaning.

Flash sequence for ME17.5 / EDC17 (from RevFlash-J2534 RE):
  1. DiagnosticSession(0x03 programming)
  2. SecurityAccess seed request → key response  (SA2, BCB-keyed)
  3. RequestDownload(address, size)
  4. EraseMemory  (Bosch extended service)
  5. TransferData (bootloader chunks)
  6. RequestTransferExit
  7. TransferData (calibration blocks)
  8. RequestTransferExit
  9. ECUReset

ME7.1.1 quirk: extra DiagnosticSession(0x85) + wait for ECU disconnect
before step 1 above.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Service(IntEnum):
    DIAGNOSTIC_SESSION    = 0x10
    ECU_RESET             = 0x11
    SECURITY_ACCESS       = 0x27
    COMMUNICATION_CONTROL = 0x28
    TESTER_PRESENT        = 0x3E
    READ_DATA_BY_ID       = 0x22
    WRITE_DATA_BY_ID      = 0x2E
    REQUEST_DOWNLOAD      = 0x34
    REQUEST_UPLOAD        = 0x35
    TRANSFER_DATA         = 0x36
    TRANSFER_EXIT         = 0x37
    ERASE_MEMORY          = 0xFF  # Bosch-specific (not in ISO standard)


class Session(IntEnum):
    DEFAULT     = 0x01
    PROGRAMMING = 0x02
    EXTENDED    = 0x03
    BOSCH_85    = 0x85  # ME7.1.1 intermediate session


class NRC(IntEnum):
    """Negative response codes (ISO 14229 Table A.1)."""
    SUB_NOT_SUPPORTED          = 0x12
    INCORRECT_MSG_LEN          = 0x13
    CONDITIONS_NOT_CORRECT     = 0x22
    REQUEST_SEQUENCE_ERROR     = 0x24
    REQUEST_OUT_OF_RANGE       = 0x31
    SECURITY_ACCESS_DENIED     = 0x33
    INVALID_KEY                = 0x35
    EXCEEDED_ATTEMPTS          = 0x36
    REQUIRED_DELAY_NOT_EXPIRED = 0x37
    UPLOAD_DOWNLOAD_REFUSED    = 0x70
    TRANSFER_DATA_SUSPENDED    = 0x71
    GENERAL_PROG_FAILURE       = 0x72
    WRONG_BLOCK_SEQ_COUNTER    = 0x73
    RESPONSE_PENDING           = 0x78  # keep waiting


@dataclass
class UDSResponse:
    service: int
    data: bytes
    negative: bool = False
    nrc: int = 0

    @property
    def ok(self) -> bool:
        return not self.negative

    @property
    def pending(self) -> bool:
        return self.negative and self.nrc == NRC.RESPONSE_PENDING

    def nrc_name(self) -> str:
        try:
            return NRC(self.nrc).name
        except ValueError:
            return f"0x{self.nrc:02X}"

    def __repr__(self) -> str:
        if self.negative:
            return f"UDSResponse(NRC={self.nrc_name()})"
        return f"UDSResponse(svc=0x{self.service:02X} len={len(self.data)})"


def parse_response(raw: bytes) -> UDSResponse:
    """Parse a raw UDS response frame into a UDSResponse."""
    if not raw:
        raise ValueError("Empty UDS response")
    if raw[0] == 0x7F:
        # Negative: 7F <original_svc> <nrc>
        return UDSResponse(service=raw[1] if len(raw) > 1 else 0,
                           data=raw,
                           negative=True,
                           nrc=raw[2] if len(raw) > 2 else 0)
    # Positive: <svc+0x40> <data...>
    return UDSResponse(service=raw[0] - 0x40, data=raw[1:])


# ── Request builders ──────────────────────────────────────────────────────────

def req_diagnostic_session(session: int) -> bytes:
    return bytes([Service.DIAGNOSTIC_SESSION, session])


def req_tester_present(suppress_response: bool = True) -> bytes:
    return bytes([Service.TESTER_PRESENT, 0x80 if suppress_response else 0x00])


def req_ecu_reset(reset_type: int = 0x01) -> bytes:
    return bytes([Service.ECU_RESET, reset_type])


def req_security_access_seed(level: int) -> bytes:
    """Request seed (odd level byte = seed request)."""
    return bytes([Service.SECURITY_ACCESS, level])


def req_security_access_key(level: int, key: bytes) -> bytes:
    """Send calculated key (even level byte = key send)."""
    return bytes([Service.SECURITY_ACCESS, level + 1]) + key


def req_request_download(address: int, size: int,
                          addr_len: int = 3, size_len: int = 3) -> bytes:
    """
    Build RequestDownload (0x34).
    addr_and_len_format byte: high nibble = addr bytes, low nibble = size bytes.
    """
    fmt = (addr_len << 4) | size_len
    return (bytes([Service.REQUEST_DOWNLOAD, 0x00, fmt])
            + address.to_bytes(addr_len, 'big')
            + size.to_bytes(size_len, 'big'))


def req_transfer_data(block_seq: int, chunk: bytes) -> bytes:
    """Build TransferData (0x36) with rolling block sequence counter."""
    return bytes([Service.TRANSFER_DATA, block_seq & 0xFF]) + chunk


def req_transfer_exit() -> bytes:
    return bytes([Service.TRANSFER_EXIT])
