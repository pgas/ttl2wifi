# protocols.py - Built-in Gopher, Gemini (TLS), HTTP/HTTPS, Telnet, XMODEM, and NTP clients
import socket
import ssl
import struct
import time

# RFC 854 Telnet protocol constants
IAC = 255
DONT = 254
DO = 253
WONT = 252
WILL = 251
SB = 250
SE = 240

OPT_BINARY = 0
OPT_ECHO = 1
OPT_SGA = 3
OPT_TTYPE = 24
OPT_NAWS = 31

# XMODEM constants
SOH = 0x01
EOT = 0x04
ACK = 0x06
NAK = 0x15
CAN = 0x18
CRC_CHR = 0x43  # 'C'

GOPHER_TYPES = {
    "0": "TXT",
    "1": "DIR",
    "2": "CSO",
    "3": "ERR",
    "4": "HEX",
    "5": "DOS",
    "6": "UUE",
    "7": "QRY",
    "8": "TEL",
    "9": "BIN",
    "g": "GIF",
    "I": "IMG",
    "h": "HTM",
    "i": "   ",
    "s": "SND",
}


class BrowserState:
    """Tracks numbered links and browsing history across Gopher and Gemini pages."""

    def __init__(self):
        self.links = []    # List of (url, label, item_type)
        self.history = []  # Stack of visited URLs
        self.cur_url = ""

    def set_page(self, url, push_history=True):
        if push_history and self.cur_url and self.cur_url != url:
            self.history.append(self.cur_url)
            if len(self.history) > 20:
                self.history.pop(0)
        self.cur_url = url
        self.links = []

    def add_link(self, url, label="", item_type=""):
        self.links.append((url, label, item_type))
        return len(self.links)


def parse_host_port(hostport, default_port):
    if ":" in hostport:
        host, port_s = hostport.rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return hostport, default_port
    return hostport, default_port


def resolve_url(base_url, ref):
    ref = ref.strip()
    if "://" in ref:
        return ref
    scheme, rest = base_url.split("://", 1)
    if "/" in rest:
        hostport, path = rest.split("/", 1)
        path = "/" + path
    else:
        hostport = rest
        path = "/"
    if ref.startswith("//"):
        return f"{scheme}:{ref}"
    if ref.startswith("/"):
        return f"{scheme}://{hostport}{ref}"
    base_dir = path.rsplit("/", 1)[0]
    return f"{scheme}://{hostport}{base_dir}/{ref}"


def stream_socket_lines(sock, flow_uart, max_bytes=262144):
    """Stream lines from sock to flow_uart with XON/XOFF flow control and Ctrl-C abort."""
    total = 0
    buf = b""
    while total < max_bytes:
        if flow_uart.check_abort():
            flow_uart.write(b"\r\n^C Aborted\r\n")
            return
        chunk = sock.read(512) if hasattr(sock, "read") else sock.recv(512)
        if not chunk:
            break
        total += len(chunk)
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.rstrip(b"\r")
    if buf:
        yield buf.rstrip(b"\r")


