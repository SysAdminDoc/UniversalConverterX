"""VideoSubtitleRemover sidecar — NDJSON CLI shim for the UCX Subtitle Remover module.

Wraps the VideoSubtitleRemover backend.SubtitleRemover engine and emits NDJSON
progress events to stdout so the C# SidecarRunner can drive the
SubtitleRemoverPage UI.

Contract: see ../README.md (sidecar contract).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}


# ─── NDJSON emitter ──────────────────────────────────────────────────────────

def emit(event: str, **fields) -> None:
    payload = {"event": event, **fields}
    sys.stdout.write(_dumps(payload) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ─── Job ─────────────────────────────────────────────────────────────────────

def run_removal(args: argparse.Namespace) -> int:
    # Lazy imports — heavy deps live in the backend package.
    try:
        from backend.processor import ProcessingConfig, SubtitleRemover
    except ImportError as exc:
        return fail("import_failed",
                    f"Could not import backend.processor: {exc}. "
                    f"Run `pip install -r requirements.txt` inside "
                    f"`tools/videosubtitleremover/`.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve shared model cache directory.
    model_dir = args.model_dir or os.environ.get("UCX_MODEL_DIR") or None
    if model_dir:
        Path(model_dir).mkdir(parents=True, exist_ok=True)
        emit("log", level="info", message=f"Model cache: {model_dir}")

    # Parse optional subtitle area rect (x1,y1,x2,y2).
    subtitle_area = None
    if args.area:
        try:
            parts = [int(v.strip()) for v in args.area.split(",")]
            if len(parts) == 4:
                subtitle_area = tuple(parts)
            else:
                emit("log", level="warn",
                     message=f"--area must be x1,y1,x2,y2 — got {args.area!r}; ignoring")
        except ValueError:
            emit("log", level="warn",
                 message=f"--area parse error: {args.area!r}; ignoring")

    config = ProcessingConfig(
        mode=args.mode,
        device=args.device,
        detection_threshold=args.threshold,
        detection_lang=args.lang,
        subtitle_area=subtitle_area,
        preserve_audio=not args.no_audio,
        output_format=args.format or out_path.suffix.lstrip(".").lower() or "mp4",
        output_quality=args.quality,
        use_hw_encode=not args.no_hw_encode,
    )

    emit("log", level="info",
         message=f"Starting subtitle removal on {in_path.name}")
    emit("log", level="info",
         message=f"Mode: {args.mode}  Device: {args.device}  "
                 f"Format: {config.output_format}  Quality: {args.quality}")
    emit("progress", percent=0.0, stage="Initializing", eta_seconds=None)

    try:
        remover = SubtitleRemover(config=config)
    except Exception as exc:
        return fail("init_failed", f"SubtitleRemover init failed: {type(exc).__name__}: {exc}")

    def _on_progress(percent: float, stage: str) -> None:
        emit("progress", percent=round(percent * 100.0, 1), stage=stage, eta_seconds=None)

    remover.on_progress = _on_progress

    is_image = in_path.suffix.lower() in _IMAGE_EXTS
    try:
        if is_image:
            ok = remover.process_image(str(in_path), str(out_path))
        else:
            ok = remover.process_video(str(in_path), str(out_path))
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:
        return fail("processing_error", f"{type(exc).__name__}: {exc}")

    if not ok:
        return fail("processing_failed", "Subtitle remover returned failure — check logs above.")

    if not out_path.is_file():
        return fail("output_missing",
                    f"Expected output was not produced: {out_path}")

    size = out_path.stat().st_size
    emit("progress", percent=100.0, stage="Complete", eta_seconds=0)
    emit("complete", output=str(out_path), size_bytes=size)
    return 0


# ─── Argument parser ─────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="videosubtitleremover-sidecar",
        description="UCX VideoSubtitleRemover sidecar — subtitle/watermark inpainting "
                    "with NDJSON progress.",
    )
    p.add_argument("--input", required=True,
                   help="Input video or image path")
    p.add_argument("--output", required=True,
                   help="Output file path")
    p.add_argument("--mode", default="sttn",
                   choices=["sttn", "lama", "propainter", "auto"],
                   help="Inpainting algorithm (default: sttn)")
    p.add_argument("--device", default="cpu",
                   help="Compute device: cpu, directml, cuda:0, cuda:1 (default: cpu)")
    p.add_argument("--lang", default="en",
                   help="OCR language code for subtitle detection (default: en)")
    p.add_argument("--area",
                   help="Restrict detection to a subtitle region: x1,y1,x2,y2 pixels")
    p.add_argument("--threshold", type=float, default=0.5,
                   help="Detection confidence threshold 0.0–1.0 (default: 0.5)")
    p.add_argument("--quality", type=int, default=23,
                   help="Output CRF quality 0-51 for video re-encode (default: 23)")
    p.add_argument("--format", default="",
                   help="Override output container format (default: inferred from --output)")
    p.add_argument("--no-audio", action="store_true",
                   help="Strip audio from output (video inputs only)")
    p.add_argument("--no-hw-encode", action="store_true",
                   help="Disable hardware encoder (NVENC/QSV) for output video")
    p.add_argument("--model-dir",
                   help="Shared model cache directory (overrides UCX_MODEL_DIR env var)")
    return p


# ─── Entry point ─────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_removal(args)
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
