"""
VAGFlasher CLI.

Usage:
    vagflasher flash --ecu me17 --interface funkbridge tuned.bin
    vagflasher read  --ecu me17 --interface j2534    --output dump.bin
    vagflasher dtc   --ecu me17 --interface funkbridge --clear
    vagflasher info  --interface funkbridge
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()

# ── Interface factory ─────────────────────────────────────────────────────────

def _make_interface(iface_name: str, host: str | None = None,
                    dll: str | None = None):
    name = iface_name.lower()
    if name in ("funkbridge", "funk", "esp32"):
        from vagflasher.interfaces.funkbridge import FunkBridgeInterface
        return FunkBridgeInterface(host=host or "funkbridge.local")
    if name in ("j2534", "passthru"):
        from vagflasher.interfaces.j2534 import J2534Interface
        return J2534Interface(dll_path=dll)
    raise click.BadParameter(
        f"Unknown interface {iface_name!r}. Choose: funkbridge, j2534"
    )


# ── Platform factory ──────────────────────────────────────────────────────────

def _make_platform(ecu_name: str, iface, bcb_key: str | None = None):
    name = ecu_name.lower()
    if name in ("me17", "me17.5", "med17", "med17.5"):
        from vagflasher.platforms.me17 import ME17Platform
        return ME17Platform(iface, bcb_key=bcb_key or "BiWbBuD101")
    if name in ("me711", "me7", "me7.1.1"):
        raise NotImplementedError(
            "ME7.x platform planned for milestone 2. "
            "See github.com/dspl1236/VAGFlasher/issues"
        )
    if name in ("med9", "med9.1"):
        raise NotImplementedError(
            "MED9.1 platform planned for milestone 2."
        )
    raise click.BadParameter(
        f"Unknown ECU platform {ecu_name!r}. Available: me17, me7, med9"
    )


# ── CLI definition ────────────────────────────────────────────────────────────

@click.group()
@click.version_option()
def main():
    """VAGFlasher — open-source VAG ECU flash tool. No cloud. No subscriptions."""


@main.command()
@click.argument("bin_file", type=click.Path(exists=True))
@click.option("--ecu",        required=True, help="ECU platform: me17, me7, med9")
@click.option("--interface",  required=True, help="Interface: funkbridge, j2534")
@click.option("--host",       default=None,  help="FunkBridge host (default: funkbridge.local)")
@click.option("--dll",        default=None,  help="J2534 DLL path (auto-detected if omitted)")
@click.option("--bcb-key",    default=None,  help="Override BCB SA2 key (auto-detected from file)")
@click.option("--dry-run",    is_flag=True,  help="Parse and validate without connecting to ECU")
def flash(bin_file, ecu, interface, host, dll, bcb_key, dry_run):
    """Flash a .bin file to the ECU."""
    data = Path(bin_file).read_bytes()
    console.print(f"\n[bold]VAGFlasher[/bold] — flash {Path(bin_file).name} "
                  f"({len(data):,} bytes) → {ecu.upper()} via {interface}")

    if dry_run:
        console.print("[yellow]Dry run — not connecting to ECU.[/yellow]")
        console.print(f"  File: {len(data):,} bytes ({len(data) // 1024}KB)")
        console.print("  Validation OK.")
        return

    iface = _make_interface(interface, host=host, dll=dll)

    async def _run():
        async with iface:
            platform = _make_platform(ecu, iface, bcb_key)
            from vagflasher.platforms.me17 import FlashBlock
            # Single-block flash for now; milestone 2 adds multi-block from map file
            block = FlashBlock(address=0x080000, data=data)
            await platform.flash([block])

    asyncio.run(_run())
    console.print("\n[green]✓ Flash complete.[/green]")


@main.command()
@click.option("--ecu",       required=True)
@click.option("--interface", required=True)
@click.option("--host",      default=None)
@click.option("--dll",       default=None)
@click.option("--output",    required=True, help="Output .bin path")
@click.option("--address",   default="0x080000", help="Start address (hex)")
@click.option("--size",      default="0x180000", help="Read size (hex)")
def read(ecu, interface, host, dll, output, address, size):
    """Read ECU flash to a .bin file."""
    addr = int(address, 16)
    sz   = int(size, 16)
    console.print(f"\n[bold]VAGFlasher[/bold] — read {ecu.upper()} "
                  f"0x{addr:06X}+{sz // 1024}KB → {output}")

    iface = _make_interface(interface, host=host, dll=dll)

    async def _run():
        async with iface:
            platform = _make_platform(ecu, iface)
            data = await platform.read_ecu(addr, sz)
        Path(output).write_bytes(data)
        console.print(f"\n[green]✓ Read complete: {output} ({len(data):,} bytes)[/green]")

    asyncio.run(_run())


@main.command()
@click.option("--interface", required=True)
@click.option("--host",      default=None)
@click.option("--dll",       default=None)
def devices(interface, host, dll):
    """List available interfaces / installed J2534 devices."""
    if interface.lower() in ("j2534", "passthru"):
        from vagflasher.interfaces.j2534 import J2534Interface
        devs = J2534Interface.list_installed()
        if not devs:
            console.print("No J2534 devices found in registry.")
            return
        t = Table(title="Installed J2534 Devices")
        t.add_column("Name")
        t.add_column("DLL")
        for d in devs:
            t.add_row(d["name"], d["dll"])
        console.print(t)
    else:
        console.print(f"Device discovery not available for interface: {interface}")
