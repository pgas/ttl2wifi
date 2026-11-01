import sys
import time
import machine
import network

UART_BAUD = 115200


def handle_cmd(line, uart, wlan, led):
    cmd = line.strip()
    if not cmd:
        return

    print(f"[UART0 RX] {cmd!r}")

    if cmd == "help":
        uart.write(
            b"Commands:\r\n"
            b"  help   - Show this help\r\n"
            b"  status - Show Pico W & Wi-Fi status\r\n"
            b"  scan   - Scan nearby Wi-Fi networks\r\n"
            b"  led    - Toggle onboard LED\r\n"
        )
    elif cmd == "status":
        mac = ":".join(f"{b:02x}" for b in wlan.config("mac"))
        ip = wlan.ifconfig()[0] if wlan.isconnected() else "disconnected"
        uart.write(f"Board: {sys.implementation._machine}\r\n".encode())
        uart.write(f"MAC:   {mac}\r\n".encode())
        uart.write(f"Wi-Fi: {'connected' if wlan.isconnected() else 'disconnected'} ({ip})\r\n".encode())
    elif cmd == "scan":
        uart.write(b"Scanning Wi-Fi...\r\n")
        nets = wlan.scan()
        for ssid, _bssid, channel, rssi, _sec, _hidden in sorted(nets, key=lambda x: x[3], reverse=True)[:10]:
            name = ssid.decode("utf-8", "replace") if ssid else "<hidden>"
            uart.write(f"  ch{channel:<2d}  {rssi:>4d} dBm  {name}\r\n".encode())
    elif cmd == "led":
        led.toggle()
        uart.write(f"LED toggled (now {led.value()})\r\n".encode())
    else:
        uart.write(f"Unknown command: {cmd} (type 'help')\r\n".encode())


def main():
    led = machine.Pin("LED", machine.Pin.OUT)
    led.on()

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    # UART0: GP0 = TX (Pin 1 -> SC131 RX), GP1 = RX (Pin 2 <- SC131 TX via 1k/2k divider)
    uart = machine.UART(
        0,
        baudrate=UART_BAUD,
        bits=8,
        parity=None,
        stop=1,
        tx=machine.Pin(0),
        rx=machine.Pin(1),
        txbuf=1024,
        rxbuf=1024,
    )

    print(f"TTL2WiFi started on UART0 (GP0=TX, GP1=RX @ {UART_BAUD} baud)")
    uart.write(b"\r\n=== Pico W TTL2WiFi Bridge Ready (115200 8N1) ===\r\n")
    uart.write(b"Type 'help' and press Enter.\r\nttl2wifi> ")

    line_buf = bytearray()
    while True:
        if uart.any():
            data = uart.read()
            if not data:
                continue
            for b in data:
                if b in (0x0D, 0x0A):  # CR or LF
                    uart.write(b"\r\n")
                    line = line_buf.decode("utf-8", "replace")
                    line_buf = bytearray()
                    try:
                        handle_cmd(line, uart, wlan, led)
                    except Exception as e:
                        print(f"[UART0 ERR] {e!r}")
                        uart.write(f"Error: {e}\r\n".encode())
                    uart.write(b"ttl2wifi> ")
                elif b in (0x08, 0x7F):  # Backspace / DEL
                    if len(line_buf) > 0:
                        line_buf = line_buf[:-1]
                        uart.write(b"\x08 \x08")
                elif 0x20 <= b <= 0x7E:
                    line_buf.append(b)
                    uart.write(bytes([b]))  # Local echo
        time.sleep_ms(10)


if __name__ == "__main__":
    main()
