# main.py - TTL2WiFi Hayes AT + Extended AT+ Modem & Protocol Bridge for Pico W
#
# Pico W specific layer: UART0 transport (FlowUART) and Wi-Fi / LED hooks (PicoModem).
# The AT command processor lives in modem.py and the protocol clients in
# gopher.py, gemini.py, httpget.py, xmodem.py, ssh.py and ntp.py, which
# are shared with the host simulator (sim/sim_bridge.py).
import sys
import time
import machine
import network

import modem
from serialio import SerialIO, XON, XOFF, CTRL_C

CONFIG_FILE = "config.json"
UART_BAUD = 115200


class FlowUART(SerialIO):
    """
    UART0 wrapper supporting configurable flow control and optional screen pagination:
      - mode 0 (AT&K0): None (transparent 8-bit binary)
      - mode 3 (AT&K3): Hardware RTS/CTS on GP2 (CTS) and GP3 (RTS) [Default]
      - mode 4 (AT&K4): Software XON/XOFF (0x11 / 0x13)
    """

    def __init__(self, baud=UART_BAUD, flow_mode=3, page_lines=0):
        super().__init__(page_lines)
        self.baud = baud
        self.flow_mode = flow_mode
        self.paused = False
        self.uart = None
        self.configure(baud, flow_mode)

    def configure(self, baud=None, flow_mode=None):
        if baud is not None:
            self.baud = baud
        if flow_mode is not None:
            self.flow_mode = flow_mode
        self.paused = False
        extra = {}
        if self.flow_mode == 3:
            extra = dict(cts=machine.Pin(2), rts=machine.Pin(3), flow=machine.UART.RTS | machine.UART.CTS)
        self.uart = machine.UART(
            0,
            baudrate=self.baud,
            bits=8,
            parity=None,
            stop=1,
            tx=machine.Pin(0),
            rx=machine.Pin(1),
            txbuf=1024,
            rxbuf=2048,
            **extra,
        )

    def _hw_read(self, n=None):
        if not self.uart.any():
            return None
        return self.uart.read(n) if n else self.uart.read()

    def _hw_write(self, data):
        self.uart.write(data)

    def _filter_rx(self, raw, intercept_ctrl_c):
        if self.flow_mode != 4:
            return SerialIO._filter_rx(self, raw, intercept_ctrl_c)
        for b in raw:
            if b == XOFF:
                self.paused = True
            elif b == XON:
                self.paused = False
            elif intercept_ctrl_c and b == CTRL_C:
                self.aborted = True
            else:
                self.rx_queue.append(b)

    def write_paced(self, data):
        """Write data respecting XON/XOFF pause in AT&K4 mode."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        mv = memoryview(data)
        off = 0
        n = len(data)
        while off < n:
            if self.flow_mode == 4:
                self._drain_hw_rx(intercept_ctrl_c=True)
                wait_start = time.ticks_ms()
                while self.paused:
                    time.sleep_ms(5)
                    self._drain_hw_rx(intercept_ctrl_c=True)
                    if self.aborted or time.ticks_diff(time.ticks_ms(), wait_start) > 15000:
                        self.paused = False
                        break
            # Retro Pacing for vintage Z80/Z180 systems (SC131 / RomWBW / CP/M):
            # 1. Chunk size (1 byte):
            #    The Z180 ASCI1 hardware only has a 1-character receive data register
            #    plus shift register (~2 bytes total), and Port B lacks hardware RTS/CTS
            #    flow control. A burst from the RP2040's 32-byte hardware FIFO immediately
            #    overruns the Z180 while CP/M's HTALK is busy echoing to ASCI0.
            # 2. Inter-byte delay (250 us):
            #    At 115,200 baud, 1 byte takes ~86.8 us. A 250 us pause yields a ~337 us
            #    inter-character window (~3,000 cps), giving HTALK ample time to read
            #    Port B and output to Port A without dropping characters.
            # 3. Newline delay (10 ms on 0x0A / LF):
            #    Scrolling a terminal display buffer on CP/M or terminal emulators
            #    takes 5-10 ms. The 10 ms pause prevents the next line's leading
            #    characters (especially CR 0x0D) from being dropped, preventing staircasing.
            chunk = mv[off : off + 1]
            self.uart.write(chunk)
            off += 1
            if chunk[0] == 0x0A:
                time.sleep_ms(10)
            else:
                time.sleep_us(250)


class PicoModem(modem.AtModem):
    def __init__(self):
        self.led = machine.Pin("LED", machine.Pin.OUT)
        self.led.on()
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        super().__init__(FlowUART(UART_BAUD, 3, 0), config_file=CONFIG_FILE)
        self.load_config()
        self.set_flow(self.flow_mode)

    def set_flow(self, mode):
        self.flow_mode = mode
        self.io.configure(flow_mode=mode)

    def wifi_scan(self):
        out = []
        for ssid_b, _bssid, ch, rssi, sec, _hid in sorted(self.wlan.scan(), key=lambda x: x[3], reverse=True)[:15]:
            name = ssid_b.decode("utf-8", "replace") if ssid_b else "<hidden>"
            out.append((name, ch, rssi, sec))
        return out

    def wifi_join(self, ssid, password, timeout_s=15):
        self.ssid = ssid
        self.password = password
        self.io.write_paced(f"+WJOIN: Connecting to '{ssid}'...\r\n")
        self.wlan.disconnect()
        self.wlan.connect(ssid, password)
        t0 = time.ticks_ms()
        while not self.wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_s * 1000:
                self.reply("ERROR: Wi-Fi connection timed out")
                return False
            if self.io.check_abort():
                self.reply("ERROR: Aborted")
                return False
            self.led.toggle()
            time.sleep_ms(250)
        self.led.on()
        ip, mask, gw, dns = self.wlan.ifconfig()
        self.io.write_paced(f"+WJOIN: Connected! IP={ip} GW={gw} DNS={dns}\r\n")
        self.reply("OK")
        return True

    def wifi_leave(self):
        self.wlan.disconnect()

    def _mac(self):
        return ":".join(f"{b:02x}" for b in self.wlan.config("mac"))

    def wifi_status(self):
        mac = self._mac()
        if self.wlan.isconnected():
            ip, mask, gw, dns = self.wlan.ifconfig()
            self.io.write_paced(
                f"+WSTAT: CONNECTED\r\n"
                f"  SSID:    {self.wlan.config('ssid')}\r\n"
                f"  RSSI:    {self.wlan.status('rssi')} dBm\r\n"
                f"  IP:      {ip}\r\n"
                f"  Netmask: {mask}\r\n"
                f"  Gateway: {gw}\r\n"
                f"  DNS:     {dns}\r\n"
                f"  MAC:     {mac}\r\n"
            )
        else:
            self.io.write_paced(f"+WSTAT: DISCONNECTED (status={self.wlan.status()}, MAC={mac})\r\n")

    def info_lines(self):
        up = self.wlan.isconnected()
        ip = self.wlan.ifconfig()[0] if up else "0.0.0.0"
        ssid = self.wlan.config("ssid") if up else "none"
        cts_v = machine.Pin(2).value()
        rts_v = machine.Pin(3).value()
        return [
            f"TTL2WiFi v{modem.VERSION} ({sys.implementation._machine})",
            f"MAC:  {self._mac()}",
            f"WiFi: {'CONNECTED' if up else 'DISCONNECTED'} (SSID={ssid}, IP={ip})",
            f"UART: {self.io.baud} 8N1, Echo={'E1' if self.echo else 'E0'}, Flow={self.flow_desc()}, Page={self.io.page_lines}",
            f"PINS: GP2/CTS={cts_v} ({'CLEAR' if cts_v == 0 else 'PAUSED'}), GP3/RTS={rts_v} ({'READY' if rts_v == 0 else 'BUSY'})",
        ]

    def run(self):
        print(f"TTL2WiFi v{modem.VERSION} AT Modem started on UART0 ({self.io.baud} 8N1, Flow={self.flow_desc()})")
        if self.ssid and self.auto_join and not self.wlan.isconnected():
            try:
                self.wlan.connect(self.ssid, self.password)
            except Exception:
                pass
        super().run()


if __name__ == "__main__":
    PicoModem().run()
