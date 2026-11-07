# AT Command Reference & Protocol Guide

`ttl2wifi` provides a standard Hayes `AT` modem interface extended with modern Internet and small-web protocol clients for vintage computers.

---

## AT Command Reference

| Command | Arguments | Description |
| :--- | :--- | :--- |
| **`AT`** | — | Attention test. Replies `OK`. |
| **`ATI`** / **`ATI0`** | — | Display bridge status: version, Wi-Fi status, IP, UART settings, and pin states. |
| **`AT?`** / **`AT+HELP`** | — | Print command summary. |
| **`ATE0`** / **`ATE1`** | — | Disable / enable local character echo. |
| **`AT&W`** | — | Save current settings (SSID, password, echo, flow mode, pager lines) to `config.json`. |
| **`ATZ`** | — | Reload configuration from `config.json`. |
| **`AT&F`** | — | Reset to factory defaults (`echo=on`, `flow=3`, `page=0`). |
| **`AT&K0`** | — | Flow control: **None** (raw 8-bit transparent binary path, ideal for XMODEM). |
| **`AT&K3`** | — | Flow control: **Hardware RTS/CTS** on `GP2` (`CTS`) and `GP3` (`RTS`) *(Default)*. |
| **`AT&K4`** | — | Flow control: **Software XON/XOFF** (`0x11` / `0x13`). |
| **`AT+PAGE=<n>`** | `<lines>` | Screen pager. Pauses output every `<n>` lines with `-- More --` prompt (`0` = continuous). |
| **`AT+WSCAN`** | — | Scan nearby 2.4 GHz Wi-Fi access points and display SSID, RSSI, channel, and security. |
| **`AT+WJOIN="ssid","pass"`** | `"ssid"[,"pass"]` | Connect to a Wi-Fi network. Follow with `AT&W` to auto-connect on boot. |
| **`AT+WSTAT`** | — | Show Wi-Fi status: connection state, IP, subnet mask, gateway, DNS, MAC, and RSSI. |
| **`AT+WLEAVE`** | — | Disconnect from Wi-Fi. |
| **`AT+WDNS="host"`** | `"hostname"` | Resolve hostname to IPv4 address via DNS. |
| **`AT+TIME`** | — | Query NTP (`pool.ntp.org`), set Pico RTC, and print formatted UTC timestamp. |
| **`ATDT<host>:<port>`** | `<host>:<port>` | Dial raw TCP stream. Returns `CONNECT`. Type `+++` (with 1s guard time) to escape, `ATO` to resume, or `ATH` to disconnect. |
| **`ATDS<host>:<port>`** | `<host>:<port>` | Dial TLS-wrapped TCP stream. Encrypts all traffic using Pico W hardware crypto. |
| **`AT+TELNET="host[:port]"`** | `"host[:port]"` | Interactive Telnet session with RFC 854 IAC negotiation (`VT100`, `80x24` `NAWS`, `SGA`, `ECHO`). Escape with `+++`. |
| **`AT+GOPHER="host[/sel]"`** | `"host[/selector]"` | Fetch Gopher menu or text file. Menus format item types and index links as `[ 1]`..`[ N]`. |
| **`AT+GEMINI="gemini://..."`** | `"url"` | Fetch Gemini page over TLS. Follows redirects and numbers links `[ 1]`..`[ N]`. |
| **`AT+GO=<n>[,"query"]`** | `<index>[,"query"]` | Follow numbered link `<n>` from the current Gopher or Gemini page without retyping URLs. |
| **`AT+BACK`** | — | Navigate back to the previous page in URL history. |
| **`AT+LINKS`** | — | Re-display numbered links for the current page. |
| **`AT+HTTPGET="url"`** | `"http(s)://..."` | Stream HTTP or HTTPS web page or document over UART. |
| **`AT+XMODEM="url"[,delay]`** | `"url"[,<delay_us>]` | Download remote file directly to retro host via 128-byte XMODEM (CRC-16 or Checksum). Optional `delay_us` adds inter-byte pacing (default: `250` µs). |
| **`AT+SSH="u@host[:p]"[,"pw"]`** | `"user@host"[,"pass"]` | Pure MicroPython SSH-2 client session. Prompts `Password:` without echo if omitted. Provides `vt100` (`80x24`) PTY shell. Escape with `+++`. |

---

## Protocol Clients & Features

### 1. Offloaded TLS 1.2
The Pico W handles all TLS handshakes, certificate management, and AES encryption off-chip. Vintage 8-bit computers can securely connect to modern HTTPS, Gemini, and TLS services without any encryption overhead.

### 2. Interactive Small-Web Browsing (Gemini & Gopher)
* When viewing a Gemini capsule (`AT+GEMINI`) or Gopher hole (`AT+GOPHER`), all links are automatically assigned bracketed numbers: `[ 1]`, `[ 2]`, etc.
* Use **`AT+GO=1`** to follow link 1.
* Use **`AT+BACK`** to return to previous pages in history.
* Use **`AT+LINKS`** to list available links on the current page without refetching.

### 3. SSH-2 Client (`AT+SSH`)
* Pure MicroPython implementation using hardware C crypto primitives (`pow()`, `cryptolib.aes`, `hashlib.sha256`).
* Key Exchange: `curve25519-sha256` and `diffie-hellman-group14-sha256`.
* Cipher & MAC: `aes128-ctr` + `hmac-sha2-256`.
* Authentication: Interactive password prompt without character echo.
* Terminal: Requests `vt100` (`80x24`) PTY and bridges directly to `UART0`.

### 4. XMODEM File Downloader (`AT+XMODEM`)
* Downloads files over HTTP, HTTPS, or Gopher and transmits them directly into CP/M (`XM.COM`) using standard 128-byte XMODEM blocks.
* Supports both CRC-16 (`'C'`) and additive Checksum (`NAK`).
* **Inter-byte Pacing (`delay_us`):** Vintage UARTs without hardware flow control (such as SC131 Port B / Z180 ASCI1) have small hardware FIFOs. `delay_us` inserts microsecond pauses between each byte of the 133-byte packet (default: `250` µs) to prevent overruns.
