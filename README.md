# VAGFlasher

[![CI](https://github.com/dspl1236/VAGFlasher/actions/workflows/ci.yml/badge.svg)](https://github.com/dspl1236/VAGFlasher/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

**Open-source VAG ECU/TCU flash tool. No cloud. No subscriptions. No phone-home.**

Works with your existing J2534 cable or the [FunkBridge ESP32 OBD dongle](https://github.com/dspl1236/esp32-isotp-ble-bridge-c7vag).

## Supported platforms

| ECU | Engine | Status |
|-----|--------|--------|
| ME17.5 (MED17.5) | EA888 Gen1/1.5 CCTA/CCZA 200HP | ✓ Milestone 1 |
| ME17.5.2 | EA888 Gen2 / 07K | ✓ Milestone 1 |
| EDC17C46 / EDC17CP44 | TDI 2.0 / 3.0 | Milestone 2 |
| MED9.1 | Cayenne / Golf V VR6 4.2 | Milestone 2 |
| ME7.x | C167CR era | Milestone 2 |

## Quick start

```bash
pip install vagflasher

# Flash via FunkBridge (ESP32 WiFi dongle)
vagflasher flash --ecu me17 --interface funkbridge tuned.bin

# Flash via J2534 cable (auto-detects installed DLL on Windows)
vagflasher flash --ecu me17 --interface j2534 tuned.bin

# Read ECU to .bin
vagflasher read --ecu me17 --interface funkbridge --output stock.bin

# List installed J2534 devices
vagflasher devices --interface j2534
```

## Hardware

VAGFlasher works with any J2534 PassThru device. For the best experience:

- **[FunkBridge OBD dongle](https://github.com/dspl1236/esp32-isotp-ble-bridge-c7vag)** — ESP32-based wireless OBD bridge.
  Flash the firmware with [FunkFlash-ESP](https://github.com/dspl1236/FunkFlash-ESP).
  Works wirelessly from phone or laptop, no drivers required.
- **Any J2534 device** (Tactrix OpenPort, VCDS, etc.) — use `--interface j2534`

## Part of the VAG open-source toolchain

```
TriCoreTool / MED9Tool / MESevenTool   ←  ROM editors, produce .bin
             ↓ verified .bin
          VAGFlasher                   ←  this tool, puts it in the car
             ↓ CAN bus
    FunkBridge / J2534 cable           ←  hardware layer
```

## Architecture

```
vagflasher/
├── protocols/
│   ├── uds.py      UDS (ISO 14229) request/response primitives
│   └── sa2.py      SA2 seed/key algorithms (BiWbBuD101, CodeRobert, MED9, ME7)
├── interfaces/
│   ├── funkbridge.py   ESP32 WebSocket interface
│   └── j2534.py        J2534 PassThru DLL interface
└── platforms/
    └── me17.py         ME17.5 / EDC17 flash sequence
```

## License

GPL-3.0 — free to use, modify, and distribute. Contributions welcome.
