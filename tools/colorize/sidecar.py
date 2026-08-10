"""Offline B&W -> colour sidecar (CPU, OpenCV DNN).

Colourises grayscale photos and video using Richard Zhang's Colorful Image
Colorization model (BSD-2-Clause) through OpenCV's DNN module. The optional
DDColor tier uses an Apache-2.0 ONNX model and optical-flow chroma propagation
to reduce frame-to-frame flicker; the portable classic tier remains the
default. Both tiers run locally and the classic tier needs no GPU or PyTorch.

The model weights are NOT bundled. `download-model` is the only networked
operation and requires explicit `--accept-license`; it fetches SHA-256 pinned
files into the shared model cache. Inference (`image` / `video`) never
downloads and fails cleanly when the model pack is absent.

Operations:
  download-model   Fetch + verify the selected colourisation model (consent required).
  check-model      Report whether the selected verified model pack is present.
  image            Colourise a single image.
  video            Colourise a video frame-by-frame (audio preserved).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg, find_ffprobe, probe_media
from ucx_assets import enforce_offline
import hw_decode


PACK_SLUG = "colorize"
MARKER_NAME = ".ucx-pack.json"
MODEL_LICENSE = "BSD-2-Clause (richzhang/colorization)"
DDCOLOR_TIER = "ddcolor-temporal"
DDCOLOR_LICENSE = "Apache-2.0 (DDColor)"
DDCOLOR_REPOSITORY = "wavespeed/image-colorizer"
DDCOLOR_REVISION = "1859b31ce0a54ba3afdf7d55bbe1a151c981b29f"
DDCOLOR_SOURCE_REVISION = "piddnad/DDColor"
DDCOLOR_WEIGHTS = "ddcolor-fp16.onnx"
DDCOLOR_WEIGHTS_SIZE = 113225654
DDCOLOR_WEIGHTS_SHA256 = "40ff5091157701a76f05f630b40ce1de7de8d15f1abfa8c403947e4e4ebab73c"
DDCOLOR_WEIGHTS_URL = (
    "https://huggingface.co/wavespeed/image-colorizer/resolve/"
    f"{DDCOLOR_REVISION}/{DDCOLOR_WEIGHTS}"
)
DDCOLOR_MARKER = ".ucx-ddcolor-pack.json"
DDCOLOR_DEFAULT_TEMPORAL_STRENGTH = 0.65

# Small definition files live on GitHub (stable). The 123 MB weights host is
# overridable via UCX_COLORIZE_MODEL_URL so a mirror or a pre-placed file can
# be used if the default source is unavailable.
_DEFAULT_WEIGHTS_URL = (
    "https://www.dropbox.com/s/dx0qvhhp5hbcx7z/"
    "colorization_release_v2.caffemodel?dl=1"
)
PROTOTXT = "colorization_deploy_v2.prototxt"
CLUSTERS = "pts_in_hull.npy"
WEIGHTS = "colorization_release_v2.caffemodel"

# (filename, url, size_bytes, sha256)
MODEL_ASSETS: list[tuple[str, str, int, str]] = [
    (PROTOTXT,
     "https://raw.githubusercontent.com/richzhang/colorization/caffe/"
     "colorization/models/colorization_deploy_v2.prototxt",
     9945, "d16418cef8df4ccd703a55ae0ef3960861d5010418f77c90d0a47689998a7169"),
    (CLUSTERS,
     "https://github.com/richzhang/colorization/raw/caffe/"
     "colorization/resources/pts_in_hull.npy",
     5088, "b5dec01315c34f43f1c8c089e84c45ae35d1838d8e77ed0e7ca930f79ffa450e"),
    (WEIGHTS,
     os.environ.get("UCX_COLORIZE_MODEL_URL", _DEFAULT_WEIGHTS_URL),
     128946764, "f5af1e602646328c792e1094f9876fe9cd4c09ac46fa886e5708a1abc89137b1"),
]
TOTAL_DOWNLOAD_BYTES = sum(item[2] for item in MODEL_ASSETS)


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def model_dir(tier: str = "classic") -> Path:
    base = os.environ.get("UCX_MODEL_DIR")
    suffix = Path(DDCOLOR_TIER) if tier == DDCOLOR_TIER else Path()
    if base:
        return Path(base) / PACK_SLUG / suffix
    return Path(__file__).resolve().parent / "_models" / suffix


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_ready(root: Path, assets: list[tuple[str, str, int, str]] = MODEL_ASSETS,
                marker_name: str = MARKER_NAME) -> bool:
    marker = root / marker_name
    if not marker.is_file():
        return False
    for name, _url, size, sha in assets:
        path = root / name
        if (not path.is_file()
                or path.stat().st_size != size
                or sha256_file(path) != sha):
            return False
    return True


def ddcolor_model_ready(root: Path) -> bool:
    return model_ready(
        root,
        [(DDCOLOR_WEIGHTS, DDCOLOR_WEIGHTS_URL, DDCOLOR_WEIGHTS_SIZE, DDCOLOR_WEIGHTS_SHA256)],
        DDCOLOR_MARKER,
    )


# ── model management ────────────────────────────────────────────────────────

def _tier_assets(tier: str) -> tuple[list[tuple[str, str, int, str]], str, str, int, str]:
    if tier == DDCOLOR_TIER:
        return (
            [(DDCOLOR_WEIGHTS, DDCOLOR_WEIGHTS_URL, DDCOLOR_WEIGHTS_SIZE, DDCOLOR_WEIGHTS_SHA256)],
            DDCOLOR_MARKER,
            DDCOLOR_LICENSE,
            DDCOLOR_WEIGHTS_SIZE,
            "DDColor temporal",
        )
    return MODEL_ASSETS, MARKER_NAME, MODEL_LICENSE, TOTAL_DOWNLOAD_BYTES, "classic CPU"


def tier_disabled(tier: str) -> bool:
    return tier == DDCOLOR_TIER and os.environ.get("UCX_DISABLE_DDCOLOR", "").lower() in {
        "1", "true", "yes", "on",
    }


def op_check_model(args: argparse.Namespace) -> int:
    tier = getattr(args, "tier", "classic")
    assets, marker, license_name, download_bytes, display = _tier_assets(tier)
    root = model_dir(tier)
    ready = model_ready(root, assets, marker)
    emit("model_status", ready=ready, path=str(root), tier=tier,
         license=license_name, download_bytes=download_bytes,
         display=display, disabled=tier_disabled(tier))
    emit("complete", output=str(root), size_bytes=0, count=1 if ready else 0)
    return 0


def _download(url: str, destination: Path, expected_sha: str, expected_size: int,
              stage: str) -> bool:
    tmp = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    downloaded = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "UCX-colorize"})
        with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as out:
            total = expected_size or int(response.headers.get("Content-Length", 0) or 0)
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if total:
                    emit("progress", percent=round(downloaded / total * 100, 1),
                         stage=stage, eta_seconds=None)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        tmp.unlink(missing_ok=True)
        emit("log", level="error", message=f"{stage}: download failed ({exc}).")
        return False

    actual = digest.hexdigest()
    if actual != expected_sha:
        tmp.unlink(missing_ok=True)
        emit("log", level="error",
             message=f"{stage}: SHA-256 mismatch (expected {expected_sha[:12]}, got {actual[:12]}).")
        return False
    tmp.replace(destination)
    return True


def op_download_model(args: argparse.Namespace) -> int:
    tier = getattr(args, "tier", "classic")
    assets, marker_name, license_name, download_bytes, display = _tier_assets(tier)
    if not args.accept_license:
        return fail("license_not_accepted",
                    f"The {display} model is licensed {license_name}. "
                    "Re-run with --accept-license to download it.")
    root = model_dir(tier)
    root.mkdir(parents=True, exist_ok=True)

    if model_ready(root, assets, marker_name):
        emit("log", level="info", message="Model already present and verified.")
        emit("complete", output=str(root), size_bytes=0, count=len(assets))
        return 0

    for name, url, size, sha in assets:
        dest = root / name
        if dest.is_file() and dest.stat().st_size == size and sha256_file(dest) == sha:
            continue
        emit("log", level="info", message=f"Downloading {name} ({size // 1024} KB)...")
        if not _download(url, dest, sha, size, f"download {name}"):
            return fail("download_failed",
                        f"Could not download {name}. Set UCX_COLORIZE_MODEL_URL to a "
                        "mirror, or place the file manually in the model directory.")

    marker = root / marker_name
    marker.write_text(json.dumps({
        "pack": PACK_SLUG,
        "tier": tier,
        "license": license_name,
        "repository": DDCOLOR_REPOSITORY if tier == DDCOLOR_TIER else "richzhang/colorization",
        "revision": DDCOLOR_REVISION if tier == DDCOLOR_TIER else "caffe",
        "assets": [
            {"name": name, "sizeBytes": size, "sha256": sha}
            for name, _url, size, sha in assets
        ],
    }, indent=2), encoding="utf-8")
    emit("complete", output=str(root), size_bytes=download_bytes, count=len(assets))
    return 0


# ── inference ──────────────────────────────────────────────────────────────

def _load_net(root: Path):
    import cv2  # noqa: PLC0415 — heavy import, only for inference
    import numpy as np  # noqa: PLC0415

    net = cv2.dnn.readNetFromCaffe(str(root / PROTOTXT), str(root / WEIGHTS))
    pts = np.load(str(root / CLUSTERS)).transpose().reshape(2, 313, 1, 1).astype(np.float32)
    net.getLayer(net.getLayerId("class8_ab")).blobs = [pts]
    net.getLayer(net.getLayerId("conv8_313_rh")).blobs = [np.full([1, 313], 2.606, np.float32)]
    return net


def _compose_lab(l_channel, ab, cv2, np):
    lab = np.concatenate((l_channel[:, :, None], ab), axis=2)
    bgr = cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_LAB2BGR)
    return np.clip(bgr * 255.0, 0, 255).round().astype(np.uint8)


def temporal_blend_ab(current_ab, previous_ab, strength: float, scene_delta: float,
                      scene_cut_threshold: float = 0.25):
    """Blend aligned chroma while resetting on a scene cut.

    This small, deterministic policy is also used by the video path's
    optical-flow alignment. It keeps scene changes from carrying stale colour
    into the next shot and provides a measurable temporal-stability knob.
    """
    import numpy as np  # noqa: PLC0415

    if previous_ab is None or scene_delta >= scene_cut_threshold:
        return current_ab.copy()
    strength = max(0.0, min(float(strength), 0.85))
    confidence = 1.0 - min(max(float(scene_delta), 0.0) / scene_cut_threshold, 1.0)
    alpha = strength * confidence
    return current_ab * (1.0 - alpha) + previous_ab * alpha


def chroma_flicker_score(chroma_frames) -> float:
    """Return mean adjacent-frame chroma change for regression fixtures."""
    import numpy as np  # noqa: PLC0415

    frames = [np.asarray(frame, dtype=np.float32) for frame in chroma_frames]
    if len(frames) < 2:
        return 0.0
    return float(np.mean([
        np.mean(np.abs(current - previous))
        for previous, current in zip(frames, frames[1:])
    ]))


class DDColorizer:
    """Local DDColor ONNX inference with optional temporal chroma propagation."""

    input_size = 256

    def __init__(self, root: Path):
        import onnxruntime as ort  # noqa: PLC0415

        options = ort.SessionOptions()
        # The pinned fp16 artifact contains a graph pattern that older ORT
        # builds incorrectly fuse. Disabling graph rewrites is deterministic
        # and still allows the CPU/CUDA execution provider to optimize kernels.
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        available = ort.get_available_providers()
        providers = [
            provider for provider in ("CUDAExecutionProvider", "CPUExecutionProvider")
            if provider in available
        ]
        if not providers:
            raise RuntimeError("ONNX Runtime has no CPU or CUDA execution provider")
        self.session = ort.InferenceSession(
            str(root / DDCOLOR_WEIGHTS), sess_options=options, providers=providers)
        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if len(inputs) != 1 or len(outputs) != 1:
            raise RuntimeError("DDColor model contract must have one input and one output")
        self.input_name = inputs[0].name
        self.output_name = outputs[0].name

    def predict(self, frame):
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        height, width = frame.shape[:2]
        image = frame.astype(np.float32) / 255.0
        original_l = cv2.cvtColor(image, cv2.COLOR_BGR2Lab)[:, :, 0]
        resized = cv2.resize(image, (self.input_size, self.input_size))
        resized_l = cv2.cvtColor(resized, cv2.COLOR_BGR2Lab)[:, :, :1]
        gray_lab = np.concatenate((resized_l, np.zeros_like(resized_l), np.zeros_like(resized_l)), axis=-1)
        gray_rgb = cv2.cvtColor(gray_lab, cv2.COLOR_LAB2RGB)
        input_tensor = np.ascontiguousarray(gray_rgb.transpose((2, 0, 1))[None], dtype=np.float32)
        output_ab = self.session.run(
            [self.output_name], {self.input_name: input_tensor})[0][0]
        if output_ab.ndim != 3 or output_ab.shape[0] != 2:
            raise RuntimeError(f"Unexpected DDColor output shape: {output_ab.shape}")
        ab = cv2.resize(
            output_ab.transpose((1, 2, 0)), (width, height), interpolation=cv2.INTER_LINEAR)
        return _compose_lab(original_l, ab, cv2, np), original_l, ab

    def colorize_video_frame(self, frame, strength: float, previous_gray=None, previous_ab=None):
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        output, gray, current_ab = self.predict(frame)
        if previous_gray is None or previous_ab is None or strength <= 0:
            return output, gray, current_ab

        current_gray = gray.astype(np.float32)
        old_gray = previous_gray.astype(np.float32)
        scene_delta = float(np.mean(np.abs(current_gray - old_gray)) / 100.0)
        if scene_delta >= 0.25:
            return output, gray, current_ab

        flow = cv2.calcOpticalFlowFarneback(
            current_gray, old_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        height, width = current_gray.shape
        grid_x, grid_y = np.meshgrid(
            np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
        previous_x = grid_x + flow[:, :, 0]
        previous_y = grid_y + flow[:, :, 1]
        warped_previous = cv2.remap(
            previous_ab.astype(np.float32), previous_x, previous_y,
            cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        blended_ab = temporal_blend_ab(current_ab, warped_previous, strength, scene_delta)
        return _compose_lab(gray, blended_ab, cv2, np), gray, blended_ab


def _colorize_bgr(net, frame):
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    h, w = frame.shape[:2]
    scaled = (frame / 255.0).astype(np.float32)
    lab = cv2.cvtColor(scaled, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0]
    L_rs = cv2.resize(L, (224, 224)) - 50
    net.setInput(cv2.dnn.blobFromImage(L_rs))
    ab = net.forward()[0].transpose(1, 2, 0)
    ab = cv2.resize(ab, (w, h))
    out = np.concatenate([L[:, :, np.newaxis], ab], axis=2)
    bgr = np.clip(cv2.cvtColor(out, cv2.COLOR_LAB2BGR), 0, 1)
    return (bgr * 255).astype(np.uint8)


def op_image(args: argparse.Namespace) -> int:
    tier = getattr(args, "tier", "classic")
    root = model_dir(tier)
    ready = ddcolor_model_ready(root) if tier == DDCOLOR_TIER else model_ready(root)
    if tier_disabled(tier):
        return fail("tier_disabled", "The DDColor temporal tier is disabled by UCX_DISABLE_DDCOLOR.")
    if not ready:
        return fail("model_missing",
                    f"{tier} colourisation model not found. Run `download-model --tier {tier} --accept-license` first.")
    try:
        import cv2  # noqa: PLC0415
    except ImportError:
        return fail("missing_opencv", "OpenCV (cv2) is not available in this build.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    frame = cv2.imread(str(src))
    if frame is None:
        return fail("bad_image", f"Could not read image: {src.name}")

    emit("progress", percent=0, stage="colourising", eta_seconds=None)
    enforce_offline()
    if tier == DDCOLOR_TIER:
        result, _gray, _ab = DDColorizer(root).predict(frame)
    else:
        result = _colorize_bgr(_load_net(root), frame)
    if not cv2.imwrite(str(out_path), result):
        return fail("write_failed", f"Could not write output: {out_path}")

    emit("progress", percent=100, stage="colourising", eta_seconds=0)
    emit("colorized", input=str(src), output=str(out_path),
         size_bytes=out_path.stat().st_size)
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_video(args: argparse.Namespace) -> int:
    tier = getattr(args, "tier", "classic")
    root = model_dir(tier)
    ready = ddcolor_model_ready(root) if tier == DDCOLOR_TIER else model_ready(root)
    if tier_disabled(tier):
        return fail("tier_disabled", "The DDColor temporal tier is disabled by UCX_DISABLE_DDCOLOR.")
    if not ready:
        return fail("model_missing",
                    f"{tier} colourisation model not found. Run `download-model --tier {tier} --accept-license` first.")
    ffmpeg = find_ffmpeg(Path(__file__).resolve().parent)
    ffprobe = find_ffprobe(Path(__file__).resolve().parent)
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found.")
    try:
        import cv2  # noqa: PLC0415
    except ImportError:
        return fail("missing_opencv", "OpenCV (cv2) is not available in this build.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe_media(ffprobe, src)
    stream = next((s for s in (info or {}).get("streams", [])
                   if s.get("codec_type") == "video"), None)
    if stream is None:
        return fail("no_video", "Input has no video stream.")
    fps = 25.0
    try:
        num, den = (stream.get("r_frame_rate") or "25/1").split("/")
        fps = float(num) / float(den) if float(den) else 25.0
    except (ValueError, ZeroDivisionError):
        fps = 25.0
    total_frames = 0
    try:
        total_frames = int(stream.get("nb_frames") or 0)
    except (TypeError, ValueError):
        total_frames = 0
    has_audio = any(s.get("codec_type") == "audio" for s in (info or {}).get("streams", []))

    enforce_offline()
    ddcolorizer = DDColorizer(root) if tier == DDCOLOR_TIER else None
    net = None if ddcolorizer is not None else _load_net(root)
    capture = cv2.VideoCapture(str(src))
    if not capture.isOpened():
        return fail("decode_failed", "Could not open the video for decoding.")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width <= 0 or height <= 0:
        capture.release()
        return fail("decode_failed", "Could not determine the video frame size.")
    capture.release()

    # Pipe colourised BGR frames straight into a single h264 encode (with the
    # original audio remuxed) so there is no lossy intermediate re-encode.
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{width}x{height}", "-r", f"{fps:.6f}", "-i", "pipe:0"]
    if has_audio:
        cmd += ["-i", str(src), "-map", "0:v:0", "-map", "1:a:0?",
                "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out_path)]

    process = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert process.stdin is not None
    allow_hw = bool(getattr(args, "hw_decode", False))
    emit(
        "log",
        level="info",
        message=(
            f"Frame decode backend: {hw_decode.frames_backend(allow_hw)}"
            + ("" if allow_hw else " (hardware decode not requested)")
        ),
    )
    index = 0
    previous_gray = None
    previous_ab = None
    temporal_strength = 0.0 if getattr(args, "no_temporal", False) else args.temporal_strength
    try:
        for _decoded_index, frame in hw_decode.frames_or_opencv(
            src, cv2, allow_hw=allow_hw
        ):
            if ddcolorizer is not None:
                colorized, previous_gray, previous_ab = ddcolorizer.colorize_video_frame(
                    frame, temporal_strength, previous_gray, previous_ab)
            else:
                colorized = _colorize_bgr(net, frame)
            process.stdin.write(colorized.tobytes())
            index += 1
            if total_frames:
                emit("progress", percent=round(index / total_frames * 100, 1),
                     stage="colourising frames", eta_seconds=None)
            elif index % 15 == 0:
                emit("progress", percent=0, stage=f"colourising frame {index}", eta_seconds=None)
    except BrokenPipeError:
        pass
    finally:
        with contextlib.suppress(Exception):
            process.stdin.close()
        process.wait()

    if index == 0:
        out_path.unlink(missing_ok=True)
        return fail("no_frames", "No frames were decoded from the input.")
    if process.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        out_path.unlink(missing_ok=True)
        return fail("encode_failed",
                    f"Could not encode the colourised video (exit {process.returncode}).")

    emit("colorized", input=str(src), output=str(out_path),
         frames=index, size_bytes=out_path.stat().st_size)
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=index)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="colorize-sidecar",
        description="Offline B&W -> colour with a portable CPU tier or DDColor temporal tier.")
    sub = p.add_subparsers(dest="op", required=True)

    dm = sub.add_parser("download-model", help="Download the colourisation model (consent required)")
    dm.add_argument("--tier", choices=("classic", DDCOLOR_TIER), default="classic")
    dm.add_argument("--accept-license", action="store_true", dest="accept_license",
                    help="Accept the selected model licence.")

    cm = sub.add_parser("check-model", help="Report whether the verified model is present")
    cm.add_argument("--tier", choices=("classic", DDCOLOR_TIER), default="classic")

    im = sub.add_parser("image", help="Colourise a single image")
    im.add_argument("--tier", choices=("classic", DDCOLOR_TIER), default="classic")
    im.add_argument("--input", required=True)
    im.add_argument("--output", required=True)

    vid = sub.add_parser("video", help="Colourise a video frame-by-frame")
    vid.add_argument("--tier", choices=("classic", DDCOLOR_TIER), default="classic")
    vid.add_argument("--input", required=True)
    vid.add_argument("--output", required=True)
    vid.add_argument(
        "--temporal-strength", type=float, default=DDCOLOR_DEFAULT_TEMPORAL_STRENGTH,
        help="DDColor chroma propagation strength (0 disables temporal blending).")
    vid.add_argument(
        "--no-temporal", action="store_true",
        help="Disable DDColor optical-flow propagation for this run (kill switch).")
    vid.add_argument(
        "--hw-decode",
        action="store_true",
        help="Opt in to NVDEC frame decoding when CUDA/PyAV are available.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "download-model":
            return op_download_model(args)
        if args.op == "check-model":
            return op_check_model(args)
        if args.op == "image":
            return op_image(args)
        if args.op == "video":
            return op_video(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:  # noqa: BLE001 — surface any failure as NDJSON
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
