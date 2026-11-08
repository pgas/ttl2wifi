# xmodem.py - 128-byte XMODEM (Checksum & CRC-16) file transfer over UART
import struct
import gopher
import net

SOH = 0x01
EOT = 0x04
ACK = 0x06
NAK = 0x15
CAN = 0x18
CRC_CHR = 0x43  # 'C'


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


def send_url(url, flow_uart, delay_us=250):
    """
    Download a URL (HTTP, HTTPS, or Gopher binary/text) and transmit it to the SC131
    over UART0 using standard 128-byte XMODEM (supports both Checksum and CRC-16).
    Optional delay_us adds an inter-byte delay within each 133-byte packet burst
    to prevent UART FIFO overrun on retro systems without hardware flow control.
    """
    scheme, host, port, path = net.split_url(url, (("http", 80), ("https", 443), ("gopher", 70)))
    raw_sock = net.connect_tcp(host, port, timeout=12.0)
    sock = raw_sock
    try:
        if scheme == "https":
            sock = net.wrap_tls(raw_sock, server_hostname=host)
        if scheme == "gopher":
            if len(path) >= 2 and path[1] in gopher.GOPHER_TYPES and (len(path) == 2 or path[2] == "/"):
                path = path[2:]
            req = (path + "\r\n").encode("utf-8")
        else:
            req = net.http_request(host, path)
        net.sock_send(sock, req)

        # If HTTP/HTTPS, skip HTTP response headers until \r\n\r\n
        pre_buf = b""
        if scheme != "gopher":
            while b"\r\n\r\n" not in pre_buf:
                c = net.sock_recv(sock, 128)
                if not c:
                    break
                pre_buf += c
            if b"\r\n\r\n" in pre_buf:
                pre_buf = pre_buf.split(b"\r\n\r\n", 1)[1]

        flow_uart.write_paced(b"+XMODEM: Start receiver now (waiting up to 60s for NAK/'C')...\r\n")

        # Flush any stale or echoed characters from UART before waiting for receiver
        if hasattr(flow_uart, "flush_rx"):
            flow_uart.flush_rx()

        # Wait for receiver initial 'C' (CRC-16) or NAK (Checksum)
        use_crc = False
        t0 = net.ticks_ms()
        while True:
            if net.ticks_diff(net.ticks_ms(), t0) > 60000:
                flow_uart.write_paced(b"\r\nERROR: XMODEM receiver timeout\r\n")
                return
            b = flow_uart.read_raw_byte(timeout_ms=200)
            if b == CRC_CHR:
                use_crc = True
                break
            if b == NAK:
                use_crc = False
                break
            if b == CAN:
                flow_uart.write_paced(b"\r\nERROR: Cancelled by receiver\r\n")
                return

        blk_num = 1
        eof_reached = False
        while not eof_reached:
            while len(pre_buf) < 128:
                c = net.sock_recv(sock, 128 - len(pre_buf))
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
                if hasattr(flow_uart, "write_paced_bytes"):
                    flow_uart.write_paced_bytes(pkt, delay_us=delay_us)
                else:
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
        net.sleep_ms(300)
        flow_uart.write_paced(b"\r\n+XMODEM: Transfer complete\r\n")
    finally:
        net.close_quiet(sock, raw_sock)

