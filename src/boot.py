# boot.py - Interactive MicroPython REPL over 3-pin SWD Debug Probe (SRAM ringbuffer)
import io, os, struct, uctypes, machine

_S0, _S1, _N = 0x4005800C, 0x40058010, 512


class _SwdTerm(io.IOBase):
    def __init__(self):
        self.b = bytearray(16 + _N * 2)
        machine.mem32[_S0] = uctypes.addressof(self.b)
        machine.mem32[_S1] = 0x53574452

    def readinto(self, buf):
        rh, rt = struct.unpack_from("<II", self.b, 8)
        if rh == rt:
            return None
        n, m = 0, len(buf)
        while rt != rh and n < m:
            buf[n] = self.b[16 + _N + rt]
            rt = (rt + 1) & (_N - 1)
            n += 1
        struct.pack_into("<I", self.b, 12, rt)
        return n

    def write(self, buf):
        th, tt = struct.unpack_from("<II", self.b, 0)
        for c in buf:
            nx = (th + 1) & (_N - 1)
            if nx == tt:
                tt = (tt + 1) & (_N - 1)
                struct.pack_into("<I", self.b, 4, tt)
            self.b[16 + th] = c
            th = nx
        struct.pack_into("<I", self.b, 0, th)
        return len(buf)


_t = _SwdTerm()
os.dupterm(_t)


def _poll(_):
    rh, rt = struct.unpack_from("<II", _t.b, 8)
    if rh != rt:
        os.dupterm_notify(None)


_tmr = machine.Timer(-1)
_tmr.init(period=15, mode=machine.Timer.PERIODIC, callback=_poll)
