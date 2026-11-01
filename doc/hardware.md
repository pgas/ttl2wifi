# Hardware Wiring: SC131 (5V TTL) to Raspberry Pi Pico W

## 1. Schematic (`UART0` + `VSYS` Power)
## 1. Schematic (`UART0` + `VSYS` Power + Optional `RTS`/`CTS` Flow Control)

```text
SC131 Header (5V TTL)                                         Raspberry Pi Pico W
+-----------------------+                                      +--------------------+
|                       |                                      |                    |
| Pin 3: 5V ------------+--------------------+-----------------+-- Pin 39: VSYS     |
|                       |                    |                 |                    |
|                       |                 +--+--+              |                    |
|                       |                 |  +  |              |                    |
|                       |              [ 470 µF ]              |                    |
|                       |                 |  -  |              |                    |
|                       |                 +--+--+              |                    |
|                       |                    |                 |                    |
| Pin 1: GND -----------+----------+---------+-----------------+-- Pin 38: GND      |
|                       |          |                           |                    |
|                       |        [ 2kΩ ]                       |                    |
|                       |          |                           |                    |
| Pin 5: RXD (SC131 TX) +-[ 1kΩ ]--+--------------------------->-- Pin 2:  GP1 (RX) |
|                       |                                      |                    |
| Pin 4: TXD (SC131 RX) <--------------------------------------+-- Pin 1:  GP0 (TX) |
|                       |                                      |                    |
+-----------------------+                                      +--------------------+
SC131 Header (5V TTL, FTDI Pinout)                           Raspberry Pi Pico W
+-------------------------------+                            +-------------------------+
|                               |                            |                         |
| Pin 3: 5V --------------------+------------------+---------+-- Pin 39: VSYS          |
|                               |                  |         |                         |
|                               |               +--+--+      |                         |
|                               |               |  +  |      |                         |
|                               |            [ 470 µF ]      |                         |
|                               |               |  -  |      |                         |
|                               |               +--+--+      |                         |
|                               |                  |         |                         |
| Pin 1: GND -------------------+------+-----+-----+---------+-- Pin 38 / Pin 3: GND   |
|                               |      |     |               |                         |
|                               |      |  [ 2kΩ ]            |                         |
|                               |      |     |               |                         |
| Pin 5: RXD (SC131 TX, 5V out) +-[ 1kΩ ]----+----------------->-- Pin 2: GP1 (UART0 RX) |
|                               |      |                     |                         |
| Pin 4: TXD (SC131 RX, in)     <------|-----------------------+-- Pin 1: GP0 (UART0 TX) |
|                               |      |                     |                         |
|                               |   [ 2kΩ ]                  |                         |
|                               |      |                     |                         |
| Pin 2: CTS (SC131 RTS, 5V out)+-[ 1kΩ ]---------------------->-- Pin 4: GP2 (UART0 CTS)|
|                               |                            |                         |
| Pin 6: RTS (SC131 CTS, in)    <------------------------------+-- Pin 5: GP3 (UART0 RTS)|
|                               |                            |                         |
+-------------------------------+                            +-------------------------+
```

## 2. Signal & Electrical Notes

- **Power (`VSYS`):** The SC131 (or USB-to-TTL 5V adapter during development) supplies `5V` to Pico W **Pin 39 (`VSYS`)**, buffered by a `470 µF` electrolytic capacitor to handle CYW43439 Wi-Fi transmit current spikes.
- **5V -> 3.3V Level Shifting (`SC131 TX` -> Pico `GP1 / UART0 RX`):**
  The `1 kΩ` / `2 kΩ` resistor voltage divider scales the 5V TTL output from the SC131 down to:
  $$V_{\text{GP1}} = 5.0\text{ V} \times \frac{2\text{ k}\Omega}{1\text{ k}\Omega + 2\text{ k}\Omega} \approx 3.33\text{ V}$$
  which is safe for the RP2040's 3.3V GPIO inputs.
- **3.3V -> 5V TTL (`Pico GP0 / UART0 TX` -> `SC131 RX`):**
  Connected directly. A 3.3V CMOS high (`~3.3V`) exceeds the `2.0V` $V_{IH}$ threshold of 5V TTL/HCT inputs (and 3.3V/5V USB-to-UART adapters).

## 3. Dual-Channel Development Setup on macOS

During development on macOS, two independent interfaces are connected to the target Pico W:

| Channel | Host Device | Pico W Pins | Purpose |
| :--- | :--- | :--- | :--- |
| **1. SWD Debug Probe** | `Debugprobe on Pico (CMSIS-DAP)` | 3-pin `DEBUG` (`SWCLK`, `GND`, `SWDIO`) | Flashing firmware, `make sync`, `make repl` (`SWDTerm` debug console) |
| **2. USB-to-TTL Adapter** | `/dev/tty.usbmodem08481` (`8086 Consultancy USB-C to UART Adaptor (5v)`) | `VSYS` (Pin 39), `GND` (Pin 38), `GP0` (Pin 1), `GP1` (Pin 2) | Emulates the SC131 5V TTL client (`minicom -D /dev/tty.usbmodem08481 -b 115200`) |

