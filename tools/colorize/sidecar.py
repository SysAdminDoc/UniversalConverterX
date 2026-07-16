"""Offline B&W -> colour sidecar (CPU, OpenCV DNN).

Colourises grayscale photos and video using Richard Zhang's Colorful Image
Colorization model (BSD-2-Clause) through OpenCV's DNN module. Runs entirely
on the CPU -- no GPU or PyTorch required -- so it works on any machine.

The model weights are NOT bundled. `download-model` is the only networked
operation and requires explicit `--accept-license`; it fetches SHA-256 pinned
files into the shared model cache. Inference (`image` / `video`) never
downloads and fails cleanly when the model pack is absent.

Operations:
  download-model   Fetch + verify the colourisation model (consent required).
  check-model      Report whether the verified model pack is present.
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


PACK_SLUG = "colorize"
MARKER_NAME = ".ucx-pack.json"
MODEL_LICENSE = "BSD-2-Clause (richzhang/colorization)"

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


def model_dir() -> Path:
    base = os.environ.get("UCX_MODEL_DIR")
    if base:
        return Path(base) / PACK_SLUG
    return Path(__file__).resolve().parent / "_models"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_ready(root: Path) -> bool:
    marker = root / MARKER_NAME
    if not marker.is_file():
        return False
    for name, _url, size, _sha in MODEL_ASSETS:
        path = root / name
        if not path.is_file() or path.stat().st_size != size:
            return False
    return True


# ── model management ────────────────────────────────────────────────────────

def op_check_model(_: argparse.Namespace) -> int:
    root = model_dir()
    ready = model_ready(root)
    emit("model_status", ready=ready, path=str(root),
         license=MODEL_LICENSE,
         download_bytes=TOTAL_DOWNLOAD_BYTES)
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
    if not args.accept_license:
        return fail("license_not_accepted",
                    f"The colourisation model is licensed {MODEL_LICENSE}. "
                    "Re-run with --accept-license to download it.")
    root = model_dir()
    root.mkdir(parents=True, exist_ok=True)

    if model_ready(root):
        emit("log", level="info", message="Model already present and verified.")
        emit("complete", output=str(root), size_bytes=0, count=len(MODEL_ASSETS))
        return 0

    for name, url, size, sha in MODEL_ASSETS:
        dest = root / name
        if dest.is_file() and dest.stat().st_size == size and sha256_file(dest) == sha:
            continue
        emit("log", level="info", message=f"Downloading {name} ({size // 1024} KB)...")
        if not _download(url, dest, sha, size, f"download {name}"):
            return fail("download_failed",
                        f"Could not download {name}. Set UCX_COLORIZE_MODEL_URL to a "
                        "mirror, or place the file manually in the model directory.")

    marker = root / MARKER_NAME
    marker.write_text(json.dumps({
        "pack": PACK_SLUG,
        "license": MODEL_LICENSE,
        "assets": [name for name, *_ in MODEL_ASSETS],
    }, indent=2), encoding="utf-8")
    emit("complete", output=str(root), size_bytes=TOTAL_DOWNLOAD_BYTES, count=len(MODEL_ASSETS))
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
    root = model_dir()
    if not model_ready(root):
        return fail("model_missing",
                    "Colourisation model not found. Run `download-model --accept-license` first.")
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
    net = _load_net(root)
    result = _colorize_bgr(net, frame)
    if not cv2.imwrite(str(out_path), result):
        return fail("write_failed", f"Could not write output: {out_path}")

    emit("progress", percent=100, stage="colourising", eta_seconds=0)
    emit("colorized", input=str(src), output=str(out_path),
         size_bytes=out_path.stat().st_size)
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_video(args: argparse.Namespace) -> int:
    root = model_dir()
    if not model_ready(root):
        return fail("model_missing",
                    "Colourisation model not found. Run `download-model --accept-license` first.")
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

    net = _load_net(root)
    capture = cv2.VideoCapture(str(src))
    if not capture.isOpened():
        return fail("decode_failed", "Could not open the video for decoding.")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width <= 0 or height <= 0:
        capture.release()
        return fail("decode_failed", "Could not determine the video frame size.")

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
    index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            process.stdin.write(_colorize_bgr(net, frame).tobytes())
            index += 1
            if total_frames:
                emit("progress", percent=round(index / total_frames * 100, 1),
                     stage="colourising frames", eta_seconds=None)
            elif index % 15 == 0:
                emit("progress", percent=0, stage=f"colourising frame {index}", eta_seconds=None)
    except BrokenPipeError:
        pass
    finally:
        capture.release()
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
        description="Offline B&W -> colour via OpenCV DNN (CPU).")
    sub = p.add_subparsers(dest="op", required=True)

    dm = sub.add_parser("download-model", help="Download the colourisation model (consent required)")
    dm.add_argument("--accept-license", action="store_true", dest="accept_license",
                    help=f"Accept the model licence ({MODEL_LICENSE}).")

    sub.add_parser("check-model", help="Report whether the verified model is present")

    im = sub.add_parser("image", help="Colourise a single image")
    im.add_argument("--input", required=True)
    im.add_argument("--output", required=True)

    vid = sub.add_parser("video", help="Colourise a video frame-by-frame")
    vid.add_argument("--input", required=True)
    vid.add_argument("--output", required=True)

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
