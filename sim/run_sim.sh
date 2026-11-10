#!/usr/bin/env bash
# run_sim.sh - Run RomWBW + ZNetSuite + TTL2WiFi bridge emulator in SimH AltairZ80
#
# Needs a RomWBW tree with romwbw-simh-acia.patch applied and SBC_simh_dual.rom built
# (see README.md in this directory). Master disk images are never modified: a working
# copy is kept in ttl2wifi/build/sim/.
#
# Environment overrides:
#   ROMWBW=/path/to/RomWBW        (default: ../../RomWBW)
#   ZNETSUITE=/path/to/znetsuite  (default: ../../znetsuite; optional, for ZTALK/ZGMI)
#   BRIDGE_PORT=9999

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TTL2WIFI_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROMWBW_DIR="${ROMWBW:-$TTL2WIFI_DIR/../RomWBW}"
ZNET_DIR="${ZNETSUITE:-$TTL2WIFI_DIR/../znetsuite}"
BRIDGE_PORT="${BRIDGE_PORT:-9999}"
BUILD_SIM_DIR="$TTL2WIFI_DIR/build/sim"

# 1. Locate altairz80
if command -v altairz80 &>/dev/null; then
  ALTAIRZ80_BIN="$(command -v altairz80)"
elif [ -x "$HOME/proj/simh-build/simh/BIN/altairz80" ]; then
  ALTAIRZ80_BIN="$HOME/proj/simh-build/simh/BIN/altairz80"
else
  echo "ERROR: altairz80 simulator binary not found."
  exit 1
fi

# 2. RomWBW ROM + stock disk images
ROM="$ROMWBW_DIR/Binary/SBC_simh_dual.rom"
if [ ! -f "$ROM" ]; then
  echo "ERROR: $ROM not found."
  echo "       Apply sim/romwbw-simh-acia.patch to RomWBW and build it:"
  echo "       cd \$ROMWBW/Source/HBIOS && make ROM_PLATFORM=SBC ROM_CONFIG=simh_dual"
  exit 1
fi
STOCK_HD512="$ROMWBW_DIR/Binary/hd512_combo.img"
STOCK_HD1K="$ROMWBW_DIR/Binary/hd1k_combo.img"
CPMCP="$ROMWBW_DIR/Tools/$(uname)/cpmcp"
CPMRM="$ROMWBW_DIR/Tools/$(uname)/cpmrm"

# 3. Working disk copies
mkdir -p "$BUILD_SIM_DIR"
WORKING_HD512="$BUILD_SIM_DIR/hd512.img"
WORKING_HD1K="$BUILD_SIM_DIR/hd1k.img"
[ -f "$WORKING_HD512" ] || cp "$STOCK_HD512" "$WORKING_HD512"
[ -f "$WORKING_HD1K" ]  || cp "$STOCK_HD1K" "$WORKING_HD1K"

# 4. Inject freshly compiled ZNetSuite binaries (if available)
if [ -x "$CPMCP" ]; then
  for app in ztalk zgmi ztelnet; do
    APP_UC="$(echo "$app" | tr a-z A-Z).COM"
    if [ -f "$ZNET_DIR/bin/$app.com" ]; then
      echo "Updating $APP_UC on working disk..."
      "$CPMRM" -f wbw_hd512 "$WORKING_HD512" "0:$APP_UC" 2>/dev/null || true
      "$CPMCP" -f wbw_hd512 "$WORKING_HD512" "$ZNET_DIR/bin/$app.com" "0:$APP_UC"
    fi
  done
fi

# 5. Start bridge emulator in background (client to SimH M2SIO0 listener)
lsof -ti:"$BRIDGE_PORT" | xargs kill -9 2>/dev/null || true
if [ ! -x "$BUILD_SIM_DIR/ttl2wifi_sim" ]; then
  echo "Building C++ desktop simulator (build/sim/ttl2wifi_sim)..."
  cmake -B "$BUILD_SIM_DIR" -S "$REPO_ROOT" && cmake --build "$BUILD_SIM_DIR" -j4
fi
echo "Starting TTL2WiFi C++ bridge emulator (client to SimH:$BRIDGE_PORT, log: build/sim/bridge.log)..."
"$BUILD_SIM_DIR/ttl2wifi_sim" --connect "127.0.0.1:$BRIDGE_PORT" > "$BUILD_SIM_DIR/bridge.log" 2>&1 &
BRIDGE_PID=$!

cleanup() {
  kill "$BRIDGE_PID" 2>/dev/null || true
  lsof -ti:"$BRIDGE_PORT" | xargs kill -9 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "============================================================"
echo "  RomWBW SimH + TTL2WiFi bridge emulator"
echo "------------------------------------------------------------"
echo "  Simulator : $ALTAIRZ80_BIN"
echo "  ROM       : $ROM"
echo "  Disk      : $WORKING_HD512"
echo "  Bridge    : 127.0.0.1:$BRIDGE_PORT -> HBIOS CIO unit 1 (ACIA)"
echo "------------------------------------------------------------"
echo "  Type '2' to boot the hard disk (CP/M A>), then e.g.:"
echo "    ZTALK 01          talk AT commands to the bridge"
echo "    ZGMI geminiprotocol.net"
echo "    ZTELNET <host> [port]"
echo "  To exit SimH: Ctrl+E, then 'quit'"
echo "============================================================"

if [ -t 0 ]; then
  SAVED_TTY=$(stty -g 2>/dev/null || true)
  trap 'cleanup; stty "$SAVED_TTY" 2>/dev/null || true' EXIT INT TERM
  stty cbreak -echo 2>/dev/null || true
fi

"$ALTAIRZ80_BIN" "$SCRIPT_DIR/simh.cfg" "$ROM" "$WORKING_HD512" "$WORKING_HD1K" "$BRIDGE_PORT"
