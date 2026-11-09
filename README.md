# ttl2wifi

A MicroPython **5V TTL-to-Wi-Fi Hayes `AT` modem and retro protocol bridge** running on a **Raspberry Pi Pico W**, built for the **SC131 (Z180 RomWBW / CP/M)** and other vintage serial systems.

---

## Highlights

* **Classic Hayes `AT` Modem:** Works with CP/M communications software (`QTERM`, `MEX`, `IMP`, `minicom`) via `AT`, `ATI`, `ATE0/1`, `ATDT<host>:<port>`, `+++`, `ATO`, and `ATH`.
* **Offloaded TLS 1.2:** Hardware-accelerated modern encryption for retro hosts via `ATDS<host>:<port>` and built-in protocol clients.
* **Built-in Small-Web Clients:** Interactive numbered link browsing for **Gemini** (`AT+GEMINI`, `AT+GO`) and **Gopher** (`AT+GOPHER`), plus **HTTP/HTTPS** (`AT+HTTPGET`) and **SSH-2** (`AT+SSH`).
* **Direct CP/M File Transfers:** Download files over Wi-Fi directly to disk via 128-byte XMODEM (`AT+XMODEM`) with configurable inter-byte pacing.
* **Flow Control & Paging:** Hardware RTS/CTS (`AT&K3`), software XON/XOFF (`AT&K4`), or raw 8-bit binary (`AT&K0`), with an optional screen pager (`AT+PAGE=22`).

---

## Installation

### Option 1: Drag-and-Drop UF2 (No tools required)

1. Hold the **`BOOTSEL`** button on the Pico W while plugging it into your computer via USB.
2. The board mounts as a mass-storage drive named **`RPI-RP2`**.
3. Drag and drop **[`firmware/ttl2wifi.uf2`](firmware/ttl2wifi.uf2)** onto the drive.
4. The Pico W reboots automatically and starts `ttl2wifi`.

*(To build the UF2 image from source: `make image`)*

### Option 2: 3-Pin SWD Probe (Development)

```sh
make flash    # Flash base MicroPython firmware over SWD
make deploy   # Build LittleFS filesystem and flash over SWD
make sync     # Fast incremental sync of src/*.py (~2s)
make repl     # Interactive debug REPL over SWD (UART0 stays 100% free)
```

---

## Quick Start

Open your serial terminal at **115,200 baud, 8N1**:

```text
AT
OK
AT+WJOIN="MyWiFiSSID","MyPassword"
OK
AT&W
OK
```

Connect to a BBS or small-web capsule:

```text
ATDTbbs.example.com:23
AT+GEMINI="gemini://geminiprotocol.net"
AT+XMODEM="http://192.168.1.100:8000/MYFILE.COM"
```

---

## Source Layout

| File | Role |
|---|---|
| `src/main.py` | Pico W layer: `FlowUART` (UART0, RTS/CTS, XON/XOFF, pacing) and Wi-Fi hooks |
| `src/modem.py` | Platform-neutral Hayes AT command processor |
| `src/serialio.py` | Serial I/O base class (pager, Ctrl-C abort, hidden input) |
| `src/net.py` | Shared socket/TLS/URL helpers, `BrowserState`, MicroPython/CPython shims |
| `src/gemini.py`, `gopher.py`, `httpget.py`, `xmodem.py`, `ssh.py`, `ntp.py` | Protocol clients |

## Host Simulator

[`sim/`](sim/README.md) runs the same `src/` code under CPython (`make sim`), and can boot RomWBW in
SimH with the emulated bridge on a serial port (`make simh`, needs the included RomWBW patch).

---

## Documentation

Full documentation is available in the [`docs/`](docs/) directory:

* [**AT Command Reference (`docs/commands.md`)**](docs/commands.md) — Complete command list, syntax, and protocol guides.
* [**Hardware & SC131 Wiring (`docs/hardware.md`)**](docs/hardware.md) — 5V TTL schematic, resistor dividers, and pinouts.
* [**XMODEM File Transfers (`docs/xmodem.md`)**](docs/xmodem.md) — Downloading files into CP/M using `HTALK` and `XM R1`.
* [**SWDTerm Architecture (`docs/swdterm.md`)**](docs/swdterm.md) — Zero-UART REPL and syncing over the 3-pin SWD probe.
* [**Roadmap & Specs (`docs/roadmap.md`)**](docs/roadmap.md) — Project design and implementation roadmap.
