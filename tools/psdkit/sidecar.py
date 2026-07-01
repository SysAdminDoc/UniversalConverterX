"""Photoshop / GIMP layered-image sidecar.

Read PSD / PSB / XCF and:
  flatten      Composite all visible layers -> single PNG / JPEG / TIFF.
  extract      Save each visible layer as its own PNG.
  info         Probe document size, layer tree, blend modes.

Backed by `psd-tools` (MIT) for PSD / PSB and `gimpformats` (LGPL) for XCF.
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


def _open(path: Path):
    ext = path.suffix.lower()
    if ext in (".psd", ".psb"):
        from psd_tools import PSDImage
        return ("psd", PSDImage.open(str(path)))
    if ext == ".xcf":
        from gimpformats.gimpXcfDocument import GimpDocument
        return ("xcf", GimpDocument(str(path)))
    raise ValueError(f"Unsupported layered-image extension: {ext}")


def op_flatten(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"File(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ext = "." + args.format.lstrip(".").lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="flatten", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            kind, doc = _open(src)
            if kind == "psd":
                composite = doc.composite()
            else:
                composite = doc.image
            if composite is None:
                return fail("flatten_failed", f"{src.name}: no composite image.")
            if target_ext in (".jpg", ".jpeg") and composite.mode == "RGBA":
                composite = composite.convert("RGB")
            out_path = out_dir / (src.stem + target_ext)
            composite.save(str(out_path))
        except ImportError as ex:
            return fail("missing_dep", str(ex))
        except Exception as ex:
            return fail("flatten_failed", f"{src.name}: {ex}")

        emit("layered_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target_ext.lstrip("."), kind=kind)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(time.monotonic() - started) if i else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_extract(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"File(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total_layers = 0
    for src in inputs:
        try:
            kind, doc = _open(src)
        except ImportError as ex:
            return fail("missing_dep", str(ex))
        except Exception as ex:
            return fail("open_failed", f"{src.name}: {ex}")
        sub_dir = out_dir / src.stem
        sub_dir.mkdir(parents=True, exist_ok=True)

        if kind == "psd":
            for idx, layer in enumerate(_walk_psd(doc)):
                if not layer.is_visible(): continue
                img = layer.composite()
                if img is None: continue
                safe = "".join(c for c in (layer.name or f"layer_{idx}")
                               if c.isalnum() or c in (" ", "-", "_")).strip() or f"layer_{idx}"
                out_path = sub_dir / f"{idx:03d}__{safe}.png"
                img.save(str(out_path))
                emit("layered_image",
                     input=str(src), output=str(out_path),
                     size_bytes=out_path.stat().st_size,
                     layer_name=layer.name, layer_index=idx, kind="psd")
                total_layers += 1
        else:
            for idx, layer in enumerate(getattr(doc, "layers", [])):
                img = getattr(layer, "image", None)
                if img is None: continue
                safe = "".join(c for c in (getattr(layer, "name", f"layer_{idx}") or "")
                               if c.isalnum() or c in (" ", "-", "_")).strip() or f"layer_{idx}"
                out_path = sub_dir / f"{idx:03d}__{safe}.png"
                img.save(str(out_path))
                emit("layered_image",
                     input=str(src), output=str(out_path),
                     size_bytes=out_path.stat().st_size,
                     layer_name=getattr(layer, "name", None),
                     layer_index=idx, kind="xcf")
                total_layers += 1

    emit("complete", output=str(out_dir), size_bytes=0, count=total_layers)
    return 0


def _walk_psd(group):
    for item in group:
        if item.is_group():
            yield from _walk_psd(item)
        else:
            yield item


def op_info(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"File not found: {src}")
    try:
        kind, doc = _open(src)
    except ImportError as ex:
        return fail("missing_dep", str(ex))
    except Exception as ex:
        return fail("open_failed", f"{src.name}: {ex}")

    if kind == "psd":
        layer_names = [l.name for l in _walk_psd(doc)]
        emit("layered_info",
             path=str(src), kind="psd",
             width=int(doc.width), height=int(doc.height),
             layer_count=len(layer_names), layers=layer_names[:128])
    else:
        layers = [getattr(l, "name", "") for l in getattr(doc, "layers", [])]
        emit("layered_info",
             path=str(src), kind="xcf",
             width=int(getattr(doc, "width", 0)),
             height=int(getattr(doc, "height", 0)),
             layer_count=len(layers), layers=layers[:128])
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="psdkit-sidecar",
                                description="PSD/PSB/XCF read + flatten + per-layer extraction.")
    sub = p.add_subparsers(dest="op", required=True)
    f = sub.add_parser("flatten", help="Composite layers to a single image.")
    f.add_argument("--input", nargs="+", required=True)
    f.add_argument("--output-dir", required=True, dest="output_dir")
    f.add_argument("--format", default="png",
                   choices=["png", "jpg", "jpeg", "tif", "tiff", "webp", "bmp"])
    e = sub.add_parser("extract", help="Save every visible layer as its own PNG.")
    e.add_argument("--input", nargs="+", required=True)
    e.add_argument("--output-dir", required=True, dest="output_dir")
    i = sub.add_parser("info", help="Probe a layered image.")
    i.add_argument("--input", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "flatten": return op_flatten(args)
        if args.op == "extract": return op_extract(args)
        if args.op == "info":    return op_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
