# ttl2wifi

A MicroPython **5V TTL-to-Wi-Fi Hayes `AT` modem and retro/small-web protocol bridge** running on a **Raspberry Pi Pico W**, built for the **SC131 (Z180 RomWBW / CP/M)** pocket computer and other vintage serial systems.

## Features

- **Classic Hayes `AT` Modem Compatibility:** Works with standard CP/M & retro terminal software (`QTERM`, `MEX`, `IMP`, `Kermit`, `minicom`) using `AT`, `ATI`, `ATE0`/`ATE1`, `ATDT<host>:<port>`, `+++`, `ATO`, and `ATH`.
- **Configurable Flow Control (`AT&K<n>`) & Pager (`AT+PAGE=<n>`):**
  - `AT&K3` *(Default)* — Hardware `RTS`/`CTS` on `GP2` (`CTS`) and `GP3` (`RTS`)
  - `AT&K4` — Software `XON`/`XOFF` (`Ctrl-S` / `Ctrl-Q`)
  - `AT&K0` — None (transparent 8-bit binary path)
  - `AT+PAGE=22` — Built-in `-- More --` screen paginator for 24-row terminals
- **Offloaded TLS & Built-in Protocol Clients:**
  - **TLS Stream Dialing (`ATDS<host>:<port>`):** Transparent TLS 1.2 wrapper for plain-text retro clients.
  - **Telnet (`AT+TELNET="host[:port]"`):** RFC 854 IAC negotiation (`VT100`, `80x24` `NAWS`, `SGA`, `ECHO`).
  - **Gopher (`AT+GOPHER="host[/selector]"`):** Formats Gopher menus and numbers links `[1]..[N]`.
  - **Gemini (`AT+GEMINI="gemini://..."`):** TLS 1.2 client with automatic redirect handling and numbered `=>` links `[1]..[N]`.
  - **Interactive Link Browsing (`AT+GO=<n>`, `AT+BACK`, `AT+LINKS`):** Follow numbered links across Gopher, Gemini, HTTP, and Telnet without retyping URLs.
  - **HTTP/HTTPS (`AT+HTTPGET="http(s)://..."`):** Stream web pages or text files.
  - **XMODEM File Downloader (`AT+XMODEM="url"`):** Download files from HTTP/HTTPS/Gopher directly into CP/M (`XM.COM`) via 128-byte XMODEM (CRC-16 or Checksum).
  - **SSH-2 Client (`AT+SSH="user@host[:port]"`):** Pure MicroPython SSH-2 client supporting `curve25519-sha256` and `diffie-hellman-group14-sha256`, `aes128-ctr`, `hmac-sha2-256`, interactive hidden `Password:` prompt, and `vt100` (`80x24`) PTY shell.
- **Zero-UART Development over 3-Pin SWD (`SWDTerm`):** Firmware flashing, file syncing (`make sync`), and interactive MicroPython REPL (`make repl`) run exclusively over the 3-pin SWD Debug Probe via non-intrusive SRAM ringbuffers, keeping `UART0` (`GP0`/`GP1`) 100% dedicated to the TTL serial interface.

---

## Documentation

- [**Hardware & SC131 5V TTL Wiring (`doc/hardware.md`)**](doc/hardware.md) — Schematic, 5V-to-3.3V resistor divider calculations, and optional hardware `RTS`/`CTS` flow control.
- [**XMODEM File Downloads on SC131 (`doc/xmodem.md`)**](doc/xmodem.md) — Workflow for fetching files into CP/M using `HTALK` and `XM R1`.
- [**SWDTerm: REPL & Sync Over 3-Pin SWD (`doc/swdterm.md`)**](doc/swdterm.md) — Architecture and SRAM shared-memory layout of the 3-pin SWD REPL bridge.
- [**Project Roadmap & AT Command Spec (`doc/roadmap.md`)**](doc/roadmap.md) — Complete specification of implemented phases and commands.

---

## AT Command Quick Reference

| Command | Description |
| :--- | :--- |
| `AT` / `ATI` / `AT?` | Attention check / Modem status & info / Command help |
| `ATE0` / `ATE1` | Disable / Enable command echo |
| `AT&K0` / `AT&K3` / `AT&K4` | Flow control: None (`&K0`), HW `RTS`/`CTS` (`&K3`, default), SW `XON`/`XOFF` (`&K4`) |
| `AT+PAGE=<lines>` | Pause output every `<lines>` rows (`e.g. AT+PAGE=22`; `0` = continuous) |
| `AT&W` / `ATZ` / `AT&F` | Save settings to `config.json` / Reload saved config / Factory defaults |
| `AT+WSCAN` | Scan nearby 2.4 GHz Wi-Fi access points |
| `AT+WJOIN="ssid","pass"` | Connect to Wi-Fi network (follow with `AT&W` to auto-connect on boot) |
| `AT+WSTAT` / `AT+WLEAVE` | Show IP, gateway, DNS, MAC & RSSI / Disconnect Wi-Fi |
| `AT+WDNS="host"` / `AT+TIME` | Resolve hostname to IP / Sync RTC via NTP & print UTC time |
| `ATDT<host>:<port>` | Dial raw TCP stream (`+++` to escape to command mode, `ATO` to resume, `ATH` to hang up) |
| `ATDS<host>:<port>` | Dial TLS-wrapped TCP stream |
| `AT+TELNET="host[:port]"` | Interactive Telnet session with RFC 854 IAC negotiation (`VT100` `80x24`) |
| `AT+GOPHER="host[/sel]"` | Fetch Gopher menu or document (numbers links `[1]..[N]`) |
| `AT+GEMINI="gemini://..."` | Fetch Gemini page over TLS (numbers links `[1]..[N]`) |
| `AT+GO=<n>[,"query"]` | Follow numbered link `[n]` from the current Gopher or Gemini page |
| `AT+BACK` / `AT+LINKS` | Return to previous page in history / List numbered links on current page |
| `AT+HTTPGET="url"` | Fetch HTTP or HTTPS URL |
| `AT+XMODEM="url"` | Download URL and send over `UART0` via 128-byte XMODEM (CRC-16 / Checksum) |
| `AT+SSH="user@host[:port]"` | Open interactive SSH-2 `vt100` shell (prompts `Password:` without echo) |

---

## Development Quick Start (macOS)

```sh
# 1. Flash MicroPython v1.24.1 (RPI_PICO_W) over SWD
make flash

# 2. Full LittleFS build & flash of src/*.py over SWD
make deploy

# 3. Fast incremental sync of src/*.py over SWD (~2s, preserves config.json)
make sync

# 4. Open SWD debug REPL (Channel 1: Debug Probe)
make repl

# 5. Open TTL serial terminal (Channel 2: USB-to-TTL Adapter on UART0)
make ttl
```
