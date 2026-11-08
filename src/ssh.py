# ssh.py - SSH-2 Client for MicroPython (Pico W)
# Supports: curve25519-sha256 (RFC 8731) & diffie-hellman-group14-sha256 (RFC 8268)
# Cipher:   aes128-ctr (via C cryptolib.aes)
# MAC:      hmac-sha2-256 (via C hashlib.sha256)

try:
    import cryptolib
except ImportError:
    cryptolib = None
import hashlib
import os
import socket
import struct
import time
import net

# SSH Message Numbers (RFC 4253 / 4252 / 4254 / 8731)
SSH_MSG_DISCONNECT = 1
SSH_MSG_IGNORE = 2
SSH_MSG_UNIMPLEMENTED = 3
SSH_MSG_DEBUG = 4
SSH_MSG_SERVICE_REQUEST = 5
SSH_MSG_SERVICE_ACCEPT = 6
SSH_MSG_KEXINIT = 20
SSH_MSG_NEWKEYS = 21
SSH_MSG_KEX_INIT = 30        # KEX_ECDH_INIT (30) / KEXDH_INIT (30)
SSH_MSG_KEX_REPLY = 31       # KEX_ECDH_REPLY (31) / KEXDH_REPLY (31)
SSH_MSG_USERAUTH_REQUEST = 50
SSH_MSG_USERAUTH_FAILURE = 51
SSH_MSG_USERAUTH_SUCCESS = 52
SSH_MSG_USERAUTH_BANNER = 53
SSH_MSG_USERAUTH_INFO_REQUEST = 60
SSH_MSG_USERAUTH_INFO_RESPONSE = 61
SSH_MSG_GLOBAL_REQUEST = 80
SSH_MSG_CHANNEL_OPEN = 90
SSH_MSG_CHANNEL_OPEN_CONFIRMATION = 91
SSH_MSG_CHANNEL_OPEN_FAILURE = 92
SSH_MSG_CHANNEL_WINDOW_ADJUST = 93
SSH_MSG_CHANNEL_DATA = 94
SSH_MSG_CHANNEL_EXTENDED_DATA = 95
SSH_MSG_CHANNEL_EOF = 96
SSH_MSG_CHANNEL_CLOSE = 97
SSH_MSG_CHANNEL_REQUEST = 98
SSH_MSG_CHANNEL_SUCCESS = 99
SSH_MSG_CHANNEL_FAILURE = 100

# Curve25519 prime 2^255 - 19 (RFC 7748)
_P25519 = (1 << 255) - 19
_BASE25519 = b"\x09" + b"\x00" * 31

# RFC 3526 Group 14 2048-bit MODP Prime (Fallback)
_DH_G14_P = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AACAA68FFFFFFFFFFFFFFFF",
    16,
)
_DH_G14_G = 2


def _x25519(k_bytes, u_bytes):
    """RFC 7748 X25519 scalar multiplication over GF(2^255 - 19)."""
    P = _P25519
    k = bytearray(k_bytes)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    scalar = int.from_bytes(k, "little")
    u = int.from_bytes(u_bytes, "little") & ((1 << 255) - 1)
    x_1, x_2, z_2, x_3, z_3, swap = u, 1, 0, u, 1, 0
    for t in range(254, -1, -1):
        k_t = (scalar >> t) & 1
        swap ^= k_t
        if swap:
            x_2, x_3 = x_3, x_2
            z_2, z_3 = z_3, z_2
        swap = k_t
        A = (x_2 + z_2) % P
        AA = (A * A) % P
        B = (x_2 - z_2) % P
        BB = (B * B) % P
        E = (AA - BB) % P
        C = (x_3 + z_3) % P
        D = (x_3 - z_3) % P
        DA = (D * A) % P
        CB = (C * B) % P
        t1 = (DA + CB) % P
        x_3 = (t1 * t1) % P
        t2 = (DA - CB) % P
        z_3 = (x_1 * ((t2 * t2) % P)) % P
        x_2 = (AA * BB) % P
        z_2 = (E * (AA + 121665 * E)) % P
    if swap:
        x_2, x_3 = x_3, x_2
        z_2, z_3 = z_3, z_2
    res = (x_2 * pow(z_2, P - 2, P)) % P
    return res.to_bytes(32, "little")


