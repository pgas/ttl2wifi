# ntp.py - Simple Network Time Protocol (SNTP) client
import socket
import struct
import time

try:
    import machine
except ImportError:
    machine = None


def sync(host="pool.ntp.org"):
    """Query NTP server, set machine.RTC() if running on MicroPython, and return UTC string."""
    NTP_DELTA = 2208988800
    try:
        addr = socket.getaddrinfo(host, 123)[0][-1]
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(5.0)
        try:
            msg = bytearray(48)
            msg[0] = 0x1B
            s.sendto(msg, addr)
            data, _ = s.recvfrom(48)
            sec = struct.unpack("!I", data[40:44])[0] - NTP_DELTA
        finally:
            s.close()
    except Exception:
        if machine is not None:
            raise
        sec = int(time.time())

    tm = time.gmtime(sec)
    if machine is not None:
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
    return f"{tm[0]:04d}-{tm[1]:02d}-{tm[2]:02d} {tm[3]:02d}:{tm[4]:02d}:{tm[5]:02d} UTC"

