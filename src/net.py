# net.py - Shared network helpers, TLS wrapper, timing shims, and BrowserState
#
# Runs unmodified on MicroPython (Pico W) and CPython (host simulator, sim/sim_bridge.py).
import socket
import ssl
import time

# True on the host simulator (CPython), False on the Pico W (MicroPython)
CPYTHON = hasattr(ssl, "create_default_context")

# MicroPython / CPython timing compatibility shims
if hasattr(time, "ticks_ms"):
    ticks_ms = time.ticks_ms
    ticks_diff = time.ticks_diff
    sleep_ms = time.sleep_ms
    sleep_us = time.sleep_us
else:
    def ticks_ms():
        return int(time.monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b

    def sleep_ms(ms):
        time.sleep(ms / 1000.0)

    def sleep_us(us):
        time.sleep(us / 1000000.0)

    # ssh.py uses time.ticks_* directly
    time.ticks_ms = ticks_ms
    time.ticks_diff = ticks_diff
    time.sleep_ms = sleep_ms
    time.sleep_us = sleep_us

# errno values meaning "no data yet" on a non-blocking socket
# (lwIP: 11/110, Linux: 11, macOS: 35)
_WOULD_BLOCK = (-11, 11, 35, -35, 110, -110)
_SSL_WANT = tuple(getattr(ssl, n) for n in ("SSLWantReadError", "SSLWantWriteError") if hasattr(ssl, n))


def would_block(e):
    """True if an OSError from a non-blocking socket just means 'try again later'."""
    if _SSL_WANT and isinstance(e, _SSL_WANT):
        return True
    return bool(e.args) and e.args[0] in _WOULD_BLOCK


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


def split_url(url, schemes):
    """
    Split 'scheme://host[:port]/path' -> (scheme, host, port, path).
    `schemes` is a sequence of (scheme, default_port); the first is used when no scheme is given.
    (A tuple rather than a dict: MicroPython dicts are unordered.)
    """
    u = url.strip()
    scheme, default_port = schemes[0]
    for s, p in schemes:
        if u.startswith(s + "://"):
            scheme, default_port = s, p
            u = u[len(s) + 3:]
            break
    if "/" in u:
        hostport, path = u.split("/", 1)
        path = "/" + path
    else:
        hostport, path = u, "/"
    host, port = parse_host_port(hostport, default_port)
    return scheme, host, port, path


def resolve_url(base_url, ref):
    ref = ref.strip()
    if "://" in ref:
        return ref
    if "://" not in base_url:
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


def connect_tcp(host, port, timeout=10.0):
    """Resolve (IPv4) and connect a TCP socket."""
    addr = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][-1]
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(addr)
    except Exception:
        sock.close()
        raise
    return sock


def wrap_tls(sock, server_hostname=None):
    """Wrap a TCP socket in TLS (MicroPython ssl.wrap_socket or CPython SSLContext).
    Certificates are not verified (Gemini uses TOFU / self-signed certs)."""
    if CPYTHON:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx.wrap_socket(sock, server_hostname=server_hostname)
    return ssl.wrap_socket(sock, server_hostname=server_hostname)


def set_nonblocking(raw_sock, sock):
    """Make a (possibly TLS-wrapped) socket non-blocking.
    CPython detaches raw_sock when wrapping; MicroPython keeps using the raw socket."""
    if CPYTHON:
        sock.setblocking(False)
    else:
        raw_sock.setblocking(False)


def close_quiet(*socks):
    for s in socks:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


def sock_send(sock, data):
    # MicroPython SSL sockets only provide write(); CPython sockets provide sendall()
    if hasattr(sock, "sendall"):
        sock.sendall(data)
    else:
        sock.write(data)


def sock_recv(sock, n):
    if hasattr(sock, "read"):
        return sock.read(n)
    return sock.recv(n)


def http_request(host, path):
    return (
        f"GET {path} HTTP/1.0\r\n"
        f"Host: {host}\r\n"
        f"User-Agent: ttl2wifi/1.0 (PicoW; SC131)\r\n"
        f"Connection: close\r\n\r\n"
    ).encode("utf-8")


def stream_socket_lines(sock, flow_uart, max_bytes=262144):
    """Stream lines from sock to flow_uart with XON/XOFF flow control and Ctrl-C abort."""
    total = 0
    buf = b""
    while total < max_bytes:
        if flow_uart.check_abort():
            flow_uart.write(b"\r\n^C Aborted\r\n")
            return
        chunk = sock_recv(sock, 512)
        if not chunk:
            break
        total += len(chunk)
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.rstrip(b"\r")
    if buf:
        yield buf.rstrip(b"\r")
