# TTL2WiFi Roadmap & AT Command Specification

This document tracks the architecture and command set for the **TTL2WiFi** bridge on the Raspberry Pi Pico W (targeting the **SC131 Z180 RomWBW / CP/M pocket computer** and other 5V TTL retro systems).

---

## Phase 1: Core Hayes AT Engine, Flow Control (`AT&K`) & Pager
- [x] **Command Parser & State Machine (`COMMAND` vs. `ONLINE` mode):**
  - `AT` — Attention check (`OK`)
  - `ATI` — Modem version, board info, Wi-Fi status, flow control, and pager settings
  - `AT?` / `AT+HELP` — Built-in command summary
  - `ATE0` / `ATE1` — Command mode local echo off / on
  - `ATZ` — Reload saved configuration from `config.json`
  - `AT&W` — Save current configuration (echo, flow control, pager, Wi-Fi credentials) to `config.json` on LittleFS
  - `AT&F` — Reset configuration to defaults
- [x] **Configurable Flow Control (`AT&K<n>`) & Screen Pager (`AT+PAGE=<n>`):**
  - `AT&K0` — Disable all flow control (transparent 8-bit binary path for `XMODEM` transfers)
  - `AT&K3` — Hardware `RTS`/`CTS` flow control on `GP2` (`CTS`) and `GP3` (`RTS`) (for 6-wire SC131 connection)
  - `AT&K4` — Software `XON`/`XOFF` flow control (`0x11` / `0x13`) (**Default**)
  - `AT+PAGE=<lines>` — Built-in `-- More --` screen paginator (e.g., `AT+PAGE=22` for 24-row VT100 displays, `0` = continuous)

## Phase 2: Wi-Fi Management (`AT+W...`)
- [x] `AT+WSCAN` — Scan nearby 2.4 GHz Wi-Fi networks and print SSID, channel, and RSSI
- [x] `AT+WJOIN="ssid","password"` — Connect to Wi-Fi AP (and persist in `config.json` via `AT&W` for auto-connect on boot)
- [x] `AT+WLEAVE` — Disconnect from Wi-Fi AP
- [x] `AT+WSTAT` — Show connection state, IP address, netmask, gateway, DNS, MAC, and RSSI
- [x] `AT+WDNS="hostname"` — Resolve a hostname via DNS and return its IPv4 address
- [x] `AT+TIME` — Synchronize clock via NTP and return UTC ISO-8601 timestamp

## Phase 3: Transparent TCP & TLS Stream Dialing
- [x] `ATDT<host>:<port>` — Dial raw TCP connection and enter `ONLINE` mode (`CONNECT`)
- [x] `ATDS<host>:<port>` — Dial **TLS-wrapped** TCP connection (offloading TLS 1.2 from the Z180) and enter `ONLINE` mode (`CONNECT`)
- [x] `+++` (with 1s guard time) — Escape from `ONLINE` mode back to `COMMAND` mode (`OK`) without dropping the socket
- [x] `ATO` — Return from `COMMAND` mode to active `ONLINE` socket
- [x] `ATH` — Hang up / close active socket (`NO CARRIER`)

## Phase 4: Built-in Retro & Small-Web Protocol Clients + XMODEM
- [x] **Telnet Client (`AT+TELNET="<host>[:port]"`):**
  - RFC 854 IAC option negotiation (`ECHO`, `SGA`, `TERMINAL-TYPE = VT100`, `NAWS = 80x24`), `0xFF` escaping, `+++` escape, and `XON`/`XOFF` flow control
- [x] **Gopher Client (`AT+GOPHER="<host>[:port]/<selector>"`):**
  - Fetch Gopher menus (type `1`), text files (type `0`), or search queries (type `7`), numbering links `[1]..[N]`
- [x] **Gemini Protocol Client (`AT+GEMINI="gemini://<host>/<path>"`):**
  - Perform TLS handshake + Gemini request (`<URL>\r\n`), follow `3x` redirects, and number `=>` gemtext links `[1]..[N]`
- [x] **Interactive Link Navigation (`AT+GO=<n>`, `AT+BACK`, `AT+LINKS`):**
  - Follow numbered links across Gopher, Gemini, HTTP, and Telnet without retyping URLs, plus browsing history stack
- [x] **HTTP/HTTPS Client (`AT+HTTPGET="http(s)://<host>/<path>"`):**
  - Fetch HTTP or HTTPS URLs and stream response headers + body over UART
- [x] **XMODEM File Downloader (`AT+XMODEM="<url>"`):**
  - Fetch any HTTP/HTTPS/Gopher file over Wi-Fi and transmit it over `UART0` using 128-byte XMODEM (supports both CRC-16 `'C'` and Checksum `NAK` for CP/M `XM.COM`)

## Phase 5: Built-in SSH-2 Client (`AT+SSH`)
- [x] **Pure MicroPython SSH-2 Client (`src/ssh.py`) using built-in C crypto primitives (`pow`, `cryptolib.aes`, `hashlib.sha256`):**
  - Key exchange: `curve25519-sha256` (RFC 7748 / RFC 8731) and `diffie-hellman-group14-sha256` (RFC 8268)
  - Cipher & MAC: `aes128-ctr` + `hmac-sha2-256`
  - Authentication: Password / keyboard-interactive auth (`ssh-userauth`) with hidden `Password:` prompt
  - Session: Request `vt100` PTY (`80x24`) + interactive `shell` channel bridged to `UART0`
  - Command: `AT+SSH="user@host[:port]"[,"password"]`
