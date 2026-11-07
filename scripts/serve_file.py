#!/usr/bin/env python3
"""
Serve a file over HTTP on the local LAN, displaying the corresponding
ttl2wifi AT+XMODEM and RomWBW CP/M XM commands.
"""

import argparse
import functools
import http.server
import os
import socket
import sys


def get_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    parser = argparse.ArgumentParser(
        description="Serve a file over LAN HTTP for ttl2wifi XMODEM download"
    )
    parser.add_argument("file", help="Path to the file to serve")
    parser.add_argument(
        "--port", "-p", type=int, default=8000, help="Port to listen on (default: 8000)"
    )
    parser.add_argument(
        "--delay",
        "-d",
        type=int,
        default=None,
        help="Optional inter-byte pacing in microseconds (e.g. 250, 500)",
    )
    args = parser.parse_args()

    filepath = os.path.abspath(args.file)
    if not os.path.isfile(filepath):
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    file_dir = os.path.dirname(filepath)
    file_name = os.path.basename(filepath)
    cpm_name = file_name.upper()
    ip = get_lan_ip()
    url = f"http://{ip}:{args.port}/{file_name}"
    at_cmd = f'AT+XMODEM="{url}",{args.delay}' if args.delay else f'AT+XMODEM="{url}"'

    print(f"\nServing '{file_name}' from {file_dir}")
    print(f"URL: {url}\n")
    print("=" * 60)
    print("1. In HTALK (Port 1):")
    print(f"   {at_cmd}")
    print("   (Wait for '+XMODEM: Start receiver now...', then Ctrl+C)")
    print()
    print("2. In CP/M:")
    print(f"   XM R1 {cpm_name}")
    print("=" * 60 + "\n")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=file_dir)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