def _ssh_str(b):
    if isinstance(b, str):
        b = b.encode("utf-8")
    return struct.pack(">I", len(b)) + b


def _ssh_mpint(n):
    if n == 0:
        return struct.pack(">I", 0)
    hex_s = "%x" % n
    if len(hex_s) & 1:
        hex_s = "0" + hex_s
    raw = bytes.fromhex(hex_s)
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return struct.pack(">I", len(raw)) + raw


def _read_ssh_str(buf, off):
    ln = struct.unpack_from(">I", buf, off)[0]
    off += 4
    return buf[off : off + ln], off + ln


def _hmac_sha256(key, msg):
    if len(key) > 64:
        key = hashlib.sha256(key).digest()
    if len(key) < 64:
        key = key + b"\x00" * (64 - len(key))
    ipad = bytes(b ^ 0x36 for b in key)
    opad = bytes(b ^ 0x5C for b in key)
    inner = hashlib.sha256(ipad + msg).digest()
    return hashlib.sha256(opad + inner).digest()


class _Aes128Ctr:
    """AES-128-CTR stream cipher built on MicroPython's C cryptolib.aes ECB."""

    def __init__(self, key16, iv16):
        self.ecb = cryptolib.aes(key16[:16], 1)
        self.ctr = bytearray(iv16[:16])

    def _inc_ctr(self):
        for i in range(15, -1, -1):
            c = (self.ctr[i] + 1) & 0xFF
            self.ctr[i] = c
            if c != 0:
                break

    def process(self, data):
        out = bytearray(len(data))
        ks = bytearray(16)
        mv_data = memoryview(data)
        for off in range(0, len(data), 16):
            self.ecb.encrypt(self.ctr, ks)
            self._inc_ctr()
            blk_len = min(16, len(data) - off)
            for j in range(blk_len):
                out[off + j] = mv_data[off + j] ^ ks[j]
        return bytes(out)


class SshSession:
    def __init__(self, sock):
        self.sock = sock
        self.tx_seq = 0
        self.rx_seq = 0
        self.tx_cipher = None
        self.rx_cipher = None
        self.tx_mac_key = None
        self.rx_mac_key = None

    def _recv_exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise OSError("SSH socket closed by peer")
            buf.extend(chunk)
        return bytes(buf)

    def send_packet(self, payload):
        block_size = 16 if self.tx_cipher else 8
        pkt_len_no_pad = 1 + len(payload)
        pad_len = block_size - ((4 + pkt_len_no_pad) % block_size)
        if pad_len < 4:
            pad_len += block_size
        padding = os.urandom(pad_len)
        pkt = struct.pack(">IB", len(payload) + 1 + pad_len, pad_len) + payload + padding

        mac = b""
        if self.tx_mac_key:
            mac = _hmac_sha256(self.tx_mac_key, struct.pack(">I", self.tx_seq) + pkt)
        if self.tx_cipher:
            pkt = self.tx_cipher.process(pkt)
        self.sock.sendall(pkt + mac)
        self.tx_seq = (self.tx_seq + 1) & 0xFFFFFFFF

    def recv_packet(self):
        while True:
            if self.rx_cipher is None:
                first8 = self._recv_exact(8)
                pkt_len, pad_len = struct.unpack(">IB", first8[:5])
                rem = (4 + pkt_len) - 8
                rest = self._recv_exact(rem) if rem > 0 else b""
                full = first8 + rest
            else:
                first16 = self.rx_cipher.process(self._recv_exact(16))
                pkt_len, pad_len = struct.unpack(">IB", first16[:5])
                rem = (4 + pkt_len) - 16
                rest = self.rx_cipher.process(self._recv_exact(rem)) if rem > 0 else b""
                full = first16 + rest
                mac_rx = self._recv_exact(32)
                mac_calc = _hmac_sha256(self.rx_mac_key, struct.pack(">I", self.rx_seq) + full)
                if mac_rx != mac_calc:
                    raise OSError("SSH HMAC verification failed")

            self.rx_seq = (self.rx_seq + 1) & 0xFFFFFFFF
            payload = full[5 : 4 + pkt_len - pad_len]
            if not payload:
                continue
            msg_id = payload[0]
            if msg_id in (SSH_MSG_IGNORE, SSH_MSG_DEBUG, SSH_MSG_GLOBAL_REQUEST, 7):  # 7 = EXT_INFO
                continue
            if msg_id == SSH_MSG_DISCONNECT:
                reason = payload[5:].decode("utf-8", "replace")
                raise OSError(f"SSH Disconnected: {reason}")
            return payload


