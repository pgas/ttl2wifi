# ttl2wifi

A MicroPython **5V TTL-to-Wi-Fi modem and protocol bridge** (Hayes `AT` + extended `AT+` commands, TCP/TLS, Gopher, Gemini, and SSH-2) running on a **Raspberry Pi Pico W**, designed for the **SC131 (Z180 RomWBW / CP/M)** pocket computer and other retro serial systems.

## Documentation

- [**Hardware & SC131 5V TTL Wiring (`doc/hardware.md`)**](doc/hardware.md) — Schematic, 5V-to-3.3V resistor divider calculations, and optional hardware `RTS`/`CTS` flow control.
- [**SWDTerm: REPL & Sync Over 3-Pin SWD (`doc/swdterm.md`)**](doc/swdterm.md) — How this project develops and debugs MicroPython exclusively over the 3-pin SWD Debug Probe (via non-intrusive SRAM ringbuffers), leaving `UART0` (`GP0`/`GP1`) 100% dedicated to the TTL serial link.
- [**Project Roadmap & AT Command Spec (`doc/roadmap.md`)**](doc/roadmap.md) — Planned Hayes `AT` commands, `AT&K` software/hardware flow control, `ATDT`/`ATDS` TCP/TLS dialing, Gopher, Gemini, and SSH-2 client.

## Quick Start (Development on macOS)

```sh
# 1. Flash MicroPython v1.24.1 (RPI_PICO_W) over SWD
make flash

# 2. Bootstrap LittleFS (src/boot.py + src/main.py) over SWD
make deploy

# 3. Sync changes in src/main.py over SWD (~1s)
make sync

# 4. Open SWD debug REPL (Channel 1: Debug Probe)
make repl

# 5. Open TTL serial terminal (Channel 2: USB-to-TTL Adapter on UART0)
make ttl
```
