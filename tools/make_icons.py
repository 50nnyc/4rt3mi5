"""Gera os ícones do 4rt3mi5 (artemis/web/icon-*.png) sem bibliotecas externas.

Desenho: anel dourado com uma flecha na diagonal (Ártemis, a caçadora) sobre fundo escuro.
Uso: .venv\\Scripts\\python tools/make_icons.py
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "artemis" / "web"
SS = 3  # supersampling por eixo (bordas suaves)


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _in_tri(px, py, a, b, c):
    def s(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = s((px, py), a, b), s((px, py), b, c), s((px, py), c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def _mix(c1, c2, t):
    return tuple(c1[i] + (c2[i] - c1[i]) * t for i in range(3))


GOLD_TOP, GOLD_MID, GOLD_LOW = (255, 241, 193), (242, 201, 76), (184, 134, 27)
BG_IN, BG_OUT = (31, 37, 54), (11, 13, 18)


def _gold(y):
    return _mix(GOLD_TOP, GOLD_MID, y / 0.55) if y < 0.55 else _mix(GOLD_MID, GOLD_LOW, (y - 0.55) / 0.45)


def _mark(x, y, s):
    """True se (x, y) — em 0..1, centrado — cai no desenho dourado (escala s em torno do centro)."""
    x, y = 0.5 + (x - 0.5) / s, 0.5 + (y - 0.5) / s
    t = 0.05
    r = math.hypot(x - 0.5, y - 0.5)
    if abs(r - 0.33) < t / 2:
        return True
    # flecha: haste da cauda (embaixo à esquerda) até perto da ponta (em cima à direita)
    if _seg_dist(x, y, 0.22, 0.78, 0.68, 0.32) < t / 2:
        return True
    tip, w = (0.80, 0.20), 0.085
    base = (0.66, 0.34)
    nx, ny = 0.7071, 0.7071  # perpendicular à flecha
    if _in_tri(x, y, tip, (base[0] - nx * w, base[1] - ny * w), (base[0] + nx * w, base[1] + ny * w)):
        return True
    for k in (0.0, 0.06):  # penas da cauda
        ax, ay = 0.25 + k, 0.75 - k
        if _seg_dist(x, y, ax, ay, ax - 0.07, ay - 0.0) < t / 2.6 or _seg_dist(x, y, ax, ay, ax, ay + 0.07) < t / 2.6:
            return True
    return False


def render(size: int, maskable: bool) -> bytes:
    s = 0.72 if maskable else 0.86      # área segura do ícone "maskable" (Android corta em círculo)
    corner = 0.0 if maskable else 0.22
    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            cov_bg = cov_mark = 0
            col = [0.0, 0.0, 0.0]
            for sy in range(SS):
                for sx in range(SS):
                    x = (px + (sx + 0.5) / SS) / size
                    y = (py + (sy + 0.5) / SS) / size
                    if corner:  # cantos arredondados
                        cx, cy = min(max(x, corner), 1 - corner), min(max(y, corner), 1 - corner)
                        if math.hypot(x - cx, y - cy) > corner:
                            continue
                    cov_bg += 1
                    if _mark(x, y, s):
                        cov_mark += 1
                        c = _gold(y)
                    else:
                        c = _mix(BG_IN, BG_OUT, min(1.0, math.hypot(x - 0.5, y - 0.45) / 0.7))
                    col[0] += c[0]; col[1] += c[1]; col[2] += c[2]
            n = SS * SS
            if cov_bg:
                row += bytes([round(col[0] / cov_bg), round(col[1] / cov_bg), round(col[2] / cov_bg), round(255 * cov_bg / n)])
            else:
                row += b"\0\0\0\0"
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    for name, size, mask in (("icon-192.png", 192, False), ("icon-512.png", 512, False), ("icon-maskable.png", 512, True)):
        (WEB / name).write_bytes(render(size, mask))
        print("gerado", name)
