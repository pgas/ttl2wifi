# serialio.py - Platform-neutral serial I/O base class (pager, abort, line input)
#
# Subclasses provide the raw byte transport:
#   - main.FlowUART        : RP2040 UART0 with RTS/CTS or XON/XOFF (Pico W)
#   - sim/sim_bridge.HostIO: TCP socket / PTY / stdio (host simulator)
import net

XON = 0x11   # Ctrl-Q
XOFF = 0x13  # Ctrl-S
CTRL_C = 0x03


class SerialIO:
    """Interface used by the AT modem and every protocol module (gopher, gemini, xmodem...)."""

    def __init__(self, page_lines=0):
        self.page_lines = page_lines
        self.cur_line = 0
        self.aborted = False
        self.rx_queue = bytearray()

    # ---- transport hooks (override) -------------------------------------
    def _hw_read(self, n=None):
        """Non-blocking read: return available bytes (at most n) or None."""
        raise NotImplementedError

    def _hw_write(self, data):
        raise NotImplementedError

    def _filter_rx(self, raw, intercept_ctrl_c):
        """Move received bytes into rx_queue (FlowUART overrides for XON/XOFF)."""
        if intercept_ctrl_c and CTRL_C in raw:
            self.aborted = True
        self.rx_queue.extend(raw)

    def write_paced(self, data):
        """Write text to the retro host (FlowUART overrides with per-byte pacing)."""
        self.write(data)

    # ---- common behaviour -----------------------------------------------
    def reset_pager(self):
        self.cur_line = 0
        self.aborted = False

    def _drain_hw_rx(self, intercept_ctrl_c=False):
        while True:
            raw = self._hw_read()
            if not raw:
                break
            self._filter_rx(raw, intercept_ctrl_c)

    def check_abort(self):
        self._drain_hw_rx(intercept_ctrl_c=True)
        if self.aborted:
            self.aborted = False
            return True
        return False

    def read_raw_byte(self, timeout_ms=1000):
        """Read a single raw 8-bit byte directly (used by XMODEM and the pager)."""
        t0 = net.ticks_ms()
        while True:
            if self.rx_queue:
                b = self.rx_queue[0]
                self.rx_queue = self.rx_queue[1:]
                return b
            c = self._hw_read(1)
            if c:
                return c[0]
            if net.ticks_diff(net.ticks_ms(), t0) > timeout_ms:
                return None
            net.sleep_ms(5)

    def flush_rx(self):
        """Discard any buffered or pending RX bytes."""
        self.rx_queue = bytearray()
        while self._hw_read():
            pass

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._hw_write(data)

    def write_paced_bytes(self, data, delay_us=250):
        """Write raw binary bytes with optional inter-byte microsecond pacing."""
        if not delay_us or delay_us <= 0:
            self._hw_write(data)
            return
        mv = memoryview(data)
        for i in range(len(mv)):
            self._hw_write(bytes(mv[i : i + 1]))
            net.sleep_us(delay_us)

    def write_line_paged(self, line_str):
        """Write a single line with CR+LF and optional screen pagination (AT+PAGE=<n>)."""
        self.write_paced(line_str + "\r\n")
        if self.page_lines > 0:
            self.cur_line += 1
            if self.cur_line >= self.page_lines:
                self.write(b"-- More (Space=page, Enter=1 line, q=quit) --")
                while True:
                    b = self.read_raw_byte(timeout_ms=60000)
                    if b is None or b in (ord("q"), ord("Q"), CTRL_C):
                        self.write(b"\r                                             \r")
                        return False
                    if b in (0x0D, 0x0A):
                        self.cur_line = self.page_lines - 1
                        break
                    if b == 0x20:
                        self.cur_line = 0
                        break
                self.write(b"\r                                             \r")
        return True

    def read_online(self):
        self._drain_hw_rx(intercept_ctrl_c=False)
        if not self.rx_queue:
            return None
        out = bytes(self.rx_queue)
        self.rx_queue = bytearray()
        return out

    read_command_bytes = read_online

    def read_hidden_line(self, prompt="Password: "):
        """Read a line without echoing characters (for interactive SSH password prompt)."""
        self.write(prompt)
        buf = bytearray()
        while True:
            b = self.read_raw_byte(timeout_ms=60000)
            if b is None or b == CTRL_C:
                self.write(b"\r\n")
                return None
            if b in (0x0D, 0x0A):
                self.write(b"\r\n")
                return buf.decode("utf-8", "replace")
            if b in (0x08, 0x7F):
                if len(buf) > 0:
                    buf = buf[:-1]
            elif 0x20 <= b <= 0x7E:
                buf.append(b)
