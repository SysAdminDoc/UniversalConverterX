"""Webfont subsetter sidecar -- shrinks TTF/OTF/WOFF/WOFF2 fonts to only
the glyphs actually used by a given text or unicode range. Built on
fontTools.subset (BSD-3); supports WOFF2 output via the brotli backend.

Two strategies:
  * --text "string"          subset glyphs that cover the string's chars
  * --unicodes "U+0000-007F" subset glyphs covering a unicode range list
                             (comma-separated; supports ranges + singletons)
  * --layout-features '*'    pass through OpenType features (default: keep the
                             web-essential features: kern liga locl ccmp mark mkmk)

Output: same stem with `.subset.<ext>` suffix.
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
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _imports():
    try:
        from fontTools.subset import Subsetter, Options, load_font, save_font  # noqa: F401
        return True
    except ImportError as ex:
        emit("error", code="missing_fonttools",
             message=f"fontTools not installed: {ex}. `pip install fonttools brotli`.")
        return False


def _parse_unicodes(spec: str) -> list[int]:
    out: list[int] = []
    for chunk in spec.split(","):
        c = chunk.strip().lstrip("U+").lstrip("u+")
        if not c: continue
        if "-" in c:
            lo, hi = c.split("-", 1)
            out.extend(range(int(lo, 16), int(hi, 16) + 1))
        else:
            out.append(int(c, 16))
    return out


def op_subset(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    from fontTools.subset import Subsetter, Options, load_font, save_font

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"Font(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.text and not args.unicodes:
        return fail("bad_args", "Provide --text or --unicodes (or both).")

    flavor = args.flavor.lower() if args.flavor else None
    if flavor and flavor not in ("woff", "woff2", ""):
        return fail("bad_flavor", "--flavor must be one of: woff | woff2 | (omit for original).")

    options = Options()
    options.flavor = flavor or None
    options.with_zopfli = bool(args.zopfli)
    options.desubroutinize = bool(args.desubroutinize)
    options.layout_features = (
        ["*"] if args.layout_features == "*"
        else [x.strip() for x in args.layout_features.split(",") if x.strip()]
    )
    options.name_IDs = ["*"] if args.keep_names else [1, 2, 3, 4, 5, 6]
    options.notdef_outline = True
    options.recommended_glyphs = True

    unicodes: list[int] = list(_parse_unicodes(args.unicodes)) if args.unicodes else []
    if args.text:
        unicodes.extend(ord(c) for c in args.text)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="subset", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            font = load_font(str(src), options)
            ss = Subsetter(options=options)
            ss.populate(unicodes=sorted(set(unicodes)))
            ss.subset(font)
            out_ext = "." + (flavor or src.suffix.lstrip(".").lower() or "ttf")
            out_path = out_dir / (src.stem + ".subset" + out_ext)
            save_font(font, str(out_path), options)
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("subset_failed", f"{src.name}: {ex}")

        before = src.stat().st_size
        after = out_path.stat().st_size
        emit("font_subset",
             input=str(src), output=str(out_path),
             size_bytes=after,
             original_size=before,
             reduction=round(1 - (after / max(1, before)), 4),
             flavor=flavor or src.suffix.lstrip("."),
             glyph_count=len(set(unicodes)))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fontsubset-sidecar",
                                description="Subset TTF/OTF/WOFF/WOFF2 webfonts.")
    sub = p.add_subparsers(dest="op", required=True)
    s = sub.add_parser("subset", help="Subset font(s) to specified glyphs.")
    s.add_argument("--input", nargs="+", required=True)
    s.add_argument("--output-dir", required=True, dest="output_dir")
    s.add_argument("--text", default=None,
                   help="String of characters to keep (covers all unique codepoints).")
    s.add_argument("--unicodes", default=None,
                   help="Comma-separated codepoints/ranges, e.g. 'U+0000-007F,U+00A0-00FF,U+2014'.")
    s.add_argument("--flavor", default="woff2",
                   help="Output flavor: woff2 | woff | (empty to keep original sfnt).")
    s.add_argument("--layout-features", default="kern,liga,locl,ccmp,mark,mkmk",
                   dest="layout_features",
                   help="OpenType features to keep ('*' for all).")
    s.add_argument("--zopfli", action="store_true",
                   help="Use Zopfli compression for WOFF (smaller, slower).")
    s.add_argument("--desubroutinize", action="store_true",
                   help="Desubroutinize CFF (smaller WOFF2 in many cases).")
    s.add_argument("--keep-names", action="store_true", dest="keep_names",
                   help="Retain all name records (default keeps web-relevant subset).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "subset": return op_subset(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