def _derive_key(K_mpint, H, char_letter, session_id, needed_bytes=32):
    d = hashlib.sha256(K_mpint + H + char_letter.encode("ascii") + session_id).digest()
    while len(d) < needed_bytes:
        d += hashlib.sha256(K_mpint + H + d).digest()
    return d[:needed_bytes]


def ssh_connect_and_run(target, password, flow_uart):
    """
    Connect to user@host[:port], perform SSH-2 KEX (curve25519-sha256 or DH group14)
    + password/keyboard-interactive auth, open a vt100 PTY + shell, and bridge UART0.
    """
    if cryptolib is None:
        raise OSError("SSH needs MicroPython cryptolib (not available in simulator)")
    if "@" not in target:
        raise ValueError('Expected "user@host[:port]"')
    user, hostport = target.split("@", 1)
    if ":" in hostport:
        host, port_s = hostport.rsplit(":", 1)
        port = int(port_s)
    else:
        host, port = hostport, 22

    addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
    raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw_sock.settimeout(15.0)
    try:
        raw_sock.connect(addr)
        V_C = b"SSH-2.0-TTL2WiFi_PicoW_1.1"
        raw_sock.sendall(V_C + b"\r\n")

        V_S = b""
        while True:
            line = b""
            while not line.endswith(b"\n"):
                c = raw_sock.recv(1)
                if not c:
                    raise OSError("Connection closed before SSH banner")
                line += c
            if line.startswith(b"SSH-2.0-") or line.startswith(b"SSH-1.99-"):
                V_S = line.rstrip(b"\r\n")
                break

        sess = SshSession(raw_sock)

        # Receive server KEXINIT first or send ours
        cookie = os.urandom(16)
        kex_payload = (
            bytes([SSH_MSG_KEXINIT])
            + cookie
            + _ssh_str("curve25519-sha256,curve25519-sha256@libssh.org,diffie-hellman-group14-sha256")
            + _ssh_str("ssh-ed25519,rsa-sha2-256,rsa-sha2-512,ecdsa-sha2-nistp256,ssh-rsa")
            + _ssh_str("aes128-ctr")
            + _ssh_str("aes128-ctr")
            + _ssh_str("hmac-sha2-256")
            + _ssh_str("hmac-sha2-256")
            + _ssh_str("none")
            + _ssh_str("none")
            + _ssh_str("")
            + _ssh_str("")
            + b"\x00"
            + struct.pack(">I", 0)
        )
        sess.send_packet(kex_payload)
        I_C = kex_payload

        I_S = sess.recv_packet()
        if I_S[0] != SSH_MSG_KEXINIT:
            raise OSError(f"Expected KEXINIT, got {I_S[0]}")

        srv_kex_bytes, _ = _read_ssh_str(I_S, 17)
        srv_kex_list = srv_kex_bytes.decode("ascii", "replace").split(",")

        use_c25519 = (
            "curve25519-sha256" in srv_kex_list
            or "curve25519-sha256@libssh.org" in srv_kex_list
        )

        if use_c25519:
            flow_uart.write(b"+SSH: Negotiating curve25519-sha256 keys...\r\n")
            priv = os.urandom(32)
            Q_C = _x25519(priv, _BASE25519)
            sess.send_packet(bytes([SSH_MSG_KEX_INIT]) + _ssh_str(Q_C))

            reply = sess.recv_packet()
            if reply[0] != SSH_MSG_KEX_REPLY:
                raise OSError(f"Expected KEX_ECDH_REPLY, got {reply[0]}")

            K_S, off = _read_ssh_str(reply, 1)
            Q_S, off = _read_ssh_str(reply, off)
            _sig, off = _read_ssh_str(reply, off)

            shared = _x25519(priv, Q_S)
            K = int.from_bytes(shared, "big")
            K_mpint = _ssh_mpint(K)

            h_ctx = hashlib.sha256()
            h_ctx.update(_ssh_str(V_C))
            h_ctx.update(_ssh_str(V_S))
            h_ctx.update(_ssh_str(I_C))
            h_ctx.update(_ssh_str(I_S))
            h_ctx.update(_ssh_str(K_S))
            h_ctx.update(_ssh_str(Q_C))
            h_ctx.update(_ssh_str(Q_S))
            h_ctx.update(K_mpint)
            H = h_ctx.digest()
        else:
            flow_uart.write(b"+SSH: Negotiating DH Group 14 SHA-256 keys...\r\n")
            x = int.from_bytes(os.urandom(32), "big") | 1
            e = pow(_DH_G14_G, x, _DH_G14_P)
            sess.send_packet(bytes([SSH_MSG_KEX_INIT]) + _ssh_mpint(e))

            reply = sess.recv_packet()
            if reply[0] != SSH_MSG_KEX_REPLY:
                raise OSError(f"Expected KEXDH_REPLY, got {reply[0]}")

            K_S, off = _read_ssh_str(reply, 1)
            f_bytes, off = _read_ssh_str(reply, off)
            _sig, off = _read_ssh_str(reply, off)

            f = int.from_bytes(f_bytes, "big")
            K = pow(f, x, _DH_G14_P)
            K_mpint = _ssh_mpint(K)

            h_ctx = hashlib.sha256()
            h_ctx.update(_ssh_str(V_C))
            h_ctx.update(_ssh_str(V_S))
            h_ctx.update(_ssh_str(I_C))
            h_ctx.update(_ssh_str(I_S))
            h_ctx.update(_ssh_str(K_S))
            h_ctx.update(_ssh_mpint(e))
            h_ctx.update(_ssh_mpint(f))
            h_ctx.update(K_mpint)
            H = h_ctx.digest()

        session_id = H

        sess.send_packet(bytes([SSH_MSG_NEWKEYS]))
        nk = sess.recv_packet()
        if nk[0] != SSH_MSG_NEWKEYS:
            raise OSError(f"Expected NEWKEYS, got {nk[0]}")

        iv_c2s = _derive_key(K_mpint, H, "A", session_id, 16)
        iv_s2c = _derive_key(K_mpint, H, "B", session_id, 16)
        key_c2s = _derive_key(K_mpint, H, "C", session_id, 16)
        key_s2c = _derive_key(K_mpint, H, "D", session_id, 16)
        mac_c2s = _derive_key(K_mpint, H, "E", session_id, 32)
        mac_s2c = _derive_key(K_mpint, H, "F", session_id, 32)

        sess.tx_cipher = _Aes128Ctr(key_c2s, iv_c2s)
        sess.rx_cipher = _Aes128Ctr(key_s2c, iv_s2c)
        sess.tx_mac_key = mac_c2s
        sess.rx_mac_key = mac_s2c

        sess.send_packet(bytes([SSH_MSG_SERVICE_REQUEST]) + _ssh_str("ssh-userauth"))
        svc = sess.recv_packet()
        if svc[0] != SSH_MSG_SERVICE_ACCEPT:
            raise OSError("ssh-userauth rejected")

        sess.send_packet(
            bytes([SSH_MSG_USERAUTH_REQUEST])
            + _ssh_str(user)
            + _ssh_str("ssh-connection")
            + _ssh_str("password")
            + b"\x00"
            + _ssh_str(password)
        )

        tried_kbd = False
        while True:
            auth_resp = sess.recv_packet()
            msg_id = auth_resp[0]
            if msg_id == SSH_MSG_USERAUTH_BANNER:
                banner, _ = _read_ssh_str(auth_resp, 1)
                flow_uart.write_paced(banner.replace(b"\n", b"\r\n"))
                continue
            if msg_id == SSH_MSG_USERAUTH_SUCCESS:
                break
            if msg_id == SSH_MSG_USERAUTH_FAILURE:
                methods, _ = _read_ssh_str(auth_resp, 1)
                if not tried_kbd and b"keyboard-interactive" in methods:
                    tried_kbd = True
                    sess.send_packet(
                        bytes([SSH_MSG_USERAUTH_REQUEST])
                        + _ssh_str(user)
                        + _ssh_str("ssh-connection")
                        + _ssh_str("keyboard-interactive")
                        + _ssh_str("")
                        + _ssh_str("")
                    )
                    continue
                raise OSError("SSH authentication failed (check username/password)")
            if msg_id == SSH_MSG_USERAUTH_INFO_REQUEST:
                num_prompts = struct.unpack_from(">I", auth_resp, 1 + 4 + len(_read_ssh_str(auth_resp, 1)[0]) + 4 + len(_read_ssh_str(auth_resp, 1 + 4 + len(_read_ssh_str(auth_resp, 1)[0]))[0]) + 4 + len(_read_ssh_str(auth_resp, 1 + 4 + len(_read_ssh_str(auth_resp, 1)[0]) + 4 + len(_read_ssh_str(auth_resp, 1 + 4 + len(_read_ssh_str(auth_resp, 1)[0]))[0]))[0]))[0]
                resp_pkt = bytes([SSH_MSG_USERAUTH_INFO_RESPONSE]) + struct.pack(">I", num_prompts)
                if num_prompts > 0:
                    resp_pkt += _ssh_str(password)
                    for _ in range(num_prompts - 1):
                        resp_pkt += _ssh_str("")
                sess.send_packet(resp_pkt)
                continue

        sess.send_packet(
            bytes([SSH_MSG_CHANNEL_OPEN])
            + _ssh_str("session")
            + struct.pack(">III", 0, 65536, 16384)
        )
        ch_resp = sess.recv_packet()
        if ch_resp[0] != SSH_MSG_CHANNEL_OPEN_CONFIRMATION:
            raise OSError("Failed to open SSH session channel")
        remote_chan = struct.unpack_from(">I", ch_resp, 5)[0]

        sess.send_packet(
            bytes([SSH_MSG_CHANNEL_REQUEST])
            + struct.pack(">I", remote_chan)
            + _ssh_str("pty-req")
            + b"\x00"
            + _ssh_str("vt100")
            + struct.pack(">IIII", 80, 24, 0, 0)
            + _ssh_str(b"\x00")
        )
        sess.send_packet(
            bytes([SSH_MSG_CHANNEL_REQUEST])
            + struct.pack(">I", remote_chan)
            + _ssh_str("shell")
            + b"\x01"
        )

        flow_uart.write(f"CONNECT SSH {host}:{port}\r\n".encode("utf-8"))
        raw_sock.settimeout(0.02)

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
                sess.send_packet(
                    bytes([SSH_MSG_CHANNEL_DATA])
                    + struct.pack(">I", remote_chan)
                    + _ssh_str(u_data)
                )

            try:
                pkt = sess.recv_packet()
            except OSError as e:
                err_s = str(e)
                if "ETIMEDOUT" in err_s or "timed out" in err_s or "110" in err_s or "11" in err_s:
                    continue
                break

            m = pkt[0]
            if m == SSH_MSG_CHANNEL_DATA:
                data, _ = _read_ssh_str(pkt, 5)
                flow_uart.write_paced(data)
            elif m == SSH_MSG_CHANNEL_EXTENDED_DATA:
                data, _ = _read_ssh_str(pkt, 9)
                flow_uart.write_paced(data)
            elif m == SSH_MSG_CHANNEL_WINDOW_ADJUST:
                pass
            elif m in (SSH_MSG_CHANNEL_EOF, SSH_MSG_CHANNEL_CLOSE):
                break
            if sess.rx_seq % 32 == 0:
                sess.send_packet(
                    bytes([SSH_MSG_CHANNEL_WINDOW_ADJUST]) + struct.pack(">II", remote_chan, 65536)
                )

        flow_uart.write(b"\r\nNO CARRIER\r\n")
    finally:
        try:
            raw_sock.close()
        except Exception:
            pass
