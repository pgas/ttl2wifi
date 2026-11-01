#!/usr/bin/env python3
"""Build a MicroPython LittleFS v2 image from src/ and flash it to Pico W over SWD."""

import subprocess
from pathlib import Path
from littlefs import LittleFS

# RP2040 / RPI_PICO_W MicroPython flash filesystem layout (2MB flash):
# Storage starts at offset 0x12C000 (XIP 0x1012C000), length 848 KB (212 x 4KB blocks)
LFS_FLASH_ADDR = 0x1012C000
BLOCK_SIZE = 4096
BLOCK_COUNT = 212


def add_dir_to_lfs(fs: LittleFS, host_dir: Path, lfs_dir: str = "") -> list[str]:
    added = []
    for entry in sorted(host_dir.iterdir()):
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        target_path = f"{lfs_dir}/{entry.name}" if lfs_dir else entry.name
        if entry.is_dir():
            fs.mkdir(target_path)
            added.extend(add_dir_to_lfs(fs, entry, target_path))
        elif entry.is_file():
            data = entry.read_bytes()
            with fs.open(target_path, "wb") as f:
                f.write(data)
            added.append(f"{target_path} ({len(data)} B)")
    return added


def main():
    project_root = Path(__file__).resolve().parent.parent
    src_dir = project_root / "src"
    build_dir = project_root / "firmware"
    build_dir.mkdir(exist_ok=True)

    fs = LittleFS(
        block_size=BLOCK_SIZE,
        block_count=BLOCK_COUNT,
        prog_size=256,
        read_size=1,
        cache_size=4096,
        lookahead_size=32,
        disk_version=0x00020001,
    )

    added = add_dir_to_lfs(fs, src_dir)
    raw = bytes(fs.context.buffer)

    last_used_block = 2
    empty_block = b"\xff" * BLOCK_SIZE
    for blk in range(BLOCK_COUNT):
        if raw[blk * BLOCK_SIZE : (blk + 1) * BLOCK_SIZE] != empty_block:
            last_used_block = blk + 1

    trimmed = raw[: last_used_block * BLOCK_SIZE]
    bin_path = build_dir / "lfs_image.bin"
    bin_path.write_bytes(trimmed)

    print(
        f"Packed {len(added)} file(s) into LittleFS image "
        f"({len(trimmed)} bytes, {last_used_block} blocks): {', '.join(added)}"
    )
    cmd = [
        "openocd",
        "-f", "interface/cmsis-dap.cfg",
        "-f", "target/rp2040.cfg",
        "-c", "adapter speed 5000",
        "-c", f"program {bin_path} 0x{LFS_FLASH_ADDR:08x} verify reset exit",
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
