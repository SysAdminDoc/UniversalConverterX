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

Default model = Real-ESRGAN x4plus. Transformer checkpoints remain usable as
local files; curated network downloads are restricted to pinned assets whose
size and SHA-256 are verified before they enter the model cache.

Models are NOT bundled. Install a curated model through `download-model
--accept-license` or pass an existing local checkpoint to `--model`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from ucx_assets import (
    AssetError,
    LicenseNotAccepted,
    VerifiedAsset,
    cached_asset,
    download_verified,
    enforce_offline,
)




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# Curated immutable release assets. Update URL, byte count, digest, and license
# together; inference never performs network access.
DOWNLOADS: dict[str, VerifiedAsset] = {
    "real-esrgan-x4plus": VerifiedAsset(
        "real-esrgan-x4plus", "RealESRGAN_x4plus.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        67040989, "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1",
        "BSD-3-Clause"),
    "real-esrgan-anime": VerifiedAsset(
        "real-esrgan-anime", "RealESRGAN_x4plus_anime_6B.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        17938799, "f872d837d3c90ed2e05227bed711af5671a6fd1c9f7d7e91c911a61f155e99da",
        "BSD-3-Clause"),
    "real-esrnet-x4": VerifiedAsset(
        "real-esrnet-x4", "RealESRNet_x4plus.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.1/RealESRNet_x4plus.pth",
        67040989, "a820b9bde89a874d7599d545567308ce6c128fc8754a53208eda016d40aa81df",
        "BSD-3-Clause"),
    "swinir-x4": VerifiedAsset(
        "swinir-x4", "001_classicalSR_DF2K_s64w8_SwinIR-M_x4.pth",
        "https://github.com/JingyunLiang/SwinIR/releases/download/v0.0/001_classicalSR_DF2K_s64w8_SwinIR-M_x4.pth",
        67869037, "4e78e33f22c1aa8a773db0cf4a7381bae97c2362c717f155439ebc690cbd9215",
        "Apache-2.0"),
    "swinir-large-x4": VerifiedAsset(
        "swinir-large-x4", "003_realSR_BSRGAN_DFOWMFC_s64w8_SwinIR-L_x4_GAN.pth",
        "https://github.com/JingyunLiang/SwinIR/releases/download/v0.0/003_realSR_BSRGAN_DFOWMFC_s64w8_SwinIR-L_x4_GAN.pth",
        142473939, "99adfa91350a84c99e946c1eb3d8fce34bc28f57d807b09dc8fe40a316328c0a",
        "Apache-2.0"),
    "scunet": VerifiedAsset(
        "scunet", "scunet_color_real_psnr.pth",
        "https://github.com/cszn/KAIR/releases/download/v1.0/scunet_color_real_psnr.pth",
        71982841, "fa78899ba2caec9d235a900e91d96c689da71c42029230c2028b00f09f809c2e",
        "MIT"),
}


def _model_dir() -> Path:
    base = os.environ.get("UCX_MODEL_DIR")
    p = Path(base) if base else Path.home() / ".cache" / "ucx" / "models"
    out = p / "superres"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _resolve_checkpoint(model_arg: str) -> Path:
    """Resolve a verified cached alias or an explicitly supplied local file."""
    p = Path(model_arg)
    if p.is_file():
        return p
    if model_arg in DOWNLOADS:
        target = cached_asset(_model_dir(), DOWNLOADS[model_arg])
        if target is None:
            raise FileNotFoundError(
                f"Verified model {model_arg!r} is not installed. Run "
                f"`download-model --model {model_arg} --accept-license`.")
        return target
    if model_arg.startswith(("http://", "https://")):
        raise ValueError("Remote checkpoint URLs are not accepted; use a curated alias or local file.")
    raise FileNotFoundError(f"Unknown model alias / file not found: {model_arg}")


def op_download_model(args: argparse.Namespace) -> int:
    asset = DOWNLOADS.get(args.model)
    if asset is None:
        return fail("unknown_model", f"Unknown curated model: {args.model}")
    try:
        target = download_verified(
            _model_dir(),
            asset,
            accept_license=args.accept_license,
            progress=lambda done, total: emit(
                "progress",
                percent=round(done / max(1, total) * 100, 1),
                stage=f"downloading {asset.asset_id}",
                eta_seconds=None,
            ),
        )
    except LicenseNotAccepted as exc:
        return fail("license_not_accepted", str(exc))
    except AssetError as exc:
        return fail("model_integrity_failed", str(exc))
    emit(
        "complete",
        output=str(target),
        size_bytes=target.stat().st_size,
        model=asset.asset_id,
        sha256=asset.sha256,
        license=asset.license,
    )
    return 0


def op_upscale(args: argparse.Namespace) -> int:
    enforce_offline()
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
    for name, asset in DOWNLOADS.items():
        local = cached_asset(_model_dir(), asset)
        emit(
            "upscale_model",
            name=name,
            url=asset.url,
            local=str(_model_dir() / asset.filename),
            ready=local is not None,
            size_bytes=asset.size_bytes,
            sha256=asset.sha256,
            license=asset.license,
        )
    emit("complete", output="", size_bytes=0, count=len(DOWNLOADS))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="superres-sidecar",
                                description="Image super-resolution via spandrel.")
    sub = p.add_subparsers(dest="op", required=True)
    u = sub.add_parser("upscale", help="Upscale image(s).")
    u.add_argument("--input", nargs="+", required=True)
    u.add_argument("--output-dir", required=True, dest="output_dir")
    u.add_argument("--model", default="real-esrgan-x4plus",
                   help=f"Verified alias from {sorted(DOWNLOADS.keys())} or local .pth path")
    u.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    u.add_argument("--dtype", default="fp16", choices=["fp16", "fp32"])
    download = sub.add_parser("download-model", help="Install a pinned model asset.")
    download.add_argument("--model", required=True, choices=sorted(DOWNLOADS))
    download.add_argument("--accept-license", action="store_true", dest="accept_license")
    sub.add_parser("models", help="List pinned model aliases and readiness.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "upscale": return op_upscale(args)
        if args.op == "download-model": return op_download_model(args)
        if args.op == "models":  return op_models(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
