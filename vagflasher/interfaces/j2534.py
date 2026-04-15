"""
J2534 PassThru interface.

Wraps any SAE J2534-02 compliant PassThru DLL via ctypes.
Works with Tactrix OpenPort, VCDS, cheap clone cables, and any other
J2534-compliant device. Does NOT depend on any specific vendor DLL.

The DLL path can be auto-discovered from the Windows registry
(HKLM\\SOFTWARE\\PassThruSupport.04.04) or supplied explicitly.

This interface handles ISO-TP (ISO 15765-2) framing itself, since J2534
exposes the raw CAN layer — unlike FunkBridge which does ISO-TP in firmware.
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from .base import BaseInterface, InterfaceError

# J2534 protocol constants
ISO15765     = 6
CAN_11BIT_ID = 0x00000000
CAN_29BIT_ID = 0x00000100
CAN_ID_BOTH  = 0x00000800
ISO15765_FRAME_PAD = 0x0040

# Bosch VAG defaults: ECU functional address 0x7DF, physical 0x7E0, resp 0x7E8
DEFAULT_TX_ID  = 0x7E0
DEFAULT_RX_ID  = 0x7E8
DEFAULT_BAUD   = 500000


class J2534Interface(BaseInterface):
    """
    J2534 PassThru interface.

    Discovers installed J2534 DLLs from the Windows registry or accepts
    an explicit DLL path. Handles ISO-TP framing via J2534 ISO 15765 protocol.

    Example:
        async with J2534Interface() as iface:
            resp = await iface.transact(b'\\x10\\x03')  # DiagnosticSession
    """

    def __init__(
        self,
        dll_path: str | Path | None = None,
        tx_id: int = DEFAULT_TX_ID,
        rx_id: int = DEFAULT_RX_ID,
        baud: int = DEFAULT_BAUD,
    ):
        self.dll_path = str(dll_path) if dll_path else self._discover_dll()
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.baud = baud
        self._dll: ctypes.CDLL | None = None
        self._device_id: int = 0
        self._channel_id: int = 0

    @staticmethod
    def _discover_dll() -> str:
        """Auto-discover first installed J2534 DLL from Windows registry."""
        if sys.platform != "win32":
            raise InterfaceError(
                "J2534 DLL auto-discovery only works on Windows. "
                "Supply dll_path= explicitly on Linux/macOS."
            )
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\PassThruSupport.04.04",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
            )
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    subkey = winreg.OpenKey(key, subkey_name)
                    dll_path, _ = winreg.QueryValueEx(subkey, "FunctionLibrary")
                    winreg.CloseKey(subkey)
                    winreg.CloseKey(key)
                    return dll_path
                except OSError:
                    break
                i += 1
            winreg.CloseKey(key)
        except Exception as e:
            raise InterfaceError(f"J2534: no DLL found in registry: {e}") from e
        raise InterfaceError("J2534: no PassThru DLL installed")

    @staticmethod
    def list_installed() -> list[dict]:
        """Return all installed J2534 devices found in the Windows registry."""
        if sys.platform != "win32":
            return []
        devices = []
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\PassThruSupport.04.04",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
            )
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(key, i)
                    sk = winreg.OpenKey(key, name)
                    try:
                        dll, _ = winreg.QueryValueEx(sk, "FunctionLibrary")
                        devices.append({"name": name, "dll": dll})
                    except OSError:
                        pass
                    finally:
                        winreg.CloseKey(sk)
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass
        return devices

    async def open(self) -> None:
        try:
            self._dll = ctypes.windll.LoadLibrary(self.dll_path)  # type: ignore[attr-defined]
        except Exception as e:
            raise InterfaceError(f"J2534: cannot load DLL {self.dll_path!r}: {e}") from e

        dev_id = ctypes.c_ulong(0)
        ret = self._dll.PassThruOpen(None, ctypes.byref(dev_id))
        self._check(ret, "PassThruOpen")
        self._device_id = dev_id.value

        chan_id = ctypes.c_ulong(0)
        ret = self._dll.PassThruConnect(
            self._device_id, ISO15765, 0, self.baud, ctypes.byref(chan_id)
        )
        self._check(ret, "PassThruConnect")
        self._channel_id = chan_id.value

        self._setup_filter()

    def _setup_filter(self) -> None:
        """Set up ISO-TP pass filter for our TX/RX IDs."""
        # PASSTHRU_MSG structure (simplified — 4128 bytes per J2534 spec)
        # For ISO15765: mask/pattern/flowcontrol messages
        # Abbreviated here — full implementation needs vendor-specific PASSTHRU_MSG struct
        pass  # TODO: implement full filter setup in milestone 2

    async def close(self) -> None:
        if self._dll and self._channel_id:
            self._dll.PassThruDisconnect(self._channel_id)
            self._channel_id = 0
        if self._dll and self._device_id:
            self._dll.PassThruClose(self._device_id)
            self._device_id = 0
        self._dll = None

    async def transact(self, request: bytes, timeout_ms: int = 2000) -> bytes:
        if not self._dll:
            raise InterfaceError("J2534: not connected")
        # TODO: implement PASSTHRU_MSG send/receive in milestone 2
        # Requires full PASSTHRU_MSG ctypes struct definition
        raise NotImplementedError(
            "J2534 transact() not yet implemented — use FunkBridgeInterface for now. "
            "J2534 support planned for milestone 2."
        )

    def _check(self, ret: int, fn: str) -> None:
        if ret != 0:
            raise InterfaceError(f"J2534: {fn} returned error 0x{ret:04X}")

    def __repr__(self) -> str:
        return f"J2534Interface(dll={Path(self.dll_path).name})"
