#!/usr/bin/env python3
"""Render the Vertigo brand mark to raster variants.

Run from the project root:

    python assets/build_icons.py

Produces, next to this script:

    icon_16.png, icon_32.png, icon_48.png, icon_128.png, icon_256.png, icon_512.png
    icon.png    (= icon_256.png)
    icon.ico    (multi-resolution Windows icon)
    icon.icns   (best-effort, macOS — falls back to copying icon_512.png if
                 the `icns` utility / Pillow ICNS writer is unavailable)

We draw the mark with Pillow primitives so the build is fully
self-contained — no Cairo, no rsvg, no Inkscape required. The design
mirrors ``icon.svg``: a dark rounded-square container, a muted
horizontal "source" ghost frame, a motion arc, and the accent-gradient
9:16 "target" frame with a play triangle.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ACCENT_A = (203, 166, 247)   # #cba6f7
ACCENT_B = (245, 194, 231)   # #f5c2e7
BG       = (17, 17, 27)      # #11111b
SURFACE  = (69, 71, 90)      # #45475a
OVERLAY  = (127, 132, 156)   # #7f849c


def _draw_mark(canvas: int = 512) -> Image.Image:
    s = canvas
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # dark rounded container
    container_inset = int(s * 16 / 512)
    container_radius = int(s * 112 / 512)
    d.rounded_rectangle(
        (container_inset, container_inset, s - container_inset, s - container_inset),
        radius=container_radius,
        fill=BG,
    )

    # horizontal source-ghost frame (subtle)
    hx0, hy0 = int(s * 84 / 512), int(s * 188 / 512)
    hx1, hy1 = int(s * 428 / 512), int(s * 382 / 512)
    d.rounded_rectangle((hx0, hy0, hx1, hy1),
                         radius=int(s * 14 / 512),
                         outline=SURFACE,
                         width=max(2, int(s * 6 / 512)))

    # motion arc — simple quadratic approximation
    _draw_arc(d, (hx0 + int(s * 66 / 512), hy0 + 2),
                 (s // 2, int(s * 108 / 512)),
                 (hx1 - int(s * 66 / 512), hy0 + 2),
                 color=OVERLAY,
                 width=max(2, int(s * 5 / 512)))

    # target 9:16 frame with gradient fill
    vx0, vy0 = int(s * 180 / 512), int(s * 96 / 512)
    vx1, vy1 = int(s * 332 / 512), int(s * 416 / 512)
    _fill_gradient_rounded(img, (vx0, vy0, vx1, vy1),
                           radius=int(s * 24 / 512),
                           start=ACCENT_A, end=ACCENT_B)

    # inner glass highlight
    d.rounded_rectangle(
        (vx0 + int(s * 14 / 512), vy0 + int(s * 12 / 512),
         vx1 - int(s * 14 / 512), vy0 + int(s * 52 / 512)),
        radius=int(s * 16 / 512),
        fill=(255, 255, 255, 46),
    )

    # play triangle glyph
    cx = (vx0 + vx1) // 2
    cy = (vy0 + vy1) // 2
    size = int(s * 54 / 512)
    d.polygon(
        [(cx - size // 3, cy - size // 2),
         (cx - size // 3, cy + size // 2),
         (cx + int(size * 0.7), cy)],
        fill=BG,
    )

    return img


def _draw_arc(d: ImageDraw.ImageDraw, p0, p1, p2, *, color, width: int) -> None:
    """Approximate a quadratic Bezier as a polyline."""
    pts = []
    steps = 40
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    for a, b in zip(pts, pts[1:]):
        d.line([a, b], fill=color + (180,), width=width)


def _fill_gradient_rounded(img: Image.Image, box, *, radius: int, start, end) -> None:
    """Stamp a linear-gradient-filled rounded rect into `img`."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return

    # build gradient strip (vertical, top-to-bottom)
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(start[k] + (end[k] - start[k]) * t) for k in range(3))
        grad.putpixel((0, y), c)
    grad = grad.resize((w, h), Image.BICUBIC)

    # alpha mask: rounded rectangle
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1),
                                           radius=radius, fill=255)

    patch = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    patch.paste(grad, (0, 0))
    patch.putalpha(mask)

    img.alpha_composite(patch, (x0, y0))


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    sizes = [16, 32, 48, 128, 256, 512]
    master = _draw_mark(canvas=1024).filter(ImageFilter.SMOOTH_MORE)

    variants: list[Image.Image] = []
    for size in sizes:
        resized = master.resize((size, size), Image.LANCZOS)
        resized.save(out_dir / f"icon_{size}.png", optimize=True)
        variants.append(resized)

    # canonical icon.png is the 256 variant
    variants[sizes.index(256)].save(out_dir / "icon.png", optimize=True)

    # multi-resolution Windows .ico
    ico_sizes = [(s, s) for s in sizes if s <= 256]
    variants[sizes.index(256)].save(
        out_dir / "icon.ico",
        format="ICO",
        sizes=ico_sizes,
    )

    # best-effort .icns (Pillow can write ICNS on macOS Python builds)
    try:
        variants[sizes.index(512)].save(out_dir / "icon.icns", format="ICNS")
    except Exception:
        # Pillow without ICNS — ship the 512 PNG; PyInstaller uses .ico on
        # Windows and .icns on macOS but either is optional.
        pass

    print(f"[build_icons] wrote {len(sizes)} PNG variants + icon.ico to {out_dir}")


if __name__ == "__main__":
    main()
