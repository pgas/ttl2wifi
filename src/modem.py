# modem.py - Platform-neutral Hayes AT command processor for ttl2wifi
#
# Shared by the Pico W firmware (main.PicoModem) and the host simulator
# (sim/sim_bridge.SimModem). Subclasses implement the Wi-Fi / hardware hooks.
import json

import gemini
import gopher
import httpget
import net
import ntp
import ssh
import telnet
import xmodem

VERSION = "1.1.0"

HELP_TEXT = (
    b"=== TTL2WiFi AT Command Reference ===\r\n"
    b"Classic Hayes Commands:\r\n"
    b"  AT                 - Attention check (OK)\r\n"
    b"  ATI                - Modem info, MAC, IP & settings\r\n"
    b"  AT? / AT+HELP      - Show this command summary\r\n"
    b"  ATE0 / ATE1        - Command echo Off / On\r\n"
    b"  AT&K0 / &K3 / &K4  - Flow control: None / HW RTS-CTS / SW XON-XOFF\r\n"
    b"  AT+PAGE=<lines>    - Screen pager (e.g. AT+PAGE=22, or 0=off)\r\n"
    b"  AT&W / ATZ / AT&F  - Save / Reload / Factory-reset config\r\n"
    b"  ATDT<host>:<port>  - Dial raw TCP stream (+++ to escape)\r\n"
    b"  ATDS<host>:<port>  - Dial TLS stream (+++ to escape)\r\n"
    b"  ATO / ATH          - Return to online socket / Hang up\r\n"
    b"Wi-Fi & Network Commands:\r\n"
    b"  AT+WSCAN           - Scan Wi-Fi access points\r\n"
    b'  AT+WJOIN="ssid","pw" - Connect to Wi-Fi network\r\n'
    b"  AT+WLEAVE / +WSTAT - Disconnect / Show Wi-Fi & IP status\r\n"
    b'  AT+WDNS="host"     - DNS lookup\r\n'
    b"  AT+TIME            - Sync RTC via NTP & print UTC time\r\n"
    b"Protocols, Browsing & File Transfer:\r\n"
    b'  AT+GOPHER="url"    - Fetch Gopher menu/file (numbers links [1]..[N])\r\n'
    b'  AT+GEMINI="url"    - Fetch Gemini page over TLS (numbers links [1]..[N])\r\n'
    b'  AT+GO=<n>[,"qry"]  - Follow numbered link [n] (or AT+BACK / AT+LINKS)\r\n'
    b'  AT+HTTPGET="url"   - Fetch HTTP/HTTPS URL\r\n'
    b'  AT+XMODEM="url"    - Download URL via 128B XMODEM (CRC/Checksum)\r\n'
    b'  AT+TELNET="h[:p]"  - Interactive Telnet session (IAC VT100 80x24)\r\n'
    b'  AT+SSH="u@host","pw" - Interactive SSH-2 PTY session\r\n'
)


def parse_quoted_args(s):
    args = []
    cur = []
    in_q = False
    for ch in s.strip():
        if ch == '"':
            in_q = not in_q
        elif ch == "," and not in_q:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur or s.endswith(","):
        args.append("".join(cur).strip())
    return args


