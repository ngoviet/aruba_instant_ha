"""Sinh brand image cho integration — quy cách repo home-assistant/brands (custom_integrations/<domain>/).

- PNG lossless, viền sát, nền ngoài ô trong suốt; icon.png 256×256, icon@2x.png 512×512.
- Logo trùng icon ⇒ chỉ để icon (HA tự dùng icon thay logo).

Vẽ bằng stdlib (zlib + struct), siêu lấy mẫu SS×SS. Thiết kế gốc, KHÔNG dùng logo Aruba/HPE (logo hãng là
lý do bị đưa vào marketplace-icons-blocklist): ô bo góc gradient cam → tím + biểu tượng Wi-Fi trắng
(3 cung + chấm). Từ HA 2026.3 HA đọc thẳng thư mục brand/ của custom integration.

Dùng: python tools/make_brand.py   (restart HA mới thấy icon mới)
"""

from __future__ import annotations

import math
import pathlib
import struct
import sys
import zlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components"
    / "aruba_instant_ha"
    / "brand"
)
TOP = (255, 130, 40)  # #FF8228
BOTTOM = (110, 50, 170)  # #6E32AA

CX, CY = 0.5, 0.74  # tâm các cung Wi-Fi
ARCS = (0.17, 0.31, 0.45)  # bán kính giữa của 3 cung
ARC_HALF = 0.045  # nửa bề dày cung
SPREAD = math.radians(46)  # nửa góc mở quanh trục đứng


def inside_router(x: float, y: float) -> bool:
    """Biểu tượng Wi-Fi (giữ tên hàm của bản gốc để render() dùng chung)."""
    dx, dy = x - CX, CY - y
    d = math.hypot(dx, dy)
    if d <= 0.06:  # chấm
        return True
    if dy <= 0:
        return False
    if abs(math.atan2(dx, dy)) > SPREAD:
        return False
    return any(abs(d - r) <= ARC_HALF for r in ARCS)


SS = 4  # siêu lấy mẫu 4×4 điểm/pixel → viền mượt
TILE_RADIUS = 0.22  # bán kính bo góc ô nền, theo tỉ lệ cạnh


def inside_tile(x: float, y: float) -> bool:
    r = TILE_RADIUS
    cx = min(max(x, r), 1 - r)
    cy = min(max(y, r), 1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render(size: int) -> bytes:
    px = bytearray()
    n = SS * SS
    for y in range(size):
        px.append(0)  # filter type 0 mỗi scanline
        t = y / (size - 1)
        bg = [TOP[i] + (BOTTOM[i] - TOP[i]) * t for i in range(3)]
        for x in range(size):
            tile = white = 0
            for sy in range(SS):
                fy = (y + (sy + 0.5) / SS) / size
                for sx in range(SS):
                    fx = (x + (sx + 0.5) / SS) / size
                    if inside_tile(fx, fy):
                        tile += 1
                        if inside_router(fx, fy):
                            white += 1
            if tile == 0:
                px.extend((0, 0, 0, 0))
                continue
            w = white / tile  # tỉ lệ trắng trong phần thuộc ô
            rgb = (round(bg[i] + (255 - bg[i]) * w) for i in range(3))
            px.extend((*rgb, round(255 * tile / n)))
    return bytes(px)


def write_png(path: pathlib.Path, size: int) -> None:
    raw = render(size)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    print(f"  {path.name:14} {size}x{size}  {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Sinh brand image vào {OUT}:")
    for name, size in (
        ("icon.png", 256),
        ("icon@2x.png", 512),
    ):
        write_png(OUT / name, size)
    print("Lưu ý: HA chỉ hiển thị brand mới SAU KHI RESTART.")
