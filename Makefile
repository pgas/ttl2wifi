# MicroPython on Raspberry Pi Pico W via 3-pin SWD Debug Probe (CMSIS-DAP)

VENV := .venv/bin
OPENOCD := openocd -f interface/cmsis-dap.cfg -f target/rp2040.cfg -c "adapter speed 5000"
FIRMWARE_UF2 := firmware/RPI_PICO_W-v1.24.1.uf2
FIRMWARE_BIN := firmware/RPI_PICO_W-v1.24.1.bin

.PHONY: help ttl repl run sync deploy reset flash probe image uf2

help:
	@echo "Standalone Drag-and-Drop UF2 Image (BOOTSEL mode - no SWD needed):"
	@echo "  make image    - Build turnkey firmware/ttl2wifi.uf2 (drag to RPI-RP2 drive)"
	@echo ""
	@echo "TTL Serial Client (SC131 / USB-to-TTL Adapter):"
	@echo "  make ttl      - Open serial terminal on /dev/cu.usbmodem08481 (115200 8N1)"
	@echo ""
	@echo "MicroPython SWD Commands (3-pin Debug Probe):"
	@echo "  make repl     - Open interactive MicroPython REPL over SWD (Ctrl-] to exit)"
	@echo "  make run      - Run src/main.py immediately on the target Pico W over SWD (<1s)"
	@echo "  make sync     - Upload src/main.py to :main.py on the Pico W over SWD (<1s)"
	@echo "  make deploy   - Full LittleFS rebuild & flash of src/*.py over SWD"
	@echo "  make reset    - Hard-reset the target Pico W over SWD"
	@echo "  make flash    - Re-flash MicroPython v1.24.1 (RPI_PICO_W) firmware over SWD"
	@echo "  make probe    - Test SWD connection to target Pico W"

ttl:
	$(VENV)/python3 -m serial.tools.miniterm /dev/cu.usbmodem08481 115200

repl:
	$(VENV)/python3 scripts/swd_repl.py

run:
	$(VENV)/python3 scripts/swd_repl.py --run src/main.py

sync:
	$(VENV)/python3 scripts/swd_repl.py --sync src

deploy deploy-swd:
	$(VENV)/python3 scripts/deploy_swd.py

image uf2:
	$(VENV)/python3 scripts/build_uf2.py

probe:
	$(OPENOCD) -c "init; targets; exit"

flash: $(FIRMWARE_BIN)
	$(OPENOCD) -c "program $(FIRMWARE_BIN) 0x10000000 verify reset exit"

reset:
	$(VENV)/python3 scripts/swd_repl.py --reset
