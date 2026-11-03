#!/usr/bin/env python3
"""
Interactive MicroPython REPL, code runner, and fast file sync over the 3-pin SWD Debug Probe.
Communicates with _SwdTerm in boot.py via SRAM ringbuffers using OpenOCD's Tcl RPC server.
"""

import argparse
import binascii
import os
import select
import socket
import subprocess
import sys
import termios
import time
import tty

SCRATCH0 = 0x4005800C
SCRATCH1 = 0x40058010
MAGIC = 0x53574452
BUF_SIZE = 512
TCL_PORT = 6666


class OpenOcdTcl:
    def __init__(self, host="127.0.0.1", port=TCL_PORT):
        self.sock = socket.create_connection((host, port), timeout=2.0)

    def cmd(self, command: str) -> str:
        self.sock.sendall(command.encode("utf-8") + b"\x1a")
        chunks = []
        while True:
            data = self.sock.recv(4096)
            if not data:
                break
            if b"\x1a" in data:
                chunks.append(data[: data.index(b"\x1a")])
                break
            chunks.append(data)
        return b"".join(chunks).decode("utf-8", errors="replace").strip()

    def read_u32(self, addr: int, count: int = 1) -> list[int]:
        out = self.cmd(f"read_memory 0x{addr:08x} 32 {count}")
        return [int(x, 0) for x in out.split()]

    def write_u32(self, addr: int, values: list[int]) -> None:
        vals = " ".join(f"0x{v:08x}" for v in values)
        self.cmd(f"write_memory 0x{addr:08x} 32 {{{vals}}}")

    def read_u8(self, addr: int, count: int) -> bytes:
        if count <= 0:
            return b""
        out = self.cmd(f"read_memory 0x{addr:08x} 8 {count}")
        return bytes(int(x, 0) for x in out.split())

    def write_u8(self, addr: int, data: bytes) -> None:
        if not data:
            return
        vals = " ".join(f"0x{b:02x}" for b in data)
        self.cmd(f"write_memory 0x{addr:08x} 8 {{{vals}}}")

    def close(self):
        self.sock.close()


