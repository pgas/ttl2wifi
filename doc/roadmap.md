# TTL2WiFi Roadmap & AT Command Specification

This document tracks the planned architecture and command set for the **TTL2WiFi** bridge on the Raspberry Pi Pico W (targeting the **SC131 Z180 RomWBW / CP/M pocket computer** and other 5V TTL retro systems).

---

## Phase 1: Core Hayes AT Engine & Software Flow Control (`AT&K`)
- [ ] **Command Parser & State Machine (`COMMAND` vs. `ONLINE` mode):**
  - `AT` — Attention check (`OK`)
  - `ATI` — Modem version, board info, Wi-Fi status, and active flow control mode
  - `ATE0` / `ATE1` — Command mode local echo off / on
  - `ATZ` — Reload saved configuration from `config.json`
  - `AT&W` — Save current configuration (echo, flow control, Wi-Fi credentials) to `config.json` on LittleFS
- [ ] **Configurable Flow Control (`AT&K<n>`):**
  - `AT&K0` — Disable all flow control (transparent 8-bit binary path for `XMODEM` transfers)
  - `AT&K3` — Hardware `RTS`/`CTS` flow control on `GP2` (`CTS`) and `GP3` (`RTS`) (for 6-wire SC131 connection)
  - `AT&K4` — Software `XON`/`XOFF` flow control (`0x11` / `0x13`) (**Default**)

## Phase 2: Wi-Fi Management (`AT+W...`)
- [ ] `AT+WSCAN` — Scan nearby 2.4 GHz Wi-Fi networks and print SSID, channel, and RSSI
- [ ] `AT+WJOIN="ssid","password"` — Connect to Wi-Fi AP (and optionally persist in `config.json` for auto-connect on boot)
- [ ] `AT+WLEAVE` — Disconnect from Wi-Fi AP
- [ ] `AT+WSTAT` — Show connection state, IP address, netmask, gateway, DNS, MAC, and RSSI
- [ ] `AT+WDNS="hostname"` — Resolve a hostname via DNS and return its IPv4 address
- [ ] `AT+TIME` — Synchronize clock via NTP and return UTC ISO-8601 timestamp

## Phase 3: Transparent TCP & TLS Stream Dialing
- [ ] `ATDT<host>:<port>` — Dial raw TCP connection (e.g., Telnet BBSes, Gopher servers) and enter `ONLINE` mode (`CONNECT`)
- [ ] `ATDS<host>:<port>` — Dial **TLS-wrapped** TCP connection (offloading TLS 1.2 from the Z180) and enter `ONLINE` mode (`CONNECT`)
- [ ] `+++` (with 1s guard time) — Escape from `ONLINE` mode back to `COMMAND` mode (`OK`) without dropping the socket
- [ ] `ATO` — Return from `COMMAND` mode to active `ONLINE` socket
- [ ] `ATH` — Hang up / close active socket (`NO CARRIER`)

## Phase 4: Built-in Retro & Small-Web Protocol Clients
- [ ] **Gopher Client (`AT+GOPHER="<host>[:port]/<selector>"`):**
  - Fetch Gopher menus (type `1`), text files (type `0`), or search queries (type `7`) and format/stream over UART with `XON`/`XOFF` flow control
- [ ] **Gemini Protocol Client (`AT+GEMINI="gemini://<host>/<path>"`):**
  - Perform TLS handshake + Gemini request (`<URL>\r\n`), parse status header (`20 text/gemini`, redirects `3x`, input prompts `1x`), and stream body over UART

## Phase 5: Built-in SSH-2 Client (`AT+SSH`)
- [ ] **Pure MicroPython SSH-2 Client (`src/ssh.py`) using built-in C crypto primitives (`pow`, `cryptolib.aes`, `hashlib.sha256`):**
  - Key exchange: `diffie-hellman-group14-sha256`
  - Cipher & MAC: `aes128-ctr` + `hmac-sha2-256`
  - Authentication: Password auth (`ssh-userauth`)
  - Session: Request `vt100` PTY (`80x24`) + interactive `shell` channel bridged to `UART0`
  - Command: `AT+SSH="user@host[:port]","password"`
