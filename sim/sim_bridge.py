#!/usr/bin/env python3
"""
sim_bridge.py - Host-side emulator for the ttl2wifi AT bridge.

Runs the *same* AT command processor and protocol clients as the Pico W firmware
(../src/modem.py, gemini.py, gopher.py, ...) under CPython. Only the transport
(HostIO) and the simulated Wi-Fi hooks (SimModem) live here.

Transports:
  --connect HOST:PORT  connect as a client to a SimH listening port (used by run_sim.sh)
  --tcp PORT           listen for a SimH / terminal connection
  --pty                create a pseudo-terminal (/dev/ttys*)
  --stdio              type AT commands directly in this terminal

Not available in the simulator: AT+SSH (needs MicroPython cryptolib).
"""

import argparse
import os
import select
import socket
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import modem  # noqa: E402
import net  # noqa: E402
from serialio import SerialIO  # noqa: E402


class HostIO(SerialIO):
    """SerialIO over a host file descriptor / socket (non-blocking reads via select)."""

    def __init__(self, fd_read, fd_write=None, sock=None, char_delay=0.0):
        super().__init__(page_lines=0)
        self.baud = 115200
        self.sock = sock
        self.fd_read = fd_read
        self.fd_write = fd_read if fd_write is None else fd_write
        self.char_delay = char_delay
        self.eof = False

    def _hw_read(self, n=None):
        if self.eof:
            return None
        r, _, _ = select.select([self.fd_read], [], [], 0)
        if not r:
            return None
        n = n or 1024
        data = self.sock.recv(n) if self.sock else os.read(self.fd_read, n)
        if not data:
            self.eof = True  # report after already-buffered input is processed
            return None
        if b"No answer on any connection" in data:
            # SimH rang before the line was ready; reconnect
            raise ConnectionError("SimH not ready")
        return data

    def read_online(self):
        data = SerialIO.read_online(self)
        if data is None and self.eof:
            raise ConnectionError("serial peer disconnected")
        return data

    read_command_bytes = read_online

    def _hw_write(self, data):
        if self.sock:
            self.sock.sendall(data)
        else:
            os.write(self.fd_write, data)

    def write_paced(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        if self.char_delay > 0:
            for i in range(len(data)):
                self._hw_write(data[i : i + 1])
                net.sleep_us(int(self.char_delay * 1e6))
        else:
            self._hw_write(data)


class SimModem(modem.AtModem):
    """AtModem with simulated Wi-Fi: the host network is always 'connected'."""

    FATAL_ERRORS = (ConnectionError,)

    def __init__(self, io, verbose=False):
        super().__init__(io, config_file=None)
        self.verbose = verbose
        self.ssid = "HostNet-Simulated"

    def log(self, msg):
        if self.verbose:
            print(f"[bridge] {msg}", file=sys.stderr, flush=True)

    def wifi_scan(self):
        return [("HostNet-Simulated", 1, -42, 3), ("GuestWiFi", 6, -65, 3)]

    def wifi_join(self, ssid, password):
        self.ssid = ssid
        self.io.write_paced(f"+WJOIN: Connected! IP=127.0.0.1 (simulated '{ssid}')\r\n")
        self.reply("OK")

    def wifi_status(self):
        self.io.write_paced(
            f"+WSTAT: CONNECTED\r\n"
            f"  SSID:    {self.ssid}\r\n"
            f"  IP:      127.0.0.1\r\n"
            f"  MAC:     00:11:22:33:44:55\r\n"
        )

    def info_lines(self):
        return [
            f"TTL2WiFi v{modem.VERSION} (host simulator, Python {sys.version.split()[0]})",
            "WiFi: CONNECTED (host network, IP=127.0.0.1)",
            f"UART: emulated 115200 8N1, Echo={'E1' if self.echo else 'E0'}, "
            f"Flow={self.flow_desc()}, Page={self.io.page_lines}",
        ]


def serve(io, verbose, echo=True):
    m = SimModem(io, verbose=verbose)
    m.echo = echo
    try:
        m.run()
    except ConnectionError as e:
        print(f"[bridge] {e}", file=sys.stderr)
    finally:
        m.close_socket()


def run_tcp_client(host, port, verbose, delay):
    """Connect to a SimH listening socket, reconnecting whenever it drops."""
    print(f"=== TTL2WiFi simulator connecting to SimH at tcp://{host}:{port} ===")
    while True:
        try:
            client = socket.create_connection((host, port), timeout=2)
        except OSError:
            net.sleep_ms(300)
            continue
        print(f"[bridge] Connected to SimH on {host}:{port}")
        client.settimeout(None)
        serve(HostIO(client.fileno(), sock=client, char_delay=delay), verbose)
        net.close_quiet(client)
        net.sleep_ms(500)


def run_tcp_server(host, port, verbose, delay):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)
    print(f"=== TTL2WiFi simulator listening on tcp://{host}:{port} ===")
    print(f"SimH: attach <dev> {host}:{port};notelnet  |  or: nc {host} {port}")
    try:
        while True:
            client, addr = server.accept()
            print(f"[bridge] Client connected from {addr[0]}:{addr[1]}")
            serve(HostIO(client.fileno(), sock=client, char_delay=delay), verbose)
            net.close_quiet(client)
    finally:
        server.close()


def run_pty(verbose, delay):
    master, slave = os.openpty()
    print(f"=== TTL2WiFi simulator on PTY: {os.ttyname(slave)} (115200 8N1) ===")
    try:
        serve(HostIO(master, char_delay=delay), verbose)
    finally:
        os.close(master)
        os.close(slave)


def run_stdio(verbose):
    # Line-buffered terminal input; local echo is done by the tty, so ATE0
    serve(HostIO(sys.stdin.fileno(), sys.stdout.fileno()), verbose, echo=False)


def main():
    p = argparse.ArgumentParser(description="TTL2WiFi AT modem / protocol bridge simulator")
    p.add_argument("--connect", metavar="HOST:PORT", help="connect to a SimH listening port (e.g. 127.0.0.1:9999)")
    p.add_argument("--tcp", type=int, default=9999, help="TCP port to listen on (default: 9999)")
    p.add_argument("--host", default="127.0.0.1", help="TCP bind address (default: 127.0.0.1)")
    p.add_argument("--pty", action="store_true", help="create a pseudo-terminal instead of TCP")
    p.add_argument("--stdio", action="store_true", help="run interactively on stdin/stdout")
    p.add_argument("-v", "--verbose", action="store_true", help="log AT commands to stderr")
    p.add_argument("--delay", type=float, default=0.0, help="per-character output delay in seconds")
    a = p.parse_args()

    try:
        if a.stdio:
            run_stdio(a.verbose)
        elif a.pty:
            run_pty(a.verbose, a.delay)
        elif a.connect:
            h, _, prt = a.connect.rpartition(":")
            run_tcp_client(h or "127.0.0.1", int(prt), a.verbose, a.delay)
        else:
            run_tcp_server(a.host, a.tcp, a.verbose, a.delay)
    except KeyboardInterrupt:
        print("\n[bridge] Stopped.")


if __name__ == "__main__":
    main()