def gopher_fetch(target, flow_uart, nav=None, query=None, push_history=True):
    """
    Fetch a Gopher menu or document and number selectable links [1], [2], ...
    """
    url = target.strip()
    if url.startswith("gopher://"):
        url = url[9:]

    item_type = "1"
    if "/" in url:
        hostport, selector = url.split("/", 1)
        if len(selector) >= 1 and selector[0] in GOPHER_TYPES and (len(selector) == 1 or selector[1] == "/"):
            item_type = selector[0]
            selector = selector[1:]
        elif not selector.startswith("/"):
            selector = "/" + selector
    else:
        hostport = url
        selector = ""

    canon_url = f"gopher://{hostport}/{item_type}{selector}"
    if nav is not None:
        nav.set_page(canon_url, push_history=push_history)

    host, port = parse_host_port(hostport, 70)
    addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    flow_uart.reset_pager()
    try:
        sock.connect(addr)
        req_sel = f"{selector}\t{query}" if query else selector
        sock.sendall((req_sel + "\r\n").encode("utf-8"))

        for raw_line in stream_socket_lines(sock, flow_uart):
            if flow_uart.check_abort():
                flow_uart.write(b"\r\n^C Aborted\r\n")
                break
            if raw_line == b".":
                break
            if b"\t" in raw_line and item_type in ("1", "7"):
                parts = raw_line.decode("utf-8", "replace").split("\t")
                if parts and len(parts[0]) >= 1:
                    t_ch = parts[0][0]
                    display = parts[0][1:]
                    sel = parts[1] if len(parts) > 1 else ""
                    h = parts[2] if len(parts) > 2 else host
                    p = parts[3] if len(parts) > 3 else "70"
                    if t_ch == "i":
                        if not flow_uart.write_line_paged("       " + display):
                            break
                    else:
                        tag = GOPHER_TYPES.get(t_ch, t_ch)
                        hp = f"{h}:{p}" if p != "70" else h
                        if sel.startswith("URL:"):
                            link_url = sel[4:]
                        elif t_ch == "8":
                            link_url = f"telnet://{hp}"
                        else:
                            if not sel.startswith("/"):
                                sel = "/" + sel
                            link_url = f"gopher://{hp}/{t_ch}{sel}"
                        idx = nav.add_link(link_url, display, t_ch) if nav is not None else 0
                        prefix = f"[{idx:>2d}:{tag}] " if idx else f"[{tag}] "
                        if not flow_uart.write_line_paged(f"{prefix}{display}"):
                            break
                    continue
            if not flow_uart.write_line_paged(raw_line.decode("utf-8", "replace")):
                break
    finally:
        sock.close()


def gemini_fetch(url, flow_uart, nav=None, max_redirects=5, push_history=True):
    """
    Fetch a Gemini (gemini://) document over TLS 1.2+ and number '=>' links [1], [2], ...
    """
    cur_url = url.strip()
    if not cur_url.startswith("gemini://"):
        cur_url = "gemini://" + cur_url

    flow_uart.reset_pager()
    for _ in range(max_redirects + 1):
        rest = cur_url[9:]
        if "/" in rest:
            hostport, path = rest.split("/", 1)
            path = "/" + path
        else:
            hostport = rest
            path = "/"
            cur_url = cur_url + "/"

        host, port = parse_host_port(hostport, 1965)
        addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(12.0)
        tls_sock = None
        try:
            raw_sock.connect(addr)
            tls_sock = ssl.wrap_socket(raw_sock, server_hostname=host)
            tls_sock.write((cur_url + "\r\n").encode("utf-8"))

            hdr = b""
            while b"\n" not in hdr and len(hdr) < 1024:
                c = tls_sock.read(1)
                if not c:
                    break
                hdr += c
            hdr_str = hdr.decode("utf-8", "replace").strip()
            flow_uart.write_paced(f"+GEMINI: {hdr_str}\r\n".encode("utf-8"))

            status = hdr_str[:2]
            meta = hdr_str[3:].strip() if len(hdr_str) > 3 else ""

            if status.startswith("3") and meta:
                cur_url = resolve_url(cur_url, meta)
                flow_uart.write_paced(f"+REDIRECT: {cur_url}\r\n".encode("utf-8"))
                continue

            if status.startswith("2"):
                if nav is not None:
                    nav.set_page(cur_url, push_history=push_history)
                is_gemtext = meta == "" or "text/gemini" in meta
                for raw_line in stream_socket_lines(tls_sock, flow_uart):
                    if flow_uart.check_abort():
                        flow_uart.write(b"\r\n^C Aborted\r\n")
                        break
                    line_s = raw_line.decode("utf-8", "replace")
                    if is_gemtext and line_s.startswith("=>"):
                        rem = line_s[2:].strip()
                        if rem:
                            parts = rem.split(None, 1)
                            ref = parts[0]
                            label = parts[1] if len(parts) > 1 else ref
                            full_link = resolve_url(cur_url, ref)
                            idx = nav.add_link(full_link, label, "GMI") if nav is not None else 0
                            line_s = f"[{idx:>2d}] {label} ({ref})" if idx else f"=> {label}"
                    if not flow_uart.write_line_paged(line_s):
                        break
            return
        finally:
            if tls_sock:
                try:
                    tls_sock.close()
                except Exception:
                    pass
            try:
                raw_sock.close()
            except Exception:
                pass

    flow_uart.write_paced(b"ERROR: Too many redirects\r\n")


