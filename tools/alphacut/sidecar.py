"""AlphaCut sidecar — NDJSON CLI shim for the UCX Background Remover module.

Wraps AlphaCut's ProcessingWorker and emits NDJSON progress events to stdout
so the C# SidecarRunner can drive the BackgroundRemoverPage UI.

Contract: see ../README.md (sidecar contract) and ../../README.md (parent).
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
from pathlib import Path

# Allow importing AlphaCut from the parent tools directory.
_here = Path(__file__).resolve().parent
_parent = _here.parent
sys.path.insert(0, str(_parent))
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_parent / "_lib"))
from ucx_assets import AssetError, LicenseNotAccepted, VerifiedAsset, cached_asset, download_verified, enforce_offline


DEFAULT_MODEL = VerifiedAsset(
    "u2net_human_seg", "u2net_human_seg.onnx",
    "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx",
    175997641, "01eb6a29a5c4d8edb30b56adad9bb3a2a0535338e480724a213e0acfd2d1c73c",
    "Apache-2.0")


def _model_root(args: argparse.Namespace) -> Path:
    return Path(
        args.model_dir
        or os.environ.get("UCX_MODEL_DIR")
        or Path.home() / ".alphacut" / "models")


# ─── NDJSON emitter ──────────────────────────────────────────────────────────

def emit(event: str, **fields) -> None:
    """Write a single NDJSON line to stdout and flush immediately."""
    payload = {"event": event, **fields}
    sys.stdout.write(_dumps(payload) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ─── AlphaCut import ─────────────────────────────────────────────────────────

def _import_alphacut():
    """Import AlphaCut module, bootstrapping it correctly in frozen context."""
    try:
        import AlphaCut  # noqa: PLC0415
        return AlphaCut
    except ImportError as exc:
        emit("error", code="import_failed",
             message=f"Could not import AlphaCut: {exc}. "
                     "Ensure AlphaCut.py is in the tools/ directory.")
        return None


# ─── Qt application setup ────────────────────────────────────────────────────

def _make_app():
    try:
        from PyQt6.QtCore import QCoreApplication  # noqa: PLC0415
        app = QCoreApplication.instance()
        if app is None:
            app = QCoreApplication(sys.argv[:1])
        return app
    except ImportError as exc:
        emit("error", code="qt_unavailable",
             message=f"PyQt6 not available: {exc}")
        return None


# ─── Worker signal handlers ──────────────────────────────────────────────────

_had_error = False
_error_message = ""


def _on_progress(pct: int) -> None:
    emit("progress", percent=float(pct), stage="Processing", eta_seconds=None)


def _on_status(text: str) -> None:
    emit("log", level="info", message=text)


def _on_log(text: str) -> None:
    emit("log", level="info", message=text)


def _on_error(msg: str) -> None:
    global _had_error, _error_message
    _had_error = True
    _error_message = msg
    emit("error", code="processing_failed", message=msg)


# ─── Job ─────────────────────────────────────────────────────────────────────

def run_bgremove(args: argparse.Namespace) -> int:
    enforce_offline()
    global _had_error, _error_message
    _had_error = False
    _error_message = ""

    AlphaCut = _import_alphacut()
    if AlphaCut is None:
        return 1

    app = _make_app()
    if app is None:
        return 1

    # Validate input
    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")

    # Build output path
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve model key
    available_models = getattr(AlphaCut, "MODELS", {})
    model_key = args.model
    if model_key not in available_models and available_models:
        matching = next(
            (key for key, config in available_models.items()
             if args.model.lower() in key.lower()
             or Path(config.get("file", "")).stem.lower() == args.model.lower()),
            None)
        if matching is None:
            model_key = next(iter(available_models))
            emit("log", level="warn",
                 message=f"Model '{args.model}' not found; using '{model_key}'")
        else:
            model_key = matching

    # Resolve output format. AlphaCut's ProcessingWorker expects the short
    # format CODE (the values of OUTPUT_FORMATS: mp4, webm, png_seq, prores,
    # ...), not the human-readable display-name keys. Map the UI/CLI aliases
    # onto those codes and validate against the real code set so a valid
    # request is never silently downgraded to the first format.
    format_codes = set(getattr(AlphaCut, "OUTPUT_FORMATS", {}).values())
    format_aliases = {
        "png_sequence": "png_seq",
        "png-sequence": "png_seq",
        "sequence": "png_seq",
        "mov": "prores",
        "chroma": "greenscreen",
        "green": "greenscreen",
        "webp": "webp_anim",
        "gif": "gif_anim",
    }
    requested = (args.format or "mp4").strip().lower()
    out_format = format_aliases.get(requested, requested)
    if format_codes and out_format not in format_codes:
        emit("log", level="warn",
             message=f"Unknown output format '{args.format}'; falling back to mp4.")
        out_format = "mp4"

    # Resolve ffmpeg
    find_ffmpeg = getattr(AlphaCut, "find_ffmpeg", None)
    if find_ffmpeg:
        ffmpeg_path = find_ffmpeg()
        if not ffmpeg_path:
            emit("log", level="warn", message="FFmpeg not found on PATH; audio may not be preserved.")

    emit("log", level="info", message=f"Starting background removal on {in_path.name}")
    emit("log", level="info", message=f"Model: {model_key}  Format: {out_format}  Quality: {args.quality}")
    emit("progress", percent=0.0, stage="Initializing", eta_seconds=None)

    # Resolve shared model cache directory (UCX_MODEL_DIR set by SidecarRunner).
    model_dir = args.model_dir or os.environ.get("UCX_MODEL_DIR") or None
    if model_dir:
        Path(model_dir).mkdir(parents=True, exist_ok=True)
        AlphaCut.MODELS_DIR = str(Path(model_dir))
        emit("log", level="info", message=f"Model cache: {model_dir}")

    try:
        ProcessingWorker = AlphaCut.ProcessingWorker
    except AttributeError:
        return fail("import_failed", "AlphaCut.ProcessingWorker not found in module.")

    # Build worker kwargs matching the ProcessingWorker signature
    worker_kwargs: dict = {
        "input_path": str(in_path),
        "output_path": str(out_path),
        "model_key": model_key,
        "output_format": out_format,
        "max_res": args.max_res if args.max_res and args.max_res > 0 else 0,
        "edge_softness": args.edge,
        "mask_shift": args.shift,
        "temporal_smooth": args.temporal,
        "keep_audio": not args.no_audio,
        "frame_skip": args.frame_skip,
        "invert_mask": args.invert,
        "spill_strength": args.spill,
        "spill_color": args.spill_color,
        "shadow_strength": args.shadow,
        "bg_color": args.bg_color,
        "bg_image_path": args.bg_image,
        "resume_from": 0,
        "quality": args.quality,
    }
    if model_dir:
        worker_kwargs["model_dir"] = model_dir

    try:
        worker = ProcessingWorker(**worker_kwargs)
    except TypeError as exc:
        # Older AlphaCut signature — try minimal kwargs
        emit("log", level="warn", message=f"Full kwargs failed ({exc}); retrying with minimal args.")
        try:
            worker = ProcessingWorker(
                input_path=str(in_path),
                output_path=str(out_path),
                model_key=model_key,
                output_format=out_format,
                max_res=worker_kwargs["max_res"],
            )
        except Exception as exc2:
            return fail("worker_init_failed", f"Could not create ProcessingWorker: {exc2}")

    # Connect signals
    finished_output: list[str] = []

    def _on_finished(output_path: str) -> None:
        finished_output.append(output_path)

    worker.progress.connect(_on_progress)
    worker.status.connect(_on_status)
    worker.log.connect(_on_log)
    worker.error.connect(_on_error)
    worker.finished.connect(_on_finished)

    # Run synchronously (not worker.start() — call worker.run() directly)
    try:
        worker.run()
    except Exception as exc:
        return fail("worker_exception", f"{type(exc).__name__}: {exc}")

    if _had_error:
        return 1

    # Determine output. A PNG sequence writes frames into a directory rather
    # than a single file, so validate the frame set instead of a lone path.
    result_path = finished_output[0] if finished_output else str(out_path)
    result_file = Path(result_path)

    if out_format == "png_seq":
        frame_dir = result_file if result_file.is_dir() else result_file.parent
        frames = sorted(frame_dir.glob("*.png")) if frame_dir.is_dir() else []
        if not frames:
            return fail("output_missing",
                        f"No PNG frames were produced in {frame_dir}.")
        size = sum(f.stat().st_size for f in frames)
        emit("progress", percent=100.0, stage="Complete", eta_seconds=0)
        emit("complete", output=str(frame_dir), size_bytes=size, count=len(frames))
        return 0

    if not result_file.is_file():
        return fail("output_missing",
                    f"Expected output file was not produced: {result_path}")

    size = result_file.stat().st_size
    emit("progress", percent=100.0, stage="Complete", eta_seconds=0)
    emit("complete", output=result_path, size_bytes=size)
    return 0


# ─── Argument parser ─────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="alphacut-sidecar",
        description="UCX AlphaCut sidecar — background removal with NDJSON progress.",
    )
    p.add_argument("--input",
                   help="Input video or image path")
    p.add_argument("--output",
                   help="Output file path")
    p.add_argument("--model", default="u2net_human_seg",
                   help="AlphaCut model key (default: u2net_human_seg)")
    p.add_argument("--format", default="mp4",
                   help="Output format: mp4, mov, webm, png_sequence (default: mp4)")
    p.add_argument("--quality", type=int, default=70,
                   help="Output quality 0-100 (default: 70)")
    p.add_argument("--max-res", type=int, default=0,
                   help="Maximum resolution cap (0 = no limit)")
    p.add_argument("--edge", type=int, default=0,
                   help="Edge softness 0-100 (default: 0)")
    p.add_argument("--shift", type=int, default=0,
                   help="Mask shift pixels (default: 0)")
    p.add_argument("--temporal", type=int, default=0,
                   help="Temporal smoothing strength 0-100 (default: 0)")
    p.add_argument("--frame-skip", type=int, default=1,
                   help="Process every N frames (default: 1 = all frames)")
    p.add_argument("--invert", action="store_true",
                   help="Invert the mask (keep background, remove subject)")
    p.add_argument("--spill", type=int, default=0,
                   help="Color spill suppression strength 0-100 (default: 0)")
    p.add_argument("--spill-color", default="green",
                   choices=["green", "blue", "red"],
                   help="Spill color to suppress (default: green)")
    p.add_argument("--shadow", type=int, default=0,
                   help="Shadow preservation strength 0-100 (default: 0)")
    p.add_argument("--bg-color",
                   help="Solid background color as hex string, e.g. #ffffff")
    p.add_argument("--bg-image",
                   help="Background image path to composite over")
    p.add_argument("--no-audio", action="store_true",
                   help="Strip audio from output (video inputs only)")
    p.add_argument("--model-dir",
                   help="Shared model cache directory (overrides UCX_MODEL_DIR env var)")
    p.add_argument("--download-model", choices=["u2net_human_seg"],
                   help="Install a pinned model instead of processing input.")
    p.add_argument("--check-model", action="store_true",
                   help="Report whether the pinned default model is installed and valid.")
    p.add_argument("--accept-license", action="store_true",
                   help="Accept the model license before network access.")
    return p


# ─── Entry point ─────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.check_model:
            target = cached_asset(_model_root(args), DEFAULT_MODEL)
            emit("model_status", ready=target is not None,
                 path=str(_model_root(args) / DEFAULT_MODEL.filename),
                 size_bytes=DEFAULT_MODEL.size_bytes, sha256=DEFAULT_MODEL.sha256,
                 license=DEFAULT_MODEL.license)
            emit("complete", output=str(target or ""),
                 size_bytes=target.stat().st_size if target else 0)
            return 0
        if args.download_model:
            root = _model_root(args)
            try:
                target = download_verified(root, DEFAULT_MODEL, accept_license=args.accept_license)
            except LicenseNotAccepted as exc:
                return fail("license_not_accepted", str(exc))
            except AssetError as exc:
                return fail("model_integrity_failed", str(exc))
            (target.with_suffix(target.suffix + ".sha256")).write_text(DEFAULT_MODEL.sha256, encoding="ascii")
            emit("complete", output=str(target), size_bytes=target.stat().st_size,
                 sha256=DEFAULT_MODEL.sha256, license=DEFAULT_MODEL.license)
            return 0
        if not args.input or not args.output:
            return fail("missing_argument", "--input and --output are required for background removal.")
        return run_bgremove(args)
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
