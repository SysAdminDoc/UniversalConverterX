"""Generate StreamKeep app icon.

Produces:
  assets/icon.png  — 1024x1024 master
  assets/icon.ico  — multi-resolution Windows icon (16..256)

Aesthetic: Catppuccin Mocha palette. Rounded dark-square tile with a
play triangle wrapped in a descending "signal" arc — reads as "press
play on a live stream and keep it". Subtle mauve→blue gradient and a
soft inner vignette for depth.
"""

from PIL import Image, ImageDraw, ImageFilter

# Catppuccin Mocha
BASE       = (17, 17, 27)     # crust
SURFACE    = (30, 30, 46)     # base
LAVENDER   = (180, 190, 254)
MAUVE      = (203, 166, 247)
BLUE       = (137, 180, 250)
GREEN      = (166, 227, 161)
TEXT       = (205, 214, 244)

SIZE = 1024


def rounded_rect_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def vertical_gradient(size, top, bottom):
    img = Image.new("RGB", (size, size), bottom)
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return img


def diagonal_gradient(size, c1, c2):
    img = Image.new("RGB", (size, size), c1)
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            px[x, y] = (r, g, b)
    return img


def build_icon():
    # Work on a supersampled canvas so every curve is crisp after resize.
    S = SIZE * 2
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Rounded-square tile with a deep vertical gradient.
    tile_bg = vertical_gradient(S, (24, 24, 37), (17, 17, 27))
    tile_rgba = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile_rgba.paste(tile_bg, (0, 0), rounded_rect_mask(S, radius=int(S * 0.22)))
    canvas = Image.alpha_composite(canvas, tile_rgba)

    # Thin stroke border (mauve → blue) to give the tile a premium edge.
    border = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border)
    bw = int(S * 0.012)
    bd.rounded_rectangle(
        (bw // 2, bw // 2, S - 1 - bw // 2, S - 1 - bw // 2),
        radius=int(S * 0.22) - bw // 2,
        outline=MAUVE + (180,),
        width=bw,
    )
    canvas = Image.alpha_composite(canvas, border)

    # Three descending signal arcs in the top-right, fading opacity.
    arcs = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ad = ImageDraw.Draw(arcs)
    cx, cy = int(S * 0.72), int(S * 0.70)
    for i, (radius, alpha) in enumerate([
        (int(S * 0.16), 235),
        (int(S * 0.24), 170),
        (int(S * 0.32), 105),
    ]):
        color = BLUE if i % 2 == 0 else MAUVE
        ad.arc(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            start=210, end=330,
            fill=color + (alpha,),
            width=int(S * 0.022),
        )
    arcs = arcs.filter(ImageFilter.GaussianBlur(radius=1.2))
    canvas = Image.alpha_composite(canvas, arcs)

    # Play triangle — lavender → blue diagonal fill, drop shadow underneath.
    tri_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # Centered-ish, slightly left so the signal arcs breathe on the right.
    tx = int(S * 0.30)
    ty_top = int(S * 0.32)
    ty_bot = int(S * 0.68)
    tx_right = int(S * 0.62)
    ty_mid = (ty_top + ty_bot) // 2
    triangle_pts = [(tx, ty_top), (tx_right, ty_mid), (tx, ty_bot)]

    tri_grad = diagonal_gradient(S, LAVENDER, BLUE).convert("RGBA")
    tri_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(tri_mask).polygon(triangle_pts, fill=255)

    # Soft drop shadow offset down-right.
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(
        [(p[0] + int(S * 0.015), p[1] + int(S * 0.018)) for p in triangle_pts],
        fill=(0, 0, 0, 170),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=int(S * 0.012)))
    canvas = Image.alpha_composite(canvas, shadow)

    tri_layer.paste(tri_grad, (0, 0), tri_mask)
    canvas = Image.alpha_composite(canvas, tri_layer)

    # Inner glow rim on the triangle for a subtle "lit" feel.
    rim = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(rim).polygon(triangle_pts, outline=(255, 255, 255, 90),
                                 width=int(S * 0.005))
    rim = rim.filter(ImageFilter.GaussianBlur(radius=1.0))
    canvas = Image.alpha_composite(canvas, rim)

    # A small green "recording" dot over the triangle base — the "keep" cue.
    dot = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dot)
    dot_r = int(S * 0.038)
    dot_cx, dot_cy = int(S * 0.36), int(S * 0.62)
    # Outer glow
    for grow, alpha in [(int(dot_r * 1.8), 60), (int(dot_r * 1.3), 110)]:
        dd.ellipse(
            (dot_cx - grow, dot_cy - grow, dot_cx + grow, dot_cy + grow),
            fill=GREEN + (alpha,),
        )
    dd.ellipse(
        (dot_cx - dot_r, dot_cy - dot_r, dot_cx + dot_r, dot_cy + dot_r),
        fill=GREEN + (255,),
    )
    dot = dot.filter(ImageFilter.GaussianBlur(radius=0.8))
    canvas = Image.alpha_composite(canvas, dot)

    # Downsample to the final 1024 with a high-quality filter.
    icon = canvas.resize((SIZE, SIZE), Image.LANCZOS)
    return icon


def main():
    icon = build_icon()
    icon.save("assets/icon.png", "PNG")
    # Multi-resolution .ico — Windows will pick the right size for taskbar,
    # Start Menu, file explorer, and high-DPI contexts.
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256)]
    icon.save("assets/icon.ico", format="ICO", sizes=sizes)
    print("Wrote assets/icon.png (1024x1024) and assets/icon.ico")


if __name__ == "__main__":
    main()
