"""Write packaging/sunder.ico (dark slate + brass mark)."""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

SIZE = 32
BG = (12, 14, 19, 255)
BRASS = (212, 160, 84, 255)
ICE = (142, 180, 232, 255)
GOLD_CORE = (240, 200, 136, 255)


def _px(x: int, y: int) -> tuple[int, int, int, int]:
    cx, cy = 15.5, 15.5
    dx, dy = x - cx, y - cy
    r2 = dx * dx + dy * dy
    if r2 > 15.6 ** 2:
        return (0, 0, 0, 0)
    if r2 > 14.2 ** 2:
        return BRASS
    color = BG
    # split
    if abs(dx) <= 1.2 and abs(dy) < 12:
        color = BRASS if abs(dx) <= 0.6 else GOLD_CORE
    # waveform ticks
    left = 8 + int(2.4 * math.sin((y - 8) / 3.2))
    right = 23 + int(2.4 * math.sin((y - 8) / 3.2 + 0.8))
    if 8 <= y <= 23:
        if abs(x - left) <= 1:
            color = ICE
        if abs(x - right) <= 1:
            color = (*ICE[:3], 180)
    if (dx * dx + dy * dy) <= 2.4 ** 2:
        color = BRASS
    return color


def build_png(size: int = SIZE) -> bytes:
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            r, g, b, a = _px(x, y)
            raw.extend((r, g, b, a))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def build_ico(path: Path) -> Path:
    png = build_png()
    # PNG-in-ICO: ICONDIR + one entry pointing at the PNG blob
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII",
        SIZE,
        SIZE,
        0,
        0,
        1,
        32,
        len(png),
        6 + 16,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entry + png)
    return path


if __name__ == "__main__":
    dest = Path(__file__).resolve().parent / "sunder.ico"
    build_ico(dest)
    print(dest)
