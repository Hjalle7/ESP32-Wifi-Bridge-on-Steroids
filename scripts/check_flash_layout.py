"""Check built ESP-IDF images, Kconfig and partition bounds before flashing.

Usage: python scripts/check_flash_layout.py wt32-eth01-4mb 4
The check does not identify physical flash; read the device flash ID separately.
"""
import argparse
import re
from pathlib import Path


def check(root, environment, flash_mb):
    """Reject mismatched headers/config, overlapping partitions or oversized apps.

    Inspect the generated binary table rather than assuming the source CSV
    was selected by the build. Application slots must be equally sized and
    aligned so either OTA destination can hold the same firmware.
    """
    build = root / ".pio" / "build" / environment
    capacity = flash_mb * 1024 * 1024
    sdkconfig = (root / ("sdkconfig." + environment)).read_text()
    if f'CONFIG_ESPTOOLPY_FLASHSIZE="{flash_mb}MB"' not in sdkconfig:
        raise ValueError("Kconfig flash size does not match the target")
    sizes = {0: 1, 1: 2, 2: 4, 3: 8, 4: 16, 5: 32, 6: 64, 7: 128}
    for name in ("bootloader.bin", "firmware.bin"):
        header = (build / name).read_bytes()[:4]
        if len(header) != 4 or header[0] != 0xE9:
            raise ValueError(f"Invalid ESP image: {name}")
        if sizes.get(header[3] >> 4) != flash_mb:
            raise ValueError(f"Wrong flash size in {name} header")
    data = (build / "partitions.bin").read_bytes()
    entries = []
    for offset in range(0, len(data), 32):
        entry = data[offset:offset + 32]
        if entry[:2] != b"\xaa\x50":
            break  # MD5 trailer or erased padding, not a partition entry.
        start = int.from_bytes(entry[4:8], "little")
        size = int.from_bytes(entry[8:12], "little")
        label = entry[12:28].split(b"\0", 1)[0].decode("ascii")
        if not size or start < 0x9000 or start + size > capacity:
            raise ValueError(f"Partition outside usable flash: {label}")
        if entry[2] == 0 and start % 0x10000:
            raise ValueError(f"Unaligned application partition: {label}")
        entries.append((start, size, entry[2], entry[3], label))
    if not entries:
        raise ValueError("No partition entries found")
    ordered = sorted(entries)
    for left, right in zip(ordered, ordered[1:]):
        if left[0] + left[1] > right[0]:
            raise ValueError(f"Overlapping partitions: {left[4]} / {right[4]}")
    slots = [e for e in entries if e[2] == 0 and e[3] in (0x10, 0x11)]
    if len(slots) != 2 or len({e[3] for e in slots}) != 2 or slots[0][1] != slots[1][1]:
        raise ValueError("Expected two equally sized OTA slots")
    image_size = (build / "firmware.bin").stat().st_size
    if image_size > min(e[1] for e in slots):
        raise ValueError("Firmware does not fit both OTA slots")
    print(f"{environment}: {flash_mb} MB headers/config verified; "
          f"{image_size} / {slots[0][1]} bytes per OTA slot "
          f"({100 * image_size / slots[0][1]:.1f}%); partition bounds OK")


def main():
    """Resolve build artifacts relative to this script and report check failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment")
    parser.add_argument("flash_mb", type=int, choices=(1, 2, 4, 8, 16, 32, 64, 128))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.environment):
        parser.error("Invalid environment name")
    try:
        check(Path(__file__).resolve().parents[1], args.environment, args.flash_mb)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Flash layout check failed: {exc}\n")


if __name__ == "__main__":
    main()
