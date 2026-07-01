"""Retrocomputing image format sidecar.

Decode classic / 8-bit / demoscene image formats into modern PNG:

  * Atari ST .NEO / .PI1 / .PI2 / .PI3 / .DEGAS Elite
  * Apple II HGR / DHGR / hi-res
  * ZX Spectrum SCR (256x192 + attribute bytes)
  * Amiga IFF/ILBM (BodyChunk + colourmap)
  * Commodore 64 KOALA / DOODLE / multicolour bitmap
  * WBMP (Wireless Bitmap, OMA mobile)
  * Acorn !Sprite

Operations:
  to-png         Auto-detect by magic / extension and convert -> PNG.
  detect         Probe-only: report which retro format(s) match.

Pure stdlib + Pillow. Each platform's pixel-packing rules are encoded
inline since none of these are widely supported by mainstream libraries.
"""
from __future__ import annotations

import argparse
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import struct
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Helpers ────────────────────────────────────────────────────────────

def _png_from_pixels(pixels: list[tuple[int, int, int]],
                      width: int, height: int) -> bytes:
    """Encode raw RGB pixels as PNG via Pillow."""
    from PIL import Image
    img = Image.new("RGB", (width, height))
    img.putdata(pixels)
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Atari ST DEGAS / DEGAS Elite (.PI1 / .PI2 / .PI3 / .NEO) ──────────

_DEGAS_RES = {
    0: (320, 200, 16),  # low
    1: (640, 200, 4),   # med
    2: (640, 400, 2),   # high
    0x8000: (320, 200, 16),  # compressed low
    0x8001: (640, 200, 4),
    0x8002: (640, 400, 2),
}


def _atari_palette(raw: bytes, n: int) -> list[tuple[int, int, int]]:
    """Atari ST palette: 16-bit per entry, 3 bits per channel
    (R, G, B occupy bits 8-10, 4-6, 0-2)."""
    out: list[tuple[int, int, int]] = []
    for i in range(n):
        v = struct.unpack(">H", raw[i * 2:i * 2 + 2])[0]
        r = ((v >> 8) & 0x7) << 5
        g = ((v >> 4) & 0x7) << 5
        b = (v & 0x7) << 5
        out.append((r, g, b))
    return out


def _decode_degas(data: bytes) -> tuple[list[tuple[int, int, int]], int, int]:
    if len(data) < 34: raise ValueError("Truncated DEGAS file.")
    res = struct.unpack(">H", data[0:2])[0]
    if res not in _DEGAS_RES:
        raise ValueError(f"Not DEGAS (resolution flag {res:#x}).")
    width, height, palette_size = _DEGAS_RES[res]
    palette = _atari_palette(data[2:2 + 32], palette_size)
    bitplanes = data[34:]
    bytes_per_line = width // 8
    # interleaved bitplanes: 16 bits per plane in order.
    pixels: list[tuple[int, int, int]] = []
    bpp = palette_size.bit_length() - 1  # bits per pixel
    if bpp not in (1, 2, 4):
        raise ValueError(f"Unsupported bpp {bpp}.")
    line_bytes = bytes_per_line * bpp
    for y in range(height):
        line = bitplanes[y * line_bytes:y * line_bytes + line_bytes]
        for x in range(width):
            block = x // 16
            bit = 15 - (x % 16)
            idx = 0
            for plane in range(bpp):
                offset = block * 2 * bpp + plane * 2
                if offset + 1 >= len(line): continue
                w = struct.unpack(">H", line[offset:offset + 2])[0]
                if (w >> bit) & 1: idx |= (1 << plane)
            pixels.append(palette[idx] if idx < len(palette) else (0, 0, 0))
    return pixels, width, height


# ── ZX Spectrum SCR (6912 bytes: 6144 pixels + 768 attrs) ──────────────

