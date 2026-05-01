"""Modern image background-removal sidecar.

Routes to the best-of-2025 segmentation models, all OSS, all production-grade:

  * BiRefNet           (CVPR 2024 -- most accurate dichotomous segmentation)
  * RMBG-2.0           (BRIA AI 2024 -- Apache-2.0, trained on 12k images, SOTA)
  * RMBG-1.4           (BRIA AI -- earlier, lighter, BSD-3)
  * IS-Net             (DIS-1.0 / 5K -- best on hair / fur details)
  * U2Net (rembg)      (legacy, fastest, smallest model)
  * SAM 2              (Meta 2024 -- promptable, but auto-mode used here)

Default backend = "birefnet" because it has the cleanest hair edges and
generalizes well to product / portrait / e-commerce shots.

Output: per input image, an `<stem>_nobg.png` with alpha channel.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# Hugging Face model ids per backend.
HF_MODELS = {
    "birefnet":  "ZhengPeng7/BiRefNet",                 # general-purpose SOTA
    "birefnet-portrait": "ZhengPeng7/BiRefNet_HR-portrait",
    "birefnet-matting":  "ZhengPeng7/BiRefNet-matting",
    "rmbg2":     "briaai/RMBG-2.0",
    "rmbg14":    "briaai/RMBG-1.4",
    "isnet":     "briaai/RMBG-1.4",  # close enough; rembg also has u2net_human_seg
}


def _segment_birefnet(images, model_id: str, device: str):
    """Yield (path, RGBA Pillow Image) for each input."""
    import torch
    from PIL import Image
    from torchvision import transforms
    from transformers import AutoModelForImageSegmentation

    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    model = AutoModelForImageSegmentation.from_pretrained(
        model_id, trust_remote_code=True, torch_dtype=dtype)
    model.to(device).eval()

    tfm = transforms.Compose([
        transforms.Resize((1024, 1024)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    for path in images:
        img = Image.open(str(path)).convert("RGB")
        x = tfm(img).unsqueeze(0).to(device, dtype=dtype)
        with torch.inference_mode():
            preds = model(x)[-1].sigmoid().cpu()
        mask = preds[0].squeeze().float().numpy()
        mask_img = Image.fromarray((mask * 255).astype("uint8")).resize(img.size)
        rgba = img.convert("RGBA")
        rgba.putalpha(mask_img)
        yield path, rgba


def _segment_rmbg(images, model_id: str, device: str):
    """RMBG-2.0 / 1.4 via transformers + custom code."""
    # The two BRIA models share the same calling convention as BiRefNet;
    # delegate to the same helper.
    yield from _segment_birefnet(images, model_id, device)


def _segment_rembg(images, model_name: str):
    """Legacy U2Net path via the `rembg` package."""
    from rembg import new_session, remove
    from PIL import Image
    sess = new_session(model_name)
    for path in images:
        with open(path, "rb") as f:
            data = remove(f.read(), session=sess, alpha_matting=True,
                          alpha_matting_foreground_threshold=240,
                          alpha_matting_background_threshold=10,
                          alpha_matting_erode_size=10)
        # rembg returns PNG bytes -- load into PIL for unified handling.
        from io import BytesIO
        yield path, Image.open(BytesIO(data)).convert("RGBA")


def op_remove(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    backend = args.backend.lower()
    started = time.monotonic()

    try:
        if backend in ("birefnet", "birefnet-portrait", "birefnet-matting"):
            stream = _segment_birefnet(inputs, HF_MODELS[backend], args.device)
        elif backend in ("rmbg2", "rmbg14"):
            stream = _segment_rmbg(inputs, HF_MODELS[backend], args.device)
        elif backend in ("u2net", "u2netp", "u2net_human_seg",
                         "isnet-general-use", "isnet-anime",
                         "silueta", "sam"):
            stream = _segment_rembg(inputs, backend)
        else:
            return fail("bad_backend",
                        f"Unsupported backend '{backend}'. Choose: "
                        "birefnet | birefnet-portrait | birefnet-matting | "
                        "rmbg2 | rmbg14 | u2net | u2net_human_seg | "
                        "isnet-general-use | isnet-anime | silueta | sam")
    except ImportError as ex:
        return fail("missing_dep", str(ex))

    total = len(inputs)
    emit("progress", percent=0, stage="bgremove", eta_seconds=None)
    for i, (src, rgba) in enumerate(stream):
        out_path = out_dir / (src.stem + "_nobg.png")
        rgba.save(str(out_path), "PNG", optimize=True)
        emit("matte_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             backend=backend)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_models(_args: argparse.Namespace) -> int:
    catalog = [
        ("birefnet", "BiRefNet (general SOTA, Apache-2.0, ~885 MB)"),
        ("birefnet-portrait", "BiRefNet HR Portrait (highest quality faces / hair)"),
        ("birefnet-matting", "BiRefNet Matting (true alpha matting)"),
        ("rmbg2", "RMBG-2.0 (BRIA AI Apache-2.0, generalist)"),
        ("rmbg14", "RMBG-1.4 (BRIA AI BSD-3, lighter)"),
        ("u2net", "U2Net via rembg (fastest, ~177 MB)"),
        ("u2net_human_seg", "U2Net human segmentation"),
        ("isnet-general-use", "IS-Net general (DIS-5K trained)"),
        ("isnet-anime", "IS-Net anime / illustrations"),
        ("silueta", "Silueta (smaller alternative)"),
        ("sam", "Segment Anything (Meta) -- promptable"),
    ]
    for name, desc in catalog:
        emit("matte_model", name=name, description=desc)
    emit("complete", output="", size_bytes=0, count=len(catalog))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bgremove-sidecar",
                                description="Modern image background removal "
                                            "(BiRefNet / RMBG-2.0 / IS-Net / U2Net / SAM).")
    sub = p.add_subparsers(dest="op", required=True)
    r = sub.add_parser("remove", help="Remove background; produce RGBA PNG.")
    r.add_argument("--input", nargs="+", required=True)
    r.add_argument("--output-dir", required=True, dest="output_dir")
    r.add_argument("--backend", default="birefnet",
                   help="Model backend (run `models` op to list).")
    r.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    sub.add_parser("models", help="List supported backends.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "remove": return op_remove(args)
        if args.op == "models": return op_models(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