def http_fetch(url, flow_uart):
    """Fetch an HTTP or HTTPS URL and stream response headers + body."""
    u = url.strip()
    use_tls = False
    if u.startswith("https://"):
        use_tls = True
        rest = u[8:]
        default_port = 443
    elif u.startswith("http://"):
        rest = u[7:]
        default_port = 80
    else:
        rest = u
        default_port = 80

    if "/" in rest:
        hostport, path = rest.split("/", 1)
        path = "/" + path
    else:
        hostport = rest
        path = "/"

    host, port = parse_host_port(hostport, default_port)
    addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
    raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw_sock.settimeout(12.0)
    sock = raw_sock
    flow_uart.reset_pager()
    try:
        raw_sock.connect(addr)
        if use_tls:
            sock = ssl.wrap_socket(raw_sock, server_hostname=host)
        req = (
            f"GET {path} HTTP/1.0\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: ttl2wifi/1.0 (PicoW; SC131)\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("utf-8")
        if hasattr(sock, "write"):
            sock.write(req)
        else:
            sock.sendall(req)

        for raw_line in stream_socket_lines(sock, flow_uart):
            if flow_uart.check_abort():
                flow_uart.write(b"\r\n^C Aborted\r\n")
                break
            if not flow_uart.write_line_paged(raw_line.decode("utf-8", "replace")):
                break
    finally:
        try:
            sock.close()
        except Exception:
            pass
        try:
            raw_sock.close()
        except Exception:
            pass


def _crc16_xmodem(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def xmodem_send_url(url, flow_uart):
    """
    Download a URL (HTTP, HTTPS, or Gopher binary/text) and transmit it to the SC131
    over UART0 using standard 128-byte XMODEM (supports both Checksum and CRC-16).
    """
    u = url.strip()
    use_tls = False
    is_gopher = False
    if u.startswith("https://"):
        use_tls = True
        rest = u[8:]
        default_port = 443
    elif u.startswith("http://"):
        rest = u[7:]
        default_port = 80
    elif u.startswith("gopher://"):
        is_gopher = True
        rest = u[9:]
        default_port = 70
    else:
        rest = u
        default_port = 80

    if "/" in rest:
        hostport, path = rest.split("/", 1)
        path = "/" + path
    else:
        hostport = rest
        path = "/"

    host, port = parse_host_port(hostport, default_port)
    addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
    raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw_sock.settimeout(12.0)
    sock = raw_sock
    try:
        raw_sock.connect(addr)
        if use_tls:
            sock = ssl.wrap_socket(raw_sock, server_hostname=host)
        if is_gopher:
            if len(path) >= 2 and path[1] in GOPHER_TYPES and (len(path) == 2 or path[2] == "/"):
                path = path[2:]
            req = (path + "\r\n").encode("utf-8")
        else:
            req = (
                f"GET {path} HTTP/1.0\r\n"
                f"Host: {host}\r\n"
                f"User-Agent: ttl2wifi/1.0 (PicoW; SC131)\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("utf-8")
        if hasattr(sock, "write"):
            sock.write(req)
        else:
            sock.sendall(req)

        # If HTTP/HTTPS, skip HTTP response headers until \r\n\r\n
        pre_buf = b""
        if not is_gopher:
            while b"\r\n\r\n" not in pre_buf:
                c = sock.read(128) if hasattr(sock, "read") else sock.recv(128)
                if not c:
                    break
                pre_buf += c
            if b"\r\n\r\n" in pre_buf:
                pre_buf = pre_buf.split(b"\r\n\r\n", 1)[1]

        flow_uart.write(b"+XMODEM: Start receiver now (waiting up to 60s for NAK/'C')...\r\n")

        # Wait for receiver initial 'C' (CRC-16) or NAK (Checksum)
        use_crc = False
        t0 = time.ticks_ms()
        while True:
            if time.ticks_diff(time.ticks_ms(), t0) > 60000:
                flow_uart.write(b"\r\nERROR: XMODEM receiver timeout\r\n")
                return
            b = flow_uart.read_raw_byte(timeout_ms=200)
            if b == CRC_CHR:
                use_crc = True
                break
            if b == NAK:
                use_crc = False
                break
            if b == CAN:
                flow_uart.write(b"\r\nERROR: Cancelled by receiver\r\n")
                return

        blk_num = 1
        eof_reached = False
        while not eof_reached:
            while len(pre_buf) < 128:
                c = sock.read(128 - len(pre_buf)) if hasattr(sock, "read") else sock.recv(128 - len(pre_buf))
                if not c:
                    eof_reached = True
                    break
                pre_buf += c

            if len(pre_buf) == 0 and eof_reached:
                break

            payload = pre_buf[:128]
            pre_buf = pre_buf[128:]
            if len(payload) < 128:
                payload = payload + bytes([0x1A]) * (128 - len(payload))

            hdr = bytes([SOH, blk_num & 0xFF, (255 - (blk_num & 0xFF)) & 0xFF])
            if use_crc:
                crc = _crc16_xmodem(payload)
                pkt = hdr + payload + struct.pack(">H", crc)
            else:
                chk = sum(payload) & 0xFF
                pkt = hdr + payload + bytes([chk])

            for _retry in range(10):
                flow_uart.write(pkt)
                resp = flow_uart.read_raw_byte(timeout_ms=10000)
                if resp == ACK:
                    blk_num = (blk_num + 1) & 0xFF
                    break
                if resp == CAN:
                    return
            else:
                return

        # Send EOT and wait for ACK
        for _ in range(5):
            flow_uart.write(bytes([EOT]))
            if flow_uart.read_raw_byte(timeout_ms=5000) == ACK:
                break
        time.sleep_ms(300)
        flow_uart.write(b"\r\n+XMODEM: Transfer complete\r\n")
    finally:
        try:
            sock.close()
        except Exception:
            pass
        try:
            raw_sock.close()
        except Exception:
            pass


def ntp_sync(host="pool.ntp.org"):
    """Query NTP server, set machine.RTC(), and return formatted UTC string."""
    import machine

    NTP_DELTA = 2208988800
    addr = socket.getaddrinfo(host, 123)[0][-1]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(5.0)
    try:
        msg = bytearray(48)
        msg[0] = 0x1B
        s.sendto(msg, addr)
        data, _ = s.recvfrom(48)
        sec = struct.unpack("!I", data[40:44])[0] - NTP_DELTA
        tm = time.gmtime(sec)
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
        return f"{tm[0]:04d}-{tm[1]:02d}-{tm[2]:02d} {tm[3]:02d}:{tm[4]:02d}:{tm[5]:02d} UTC"
    finally:
        s.close()


def _process_telnet_rx(chunk, state, sock, term_type="VT100", width=80, height=24):
    """
    Process incoming Telnet bytes, handling RFC 854 IAC commands & subnegotiation
    (ECHO, SGA, TERMINAL-TYPE, NAWS) and returning clean display bytes for the UART.
    """
    out = bytearray()
    reply = bytearray()
    mode = state["mode"]
    sb_buf = state["sb_buf"]

    for b in chunk:
        if mode == "DATA":
            if b == IAC:
                mode = "IAC"
            else:
                out.append(b)
        elif mode == "IAC":
            if b == IAC:
                out.append(IAC)
                mode = "DATA"
            elif b in (DO, DONT, WILL, WONT):
                state["cmd"] = b
                mode = "OPT"
            elif b == SB:
                sb_buf[:] = b""
                mode = "SB"
            else:
                mode = "DATA"
        elif mode == "OPT":
            cmd = state["cmd"]
            opt = b
            if cmd == DO:
                if opt in (OPT_TTYPE, OPT_SGA, OPT_BINARY):
                    reply.extend(bytes([IAC, WILL, opt]))
                elif opt == OPT_NAWS:
                    reply.extend(bytes([IAC, WILL, OPT_NAWS]))
                    reply.extend(
                        bytes([IAC, SB, OPT_NAWS])
                        + struct.pack(">HH", width, height)
                        + bytes([IAC, SE])
                    )
                else:
                    reply.extend(bytes([IAC, WONT, opt]))
            elif cmd == WILL:
                if opt in (OPT_ECHO, OPT_SGA, OPT_BINARY):
                    reply.extend(bytes([IAC, DO, opt]))
                else:
                    reply.extend(bytes([IAC, DONT, opt]))
            elif cmd == DONT:
                reply.extend(bytes([IAC, WONT, opt]))
            elif cmd == WONT:
                reply.extend(bytes([IAC, DONT, opt]))
            mode = "DATA"
        elif mode == "SB":
            if b == IAC:
                mode = "SB_IAC"
            else:
                sb_buf.append(b)
        elif mode == "SB_IAC":
            if b == SE:
                if len(sb_buf) >= 2 and sb_buf[0] == OPT_TTYPE and sb_buf[1] == 1:
                    reply.extend(
                        bytes([IAC, SB, OPT_TTYPE, 0])
                        + term_type.encode("ascii")
                        + bytes([IAC, SE])
                    )
                mode = "DATA"
            elif b == IAC:
                sb_buf.append(IAC)
                mode = "SB"
            else:
                mode = "DATA"

    state["mode"] = mode
    if reply:
        sock.sendall(reply)
    return bytes(out)


def telnet_session(target, flow_uart, term_type="VT100", width=80, height=24):
    """
    Interactive RFC 854 Telnet client with IAC option negotiation (VT100, 80x24, SGA, ECHO).
    """
    u = target.strip()
    if u.startswith("telnet://"):
        u = u[9:].rstrip("/")
    host, port = parse_host_port(u, 23)
    addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    try:
        sock.connect(addr)
        sock.setblocking(False)
        flow_uart.write_paced(f"CONNECT TELNET {host}:{port} ({term_type} {width}x{height})\r\n".encode("utf-8"))

        state = {"mode": "DATA", "cmd": 0, "sb_buf": bytearray()}
        plus_count = 0
        last_rx_ms = time.ticks_ms()

        while True:
            u_data = flow_uart.read_online()
            if u_data:
                now = time.ticks_ms()
                if u_data == b"+" and time.ticks_diff(now, last_rx_ms) > 800:
                    plus_count = 1
                elif u_data == b"+" and 0 < plus_count < 3:
                    plus_count += 1
                    if plus_count == 3:
                        break
                else:
                    plus_count = 0
                last_rx_ms = now
                if b"\xff" in u_data:
                    u_data = u_data.replace(b"\xff", b"\xff\xff")
                sock.sendall(u_data)

            try:
                chunk = sock.recv(256)
                if chunk == b"":
                    break
                if chunk:
                    clean = _process_telnet_rx(chunk, state, sock, term_type, width, height)
                    if clean:
                        flow_uart.write_paced(clean)
            except OSError as e:
                if e.args and e.args[0] in (-11, 11, 110, -110):
                    pass
                else:
                    break

            time.sleep_ms(5)

        flow_uart.write_paced(b"\r\nNO CARRIER\r\n")
    finally:
        try:
            sock.close()
        except Exception:
            pass
