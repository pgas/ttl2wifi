# AT Command Reference

Default serial parameters: **115,200 baud, 8N1**. Commands are case-insensitive and must start with `AT` (except `HELP` and `+++`).

## Hayes & Configuration Commands

| Command | Description |
| :--- | :--- |
| `AT` | Attention check (`OK`). |
| `ATI` | Print firmware version, flow control, pacing, pager, and Wi-Fi/IP status. |
| `AT?` / `AT+HELP` / `HELP` | Print command summary. |
| `ATE0` / `ATE1` | Command-mode local echo Off / On (default: `E1`). |
| `AT&K0` | Flow control: **None** (default; 8-bit transparent for 3-wire UARTs and XMODEM). |
| `AT&K3` | Flow control: **Hardware RTS/CTS** on `GP2` (`CTS`) and `GP3` (`RTS`). |
| `AT&K4` | Flow control: **Software XON/XOFF** (`0x11` / `0x13`). |
| `AT+DELAY=<us>[,<ms>]` | Output pacing: `<us>` per byte, `<ms>` per newline (default: `500,20`; `0,0` = off). Query with `AT+DELAY?`. |
| `AT+PAGE=<lines>` | Pause output every `<lines>` lines with `-- More --` prompt (`0` = off, default: `0`). |
| `AT&W` | Save current configuration (Wi-Fi credentials, echo, flow, pacing, pager) to flash. |
| `ATZ` | Reload saved configuration from flash. |
| `AT&F` | Reset configuration to factory defaults in RAM (use `AT&W` to persist). |

## Stream Dialing (TCP & TLS)

| Command | Description |
| :--- | :--- |
| `ATDT<host>[:<port>]` | Dial raw TCP connection (default port `23`). Enters `ONLINE` mode on `CONNECT`. |
| `ATDS<host>[:<port>]` | Dial TLS-encrypted connection (default port `443`) with SNI set to `<host>`. Enters `ONLINE` mode on `CONNECT`. |
| `+++` | Escape from `ONLINE` mode to `COMMAND` mode (`OK`) without closing the socket (requires 1s guard silence before and after `+++`). |
| `ATO` | Return from `COMMAND` mode to the active `ONLINE` socket. |
| `ATH` | Hang up and close the active socket (`NO CARRIER`). |

## Wi-Fi, Network & File Transfer

| Command | Description |
| :--- | :--- |
| `AT+WSCAN` | Scan 2.4 GHz Wi-Fi access points (channel, RSSI, security, SSID). |
| `AT+WJOIN="ssid"[,"pass"]` | Connect to Wi-Fi network. Follow with `AT&W` to auto-connect on boot. |
| `AT+WLEAVE` | Disconnect from Wi-Fi. |
| `AT+WSTAT` | Print Wi-Fi connection status, IP, netmask, gateway, DNS, MAC, and RSSI. |
| `AT+WDNS="host"` | Resolve hostname via DNS and print IPv4 address. |
| `AT+TIME` | Query NTP (`pool.ntp.org`), sync RTC, and print UTC timestamp. |
| `AT+XMODEM="url"[,<delay_us>]` | Fetch HTTP/HTTPS URL into memory and transmit over UART via 128-byte XMODEM (auto-detects `'C'` CRC-16 or `NAK` checksum; default byte pacing uses current `char_delay_us` or `500` µs). |
