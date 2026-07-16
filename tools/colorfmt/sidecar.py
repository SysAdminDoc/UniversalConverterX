"""Color-format converter sidecar.

Convert between every common color representation: hex (#RRGGBB[AA]),
RGB (sRGB 8-bit and float), HSL, HSV, CMYK, CIE Lab (D65), and CSS named
colors. Reads a list of colors from a .txt / .json / .csv file and emits
a CSV table with every form, plus a JSON sidecar that can be re-imported.

Operations:
  expand       Color list -> CSV with hex/rgb/hsl/hsv/cmyk/lab/name columns.
  to-json      Color list -> JSON array of fully-expanded objects.
  to-css       Color list -> CSS custom-property block (--color-<n>).

Pure stdlib — color math (sRGB <-> linear, XYZ <-> Lab) implemented inline.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── CSS named colors (CSS Color Module Level 4 baseline) ───────────────

CSS_NAMED = {
    "aliceblue":(240,248,255),"antiquewhite":(250,235,215),"aqua":(0,255,255),
    "aquamarine":(127,255,212),"azure":(240,255,255),"beige":(245,245,220),
    "bisque":(255,228,196),"black":(0,0,0),"blanchedalmond":(255,235,205),
    "blue":(0,0,255),"blueviolet":(138,43,226),"brown":(165,42,42),
    "burlywood":(222,184,135),"cadetblue":(95,158,160),"chartreuse":(127,255,0),
    "chocolate":(210,105,30),"coral":(255,127,80),"cornflowerblue":(100,149,237),
    "cornsilk":(255,248,220),"crimson":(220,20,60),"cyan":(0,255,255),
    "darkblue":(0,0,139),"darkcyan":(0,139,139),"darkgoldenrod":(184,134,11),
    "darkgray":(169,169,169),"darkgreen":(0,100,0),"darkkhaki":(189,183,107),
    "darkmagenta":(139,0,139),"darkolivegreen":(85,107,47),"darkorange":(255,140,0),
    "darkorchid":(153,50,204),"darkred":(139,0,0),"darksalmon":(233,150,122),
    "darkseagreen":(143,188,143),"darkslateblue":(72,61,139),
    "darkslategray":(47,79,79),"darkturquoise":(0,206,209),"darkviolet":(148,0,211),
    "deeppink":(255,20,147),"deepskyblue":(0,191,255),"dimgray":(105,105,105),
    "dodgerblue":(30,144,255),"firebrick":(178,34,34),"floralwhite":(255,250,240),
    "forestgreen":(34,139,34),"fuchsia":(255,0,255),"gainsboro":(220,220,220),
    "ghostwhite":(248,248,255),"gold":(255,215,0),"goldenrod":(218,165,32),
    "gray":(128,128,128),"green":(0,128,0),"greenyellow":(173,255,47),
    "honeydew":(240,255,240),"hotpink":(255,105,180),"indianred":(205,92,92),
    "indigo":(75,0,130),"ivory":(255,255,240),"khaki":(240,230,140),
    "lavender":(230,230,250),"lavenderblush":(255,240,245),"lawngreen":(124,252,0),
    "lemonchiffon":(255,250,205),"lightblue":(173,216,230),"lightcoral":(240,128,128),
    "lightcyan":(224,255,255),"lightgoldenrodyellow":(250,250,210),
    "lightgray":(211,211,211),"lightgreen":(144,238,144),"lightpink":(255,182,193),
    "lightsalmon":(255,160,122),"lightseagreen":(32,178,170),
    "lightskyblue":(135,206,250),"lightslategray":(119,136,153),
    "lightsteelblue":(176,196,222),"lightyellow":(255,255,224),"lime":(0,255,0),
    "limegreen":(50,205,50),"linen":(250,240,230),"magenta":(255,0,255),
    "maroon":(128,0,0),"mediumaquamarine":(102,205,170),"mediumblue":(0,0,205),
    "mediumorchid":(186,85,211),"mediumpurple":(147,112,219),
    "mediumseagreen":(60,179,113),"mediumslateblue":(123,104,238),
    "mediumspringgreen":(0,250,154),"mediumturquoise":(72,209,204),
    "mediumvioletred":(199,21,133),"midnightblue":(25,25,112),
    "mintcream":(245,255,250),"mistyrose":(255,228,225),"moccasin":(255,228,181),
    "navajowhite":(255,222,173),"navy":(0,0,128),"oldlace":(253,245,230),
    "olive":(128,128,0),"olivedrab":(107,142,35),"orange":(255,165,0),
    "orangered":(255,69,0),"orchid":(218,112,214),"palegoldenrod":(238,232,170),
    "palegreen":(152,251,152),"paleturquoise":(175,238,238),
    "palevioletred":(219,112,147),"papayawhip":(255,239,213),"peachpuff":(255,218,185),
    "peru":(205,133,63),"pink":(255,192,203),"plum":(221,160,221),
    "powderblue":(176,224,230),"purple":(128,0,128),"rebeccapurple":(102,51,153),
    "red":(255,0,0),"rosybrown":(188,143,143),"royalblue":(65,105,225),
    "saddlebrown":(139,69,19),"salmon":(250,128,114),"sandybrown":(244,164,96),
    "seagreen":(46,139,87),"seashell":(255,245,238),"sienna":(160,82,45),
    "silver":(192,192,192),"skyblue":(135,206,235),"slateblue":(106,90,205),
    "slategray":(112,128,144),"snow":(255,250,250),"springgreen":(0,255,127),
    "steelblue":(70,130,180),"tan":(210,180,140),"teal":(0,128,128),
    "thistle":(216,191,216),"tomato":(255,99,71),"turquoise":(64,224,208),
    "violet":(238,130,238),"wheat":(245,222,179),"white":(255,255,255),
    "whitesmoke":(245,245,245),"yellow":(255,255,0),"yellowgreen":(154,205,50),
}
_REVERSE_NAMED = {v: k for k, v in CSS_NAMED.items()}


# ── Parsing ────────────────────────────────────────────────────────────

_HEX_RE = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$",
                     re.IGNORECASE)
_RGB_RE = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)"
                     r"\s*(?:,\s*([\d.]+)\s*)?\)", re.IGNORECASE)


def _parse(spec: str) -> tuple[int, int, int, float]:
    s = spec.strip().lower()
    if not s: raise ValueError("Empty color.")
    if s in CSS_NAMED:
        r, g, b = CSS_NAMED[s]; return r, g, b, 1.0
    m = _HEX_RE.match(s)
    if m:
        h = m.group(1)
        if len(h) == 3: h = "".join(c * 2 for c in h)
        if len(h) == 4: h = "".join(c * 2 for c in h)
        r = int(h[0:2], 16); g = int(h[2:4], 16); b = int(h[4:6], 16)
        a = int(h[6:8], 16) / 255.0 if len(h) == 8 else 1.0
        return r, g, b, a
    m = _RGB_RE.match(s)
    if m:
        r = int(round(float(m.group(1))))
        g = int(round(float(m.group(2))))
        b = int(round(float(m.group(3))))
        a = float(m.group(4)) if m.group(4) else 1.0
        return r, g, b, a
    raise ValueError(f"Unrecognized color: {spec}")


# ── Conversions ────────────────────────────────────────────────────────

def _to_hex(r: int, g: int, b: int, a: float) -> str:
    if a >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"#{r:02x}{g:02x}{b:02x}{int(round(a*255)):02x}"


def _to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    rn, gn, bn = r / 255, g / 255, b / 255
    mx = max(rn, gn, bn); mn = min(rn, gn, bn); d = mx - mn
    L = (mx + mn) / 2
    if d == 0: return 0.0, 0.0, L * 100
    S = d / (1 - abs(2 * L - 1)) if L not in (0, 1) else 0
    if mx == rn:   H = ((gn - bn) / d) % 6
    elif mx == gn: H = ((bn - rn) / d) + 2
    else:          H = ((rn - gn) / d) + 4
    return H * 60, S * 100, L * 100


def _to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    rn, gn, bn = r / 255, g / 255, b / 255
    mx = max(rn, gn, bn); mn = min(rn, gn, bn); d = mx - mn
    if d == 0: H = 0
    elif mx == rn: H = ((gn - bn) / d) % 6
    elif mx == gn: H = ((bn - rn) / d) + 2
    else:          H = ((rn - gn) / d) + 4
    S = 0 if mx == 0 else d / mx
    return H * 60, S * 100, mx * 100


def _to_cmyk(r: int, g: int, b: int) -> tuple[float, float, float, float]:
    rn, gn, bn = r / 255, g / 255, b / 255
    K = 1 - max(rn, gn, bn)
    if K == 1: return 0, 0, 0, 100
    C = (1 - rn - K) / (1 - K)
    M = (1 - gn - K) / (1 - K)
    Y = (1 - bn - K) / (1 - K)
    return C * 100, M * 100, Y * 100, K * 100


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    R = _srgb_to_linear(r / 255)
    G = _srgb_to_linear(g / 255)
    B = _srgb_to_linear(b / 255)
    # sRGB -> XYZ (D65)
    X = R * 0.4124564 + G * 0.3575761 + B * 0.1804375
    Y = R * 0.2126729 + G * 0.7151522 + B * 0.0721750
    Z = R * 0.0193339 + G * 0.1191920 + B * 0.9503041
    Xn, Yn, Zn = 0.95047, 1.00000, 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(X / Xn), f(Y / Yn), f(Z / Zn)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    bb = 200 * (fy - fz)
    return L, a, bb


def _expand(spec: str) -> dict:
    r, g, b, a = _parse(spec)
    H, S, L = _to_hsl(r, g, b)
    Hv, Sv, V = _to_hsv(r, g, b)
    C, M, Y, K = _to_cmyk(r, g, b)
    Lab = _to_lab(r, g, b)
    return {
        "input":  spec.strip(),
        "hex":    _to_hex(r, g, b, a),
        "rgb":    f"rgb({r}, {g}, {b})",
        "rgba":   f"rgba({r}, {g}, {b}, {a:.3f})",
        "rgb_arr": [r, g, b],
        "alpha":  round(a, 3),
        "hsl":    f"hsl({H:.1f}, {S:.1f}%, {L:.1f}%)",
        "hsv":    f"hsv({Hv:.1f}, {Sv:.1f}%, {V:.1f}%)",
        "cmyk":   f"cmyk({C:.1f}%, {M:.1f}%, {Y:.1f}%, {K:.1f}%)",
        "lab":    f"lab({Lab[0]:.2f}, {Lab[1]:.2f}, {Lab[2]:.2f})",
        "name":   _REVERSE_NAMED.get((r, g, b), ""),
    }


def _read_colors(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x) for x in data]
        if isinstance(data, dict):
            return [str(v) for v in data.values()]
        raise ValueError("JSON must be array or object of color strings.")
    # treat as line-delimited; ignore comments/blank
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def op_expand(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Color list(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            colors = _read_colors(src)
            rows = [_expand(c) for c in colors]
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            keys = ["input", "hex", "rgb", "rgba", "alpha",
                    "hsl", "hsv", "cmyk", "lab", "name"]
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("color_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", count=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Color list(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            colors = _read_colors(src)
            rows = [_expand(c) for c in colors]
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("color_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", count=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_css(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Color list(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            colors = _read_colors(src)
            rows = [_expand(c) for c in colors]
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".css")
        lines = [":root {"]
        for n, r in enumerate(rows, 1):
            label = r["name"] or f"color-{n}"
            lines.append(f"  --{label}: {r['hex']};")
        lines.append("}\n")
        out_path.write_text("\n".join(lines), encoding="utf-8")
        emit("color_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="css", count=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="colorfmt-sidecar",
                                description="Color format conversion (hex/RGB/HSL/HSV/CMYK/Lab/CSS named).")
    sub = p.add_subparsers(dest="op", required=True)

    e = sub.add_parser("expand", help="Color list -> CSV with every form.")
    e.add_argument("--input", nargs="+", required=True)
    e.add_argument("--output-dir", required=True, dest="output_dir")

    j = sub.add_parser("to-json", help="Color list -> JSON array.")
    j.add_argument("--input", nargs="+", required=True)
    j.add_argument("--output-dir", required=True, dest="output_dir")

    c = sub.add_parser("to-css", help="Color list -> CSS variables block.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "expand":  return op_expand(args)
        if args.op == "to-json": return op_to_json(args)
        if args.op == "to-css":  return op_to_css(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
