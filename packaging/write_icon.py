"""Write packaging/sunder.ico and the UI favicon from the in-app mark."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

BG = (18, 21, 28, 255)
BRASS = (212, 160, 84, 255)
BRASS_EDGE = (212, 160, 84, 115)
ICE = (142, 180, 232, 255)
ICE_SOFT = (142, 180, 232, 140)
SIZES = (16, 32, 48, 256)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if value < lo else hi if value > hi else value


def _dist_seg(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    vx, vy = bx - ax, by - ay
    length2 = vx * vx + vy * vy
    if length2 <= 1e-9:
        dx, dy = px - ax, py - ay
        return (dx * dx + dy * dy) ** 0.5
    t = _clamp(((px - ax) * vx + (py - ay) * vy) / length2)
    dx, dy = px - (ax + t * vx), py - (ay + t * vy)
    return (dx * dx + dy * dy) ** 0.5


def _cubic(p0, p1, p2, p3, steps: int = 24) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        x = u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def _polyline_dist(px: float, py: float, pts: list[tuple[float, float]]) -> float:
    best = 1e9
    for i in range(len(pts) - 1):
        d = _dist_seg(px, py, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        if d < best:
            best = d
    return best


def _sd_round_rect(px: float, py: float, width: float, height: float, radius: float) -> float:
    qx = abs(px - width / 2) - (width / 2 - radius)
    qy = abs(py - height / 2) - (height / 2 - radius)
    outside = (max(qx, 0.0) ** 2 + max(qy, 0.0) ** 2) ** 0.5
    return outside + min(max(qx, qy), 0.0) - radius


def _cover(distance: float, pixel: float, width: float = 0.0) -> float:
    if width > 0:
        return _clamp(0.5 - (abs(distance) - width * 0.5) / pixel)
    return _clamp(0.5 - distance / pixel)


def _mix(dst: list[float], color: tuple[int, int, int, int], cover: float) -> None:
    if cover <= 0:
        return
    src_a = (color[3] / 255.0) * cover
    out_a = src_a + dst[3] * (1.0 - src_a)
    if out_a <= 1e-6:
        dst[0] = dst[1] = dst[2] = dst[3] = 0.0
        return
    for i in range(3):
        dst[i] = (color[i] / 255.0 * src_a + dst[i] * dst[3] * (1.0 - src_a)) / out_a
    dst[3] = out_a


WAVE_A = _cubic((14, 40), (20, 37), (24, 28), (24, 22)) + _cubic((24, 22), (24, 28), (28, 37), (34, 40))[1:]
WAVE_B = _cubic((30, 40), (36, 37), (40, 28), (40, 22)) + _cubic((40, 22), (40, 28), (44, 37), (50, 40))[1:]


def render_rgba(size: int) -> bytes:
    pixel = 64.0 / size
    rows: list[list[list[float]]] = []
    for y in range(size):
        row: list[list[float]] = []
        py = (y + 0.5) * pixel
        for x in range(size):
            px = (x + 0.5) * pixel
            pix = [0.0, 0.0, 0.0, 0.0]
            box = _sd_round_rect(px, py, 64.0, 64.0, 16.0)
            _mix(pix, BG, _cover(box, pixel))
            _mix(pix, BRASS_EDGE, _cover(_sd_round_rect(px, py, 62.5, 62.5, 15.25) + 0.1, pixel, 1.35))
            _mix(pix, ICE, _cover(_polyline_dist(px, py, WAVE_A) - 1.1, pixel))
            _mix(pix, ICE_SOFT, _cover(_polyline_dist(px, py, WAVE_B) - 1.1, pixel))
            _mix(pix, BRASS, _cover(_dist_seg(px, py, 32.0, 12.0, 32.0, 52.0) - 1.2, pixel))
            core = ((px - 32.0) ** 2 + (py - 32.0) ** 2) ** 0.5 - 3.2
            _mix(pix, BRASS, _cover(core, pixel))
            row.append(pix)
        rows.append(row)
    out = bytearray()
    for y in range(size):
        for x in range(size):
            r, g, b, a = rows[y][x]
            out.extend(
                (
                    int(_clamp(r) * 255 + 0.5),
                    int(_clamp(g) * 255 + 0.5),
                    int(_clamp(b) * 255 + 0.5),
                    int(_clamp(a) * 255 + 0.5),
                )
            )
    return bytes(out)


def _png(rgba: bytes, size: int) -> bytes:
    raw = bytearray()
    row = size * 4
    for y in range(size):
        raw.append(0)
        raw.extend(rgba[y * row : (y + 1) * row])

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


def _bmp_ico_image(rgba: bytes, size: int) -> bytes:
    xor = bytearray()
    for y in range(size - 1, -1, -1):
        row = y * size * 4
        for x in range(size):
            i = row + x * 4
            r, g, b, a = rgba[i : i + 4]
            xor.extend((b, g, r, a))
    and_stride = ((size + 31) // 32) * 4
    mask = bytearray(and_stride * size)
    for y in range(size):
        src_y = size - 1 - y
        for x in range(size):
            alpha = rgba[(src_y * size + x) * 4 + 3]
            if alpha < 128:
                byte_i = y * and_stride + (x >> 3)
                mask[byte_i] |= 0x80 >> (x & 7)
    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        size,
        size * 2,
        1,
        32,
        0,
        len(xor),
        0,
        0,
        0,
        0,
    )
    return header + xor + bytes(mask)


def build_ico_bytes(sizes: tuple[int, ...] = SIZES) -> bytes:
    images = []
    for size in sizes:
        rgba = render_rgba(size)
        blob = _png(rgba, size) if size >= 256 else _bmp_ico_image(rgba, size)
        images.append((size, blob))
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = bytearray()
    for size, blob in images:
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0,
            0,
            1,
            32,
            len(blob),
            offset,
        )
        offset += len(blob)
    return header + bytes(entries) + b"".join(blob for _, blob in images)


def write_icons(root: Path | None = None) -> tuple[Path, Path]:
    root = root or Path(__file__).resolve().parents[1]
    packaging = root / "packaging" / "sunder.ico"
    favicon = root / "sunder" / "desktop" / "static" / "favicon.ico"
    packaging.parent.mkdir(parents=True, exist_ok=True)
    favicon.parent.mkdir(parents=True, exist_ok=True)
    packaging.write_bytes(build_ico_bytes(SIZES))
    favicon.write_bytes(build_ico_bytes((16, 32, 48)))
    return packaging, favicon


if __name__ == "__main__":
    pkg, fav = write_icons()
    print(pkg)
    print(fav)
