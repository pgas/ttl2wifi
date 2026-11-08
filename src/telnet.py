# telnet.py - Interactive RFC 854 Telnet client with IAC option negotiation
import struct
import net

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


def session(target, flow_uart, term_type="VT100", width=80, height=24):
    """
    Interactive RFC 854 Telnet client with IAC option negotiation (VT100, 80x24, SGA, ECHO).
    """
    u = target.strip()
    if u.startswith("telnet://"):
        u = u[9:].rstrip("/")
    host, port = net.parse_host_port(u, 23)
    sock = net.connect_tcp(host, port, timeout=10.0)
    try:
        sock.setblocking(False)
        flow_uart.write_paced(f"CONNECT TELNET {host}:{port} ({term_type} {width}x{height})\r\n".encode("utf-8"))

        state = {"mode": "DATA", "cmd": 0, "sb_buf": bytearray()}
        plus_count = 0
        last_rx_ms = net.ticks_ms()

        while True:
            u_data = flow_uart.read_online()
            if u_data:
                now = net.ticks_ms()
                if u_data == b"+" and net.ticks_diff(now, last_rx_ms) > 800:
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
                if not net.would_block(e):
                    break

            net.sleep_ms(5)

        flow_uart.write_paced(b"\r\nNO CARRIER\r\n")
    finally:
        net.close_quiet(sock)

