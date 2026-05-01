"""Modern face restoration sidecar.

Wraps two SOTA OSS restoration models:

  * CodeFormer (NeurIPS 2022 -- still top-tier; controllable fidelity/quality slider)
  * GFPGAN v1.4 (legacy, still excellent on photographic faces)

CodeFormer's killer feature is its `--w` (weight) slider: 0.0 = max identity
preservation, 1.0 = max quality. Use 0.5-0.7 for old photos, 0.7-0.9 for
deepfake-grade enhancement.

Wraps the upstream `codeformer-pip` package which bundles the inference
runtime; downloads weights from the maintainer's mirror on first use.
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


def op_restore_codeformer(args: argparse.Namespace) -> int:
    try:
        from codeformer import CodeFormer
    except ImportError:
        try:
            from codeformer_pip import CodeFormer  # alternative pkg name
        except ImportError as ex:
            return fail("missing_codeformer",
                        f"codeformer not installed: {ex}. "
                        "`pip install codeformer-pip`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cf = CodeFormer()
    if hasattr(cf, "fidelity_weight"):
        cf.fidelity_weight = float(args.w)
    upscale = int(args.upscale)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="restore", eta_seconds=None)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "_restored.png")
        try:
            res = cf.run(str(src), output_path=str(out_path),
                         fidelity_weight=float(args.w),
                         upscale=upscale,
                         face_upsample=bool(args.face_upsample),
                         background_enhance=bool(args.bg_enhance))
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("restore_failed", f"{src.name}: {ex}")

        emit("face_restore",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0,
             backend="codeformer", fidelity=float(args.w), upscale=upscale)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_restore_gfpgan(args: argparse.Namespace) -> int:
    try:
        from gfpgan import GFPGANer
        import cv2
    except ImportError as ex:
        return fail("missing_gfpgan",
                    f"gfpgan / opencv not installed: {ex}. "
                    "`pip install gfpgan opencv-python-headless`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    restorer = GFPGANer(
        model_path=args.model,  # auto-downloads if not cached
        upscale=int(args.upscale),
        arch="clean", channel_multiplier=2,
        bg_upsampler=None,
    )
    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            img = cv2.imread(str(src), cv2.IMREAD_COLOR)
            _, _, restored = restorer.enhance(
                img, has_aligned=False, only_center_face=False,
                paste_back=True, weight=float(args.w))
            out_path = out_dir / (src.stem + "_gfpgan.png")
            cv2.imwrite(str(out_path), restored)
        except Exception as ex:
            return fail("restore_failed", f"{src.name}: {ex}")
        emit("face_restore",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             backend="gfpgan", upscale=int(args.upscale))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="facerestore-sidecar",
                                description="Face restoration (CodeFormer / GFPGAN).")
    sub = p.add_subparsers(dest="op", required=True)
    cf = sub.add_parser("codeformer", help="Restore via CodeFormer.")
    cf.add_argument("--input", nargs="+", required=True)
    cf.add_argument("--output-dir", required=True, dest="output_dir")
    cf.add_argument("--w", type=float, default=0.7,
                    help="Fidelity weight 0..1 (0=identity, 1=quality). Default 0.7.")
    cf.add_argument("--upscale", type=int, default=1,
                    help="Output scale factor (1, 2, 4).")
    cf.add_argument("--face-upsample", action="store_true",
                    help="Apply face-only upsampling pass.")
    cf.add_argument("--bg-enhance", action="store_true",
                    help="Run Real-ESRGAN background pass.")

    gp = sub.add_parser("gfpgan", help="Restore via GFPGAN v1.4.")
    gp.add_argument("--input", nargs="+", required=True)
    gp.add_argument("--output-dir", required=True, dest="output_dir")
    gp.add_argument("--model", default="https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth")
    gp.add_argument("--w", type=float, default=0.5)
    gp.add_argument("--upscale", type=int, default=2)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "codeformer": return op_restore_codeformer(args)
        if args.op == "gfpgan":     return op_restore_gfpgan(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
