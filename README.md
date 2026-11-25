# ttl2wifi

C++ **5V TTL-to-Wi-Fi Hayes `AT` modem and TLS coprocessor** for the **Raspberry Pi Pico W**, built for the **SC131 (Z180 RomWBW / CP/M)** and other vintage serial computers.

## Features

- **Hayes `AT` TCP & TLS Streams:** Transparent TCP (`ATDT<host>:<port>`) and hardware-offloaded TLS (`ATDS<host>:<port>`) with `+++` escape, `ATO`, and `ATH`. Powers native CP/M networking suites (`ZNetSuite`: `ZTELNET`, `ZGOPHER`, `ZGMI`, `ZIRC`) and classic terminals (`ZTALK`, `QTERM`, `IMP`).
- **Bootstrap XMODEM Downloader:** Download any HTTP/HTTPS file directly into CP/M (`XM.COM`) via 128-byte XMODEM (`AT+XMODEM="url"[,delay]`), supporting both CRC-16 and checksum modes.
- **Retro UART Pacing & Flow Control:** Configurable inter-character and newline delays (`AT+DELAY`), hardware RTS/CTS (`AT&K3`), software XON/XOFF (`AT&K4`), or raw binary (`AT&K0`), plus an optional `-- More --` screen pager (`AT+PAGE=<lines>`).
- **Wi-Fi, DNS & NTP:** Scan and join networks (`AT+WSCAN`, `AT+WJOIN`), persist config to flash (`AT&W`), resolve hostnames (`AT+WDNS`), and fetch UTC time (`AT+TIME`).

## Build & Flash

### 1. Drag-and-Drop UF2
1. Build firmware: `make pico` (outputs `build/pico/ttl2wifi.uf2`).
2. Hold **`BOOTSEL`** on the Pico W while plugging into USB (`RPI-RP2` drive mounts).
3. Copy `build/pico/ttl2wifi.uf2` to the drive.

### 2. SWD Debug Probe
```sh
make flash    # Build and flash build/pico/ttl2wifi.elf via OpenOCD (CMSIS-DAP)
make reset    # Reset target over SWD
```

### 3. Desktop & SimH Emulator
```sh
make sim      # Run native AT bridge on host stdio
make simh     # Boot RomWBW in SimH AltairZ80 wired to the C++ bridge (see sim/README.md)
```

## Quick Start (115200 8N1)

```text
AT+WJOIN="MySSID","MyPassword"
AT&W
ATDTbbs.example.com:23
ATDSirc.libera.chat:6697
AT+XMODEM="http://192.168.1.100:8000/MYFILE.COM"
```

## Source Layout

| Path | Description |
| :--- | :--- |
| `src/core/` | Platform-neutral AT state machine (`AtModem`), paced/paged `ISerialIO`, `INetwork`, and JSON config |
| `src/protocols/` | HTTP/HTTPS 128-byte XMODEM sender (`xmodem.cpp`) and SNTP client (`ntp.cpp`) |
| `src/platform/pico/` | RP2040 UART0 + RTS/CTS (`pico_uart.cpp`), CYW43 Wi-Fi + lwIP + mbedTLS (`pico_net.cpp`), flash storage (`pico_flash.cpp`) |
| `src/platform/desktop/` | POSIX socket/stdio I/O (`posix_io.cpp`) and BSD sockets + OpenSSL (`posix_net.cpp`) |
| [`sim/`](sim/README.md) | SimH AltairZ80 + RomWBW dual-serial setup |

## Documentation

- [**AT Command Reference (`doc/commands.md`)**](doc/commands.md)
- [**Hardware & SC131 Wiring (`doc/hardware.md`)**](doc/hardware.md)
- [**XMODEM File Transfers (`doc/xmodem.md`)**](doc/xmodem.md)
