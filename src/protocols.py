# protocols.py - Built-in Gopher, Gemini (TLS), HTTP/HTTPS, Telnet, and NTP clients for TTL2WiFi
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


def parse_host_port(hostport, default_port):
    if ":" in hostport:
        host, port_s = hostport.rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return hostport, default_port
    return hostport, default_port


def stream_socket_lines(sock, flow_uart, max_bytes=262144):
    """Stream lines from sock to flow_uart with XON/XOFF flow control and Ctrl-C abort."""
    total = 0
    buf = b""
    while total < max_bytes:
        if flow_uart.check_abort():
            flow_uart.write(b"\r\n^C Aborted\r\n")
            return False
        chunk = sock.read(512) if hasattr(sock, "read") else sock.recv(512)
        if not chunk:
            break
        total += len(chunk)
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.rstrip(b"\r")
            yield line
    if buf:
        yield buf.rstrip(b"\r")
    return True


def gopher_fetch(target, flow_uart):
    """
    Fetch a Gopher selector.
    Accepts:
      - "gopher://host[:port]/[T][selector]"
      - "host[:port][/selector]"
    """
    url = target.strip()
    if url.startswith("gopher://"):
        url = url[9:]

    item_type = "1"
    if "/" in url:
        hostport, selector = url.split("/", 1)
        # Standard Gopher URLs optionally put the 1-char item type right after the first '/'
        if len(selector) >= 2 and selector[1] == "/" and selector[0] in GOPHER_TYPES:
            item_type = selector[0]
            selector = selector[1:]
        elif not selector.startswith("/"):
            selector = "/" + selector
    else:
        hostport = url
        selector = ""

    host, port = parse_host_port(hostport, 70)
    addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    try:
        sock.connect(addr)
        req = (selector + "\r\n").encode("utf-8")
        sock.sendall(req)

        for raw_line in stream_socket_lines(sock, flow_uart):
            if flow_uart.check_abort():
                flow_uart.write(b"\r\n^C Aborted\r\n")
                break
            if raw_line == b".":
                break
            # Format Gopher directory lines if tab-delimited, otherwise print raw text
            if b"\t" in raw_line and item_type == "1":
                parts = raw_line.decode("utf-8", "replace").split("\t")
                if parts and len(parts[0]) >= 1:
                    t_ch = parts[0][0]
                    display = parts[0][1:]
                    sel = parts[1] if len(parts) > 1 else ""
                    h = parts[2] if len(parts) > 2 else ""
                    p = parts[3] if len(parts) > 3 else "70"
                    if t_ch == "i":
                        flow_uart.write_paced((display + "\r\n").encode("utf-8"))
                    else:
                        tag = GOPHER_TYPES.get(t_ch, f"[{t_ch}]")
                        loc = f"{h}:{p}{sel}" if p != "70" else f"{h}{sel}"
                        line_out = f"[{tag}] {display}\r\n      -> {loc}\r\n"
                        flow_uart.write_paced(line_out.encode("utf-8"))
                    continue
            flow_uart.write_paced(raw_line + b"\r\n")
    finally:
        sock.close()


def gemini_fetch(url, flow_uart, max_redirects=5):
    """
    Fetch a Gemini (gemini://) document over TLS 1.2+.
    Automatically follows up to max_redirects 3x redirects.
    """
    cur_url = url.strip()
    if not cur_url.startswith("gemini://"):
        cur_url = "gemini://" + cur_url

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

            # Read Gemini response header line (<STATUS> <META>\r\n)
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

            # Handle 3x Redirect
            if status.startswith("3") and meta:
                if meta.startswith("gemini://"):
                    cur_url = meta
                elif meta.startswith("/"):
                    cur_url = f"gemini://{hostport}{meta}"
                else:
                    base = cur_url.rsplit("/", 1)[0]
                    cur_url = f"{base}/{meta}"
                flow_uart.write_paced(f"+REDIRECT: {cur_url}\r\n".encode("utf-8"))
                continue

            # Stream response body for 2x Success
            if status.startswith("2"):
                for raw_line in stream_socket_lines(tls_sock, flow_uart):
                    if flow_uart.check_abort():
                        flow_uart.write(b"\r\n^C Aborted\r\n")
                        break
                    flow_uart.write_paced(raw_line + b"\r\n")
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
            flow_uart.write_paced(raw_line + b"\r\n")
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

    NTP_DELTA = 2208988800  # 1900-01-01 to 1970-01-01
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
        # machine.RTC().datetime((year, month, day, weekday, hours, minutes, seconds, subseconds))
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
                # Handle TERMINAL-TYPE SEND (24, 1) -> IS (24, 0) + term_type
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
            # 1. UART -> Telnet socket (escaping 0xFF as 0xFF 0xFF, and checking '+++')
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

            # 2. Telnet socket -> IAC parser -> UART (paced by XON/XOFF)
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


