"""GFPGAN sidecar — NDJSON face restoration / photo enhancement.

Wraps GFPGAN v1.4 (TencentARC, Apache-2.0) for blind face restoration on old
or degraded photos. Optionally pairs with Real-ESRGAN background upscaling
when available — but degrades cleanly to face-only if not.

Subcommands:
  restore       restore one image
  list-models   enumerate .pth weights discoverable in tools/gfpgan/models/

Standard NDJSON contract: progress / log / complete / error / model events.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


# ── NDJSON helpers ───────────────────────────────────────────────────────────

def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def log(level: str, message: str) -> None:
    emit("log", level=level, message=message)


def progress(percent: float, stage: str = "", eta: int | None = None) -> None:
    payload: dict = {"percent": round(percent, 1), "stage": stage}
    if eta is not None:
        payload["eta_seconds"] = eta
    emit("progress", **payload)


# ── Bootstrap ────────────────────────────────────────────────────────────────

def _ensure_deps() -> None:
    """Install gfpgan + torch on first run.

    PyInstaller fork-bomb guard: when frozen, sys.executable is this sidecar
    exe — pip install would re-spawn the exe. Bundle deps at build time.
    """
    if getattr(sys, "frozen", False):
        try:
            import gfpgan  # noqa: F401
            import torch   # noqa: F401
            return
        except ImportError:
            fail("missing_dep",
                 "gfpgan / torch not bundled into this frozen sidecar. "
                 "Rebuild after `pip install gfpgan torch torchvision`.")
            sys.exit(1)

    try:
        import gfpgan  # noqa: F401
        import torch   # noqa: F401
        return
    except ImportError:
        pass

    log("info", "gfpgan / torch not found — installing (this can take a few minutes)...")
    progress(0.5, "installing dependencies")
    for extra in [[], ["--user"], ["--break-system-packages"]]:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "gfpgan>=1.3.8", "basicsr>=1.4.2", "facexlib>=0.3.0",
             "torch>=2.0.0", "torchvision>=0.15.0", *extra],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            log("info", "dependencies installed.")
            return
    fail("install_failed", "Could not install gfpgan / torch.")
    sys.exit(1)


# ── Model discovery ──────────────────────────────────────────────────────────

def _models_dir_local() -> Path:
    return Path(__file__).resolve().parent / "models"


def _models_dir_shared() -> Path | None:
    base = os.environ.get("UCX_MODEL_DIR")
    if not base:
        return None
    return Path(base) / "gfpgan"


def discover_models() -> list[Path]:
    found: list[Path] = []
    for d in (_models_dir_shared(), _models_dir_local()):
        if d and d.is_dir():
            found.extend(sorted(d.glob("*.pth")))
    seen: dict[str, Path] = {}
    for p in found:
        seen.setdefault(p.name.lower(), p)
    return list(seen.values())


def resolve_model(arg_path: str | None) -> Path | None:
    if arg_path:
        p = Path(arg_path)
        return p if p.is_file() else None
    candidates = discover_models()
    if not candidates:
        return None
    # Prefer GFPGANv1.4 if present.
    for p in candidates:
        if "1.4" in p.name:
            return p
    return candidates[0]


def op_list_models(_: argparse.Namespace) -> int:
    found = discover_models()
    for p in found:
        emit("model", name=p.name, path=str(p),
             location=str(p.parent), size_bytes=p.stat().st_size)
    emit("complete", count=len(found))
    return 0


# ── restore ──────────────────────────────────────────────────────────────────

def op_restore(args: argparse.Namespace) -> int:
    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input not found: {in_path}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    model_path = resolve_model(args.model)
    if model_path is None:
        return fail(
            "missing_model",
            "No GFPGAN .pth model found. Pass --model <path>, or drop "
            "GFPGANv1.4.pth into tools/gfpgan/models/. The first run can also "
            "auto-download via the gfpgan package — set UCX_MODEL_DIR to point "
            "the cache somewhere persistent.",
        )
    log("info", f"Model: {model_path.name}")

    progress(2.0, "loading dependencies")
    import cv2          # type: ignore
    import torch        # type: ignore
    from gfpgan import GFPGANer  # type: ignore

    upscale = max(1, min(args.upscale, 4))
    weight = max(0.0, min(args.weight, 1.0))

    progress(8.0, "loading model")
    log("info", f"Device: {'CUDA' if torch.cuda.is_available() else 'CPU'}; "
                f"upscale={upscale}, weight={weight:.2f}, only-center={args.only_center_face}")

    restorer = GFPGANer(
        model_path=str(model_path),
        upscale=upscale,
        arch="clean",
        channel_multiplier=2,
        bg_upsampler=None,    # background upsampling left to a separate Real-ESRGAN pass
    )

    progress(20.0, "decoding image")
    img = cv2.imread(str(in_path), cv2.IMREAD_COLOR)
    if img is None:
        return fail("decode_failed", f"OpenCV could not decode {in_path.name}")

    progress(40.0, "restoring faces")
    try:
        # GFPGANer.enhance returns (cropped_faces, restored_faces, restored_img)
        _, _, restored = restorer.enhance(
            img,
            has_aligned=False,
            only_center_face=args.only_center_face,
            paste_back=True,
            weight=weight,
        )
    except Exception as exc:
        return fail("restore_failed", f"GFPGAN error: {exc}")

    if restored is None:
        return fail("no_faces", "No faces detected and no fallback image returned.")

    progress(85.0, "encoding output")
    # Choose JPEG quality if the user asked for .jpg/.jpeg; PNG otherwise.
    ext = out_path.suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        ok = cv2.imwrite(str(out_path), restored, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    elif ext == ".webp":
        ok = cv2.imwrite(str(out_path), restored, [int(cv2.IMWRITE_WEBP_QUALITY), 92])
    else:
        ok = cv2.imwrite(str(out_path), restored)
    if not ok or not out_path.is_file():
        return fail("encode_failed", f"OpenCV could not write {out_path}")

    progress(100.0, "done", 0)
    emit("complete",
         output=str(out_path),
         size_bytes=out_path.stat().st_size,
         model=model_path.name,
         upscale=upscale)
    return 0


# ── argparse + main ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gfpgan-sidecar",
        description="UCX GFPGAN sidecar — blind face restoration for photos.",
    )
    sub = p.add_subparsers(dest="op", required=True)

    r = sub.add_parser("restore", help="Restore one photo")
    r.add_argument("--input",  required=True)
    r.add_argument("--output", required=True)
    r.add_argument("--model",  default=None,
                   help="Path to GFPGAN .pth weights. Defaults to GFPGANv1.4.pth "
                        "in tools/gfpgan/models/ if present.")
    r.add_argument("--upscale", type=int, default=2,
                   help="Output upscale factor 1–4 (default 2).")
    r.add_argument("--weight",  type=float, default=0.5,
                   help="Restoration strength 0.0–1.0 (default 0.5).")
    r.add_argument("--only-center-face", action="store_true",
                   help="Restore only the largest face (faster, single subject).")

    sub.add_parser("list-models", help="Enumerate available .pth models")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "restore":
            _ensure_deps()
            return op_restore(args)
        if args.op == "list-models":
            return op_list_models(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