class AtModem:
    """Hayes AT modem state machine on top of a serialio.SerialIO transport."""

    # Exceptions that must escape run() (e.g. host disconnects in the simulator)
    FATAL_ERRORS = ()

    def __init__(self, io, config_file=None):
        self.io = io
        self.config_file = config_file
        self.nav = net.BrowserState()

        self.echo = True
        self.flow_mode = 3  # Default AT&K3 (Hardware RTS/CTS)
        self.ssid = ""
        self.password = ""
        self.auto_join = True

        # Online socket state (for ATDT / ATDS / +++ / ATO / ATH)
        self.mode = "COMMAND"
        self.sock = None
        self.raw_sock = None
        self.peer_desc = ""
        self.plus_count = 0
        self.last_rx_ms = 0

        self._line_buf = bytearray()
        self._last_cr = False

    # ---- hooks (override in platform subclass) --------------------------
    def log(self, msg):
        print(msg)

    def set_flow(self, mode):
        self.flow_mode = mode

    def wifi_scan(self):
        """Return list of (ssid, channel, rssi, security)."""
        return []

    def wifi_join(self, ssid, password):
        self.ssid = ssid
        self.password = password
        self.reply("OK")

    def wifi_leave(self):
        pass

    def wifi_status(self):
        self.io.write_paced(b"+WSTAT: UNKNOWN\r\n")

    def info_lines(self):
        return [f"TTL2WiFi v{VERSION}"]

    # ---- configuration --------------------------------------------------
    def load_config(self):
        if not self.config_file:
            return False
        try:
            with open(self.config_file, "r") as f:
                cfg = json.load(f)
        except Exception:
            return False
        self.echo = bool(cfg.get("echo", True))
        self.flow_mode = int(cfg.get("flow_mode", 3))
        self.io.page_lines = int(cfg.get("page_lines", 0))
        self.ssid = cfg.get("ssid", "")
        self.password = cfg.get("password", "")
        self.auto_join = bool(cfg.get("auto_join", True))
        return True

    def save_config(self):
        if not self.config_file:
            return
        cfg = {
            "echo": self.echo,
            "flow_mode": self.flow_mode,
            "page_lines": self.io.page_lines,
            "ssid": self.ssid,
            "password": self.password,
            "auto_join": self.auto_join,
        }
        with open(self.config_file, "w") as f:
            json.dump(cfg, f)

    # ---- helpers --------------------------------------------------------
    def reply(self, text="OK"):
        self.io.write_paced(f"{text}\r\n")

    def flow_desc(self):
        if self.flow_mode == 0:
            return "&K0 (None)"
        if self.flow_mode == 3:
            return "&K3 (HW RTS/CTS)"
        return "&K4 (SW XON/XOFF)"

    def banner(self):
        return (
            f"\r\nTTL2WiFi v{VERSION} Hayes AT / Protocol Bridge Ready (115200 8N1, {self.flow_desc()})\r\n"
            f"Type AT? for commands.\r\nOK\r\n"
        )

    def dial_stream(self, target, use_tls=False):
        host, port = net.parse_host_port(target.strip(), 443 if use_tls else 23)
        self.close_socket()
        try:
            raw_s = net.connect_tcp(host, port, timeout=10.0)
        except Exception as e:
            self.reply(f"NO CARRIER ({e})")
            return
        try:
            s = net.wrap_tls(raw_s, server_hostname=host) if use_tls else raw_s
            net.set_nonblocking(raw_s, s)
            self.raw_sock = raw_s
            self.sock = s
            self.peer_desc = f"{'TLS ' if use_tls else ''}{host}:{port}"
            self.mode = "ONLINE"
            self.plus_count = 0
            self.last_rx_ms = net.ticks_ms()
            self.reply(f"CONNECT {self.peer_desc}")
        except Exception as e:
            net.close_quiet(raw_s)
            self.reply(f"NO CARRIER ({e})")

    def close_socket(self):
        net.close_quiet(self.sock, self.raw_sock)
        self.sock = None
        self.raw_sock = None
        self.mode = "COMMAND"

    def follow_url(self, url, query=None, push_history=True):
        if url.startswith("gemini://"):
            if query:
                url = f"{url}?{query}"
            gemini.fetch(url, self.io, nav=self.nav, push_history=push_history)
        elif url.startswith("http://") or url.startswith("https://"):
            httpget.fetch(url, self.io)
        elif url.startswith("telnet://"):
            telnet.session(url, self.io)
            return
        else:
            gopher.fetch(url, self.io, nav=self.nav, query=query, push_history=push_history)
        self.reply("OK")

    def print_info(self):
        for line in self.info_lines():
            self.io.write_paced(line + "\r\n")
        self.reply("OK")

    # ---- command dispatcher ---------------------------------------------
    def handle_command(self, line):
        cmd_raw = line.strip()
        if not cmd_raw:
            return

        self.log(f"[AT CMD] {cmd_raw!r}")
        up = cmd_raw.upper()

        if up == "HELP":
            self.io.write_paced(HELP_TEXT)
            self.reply("OK")
            return

        if not up.startswith("AT"):
            self.reply("ERROR (Commands must start with AT; type AT? for help)")
            return

        body = cmd_raw[2:].strip()
        body_up = body.upper()

        if body_up == "":
            self.reply("OK")
        elif body_up in ("?", "+HELP"):
            self.io.write_paced(HELP_TEXT)
            self.reply("OK")
        elif body_up in ("I", "I0", "I1"):
            self.print_info()
        elif body_up in ("E0", "E1"):
            self.echo = body_up == "E1"
            self.reply("OK")
        elif body_up in ("&K0", "&K3", "&K4"):
            self.set_flow(int(body_up[2]))
            self.reply("OK")
        elif body_up.startswith("+PAGE="):
            self.io.page_lines = max(0, int(body[6:].strip()))
            self.reply("OK")
        elif body_up == "&W":
            self.save_config()
            self.reply("OK")
        elif body_up == "Z":
            self.load_config()
            self.set_flow(self.flow_mode)
            self.reply("OK")
        elif body_up == "&F":
            self.echo = True
            self.io.page_lines = 0
            self.set_flow(3)
            self.reply("OK")
        elif body_up == "O":
            if self.sock:
                self.mode = "ONLINE"
                self.plus_count = 0
                self.reply(f"CONNECT {self.peer_desc}")
            else:
                self.reply("NO CARRIER")
        elif body_up in ("H", "H0"):
            self.close_socket()
            self.reply("NO CARRIER")
        elif body_up.startswith("DT"):
            self.dial_stream(body[2:], use_tls=False)
        elif body_up.startswith("DS"):
            self.dial_stream(body[2:], use_tls=True)
        elif body_up.startswith("D"):
            self.dial_stream(body[1:], use_tls=False)
        elif body_up == "+WSCAN":
            self.io.write_paced(b"+WSCAN: Scanning...\r\n")
            for name, ch, rssi, sec in self.wifi_scan():
                self.io.write_paced(f"  ch{ch:<2d}  {rssi:>4d} dBm  sec={sec}  {name}\r\n")
            self.reply("OK")
        elif body_up.startswith("+WJOIN="):
            args = parse_quoted_args(body[7:])
            if args and args[0]:
                self.wifi_join(args[0], args[1] if len(args) > 1 else "")
            else:
                self.reply('ERROR: Usage AT+WJOIN="ssid","password"')
        elif body_up == "+WLEAVE":
            self.wifi_leave()
            self.reply("OK")
        elif body_up == "+WSTAT":
            self.wifi_status()
            self.reply("OK")
        elif body_up.startswith("+WDNS="):
            host = parse_quoted_args(body[6:])[0]
            ip = net.socket.getaddrinfo(host, 80, net.socket.AF_INET)[0][-1][0]
            self.io.write_paced(f"+WDNS: {host} -> {ip}\r\n")
            self.reply("OK")
        elif body_up == "+TIME":
            self.io.write_paced(f"+TIME: {ntp.sync()}\r\n")
            self.reply("OK")
        elif body_up.startswith("+GOPHER="):
            gopher.fetch(parse_quoted_args(body[8:])[0], self.io, nav=self.nav)
            self.reply("OK")
        elif body_up.startswith("+GEMINI="):
            gemini.fetch(parse_quoted_args(body[8:])[0], self.io, nav=self.nav)
            self.reply("OK")
        elif body_up.startswith("+GO="):
            args = parse_quoted_args(body[4:])
            idx = int(args[0])
            query = args[1] if len(args) > 1 else None
            if 1 <= idx <= len(self.nav.links):
                url, _label, _t = self.nav.links[idx - 1]
                self.io.write_paced(f"+GO [{idx}]: {url}\r\n")
                self.follow_url(url, query=query, push_history=True)
            else:
                self.reply(f"ERROR: Link [{idx}] out of range (1..{len(self.nav.links)})")
        elif body_up == "+BACK":
            if self.nav.history:
                prev_url = self.nav.history.pop()
                self.io.write_paced(f"+BACK: {prev_url}\r\n")
                self.follow_url(prev_url, push_history=False)
            else:
                self.reply("ERROR: History is empty")
        elif body_up == "+LINKS":
            self.io.reset_pager()
            if not self.nav.links:
                self.io.write_paced(b"+LINKS: None\r\n")
            else:
                for i, (u, lbl, t) in enumerate(self.nav.links, 1):
                    if not self.io.write_line_paged(f"[{i:>2d}:{t}] {lbl} -> {u}"):
                        break
            self.reply("OK")
        elif body_up.startswith("+HTTPGET="):
            httpget.fetch(parse_quoted_args(body[9:])[0], self.io)
            self.reply("OK")
        elif body_up.startswith("+XMODEM="):
            args = parse_quoted_args(body[8:])
            delay_us = int(args[1]) if len(args) > 1 and args[1].isdigit() else 250
            xmodem.send_url(args[0], self.io, delay_us=delay_us)
            self.reply("OK")
        elif body_up.startswith("+TELNET="):
            telnet.session(parse_quoted_args(body[8:])[0], self.io)
        elif body_up.startswith("+SSH="):
            args = parse_quoted_args(body[5:])
            if len(args) >= 2:
                ssh.ssh_connect_and_run(args[0], args[1], self.io)
            elif len(args) == 1 and args[0]:
                pw = self.io.read_hidden_line("Password: ")
                if pw is not None:
                    ssh.ssh_connect_and_run(args[0], pw, self.io)
                else:
                    self.reply("ERROR: Aborted")
            else:
                self.reply('ERROR: Usage AT+SSH="user@host[:port]"[,"password"]')
        else:
            self.reply(f"ERROR: Unknown command AT{body}")

    # ---- main loop ------------------------------------------------------
    def _hang_up(self):
        self.close_socket()
        self.io.write_paced(b"\r\nNO CARRIER\r\n")

    def poll_online(self):
        u_data = self.io.read_online()
        if u_data:
            now = net.ticks_ms()
            guard = net.ticks_diff(now, self.last_rx_ms) > 800
            if u_data == b"+++" and guard:
                # Whole escape sequence arrived in one chunk (e.g. from SimH)
                self.plus_count = 3
            elif u_data == b"+" and guard:
                self.plus_count = 1
            elif u_data == b"+" and 0 < self.plus_count < 3:
                self.plus_count += 1
            else:
                self.plus_count = 0
            self.last_rx_ms = now
            if self.plus_count == 3:
                self.mode = "COMMAND"
                self.io.write_paced(b"\r\nOK\r\n")
                return
            try:
                net.sock_send(self.sock, u_data)
            except Exception:
                self._hang_up()
                return

        try:
            chunk = net.sock_recv(self.sock, 256)
            if chunk == b"":
                self._hang_up()
                return
            if chunk:
                self.io.write_paced(chunk)
        except OSError as e:
            if not net.would_block(e):
                self._hang_up()

    def poll_command(self):
        data = self.io.read_command_bytes()
        if not data:
            return
        for b in data:
            if b in (0x0D, 0x0A):
                if b == 0x0A and self._last_cr:
                    self._last_cr = False  # CR+LF counts as one line terminator
                    continue
                self._last_cr = b == 0x0D
                if self.echo:
                    self.io.write(b"\r\n")
                if len(self._line_buf) > 0:
                    line = self._line_buf.decode("utf-8", "replace")
                    self._line_buf = bytearray()
                    try:
                        self.handle_command(line)
                    except Exception as e:
                        if isinstance(e, self.FATAL_ERRORS):
                            raise
                        self.log(f"[AT ERR] {e!r}")
                        self.reply(f"ERROR: {e}")
                continue
            self._last_cr = False
            if b in (0x08, 0x7F):
                if len(self._line_buf) > 0:
                    self._line_buf = self._line_buf[:-1]
                    if self.echo:
                        self.io.write(b"\x08 \x08")
            elif 0x20 <= b <= 0x7E:
                self._line_buf.append(b)
                if self.echo:
                    self.io.write(bytes([b]))

    def run(self):
        """Main loop: never returns except via FATAL_ERRORS."""
        self.io.write_paced(self.banner())
        while True:
            if self.mode == "ONLINE" and self.sock:
                self.poll_online()
                net.sleep_ms(5)
            else:
                self.poll_command()
                net.sleep_ms(10)
