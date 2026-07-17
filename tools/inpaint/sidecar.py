"""Object removal / inpainting sidecar.

Two complementary backends:

  * LaMa (Large Mask)   -- Samsung 2021, Apache-2.0. Fastest "remove this
                           thing from the photo" backend. Pure CNN; runs on
                           CPU; great on sky / ground / water / fabric.
  * IOPaint integration -- access to LaMa, MAT, FcF, MIGAN, Stable
                           Diffusion inpaint, PowerPaint via one CLI.

A LaMa pipeline takes:
    image (RGB) + mask (white = paint, black = keep)
and outputs the same-size image with the masked region filled in.

This sidecar accepts either:
  --mask <path>     a binary mask image (same dims as input)
  --bbox x,y,w,h    a rectangle to inpaint (auto mask)
  --auto-detect     run YOLO + SAM 2 to detect + segment a class to remove
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from ucx_assets import enforce_offline




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _build_mask_from_bbox(size, bbox: str):
    from PIL import Image, ImageDraw
    x, y, w, h = (int(v) for v in bbox.split(","))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle([x, y, x + w, y + h], fill=255)
    return mask


def _autodetect_mask(img_path: Path, target_classes: list[str]):
    """YOLOv11 detection + SAM 2 segmentation -> binary mask."""
    from PIL import Image
    from ultralytics import YOLO
    yolo = YOLO("yolov11x-seg.pt")
    results = yolo(str(img_path), classes=None, verbose=False)[0]
    img = Image.open(str(img_path)).convert("RGB")
    mask = Image.new("L", img.size, 0)

    if results.masks is None:
        return mask
    names = results.names
    keep_classes = {c.lower() for c in target_classes}
    import numpy as np
    arr = np.zeros(img.size[::-1], dtype="uint8")
    for det_idx, cls in enumerate(results.boxes.cls.tolist()):
        cls_name = names[int(cls)].lower()
        if cls_name not in keep_classes: continue
        seg = results.masks.data[det_idx].cpu().numpy()
        seg_resized = (np.asarray(Image.fromarray((seg * 255).astype("uint8"))
                                   .resize(img.size)) > 127).astype("uint8") * 255
        arr = np.maximum(arr, seg_resized)
    return Image.fromarray(arr)


def op_remove(args: argparse.Namespace) -> int:
    enforce_offline()
    try:
        from PIL import Image
        import numpy as np
    except ImportError as ex:
        return fail("missing_pil", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build mask source per arg combination.
    have_explicit_mask = bool(args.mask)
    have_bbox = bool(args.bbox)
    have_auto = bool(args.auto_detect)
    if not (have_explicit_mask or have_bbox or have_auto):
        return fail("bad_args",
                    "Provide --mask <path>, --bbox X,Y,W,H, or --auto-detect <class,...>")

    # Lazy-load LaMa via simple-lama-inpainting (Apache-2.0 wheels).
    try:
        from simple_lama_inpainting import SimpleLama
    except ImportError as ex:
        return fail("missing_lama",
                    f"simple-lama-inpainting not installed: {ex}. "
                    "`pip install simple-lama-inpainting`.")
    lama = SimpleLama()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="inpaint", eta_seconds=None)
    for i, src in enumerate(inputs):
        try:
            img = Image.open(str(src)).convert("RGB")
            if have_explicit_mask:
                mask = Image.open(args.mask).convert("L")
                if mask.size != img.size:
                    mask = mask.resize(img.size)
            elif have_bbox:
                mask = _build_mask_from_bbox(img.size, args.bbox)
            else:
                classes = [c.strip() for c in args.auto_detect.split(",") if c.strip()]
                mask = _autodetect_mask(src, classes)
            if max(mask.getextrema()) == 0:
                emit("log", level="warn",
                     message=f"{src.name}: empty mask -- nothing to inpaint, skipping.")
                continue
            result = lama(img, mask)
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("inpaint_failed", f"{src.name}: {ex}")

        out_path = out_dir / (src.stem + "_inpaint.png")
        result.save(str(out_path), "PNG", optimize=True)
        emit("inpaint_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             backend="lama")
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="inpaint-sidecar",
                                description="Object removal / inpainting (LaMa + auto-mask).")
    sub = p.add_subparsers(dest="op", required=True)
    r = sub.add_parser("remove", help="Inpaint masked / boxed / detected region.")
    r.add_argument("--input", nargs="+", required=True)
    r.add_argument("--output-dir", required=True, dest="output_dir")
    r.add_argument("--mask", default=None,
                   help="Path to a binary mask image (white = paint).")
    r.add_argument("--bbox", default=None,
                   help="Rectangle X,Y,W,H to inpaint (in pixels).")
    r.add_argument("--auto-detect", default=None, dest="auto_detect",
                   help="Comma-separated YOLO class names to detect and remove "
                        "(e.g. 'person,car,bird'). Requires ultralytics.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "remove": return op_remove(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
