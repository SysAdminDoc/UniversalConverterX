"""Image super-resolution sidecar covering modern transformer-based models.

Built on `spandrel` (BSD-3, the same loader used by ChaiNNer), which auto-
detects the architecture of a .pth checkpoint and gives back a unified
forward function. Supports:

  * Real-ESRGAN / Real-ESRNet / ESRGAN          (CNN-based, broadly compatible)
  * RealCUGAN / Real-CUGAN-Pro                  (anime-tuned)
  * SwinIR / SwinIR-Large                       (transformer)
  * HAT / HAT-Light / HAT-L                     (CVPR 2023 transformer SOTA)
  * DAT / DAT-Light / DAT-2                     (Dual Aggregation Transformer)
  * OmniSR                                       (lightweight transformer)
  * DRCT / DRCT-L                               (CVPR 2024)
  * SCUNet                                       (joint denoise + SR)
  * APISR                                        (anime production)

Default model = HAT-L x4 because it has the cleanest results on photographic
content. Anime / illustration users should pass --model real-cugan-pro or apisr.

Models are NOT bundled. Pass --model <repo-id-or-local-path>; we cache to
`<UCX_MODEL_DIR>/superres/`.
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
import os
import sys
import time
import urllib.request
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# Curated download URLs for OSS checkpoints. All MIT/Apache/BSD licensed.
DOWNLOADS: dict[str, str] = {
    # Real-ESRGAN family
    "real-esrgan-x4plus":
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    "real-esrgan-anime":
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
    "real-esrnet-x4":
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.1/RealESRNet_x4plus.pth",
    # HAT family (Hybrid Attention Transformer)
    "hat-l-x4":
        "https://github.com/XPixelGroup/HAT/releases/download/v0.1.0/HAT-L_SRx4_ImageNet-pretrain.pth",
    "hat-x4":
        "https://github.com/XPixelGroup/HAT/releases/download/v0.1.0/HAT_SRx4_ImageNet-pretrain.pth",
    # DAT family
    "dat-x4":
        "https://github.com/zhengchen1999/DAT/releases/download/v1/DAT_x4.pth",
    "dat-light-x4":
        "https://github.com/zhengchen1999/DAT/releases/download/v1/DAT_light_x4.pth",
    # SwinIR
    "swinir-x4":
        "https://github.com/JingyunLiang/SwinIR/releases/download/v0.0/001_classicalSR_DF2K_s64w8_SwinIR-M_x4.pth",
    "swinir-large-x4":
        "https://github.com/JingyunLiang/SwinIR/releases/download/v0.0/003_realSR_BSRGAN_DFOWMFC_s64w8_SwinIR-L_x4_GAN.pth",
    # APISR (anime production SR, CVPR 2024)
    "apisr-x4":
        "https://github.com/Kiteretsu77/APISR/releases/download/v1.0.1/4x_APISR_GRL_GAN_generator.pth",
    "apisr-x2":
        "https://github.com/Kiteretsu77/APISR/releases/download/v1.0.1/2x_APISR_RRDB_GAN_generator.pth",
    # SCUNet (joint denoise + SR)
    "scunet":
        "https://github.com/cszn/KAIR/releases/download/v1.0/scunet_color_real_psnr.pth",
}


def _model_dir() -> Path:
    base = os.environ.get("UCX_MODEL_DIR")
    p = Path(base) if base else Path.home() / ".cache" / "ucx" / "models"
    out = p / "superres"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _resolve_checkpoint(model_arg: str) -> Path:
    """Resolve `model_arg` (alias, URL, or path) to a local .pth file."""
    p = Path(model_arg)
    if p.is_file(): return p
    if model_arg in DOWNLOADS:
        url = DOWNLOADS[model_arg]
        target = _model_dir() / Path(url).name
        if not target.is_file():
            emit("log", level="info",
                 message=f"Downloading {model_arg} from {url}...")
            urllib.request.urlretrieve(url, str(target))
        return target
    if model_arg.startswith(("http://", "https://")):
        target = _model_dir() / Path(model_arg).name
        if not target.is_file():
            urllib.request.urlretrieve(model_arg, str(target))
        return target
    raise FileNotFoundError(f"Unknown model alias / file not found: {model_arg}")


def op_upscale(args: argparse.Namespace) -> int:
    try:
        import torch
        from PIL import Image
        import numpy as np
        from spandrel import ModelLoader
    except ImportError as ex:
        return fail("missing_dep",
                    f"spandrel/torch/Pillow not installed: {ex}. "
                    "`pip install spandrel torch torchvision`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        ckpt = _resolve_checkpoint(args.model)
    except Exception as ex:
        return fail("missing_model", str(ex))

    device = "cuda" if (args.device == "cuda" and torch.cuda.is_available()) else "cpu"
    dtype = torch.float16 if device == "cuda" and args.dtype == "fp16" else torch.float32
    emit("log", level="info",
         message=f"Loading {ckpt.name} via spandrel on {device} ({dtype})...")
    loader = ModelLoader()
    model = loader.load_from_file(str(ckpt))
    model = model.to(device).eval()
    if dtype == torch.float16:
        model = model.half()
    scale = getattr(model, "scale", 4)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="upscale", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            img = Image.open(str(src)).convert("RGB")
            arr = np.asarray(img).astype("float32") / 255.0
            t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(device, dtype=dtype)
            with torch.inference_mode():
                out = model(t)
            out_arr = (out.clamp(0, 1).squeeze(0).permute(1, 2, 0).float().cpu().numpy()
                       * 255).round().astype("uint8")
            out_img = Image.fromarray(out_arr)
            out_path = out_dir / f"{src.stem}_x{int(scale)}{src.suffix or '.png'}"
            if out_path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"):
                out_path = out_path.with_suffix(".png")
            out_img.save(str(out_path), quality=95)
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("upscale_failed", f"{src.name}: {ex}")

        emit("upscale_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             scale=int(scale), model=ckpt.stem, backend="spandrel")
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_models(_args: argparse.Namespace) -> int:
    for name, url in DOWNLOADS.items():
        emit("upscale_model", name=name, url=url,
             local=str((_model_dir() / Path(url).name)))
    emit("complete", output="", size_bytes=0, count=len(DOWNLOADS))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="superres-sidecar",
                                description="Image super-resolution via spandrel.")
    sub = p.add_subparsers(dest="op", required=True)
    u = sub.add_parser("upscale", help="Upscale image(s).")
    u.add_argument("--input", nargs="+", required=True)
    u.add_argument("--output-dir", required=True, dest="output_dir")
    u.add_argument("--model", default="hat-l-x4",
                   help=f"Alias from {sorted(DOWNLOADS.keys())}, URL, or path to .pth")
    u.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    u.add_argument("--dtype", default="fp16", choices=["fp16", "fp32"])
    sub.add_parser("models", help="List built-in model aliases + download URLs.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "upscale": return op_upscale(args)
        if args.op == "models":  return op_models(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
