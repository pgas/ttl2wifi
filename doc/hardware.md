# Hardware Wiring: SC131 (5V TTL) to Raspberry Pi Pico W

## 1. Schematic (`UART0` + `VSYS` + Optional `RTS`/`CTS`)

```text
SC131 Serial Header (5V TTL)                                 Raspberry Pi Pico W
+-------------------------------+                            +-------------------------+
| Pin 3: 5v --------------------+------------------+---------+-- Pin 39: VSYS          |
|                               |               [470 µF]     |                         |
| Pin 1: 0v (GND) --------------+------+-----+-----+---------+-- Pin 38 / Pin 3: GND   |
|                               |      |     |               |                         |
|                               |      |  [ 2kΩ ]            |                         |
| Pin 5: Tx (SC131 5V TX out) --+-[ 1kΩ ]----+----------------->-- Pin 2: GP1 (UART0 RX) |
|                               |      |                     |                         |
| Pin 4: Rx (SC131 RX in)     <--------|-----------------------+-- Pin 1: GP0 (UART0 TX) |
|                               |   [ 2kΩ ]                  |                         |
| Pin 2: Rt (SC131 5V RTS out)--+-[ 1kΩ ]---------------------->-- Pin 4: GP2 (UART0 CTS)|
|                               |                            |                         |
| Pin 6: Ct (SC131 CTS in)    <------------------------------+-- Pin 5: GP3 (UART0 RTS)|
+-------------------------------+                            +-------------------------+
```

## 2. Pin Mapping

| Pico W Pin | Pico W Signal | Direction | SC131 Silkscreen (`0v Rt 5v Rx Tx Ct`) | USB-to-TTL Adapter | Level Shifting |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Pin 39** | `VSYS` | Power In | **Pin 3 (`5v`)** | `5V` / `VCC` | `470 µF` cap across `VSYS`–`GND` |
| **Pin 38 / 3** | `GND` | Ground | **Pin 1 (`0v`)** | `GND` | Common ground |
| **Pin 1** | `GP0` (`UART0 TX`) | 3.3V Out | **Pin 4 (`Rx` - SC131 RX in)** | `RX` / `RXD` (in) | Direct wire (3.3V > 2.0V TTL $V_{IH}$) |
| **Pin 2** | `GP1` (`UART0 RX`) | 3.3V In | **Pin 5 (`Tx` - SC131 5V TX out)** | `TX` / `TXD` (out) | `1 kΩ` series + `2 kΩ` to `GND` (~3.33V) |
| **Pin 4** | `GP2` (`UART0 CTS`) | 3.3V In | **Pin 2 (`Rt` - SC131 5V RTS out)** | `RTS` (out) | `1 kΩ` series + `2 kΩ` to `GND` (~3.33V) |
| **Pin 5** | `GP3` (`UART0 RTS`) | 3.3V Out | **Pin 6 (`Ct` - SC131 CTS in)** | `CTS` (in) | Direct wire (optional; used by `AT&K3`) |

## 3. SC131 Notes

1. **Port B Power Jumper (`JP2`):** SC131 Serial Port B does not power Pin 3 (`5v`) by default. Fit a jumper across **`JP2`** to power the Pico W from the SC131.
2. **Port B Flow Control (`ASCI1`):** The Z180 does not expose hardware RTS/CTS on `ASCI1` (Port B). Use default `AT&K0` with output pacing (`AT+DELAY=500,20`) on 3-wire Port B connections, or `AT&K3` on 6-wire ports with hardware handshaking.
