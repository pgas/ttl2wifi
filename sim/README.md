# sim/ — TTL2WiFi bridge emulator + RomWBW SimH setup

| File | Purpose |
|---|---|
| `run_sim.sh` | Starts SimH AltairZ80 with RomWBW, with `ttl2wifi_sim` wired to HBIOS CIO unit 1 |
| `simh.cfg` | SimH config: console on SIO, bridge on M2SIO0 (6850 ACIA @ 0x10) |
| `romwbw-simh-acia.patch` | RomWBW changes needed for the ACIA bridge port under SimH |

## Bridge emulator only

```sh
make sim                         # type AT commands directly in stdio mode
./build/sim/ttl2wifi_sim --connect 127.0.0.1:8823  # connect to SimH listener
```

Everything works identically to the Pico W firmware (TCP/TLS dialing, Gopher, Gemini, HTTP, XMODEM, NTP). Wi-Fi scan and status are simulated on the host.

## RomWBW in SimH

1. Patch and build RomWBW (tested against RomWBW `73950cf8`):

   ```sh
   cd $ROMWBW
   git apply /path/to/ttl2wifi/sim/romwbw-simh-acia.patch
   cd Source/HBIOS && make ROM_PLATFORM=SBC ROM_CONFIG=simh_dual   # -> Binary/SBC_simh_dual.rom
   ```

   The patch adds the `SBC_simh_dual` config (ACIA on 0x10, 9600 baud, polled), an `ACIA_POLL` option
   (SimH's M2SIO raises no interrupts), skips ACIA hardware detection (fails on M2SIO), and moves ACIA
   after SSER in `hbios.asm` so the console stays unit 0 and the bridge is unit 1, as on the SC131.

2. Run (optionally build [znetsuite](../../znetsuite) first; its `ZTALK`/`ZGMI` get copied onto the disk):

   ```sh
   ./sim/run_sim.sh     # ROMWBW=..., ZNETSUITE=... to override ../RomWBW, ../znetsuite
   ```

   Press `2` to boot CP/M, then `ZTALK 01` or `ZGMI geminiprotocol.net`. Exit SimH with `Ctrl+E`, `quit`.
   The emulator log is in `build/sim/bridge.log`.
