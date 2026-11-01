# main.py - TTL2WiFi Hayes AT + Extended AT+ Modem & Protocol Bridge for Pico W
import json
import socket
import ssl
import sys
import time
import machine
import network

import protocols
import ssh

VERSION = "1.0.0"
CONFIG_FILE = "config.json"
UART_BAUD = 115200

XON = 0x11   # Ctrl-Q
XOFF = 0x13  # Ctrl-S
CTRL_C = 0x03


class FlowUART:
    """
    UART0 wrapper supporting configurable flow control:
      - mode 0 (AT&K0): None (transparent 8-bit binary)
      - mode 3 (AT&K3): Hardware RTS/CTS on GP2 (CTS) and GP3 (RTS)
      - mode 4 (AT&K4): Software XON/XOFF (0x11 / 0x13) [Default]
    """

    def __init__(self, baud=UART_BAUD, flow_mode=4):
        self.baud = baud
        self.flow_mode = flow_mode
        self.paused = False
        self.aborted = False
        self.rx_queue = bytearray()
        self.uart = None
        self.configure(baud, flow_mode)

    def configure(self, baud=None, flow_mode=None):
        if baud is not None:
            self.baud = baud
        if flow_mode is not None:
            self.flow_mode = flow_mode
        self.paused = False
        if self.flow_mode == 3:
            self.uart = machine.UART(
                0,
                baudrate=self.baud,
                bits=8,
                parity=None,
                stop=1,
                tx=machine.Pin(0),
                rx=machine.Pin(1),
                cts=machine.Pin(2),
                rts=machine.Pin(3),
                flow=machine.UART.RTS | machine.UART.CTS,
                txbuf=1024,
                rxbuf=2048,
            )
        else:
            self.uart = machine.UART(
                0,
                baudrate=self.baud,
                bits=8,
                parity=None,
                stop=1,
                tx=machine.Pin(0),
                rx=machine.Pin(1),
                txbuf=1024,
                rxbuf=2048,
            )

    def _drain_hw_rx(self, intercept_ctrl_c=False):
        while self.uart.any():
            raw = self.uart.read()
            if not raw:
                break
            if self.flow_mode == 4:
                for b in raw:
                    if b == XOFF:
                        self.paused = True
                    elif b == XON:
                        self.paused = False
                    elif intercept_ctrl_c and b == CTRL_C:
                        self.aborted = True
                    else:
                        self.rx_queue.append(b)
            else:
                if intercept_ctrl_c and CTRL_C in raw:
                    self.aborted = True
                self.rx_queue.extend(raw)

    def check_abort(self):
        self._drain_hw_rx(intercept_ctrl_c=True)
        if self.aborted:
            self.aborted = False
            return True
        return False

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.uart.write(data)

    def write_paced(self, data):
        """Write data respecting XON/XOFF pause in AT&K4 mode."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        mv = memoryview(data)
        off = 0
        n = len(data)
        while off < n:
            if self.flow_mode == 4:
                self._drain_hw_rx(intercept_ctrl_c=True)
                wait_start = time.ticks_ms()
                while self.paused:
                    time.sleep_ms(5)
                    self._drain_hw_rx(intercept_ctrl_c=True)
                    # Safety timeout (15s) or Ctrl-C unpauses
                    if self.aborted or time.ticks_diff(time.ticks_ms(), wait_start) > 15000:
                        self.paused = False
                        break
            chunk = mv[off : off + 64]
            self.uart.write(chunk)
            off += len(chunk)

    def read_command_bytes(self):
        self._drain_hw_rx(intercept_ctrl_c=False)
        if not self.rx_queue:
            return None
        out = bytes(self.rx_queue)
        self.rx_queue = bytearray()
        return out

    def read_online(self):
        self._drain_hw_rx(intercept_ctrl_c=False)
        if not self.rx_queue:
            return None
        out = bytes(self.rx_queue)
        self.rx_queue = bytearray()
        return out


class AtModem:
    def __init__(self):
        self.led = machine.Pin("LED", machine.Pin.OUT)
        self.led.on()
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)

        self.echo = True
        self.flow_mode = 4  # Default AT&K4 (XON/XOFF)
        self.ssid = ""
        self.password = ""
        self.auto_join = True

        self.load_config(silent=True)
        self.io = FlowUART(UART_BAUD, self.flow_mode)

        # Online socket state (for ATDT / ATDS / +++ / ATO / ATH)
        self.mode = "COMMAND"  # "COMMAND" or "ONLINE"
        self.sock = None
        self.raw_sock = None
        self.peer_desc = ""
        self.plus_count = 0
        self.last_rx_ms = 0

    def load_config(self, silent=False):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
            self.echo = bool(cfg.get("echo", True))
            self.flow_mode = int(cfg.get("flow_mode", 4))
            self.ssid = cfg.get("ssid", "")
            self.password = cfg.get("password", "")
            self.auto_join = bool(cfg.get("auto_join", True))
            if not silent and hasattr(self, "io"):
                self.io.configure(flow_mode=self.flow_mode)
            return True
        except Exception:
            return False

    def save_config(self):
        cfg = {
            "echo": self.echo,
            "flow_mode": self.flow_mode,
            "ssid": self.ssid,
            "password": self.password,
            "auto_join": self.auto_join,
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f)

    def reply(self, text="OK"):
        self.io.write_paced(f"{text}\r\n")

    def flow_desc(self):
        if self.flow_mode == 0:
            return "&K0 (None)"
        if self.flow_mode == 3:
            return "&K3 (HW RTS/CTS)"
        return "&K4 (SW XON/XOFF)"

    def parse_quoted_args(self, s):
        """Parse comma-separated args, stripping optional surrounding quotes."""
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

    def wifi_join(self, ssid, password, timeout_s=15):
        self.ssid = ssid
        self.password = password
        self.io.write_paced(f"+WJOIN: Connecting to '{ssid}'...\r\n")
        self.wlan.disconnect()
        self.wlan.connect(ssid, password)
        t0 = time.ticks_ms()
        while not self.wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_s * 1000:
                self.reply("ERROR: Wi-Fi connection timed out")
                return False
            if self.io.check_abort():
                self.reply("ERROR: Aborted")
                return False
            self.led.toggle()
            time.sleep_ms(250)
        self.led.on()
        ip, mask, gw, dns = self.wlan.ifconfig()
        self.io.write_paced(f"+WJOIN: Connected! IP={ip} GW={gw} DNS={dns}\r\n")
        self.reply("OK")
        return True

    def dial_stream(self, target, use_tls=False):
        host, port = protocols.parse_host_port(target.strip(), 443 if use_tls else 23)
        self.close_socket()
        addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
        raw_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_s.settimeout(10.0)
        try:
            raw_s.connect(addr)
            if use_tls:
                s = ssl.wrap_socket(raw_s, server_hostname=host)
            else:
                s = raw_s
            raw_s.setblocking(False)
            self.raw_sock = raw_s
            self.sock = s
            self.peer_desc = f"{'TLS ' if use_tls else ''}{host}:{port}"
            self.mode = "ONLINE"
            self.plus_count = 0
            self.last_rx_ms = time.ticks_ms()
            self.reply(f"CONNECT {self.peer_desc}")
        except Exception as e:
            try:
                raw_s.close()
            except Exception:
                pass
            self.reply(f"NO CARRIER ({e})")

    def close_socket(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        if self.raw_sock:
            try:
                self.raw_sock.close()
            except Exception:
                pass
            self.raw_sock = None
        self.mode = "COMMAND"

    def print_help(self):
        self.io.write_paced(
            b"=== TTL2WiFi AT Command Reference ===\r\n"
            b"Classic Hayes Commands:\r\n"
            b"  AT                 - Attention check (OK)\r\n"
            b"  ATI                - Modem info, MAC, IP & settings\r\n"
            b"  AT? / AT+HELP      - Show this command summary\r\n"
            b"  ATE0 / ATE1        - Command echo Off / On\r\n"
            b"  AT&K0              - Flow control: None (8-bit binary)\r\n"
            b"  AT&K3              - Flow control: Hardware RTS/CTS (GP2/GP3)\r\n"
            b"  AT&K4              - Flow control: Software XON/XOFF (Default)\r\n"
            b"  AT&W / ATZ / AT&F  - Save / Reload / Factory-reset config\r\n"
            b"  ATDT<host>:<port>  - Dial raw TCP stream (+++ to escape)\r\n"
            b"  ATDS<host>:<port>  - Dial TLS stream (+++ to escape)\r\n"
            b"  ATO / ATH          - Return to online socket / Hang up\r\n"
            b"Extended Wi-Fi & Protocol Commands:\r\n"
            b"  AT+WSCAN           - Scan Wi-Fi access points\r\n"
            b'  AT+WJOIN="ssid","pw" - Connect to Wi-Fi network\r\n'
            b"  AT+WLEAVE          - Disconnect Wi-Fi\r\n"
            b"  AT+WSTAT           - Detailed Wi-Fi & IP status\r\n"
            b'  AT+WDNS="host"     - DNS lookup\r\n'
            b"  AT+TIME            - Sync RTC via NTP & print UTC time\r\n"
            b'  AT+GOPHER="url"    - Fetch Gopher menu or file (Ctrl-C aborts)\r\n'
            b'  AT+GEMINI="url"    - Fetch Gemini page over TLS (Ctrl-C aborts)\r\n'
            b'  AT+HTTPGET="url"   - Fetch HTTP/HTTPS URL (Ctrl-C aborts)\r\n'
            b'  AT+TELNET="h[:p]"  - Interactive Telnet session (IAC VT100 80x24)\r\n'
            b'  AT+SSH="u@host","pw" - Interactive SSH-2 PTY session\r\n'
        )
        self.reply("OK")

    def print_info(self):
        mac = ":".join(f"{b:02x}" for b in self.wlan.config("mac"))
        ip = self.wlan.ifconfig()[0] if self.wlan.isconnected() else "0.0.0.0"
        ssid = self.wlan.config("ssid") if self.wlan.isconnected() else "none"
        self.io.write_paced(
            f"TTL2WiFi v{VERSION} ({sys.implementation._machine})\r\n"
            f"MAC:  {mac}\r\n"
            f"WiFi: {'CONNECTED' if self.wlan.isconnected() else 'DISCONNECTED'} (SSID={ssid}, IP={ip})\r\n"
            f"UART: {self.io.baud} 8N1, Echo={'E1' if self.echo else 'E0'}, Flow={self.flow_desc()}\r\n"
        )
        self.reply("OK")

    def handle_command(self, line):
        cmd_raw = line.strip()
        if not cmd_raw:
            return

        print(f"[AT CMD] {cmd_raw!r}")
        up = cmd_raw.upper()

        # Convenience alias for interactive users typing 'help'
        if up == "HELP":
            self.print_help()
            return

        if not up.startswith("AT"):
            self.reply("ERROR (Commands must start with AT; type AT? for help)")
            return

        body = cmd_raw[2:].strip()
        body_up = body.upper()

        if body_up == "":
            self.reply("OK")
        elif body_up in ("?", "+HELP"):
            self.print_help()
        elif body_up in ("I", "I0", "I1"):
            self.print_info()
        elif body_up == "E0":
            self.echo = False
            self.reply("OK")
        elif body_up == "E1":
            self.echo = True
            self.reply("OK")
        elif body_up == "&K0":
            self.flow_mode = 0
            self.io.configure(flow_mode=0)
            self.reply("OK")
        elif body_up == "&K3":
            self.flow_mode = 3
            self.io.configure(flow_mode=3)
            self.reply("OK")
        elif body_up == "&K4":
            self.flow_mode = 4
            self.io.configure(flow_mode=4)
            self.reply("OK")
        elif body_up == "&W":
            self.save_config()
            self.reply("OK")
        elif body_up == "Z":
            self.load_config(silent=False)
            self.reply("OK")
        elif body_up == "&F":
            self.echo = True
            self.flow_mode = 4
            self.io.configure(flow_mode=4)
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
            nets = self.wlan.scan()
            for ssid_b, _bssid, ch, rssi, sec, _hid in sorted(nets, key=lambda x: x[3], reverse=True)[:15]:
                name = ssid_b.decode("utf-8", "replace") if ssid_b else "<hidden>"
                self.io.write_paced(f"  ch{ch:<2d}  {rssi:>4d} dBm  sec={sec}  {name}\r\n")
            self.reply("OK")
        elif body_up.startswith("+WJOIN="):
            args = self.parse_quoted_args(body[7:])
            if len(args) >= 2:
                self.wifi_join(args[0], args[1])
            elif len(args) == 1 and args[0]:
                self.wifi_join(args[0], "")
            else:
                self.reply('ERROR: Usage AT+WJOIN="ssid","password"')
        elif body_up == "+WLEAVE":
            self.wlan.disconnect()
            self.reply("OK")
        elif body_up == "+WSTAT":
            mac = ":".join(f"{b:02x}" for b in self.wlan.config("mac"))
            if self.wlan.isconnected():
                ip, mask, gw, dns = self.wlan.ifconfig()
                ssid = self.wlan.config("ssid")
                rssi = self.wlan.status("rssi")
                self.io.write_paced(
                    f"+WSTAT: CONNECTED\r\n"
                    f"  SSID:    {ssid}\r\n"
                    f"  RSSI:    {rssi} dBm\r\n"
                    f"  IP:      {ip}\r\n"
                    f"  Netmask: {mask}\r\n"
                    f"  Gateway: {gw}\r\n"
                    f"  DNS:     {dns}\r\n"
                    f"  MAC:     {mac}\r\n"
                )
            else:
                self.io.write_paced(f"+WSTAT: DISCONNECTED (status={self.wlan.status()}, MAC={mac})\r\n")
            self.reply("OK")
        elif body_up.startswith("+WDNS="):
            host = self.parse_quoted_args(body[6:])[0]
            ip = socket.getaddrinfo(host, 80)[0][-1][0]
            self.io.write_paced(f"+WDNS: {host} -> {ip}\r\n")
            self.reply("OK")
        elif body_up == "+TIME":
            ts = protocols.ntp_sync()
            self.io.write_paced(f"+TIME: {ts}\r\n")
            self.reply("OK")
        elif body_up.startswith("+GOPHER="):
            target = self.parse_quoted_args(body[8:])[0]
            protocols.gopher_fetch(target, self.io)
            self.reply("OK")
        elif body_up.startswith("+GEMINI="):
            target = self.parse_quoted_args(body[8:])[0]
            protocols.gemini_fetch(target, self.io)
            self.reply("OK")
        elif body_up.startswith("+HTTPGET="):
            target = self.parse_quoted_args(body[9:])[0]
            protocols.http_fetch(target, self.io)
            self.reply("OK")
        elif body_up.startswith("+TELNET="):
            target = self.parse_quoted_args(body[8:])[0]
            protocols.telnet_session(target, self.io)
        elif body_up.startswith("+SSH="):
            args = self.parse_quoted_args(body[5:])
            if len(args) >= 2:
                ssh.ssh_connect_and_run(args[0], args[1], self.io)
            else:
                self.reply('ERROR: Usage AT+SSH="user@host[:port]","password"')
        else:
            self.reply(f"ERROR: Unknown command AT{body}")

    def poll_online(self):
        # 1. UART -> Socket (with '+++' escape detection)
        u_data = self.io.read_online()
        if u_data:
            now = time.ticks_ms()
            if u_data == b"+" and time.ticks_diff(now, self.last_rx_ms) > 800:
                self.plus_count = 1
            elif u_data == b"+" and 0 < self.plus_count < 3:
                self.plus_count += 1
                if self.plus_count == 3:
                    self.mode = "COMMAND"
                    self.io.write_paced(b"\r\nOK\r\n")
                    return
            else:
                self.plus_count = 0
            self.last_rx_ms = now
            try:
                if hasattr(self.sock, "write"):
                    self.sock.write(u_data)
                else:
                    self.sock.sendall(u_data)
            except Exception:
                self.close_socket()
                self.io.write_paced(b"\r\nNO CARRIER\r\n")
                return

        # 2. Socket -> UART (paced by XON/XOFF)
        try:
            chunk = self.sock.read(256) if hasattr(self.sock, "read") else self.sock.recv(256)
            if chunk == b"":
                self.close_socket()
                self.io.write_paced(b"\r\nNO CARRIER\r\n")
                return
            if chunk:
                self.io.write_paced(chunk)
        except OSError as e:
            # EAGAIN / EWOULDBLOCK (-11 / 11) on non-blocking socket means no data right now
            if e.args and e.args[0] in (-11, 11, 110, -110):
                pass
            else:
                self.close_socket()
                self.io.write_paced(b"\r\nNO CARRIER\r\n")

    def run(self):
        print(f"TTL2WiFi v{VERSION} AT Modem started on UART0 ({self.io.baud} 8N1, Flow={self.flow_desc()})")
        self.io.write_paced(
            f"\r\nTTL2WiFi v{VERSION} Hayes AT / Protocol Bridge Ready ({self.io.baud} 8N1, {self.flow_desc()})\r\n"
            f"Type AT? for commands.\r\nOK\r\n"
        )

        if self.ssid and self.auto_join and not self.wlan.isconnected():
            try:
                self.wlan.connect(self.ssid, self.password)
            except Exception:
                pass

        line_buf = bytearray()
        while True:
            if self.mode == "ONLINE" and self.sock:
                self.poll_online()
                time.sleep_ms(5)
                continue

            data = self.io.read_command_bytes()
            if data:
                for b in data:
                    if b in (0x0D, 0x0A):
                        if self.echo:
                            self.io.write(b"\r\n")
                        if len(line_buf) > 0:
                            line = line_buf.decode("utf-8", "replace")
                            line_buf = bytearray()
                            try:
                                self.handle_command(line)
                            except Exception as e:
                                print(f"[AT ERR] {e!r}")
                                self.reply(f"ERROR: {e}")
                    elif b in (0x08, 0x7F):
                        if len(line_buf) > 0:
                            line_buf = line_buf[:-1]
                            if self.echo:
                                self.io.write(b"\x08 \x08")
                    elif 0x20 <= b <= 0x7E:
                        line_buf.append(b)
                        if self.echo:
                            self.io.write(bytes([b]))
            time.sleep_ms(10)


if __name__ == "__main__":
    AtModem().run()