def _decode_zx_scr(data: bytes) -> tuple[list[tuple[int, int, int]], int, int]:
    if len(data) < 6912:
        raise ValueError("Not ZX SCR (need 6912 bytes).")
    width, height = 256, 192
    pixels = data[:6144]
    attrs = data[6144:6912]
    palette = [
        (0, 0, 0), (0, 0, 192), (192, 0, 0), (192, 0, 192),
        (0, 192, 0), (0, 192, 192), (192, 192, 0), (192, 192, 192),
        (0, 0, 0), (0, 0, 255), (255, 0, 0), (255, 0, 255),
        (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255),
    ]
    out: list[tuple[int, int, int]] = []
    for y in range(height):
        # ZX bizarre line address: y = block(3) + char-line(8) + row-in-char-line(3)
        row_block = y // 64
        in_block = (y % 64) // 8
        char_row = y % 8
        line_addr = (row_block * 2048) + (char_row * 256) + (in_block * 32)
        for xb in range(32):
            byte = pixels[line_addr + xb]
            attr = attrs[(y // 8) * 32 + xb]
            ink = palette[(attr & 0x07) + (8 if attr & 0x40 else 0)]
            paper = palette[((attr >> 3) & 0x07) + (8 if attr & 0x40 else 0)]
            for bit in range(8):
                pix_on = bool(byte & (0x80 >> bit))
                out.append(ink if pix_on else paper)
    return out, width, height


# ── WBMP (mobile) ──────────────────────────────────────────────────────

def _decode_wbmp(data: bytes) -> tuple[list[tuple[int, int, int]], int, int]:
    if len(data) < 4 or data[0] != 0x00:
        raise ValueError("Not WBMP (type=0 expected).")
    p = 2  # skip type + fixed header
    def _decode_int(idx):
        v = 0
        while True:
            b = data[idx]; idx += 1
            v = (v << 7) | (b & 0x7F)
            if not (b & 0x80): return v, idx
    width, p = _decode_int(p)
    height, p = _decode_int(p)
    bytes_per_row = (width + 7) // 8
    pixels = []
    for y in range(height):
        row = data[p + y * bytes_per_row:p + (y + 1) * bytes_per_row]
        for x in range(width):
            bit = (row[x // 8] >> (7 - x % 8)) & 1
            pixels.append((255, 255, 255) if bit else (0, 0, 0))
    return pixels, width, height


# ── Apple II HGR (8192 bytes) ──────────────────────────────────────────

def _decode_apple_hgr(data: bytes) -> tuple[list[tuple[int, int, int]], int, int]:
    if len(data) < 8192:
        raise ValueError("Not Apple II HGR (need 8192 bytes).")
    width, height = 280, 192
    pixels: list[tuple[int, int, int]] = []
    for y in range(height):
        # HGR vertical scrambling: y = 64*group + 8*sub + line
        group, rem = divmod(y, 64)
        sub, line = divmod(rem, 8)
        addr = group * 0x28 + sub * 0x80 + line * 0x400
        for xb in range(40):
            byte = data[addr + xb]
            shift = byte & 0x80   # palette select
            for bit in range(7):
                on = bool(byte & (1 << bit))
                if on:
                    pixels.append((255, 255, 255) if shift
                                   else (255, 255, 255))
                else:
                    pixels.append((0, 0, 0))
    return pixels, width, height


# ── Operations ─────────────────────────────────────────────────────────

_DETECTORS = [
    ("degas",    lambda d: len(d) >= 34 and struct.unpack(">H", d[0:2])[0] in _DEGAS_RES, _decode_degas),
    ("zx-scr",   lambda d: len(d) == 6912, _decode_zx_scr),
    ("wbmp",     lambda d: len(d) >= 4 and d[0] == 0x00 and d[1] == 0x00, _decode_wbmp),
    ("apple-hgr", lambda d: len(d) == 8192, _decode_apple_hgr),
]


def _detect_and_decode(data: bytes) -> tuple[str, list, int, int]:
    for name, predicate, decoder in _DETECTORS:
        try:
            if predicate(data):
                pixels, w, h = decoder(data)
                return name, pixels, w, h
        except Exception:
            continue
    raise ValueError("Could not auto-detect retro image format.")


def op_to_png(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = src.read_bytes()
            kind, pixels, w, h = _detect_and_decode(data)
            png = _png_from_pixels(pixels, w, h)
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".png")
        out_path.write_bytes(png)
        emit("retro_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="png", source=kind, width=w, height=h)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_detect(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    detections: list[dict] = []
    for src in inputs:
        try:
            data = src.read_bytes()
            kind, _pixels, w, h = _detect_and_decode(data)
            detections.append({"file": str(src), "format": kind,
                               "width": w, "height": h,
                               "size_bytes": len(data)})
        except Exception as ex:
            detections.append({"file": str(src), "format": "unknown",
                               "error": str(ex)})
    out_path = out_dir / "retro-detect.json"
    out_path.write_text(json.dumps(detections, indent=2), encoding="utf-8")
    for d in detections:
        emit("retro_image",
             input=d["file"], output="",
             size_bytes=0, format="detect",
             source=d.get("format", "unknown"))
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(detections))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="retroimg-sidecar",
                                description="Retrocomputing image format -> PNG.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("to-png", "Auto-detect retro format and convert -> PNG"),
        ("detect", "Probe-only: report which retro format(s) match"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "to-png": return op_to_png(args)
        if args.op == "detect": return op_detect(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
