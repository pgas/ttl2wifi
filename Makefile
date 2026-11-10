# TTL2WiFi - Raspberry Pi Pico W C++ AT Modem & Retro Protocol Bridge

OPENOCD := openocd -f interface/cmsis-dap.cfg -f target/rp2040.cfg -c "adapter speed 5000"
PICO_ELF := build/pico/ttl2wifi.elf
PICO_UF2 := build/pico/ttl2wifi.uf2
SIM_BIN  := build/sim/ttl2wifi_sim

.PHONY: help pico uf2 image firmware sim simh flash reset probe clean ttl

help:
	@echo "TTL2WiFi C++ Build & Flash Commands"
	@echo "==================================="
	@echo "Firmware (Raspberry Pi Pico W):"
	@echo "  make pico / make uf2 - Build turnkey build/pico/ttl2wifi.uf2"
	@echo "  make flash           - Flash build/pico/ttl2wifi.elf over SWD probe"
	@echo "  make reset           - Hardware reset target over SWD probe"
	@echo "  make probe           - Test CMSIS-DAP SWD connection to Pico W"
	@echo ""
	@echo "Host Simulator (macOS / Linux):"
	@echo "  make sim             - Build & run native AT bridge emulator (stdio)"
	@echo "  make simh            - Run RomWBW in SimH connected to C++ bridge"
	@echo ""
	@echo "Utilities:"
	@echo "  make ttl             - Open serial terminal on /dev/cu.usbmodem08481 (115200 8N1)"
	@echo "  make clean           - Remove build directories"

pico uf2 image firmware:
	@mkdir -p build/pico
	cmake -B build/pico -DPICO_BOARD=pico_w -S . && cmake --build build/pico
	@echo "\n==> Turnkey firmware ready: $(PICO_UF2)\n"

sim:
	@mkdir -p build/sim
	cmake -B build/sim -S . && cmake --build build/sim
	./$(SIM_BIN) --stdio

simh:
	./sim/run_sim.sh

$(PICO_ELF): pico

flash: $(PICO_ELF)
	$(OPENOCD) -c "program $(PICO_ELF) verify reset exit"

reset:
	$(OPENOCD) -c "init; reset run; exit"

probe:
	$(OPENOCD) -c "init; targets; exit"

ttl:
	python3 -m serial.tools.miniterm /dev/cu.usbmodem08481 115200

clean:
	rm -rf build/sim build/pico
