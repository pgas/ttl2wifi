#!/usr/bin/env python3
"""
Build a turnkey drag-and-drop UF2 firmware image for the Raspberry Pi Pico W.

Combines:
  1. Base MicroPython v1.24.1 firmware (flash offset 0x000000 / 0x10000000)
  2. LittleFS v2 filesystem image of src/ (flash offset 0x12C000 / 0x1012C000)

Produces:
  firmware/ttl2wifi.uf2 (complete turnkey image to drag-and-drop into RPI-RP2 drive)
"""

import argparse
import struct
from pathlib import Path
from littlefs import LittleFS

# RP2040 / Pico W Flash Memory Map (2MB total):
# Base MicroPython firmware: 0x10000000
# LittleFS filesystem:       0x1012C000 (length 848 KB = 212 x 4KB blocks)
LFS_FLASH_ADDR = 0x1012C000
BLOCK_SIZE = 4096
BLOCK_COUNT = 212
RP2040_FAMILY_ID = 0xE48BFF56
UF2_MAGIC_START0 = 0x0A324655
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30


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


def parse_uf2(uf2_path: Path) -> list[tuple[int, bytes]]:
    """Parse existing UF2 file into list of (target_addr, 256-byte payload)."""
    blocks = []
    with uf2_path.open("rb") as f:
        while True:
            chunk = f.read(512)
            if not chunk or len(chunk) < 512:
                break
            m1, m2, flags, addr, size, bno, nblocks, fid = struct.unpack(
                "<8I", chunk[:32]
            )
            if m1 == UF2_MAGIC_START0 and m2 == UF2_MAGIC_START1:
                blocks.append((addr, chunk[32 : 32 + size]))
    return blocks


def write_uf2(blocks: list[tuple[int, bytes]], out_path: Path):
    """Write blocks into a standard UF2 file."""
    total = len(blocks)
    with out_path.open("wb") as f:
        for idx, (addr, data) in enumerate(blocks):
            hdr = struct.pack(
                "<8I",
                UF2_MAGIC_START0,
                UF2_MAGIC_START1,
                0x00002000,  # flags: familyID present
                addr,
                len(data),
                idx,
                total,
                RP2040_FAMILY_ID,
            )
            pad = b"\x00" * (512 - 32 - len(data) - 4)
            ftr = struct.pack("<I", UF2_MAGIC_END)
            f.write(hdr + data + pad + ftr)


def main():
    project_root = Path(__file__).resolve().parent.parent
    src_dir = project_root / "src"
    build_dir = project_root / "firmware"
    base_uf2 = build_dir / "RPI_PICO_W-v1.24.1.uf2"
    output_uf2 = build_dir / "ttl2wifi.uf2"

    parser = argparse.ArgumentParser(description="Build turnkey ttl2wifi UF2 image")
    parser.add_argument(
        "--output", "-o", type=Path, default=output_uf2, help="Output UF2 path"
    )
    args = parser.parse_args()

    if not base_uf2.is_file():
        url = "https://micropython.org/resources/firmware/RPI_PICO_W-v1.24.1.uf2"
        print(f"Downloading base MicroPython firmware from {url}...")
        import urllib.request
        build_dir.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, base_uf2)
        print(f"Saved to {base_uf2}")

    print("1. Packing src/ into LittleFS image...")
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

    # Save standalone LFS image bin
    bin_path = build_dir / "lfs_image.bin"
    bin_path.write_bytes(raw)
    print(f"   Packed {len(added)} files into LittleFS ({len(raw)} bytes):")
    for f in added:
        print(f"     - {f}")

    print(f"\n2. Reading base MicroPython firmware from {base_uf2.name}...")
    combined_blocks = parse_uf2(base_uf2)
    print(f"   Firmware: {len(combined_blocks)} blocks ({len(combined_blocks) * 256} bytes)")

    print(f"\n3. Appending LittleFS filesystem at 0x{LFS_FLASH_ADDR:08X}...")
    lfs_blocks = 0
    for off in range(0, len(raw), 256):
        combined_blocks.append((LFS_FLASH_ADDR + off, raw[off : off + 256]))
        lfs_blocks += 1
    print(f"   Filesystem: {lfs_blocks} blocks ({lfs_blocks * 256} bytes)")

    print(f"\n4. Generating turnkey UF2: {args.output}...")
    write_uf2(combined_blocks, args.output)
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(
        f"   Done! {args.output.name} ({size_mb:.2f} MB, {len(combined_blocks)} UF2 blocks)\n"
        f"   Ready to drag-and-drop into RPI-RP2 in BOOTSEL mode."
    )


if __name__ == "__main__":
    main()