def ensure_openocd():
    try:
        return OpenOcdTcl(), None
    except OSError:
        proc = subprocess.Popen(
            [
                "openocd",
                "-f", "interface/cmsis-dap.cfg",
                "-f", "target/rp2040.cfg",
                "-c", "adapter speed 5000",
                "-c", f"tcl_port {TCL_PORT}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            time.sleep(0.1)
            try:
                return OpenOcdTcl(), proc
            except OSError:
                continue
        proc.kill()
        raise RuntimeError("Failed to start OpenOCD Tcl server")


def drain_tx(ocd: OpenOcdTcl, shm_addr: int) -> bytes:
    tx_head, tx_tail = ocd.read_u32(shm_addr, 2)
    if tx_head == tx_tail:
        return b""
    out = bytearray()
    while tx_tail != tx_head:
        if tx_head > tx_tail:
            chunk_len = tx_head - tx_tail
        else:
            chunk_len = BUF_SIZE - tx_tail
        out.extend(ocd.read_u8(shm_addr + 16 + tx_tail, chunk_len))
        tx_tail = (tx_tail + chunk_len) & (BUF_SIZE - 1)
    ocd.write_u32(shm_addr + 4, [tx_tail])
    return bytes(out)


def push_rx(ocd: OpenOcdTcl, shm_addr: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        rx_head, rx_tail = ocd.read_u32(shm_addr + 8, 2)
        used = (rx_head - rx_tail) & (BUF_SIZE - 1)
        free = (BUF_SIZE - 1) - used
        if free == 0:
            time.sleep(0.015)
            continue
        chunk = data[offset : offset + min(free, 256)]
        first_len = min(len(chunk), BUF_SIZE - rx_head)
        ocd.write_u8(shm_addr + 16 + BUF_SIZE + rx_head, chunk[:first_len])
        if first_len < len(chunk):
            ocd.write_u8(shm_addr + 16 + BUF_SIZE, chunk[first_len:])
        rx_head = (rx_head + len(chunk)) & (BUF_SIZE - 1)
        ocd.write_u32(shm_addr + 8, [rx_head])
        offset += len(chunk)


def exec_raw(ocd: OpenOcdTcl, shm_addr: int, code: bytes) -> None:
    """Execute Python code in MicroPython Raw REPL mode (Ctrl-A ... Ctrl-D) and stream output."""
    drain_tx(ocd, shm_addr)
    push_rx(ocd, shm_addr, b"\r\x03\x03\x01")
    deadline = time.time() + 1.0
    buf = b""
    while time.time() < deadline:
        buf += drain_tx(ocd, shm_addr)
        if b"raw REPL; CTRL-B to exit\r\n>" in buf:
            break
        time.sleep(0.015)

    push_rx(ocd, shm_addr, code.replace(b"\r\n", b"\n") + b"\x04")
    # Wait for 'OK' acknowledgement, then stream output until '\x04>'
    state = "WAIT_OK"
    pending = b""
    deadline = time.time() + 10.0
    while time.time() < deadline:
        chunk = drain_tx(ocd, shm_addr)
        if not chunk:
            time.sleep(0.015)
            continue
        deadline = time.time() + 3.0
        pending += chunk
        if state == "WAIT_OK":
            idx = pending.find(b"OK")
            if idx != -1:
                pending = pending[idx + 2 :]
                state = "STREAM"
        if state == "STREAM":
            end_idx = pending.find(b"\x04")
            if end_idx != -1:
                sys.stdout.buffer.write(pending[:end_idx])
                sys.stdout.buffer.flush()
                rest = pending[end_idx + 1 :]
                err_end = rest.find(b"\x04")
                while err_end == -1:
                    c = drain_tx(ocd, shm_addr)
                    if c:
                        rest += c
                        err_end = rest.find(b"\x04")
                    else:
                        time.sleep(0.015)
                if rest[:err_end]:
                    sys.stderr.buffer.write(rest[:err_end])
                    sys.stderr.buffer.flush()
                break
            else:
                sys.stdout.buffer.write(pending)
                sys.stdout.buffer.flush()
                pending = b""

    # Exit raw REPL back to friendly REPL (Ctrl-B)
    push_rx(ocd, shm_addr, b"\x02")
    time.sleep(0.05)
    drain_tx(ocd, shm_addr)


def _upload_file_chunked(ocd: OpenOcdTcl, shm_addr: int, filename: str, data: bytes) -> None:
    exec_raw(ocd, shm_addr, f"import binascii, gc; gc.collect(); _f = open({filename!r}, 'wb')\n".encode("utf-8"))
    for off in range(0, len(data), 768):
        b64 = binascii.b2a_base64(data[off : off + 768], newline=False).decode("ascii")
        exec_raw(ocd, shm_addr, f"_f.write(binascii.a2b_base64({b64!r}))\n".encode("utf-8"))
    exec_raw(
        ocd,
        shm_addr,
        f"_f.close(); del _f; gc.collect(); print('Synced {filename} ({len(data)} bytes)')\n".encode("utf-8"),
    )


def put_file(ocd: OpenOcdTcl, shm_addr: int, local_path: str, remote_path: str) -> None:
    data = open(local_path, "rb").read()
    _upload_file_chunked(ocd, shm_addr, remote_path, data)
    # Hardware reset via SWD so boot.py + new main.py start with a clean heap
    ocd.cmd("reset run")


def sync_dir(ocd: OpenOcdTcl, shm_addr: int, src_dir: str) -> None:
    from pathlib import Path

    root = Path(src_dir)
    files = [p for p in sorted(root.glob("*.py")) if p.name != "boot.py"]
    for p in files:
        _upload_file_chunked(ocd, shm_addr, p.name, p.read_bytes())
    ocd.cmd("reset run")


def main():
    parser = argparse.ArgumentParser(description="MicroPython REPL over SWD Debug Probe")
    parser.add_argument("-c", "--command", help="Execute a Python snippet over SWD")
    parser.add_argument("-r", "--run", help="Execute a local .py file on the target over SWD")
    parser.add_argument("-p", "--put", nargs=2, metavar=("LOCAL", "REMOTE"), help="Upload a file to the target over SWD")
    parser.add_argument("-s", "--sync", metavar="DIR", help="Sync all .py files in DIR to the target over SWD")
    parser.add_argument("--reset", action="store_true", help="Soft-reboot the target Pico W over SWD")
    args = parser.parse_args()

    ocd, proc = ensure_openocd()
    try:
        shm_addr, magic = ocd.read_u32(SCRATCH0, 2)
        if magic != MAGIC:
            print(f"Error: SWD REPL bridge not active (magic=0x{magic:08x}). Run 'make deploy' first.", file=sys.stderr)
            sys.exit(1)

        if args.reset:
            ocd.cmd("reset run")
            print("Triggered hardware reset on target Pico W.")
            return

        if args.command is not None:
            exec_raw(ocd, shm_addr, args.command.encode("utf-8") + b"\n")
            return

        if args.run is not None:
            with open(args.run, "rb") as f:
                exec_raw(ocd, shm_addr, f.read())
            return

        if args.put is not None:
            put_file(ocd, shm_addr, args.put[0], args.put[1])
            return

        if args.sync is not None:
            sync_dir(ocd, shm_addr, args.sync)
            return

        print(f"Connected to Pico W MicroPython REPL over SWD (shm @ 0x{shm_addr:08x}). Press Ctrl-] to exit.\r")
        push_rx(ocd, shm_addr, b"\r")

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                out = drain_tx(ocd, shm_addr)
                if out:
                    os.write(sys.stdout.fileno(), out)
                r, _, _ = select.select([fd], [], [], 0.02)
                if r:
                    ch = os.read(fd, 64)
                    if not ch or b"\x1d" in ch:  # Ctrl-]
                        break
                    push_rx(ocd, shm_addr, ch)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            print("\nDisconnected from SWD REPL.")
    finally:
        if proc is not None:
            try:
                ocd.cmd("shutdown")
            except Exception:
                pass
        ocd.close()
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=2.0)


if __name__ == "__main__":
    main()
