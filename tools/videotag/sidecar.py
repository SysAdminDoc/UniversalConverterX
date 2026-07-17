"""Offline sampled image/video object tagging with a pinned EfficientDet model.

The downloadable model is MediaPipe EfficientDet-Lite0 int8 v1. Inference uses
the standalone LiteRT runtime rather than MediaPipe Tasks because the latter
documents SDK utilization metrics. LiteRT's portable metrics implementation is
a no-op, and the ``tag`` operation contains no network path.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from ucx_assets import enforce_offline


MODEL_NAME = "MediaPipe EfficientDet-Lite0 int8"
MODEL_FILE = "efficientdet_lite0-int8-v1.tflite"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/object_detector/"
    "efficientdet_lite0/int8/1/efficientdet_lite0.tflite"
)
MODEL_SIZE = 4_602_795
MODEL_SHA256 = "0720bf247bd76e6594ea28fa9c6f7c5242be774818997dbbeffc4da460c723bb"
MODEL_LICENSE = "Apache-2.0"
MODEL_SOURCE = "google-ai-edge/mediapipe"
IMAGE_SIZE = 320
ANCHOR_COUNT = 19_206
MAX_DETECTIONS = 25
MAX_SAMPLED_FRAMES = 10_000
IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_root(args: argparse.Namespace) -> Path:
    explicit = getattr(args, "model_dir", None)
    if explicit:
        return Path(explicit).expanduser().resolve()
    shared = os.environ.get("UCX_MODEL_DIR")
    if shared:
        return (Path(shared) / "videotag").resolve()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return (Path(local) / "UniversalConverterX" / "models" / "videotag").resolve()
    return (Path(__file__).resolve().parent / "_models").resolve()


def model_path(args: argparse.Namespace) -> Path:
    return model_root(args) / MODEL_FILE


def model_ready(path: Path) -> bool:
    return path.is_file() and path.stat().st_size == MODEL_SIZE and sha256_file(path) == MODEL_SHA256


def _download_model(destination: Path) -> bool:
    staged = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    staged.unlink(missing_ok=True)
    digest = hashlib.sha256()
    downloaded = 0
    try:
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "UniversalConverterX-videotag"})
        with urllib.request.urlopen(request, timeout=120) as response, staged.open("xb") as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MODEL_SIZE:
                    raise ValueError("download exceeded the pinned size")
                handle.write(chunk)
                digest.update(chunk)
                emit("progress", percent=round(downloaded / MODEL_SIZE * 100, 1),
                     stage="download-model", eta_seconds=None)
        if downloaded != MODEL_SIZE or digest.hexdigest() != MODEL_SHA256:
            raise ValueError("download did not match the pinned size and SHA-256")
        os.replace(staged, destination)
        return True
    except (OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
        staged.unlink(missing_ok=True)
        emit("log", level="error", message=f"Model download failed: {exc}")
        return False


def op_download_model(args: argparse.Namespace) -> int:
    if not args.accept_license:
        return fail(
            "license_not_accepted",
            f"{MODEL_NAME} is licensed {MODEL_LICENSE}; re-run with --accept-license.",
        )
    destination = model_path(args)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if model_ready(destination):
        emit("log", level="info", message="Pinned model is already installed and verified.")
    elif not _download_model(destination):
        return fail("download_failed", "The pinned model could not be downloaded and verified.")
    emit("complete", output=str(destination), size_bytes=MODEL_SIZE, sha256=MODEL_SHA256)
    return 0


def _runtime_versions() -> tuple[dict[str, str], str | None]:
    versions: dict[str, str] = {}
    try:
        from ai_edge_litert.interpreter import Interpreter  # noqa: F401
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        versions = {
            "ai-edge-litert": importlib.metadata.version("ai-edge-litert"),
            "opencv-python-headless": importlib.metadata.version("opencv-python-headless"),
            "numpy": importlib.metadata.version("numpy"),
        }
        return versions, None
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        return versions, str(exc)


def op_probe(args: argparse.Namespace) -> int:
    versions, runtime_error = _runtime_versions()
    path = model_path(args)
    ready = model_ready(path)
    available = runtime_error is None and ready
    emit(
        "backend", available=available, runtime_available=runtime_error is None,
        runtime_versions=versions, runtime_error=runtime_error, model_ready=ready,
        model=str(path), model_sha256=MODEL_SHA256, telemetry=False,
        inference_network=False, license=MODEL_LICENSE,
    )
    emit("complete", output=str(path), size_bytes=path.stat().st_size if ready else 0,
         available=available)
    return 0 if available else 1


def generate_anchors(image_size: int = IMAGE_SIZE):
    import numpy as np

    feature_sizes = [image_size]
    for _ in range(7):
        feature_sizes.append((feature_sizes[-1] - 1) // 2 + 1)
    boxes: list[tuple[float, float, float, float]] = []
    for level in range(3, 8):
        size = feature_sizes[level]
        stride = image_size / size
        shapes: list[tuple[float, float]] = []
        for scale_index in range(3):
            base = 3.0 * stride * 2 ** (scale_index / 3)
            for aspect in (1.0, 2.0, 0.5):
                shapes.append((base / math.sqrt(aspect), base * math.sqrt(aspect)))
        for y in (np.arange(size) + 0.5) * stride:
            for x in (np.arange(size) + 0.5) * stride:
                for height, width in shapes:
                    boxes.append((y - height / 2, x - width / 2, y + height / 2, x + width / 2))
    result = np.asarray(boxes, dtype=np.float32)
    if result.shape != (ANCHOR_COUNT, 4):
        raise RuntimeError(f"Unexpected anchor shape: {result.shape}")
    return result


def decode_boxes(raw, anchors):
    import numpy as np

    anchor_y = (anchors[:, 0] + anchors[:, 2]) / 2
    anchor_x = (anchors[:, 1] + anchors[:, 3]) / 2
    anchor_h = anchors[:, 2] - anchors[:, 0]
    anchor_w = anchors[:, 3] - anchors[:, 1]
    ty, tx, th, tw = raw.T
    height = np.exp(np.clip(th, -20, 20)) * anchor_h
    width = np.exp(np.clip(tw, -20, 20)) * anchor_w
    center_y = ty * anchor_h + anchor_y
    center_x = tx * anchor_w + anchor_x
    return np.stack(
        (center_y - height / 2, center_x - width / 2,
         center_y + height / 2, center_x + width / 2), axis=1,
    )


def non_max_suppression(boxes, scores, threshold: float = 0.5, limit: int = MAX_DETECTIONS) -> list[int]:
    import numpy as np

    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size and len(keep) < limit:
        current = int(order[0])
        keep.append(current)
        if order.size == 1:
            break
        rest = order[1:]
        y1 = np.maximum(boxes[current, 0], boxes[rest, 0])
        x1 = np.maximum(boxes[current, 1], boxes[rest, 1])
        y2 = np.minimum(boxes[current, 2], boxes[rest, 2])
        x2 = np.minimum(boxes[current, 3], boxes[rest, 3])
        intersection = np.maximum(0, y2 - y1) * np.maximum(0, x2 - x1)
        current_area = max(0, boxes[current, 2] - boxes[current, 0]) * max(0, boxes[current, 3] - boxes[current, 1])
        rest_area = np.maximum(0, boxes[rest, 2] - boxes[rest, 0]) * np.maximum(0, boxes[rest, 3] - boxes[rest, 1])
        union = current_area + rest_area - intersection
        iou = np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)
        order = rest[iou <= threshold]
    return keep


def _labels(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            labels = archive.read("labels.txt").decode("utf-8").splitlines()
    except (KeyError, OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"Model labels are unavailable: {exc}") from exc
    if len(labels) < 80:
        raise RuntimeError("Model label table is incomplete.")
    return labels


class Detector:
    def __init__(self, path: Path, threads: int) -> None:
        import numpy as np
        from ai_edge_litert.interpreter import Interpreter

        self.np = np
        self.labels = _labels(path)
        self.anchors = generate_anchors()
        self.interpreter = Interpreter(model_path=str(path), num_threads=threads)
        self.interpreter.allocate_tensors()
        self.input = self.interpreter.get_input_details()[0]
        outputs = self.interpreter.get_output_details()
        self.box_output = next((item for item in outputs if tuple(item["shape"])[-1] == 4), None)
        self.score_output = next((item for item in outputs if tuple(item["shape"])[-1] != 4), None)
        if self.box_output is None or self.score_output is None:
            raise RuntimeError("Model output tensors do not match EfficientDet-Lite0.")

    def detect(self, bgr, threshold: float) -> list[dict[str, Any]]:
        import cv2

        height, width = bgr.shape[:2]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv2.INTER_LINEAR)
        tensor = resized[None, ...].astype(self.input["dtype"])
        self.interpreter.set_tensor(self.input["index"], tensor)
        self.interpreter.invoke()
        raw_boxes = self.interpreter.get_tensor(self.box_output["index"])[0]
        scores = self.interpreter.get_tensor(self.score_output["index"])[0]
        classes = scores.argmax(axis=1)
        confidence = scores[self.np.arange(scores.shape[0]), classes]
        candidates = self.np.flatnonzero(confidence >= threshold)
        if not candidates.size:
            return []
        decoded = decode_boxes(raw_boxes, self.anchors)
        detections: list[dict[str, Any]] = []
        for class_id in self.np.unique(classes[candidates]):
            label = self.labels[int(class_id)] if int(class_id) < len(self.labels) else ""
            if not label or label == "???":
                continue
            selected = candidates[classes[candidates] == class_id]
            for local_index in non_max_suppression(decoded[selected], confidence[selected]):
                anchor_index = int(selected[local_index])
                y1, x1, y2, x2 = decoded[anchor_index]
                left = max(0.0, min(float(width), float(x1) * width / IMAGE_SIZE))
                top = max(0.0, min(float(height), float(y1) * height / IMAGE_SIZE))
                right = max(left, min(float(width), float(x2) * width / IMAGE_SIZE))
                bottom = max(top, min(float(height), float(y2) * height / IMAGE_SIZE))
                detections.append({
                    "label": label,
                    "score": round(float(confidence[anchor_index]), 6),
                    "box": {
                        "x": round(left, 2), "y": round(top, 2),
                        "width": round(right - left, 2), "height": round(bottom - top, 2),
                    },
                })
        detections.sort(key=lambda item: (-float(item["score"]), str(item["label"])))
        return detections[:MAX_DETECTIONS]


def _sample_frames(source: Path, interval: float, max_frames: int):
    import cv2

    if source.suffix.lower() in IMAGE_EXTENSIONS:
        frame = cv2.imread(str(source), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("OpenCV could not decode the image.")
        yield 0.0, frame
        return
    capture = cv2.VideoCapture(str(source))
    try:
        if not capture.isOpened():
            raise RuntimeError("OpenCV could not open the video.")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0 or frame_count <= 0:
            raise RuntimeError("Video duration is unavailable.")
        duration = max(0.0, (frame_count - 1) / fps)
        timestamp = 0.0
        count = 0
        while count < max_frames and timestamp <= duration + 1e-6:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if ok and frame is not None:
                yield timestamp, frame
            timestamp += interval
            count += 1
    finally:
        capture.release()


def aggregate_tags(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aggregate: dict[str, dict[str, Any]] = {}
    for frame in frames:
        timestamp = float(frame["timestampSeconds"])
        frame_labels: set[str] = set()
        for detection in frame["detections"]:
            label = str(detection["label"])
            item = aggregate.setdefault(label, {
                "label": label, "maxScore": 0.0, "detections": 0,
                "frames": 0, "firstSeenSeconds": timestamp, "lastSeenSeconds": timestamp,
            })
            item["maxScore"] = max(float(item["maxScore"]), float(detection["score"]))
            item["detections"] = int(item["detections"]) + 1
            item["firstSeenSeconds"] = min(float(item["firstSeenSeconds"]), timestamp)
            item["lastSeenSeconds"] = max(float(item["lastSeenSeconds"]), timestamp)
            frame_labels.add(label)
        for label in frame_labels:
            aggregate[label]["frames"] = int(aggregate[label]["frames"]) + 1
    result = list(aggregate.values())
    for item in result:
        item["maxScore"] = round(float(item["maxScore"]), 6)
        item["firstSeenSeconds"] = round(float(item["firstSeenSeconds"]), 3)
        item["lastSeenSeconds"] = round(float(item["lastSeenSeconds"]), 3)
    result.sort(key=lambda item: (-int(item["frames"]), -float(item["maxScore"]), str(item["label"])))
    return result


def _write_atomic(output: Path, payload: dict[str, Any], overwrite: bool) -> None:
    if output.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_name(f".{output.name}.{os.getpid()}.ucx-videotag.tmp")
    staged.unlink(missing_ok=True)
    try:
        staged.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(staged, output)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def op_tag(args: argparse.Namespace) -> int:
    source = Path(args.input).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not source.is_file():
        return fail("missing_input", f"Input not found: {source}")
    if output.suffix.lower() != ".json":
        return fail("invalid_output", "Output must end with .json.")
    if output.exists() and not args.overwrite:
        return fail("output_exists", f"Output already exists: {output}")
    path = model_path(args)
    if not model_ready(path):
        return fail("missing_model", f"Pinned model is absent or invalid: {path}")
    versions, runtime_error = _runtime_versions()
    if runtime_error:
        return fail("missing_runtime", f"LiteRT runtime is unavailable: {runtime_error}")
    try:
        enforce_offline()
        detector = Detector(path, args.threads)
        frames: list[dict[str, Any]] = []
        for index, (timestamp, frame) in enumerate(
                _sample_frames(source, args.interval_seconds, args.max_frames)):
            height, width = frame.shape[:2]
            frames.append({
                "timestampSeconds": round(timestamp, 3),
                "width": int(width), "height": int(height),
                "detections": detector.detect(frame, args.threshold),
            })
            emit("progress", percent=None, stage="tag", current=index + 1,
                 total=None, eta_seconds=None)
        if not frames:
            return fail("decode_failed", "No frames could be sampled from the input.")
        payload: dict[str, Any] = {
            "schemaVersion": 1,
            "source": str(source),
            "engine": "videotag",
            "offline": True,
            "telemetry": False,
            "model": {
                "name": MODEL_NAME, "source": MODEL_SOURCE, "license": MODEL_LICENSE,
                "sha256": MODEL_SHA256, "sizeBytes": MODEL_SIZE,
            },
            "runtime": versions,
            "sampleIntervalSeconds": args.interval_seconds,
            "threshold": args.threshold,
            "sampledFrames": len(frames),
            "frames": frames,
            "summary": aggregate_tags(frames),
        }
        _write_atomic(output, payload, args.overwrite)
    except (OSError, RuntimeError, ValueError) as exc:
        return fail("tag_failed", str(exc))
    emit("complete", output=str(output), size_bytes=output.stat().st_size,
         sampled_frames=len(frames), tags=len(payload["summary"]))
    return 0


def _bounded_float(minimum: float, maximum: float):
    def parse(value: str) -> float:
        result = float(value)
        if not minimum <= result <= maximum:
            raise argparse.ArgumentTypeError(f"must be between {minimum} and {maximum}")
        return result
    return parse


def _bounded_int(minimum: int, maximum: int):
    def parse(value: str) -> int:
        result = int(value)
        if not minimum <= result <= maximum:
            raise argparse.ArgumentTypeError(f"must be between {minimum} and {maximum}")
        return result
    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    probe = commands.add_parser("probe", help="Report runtime and pinned model readiness.")
    probe.add_argument("--model-dir")
    probe.set_defaults(func=op_probe)
    download = commands.add_parser("download-model", help="Explicitly download the pinned model.")
    download.add_argument("--accept-license", action="store_true")
    download.add_argument("--model-dir")
    download.set_defaults(func=op_download_model)
    tag = commands.add_parser("tag", help="Sample a local image/video and write object tags as JSON.")
    tag.add_argument("--input", required=True)
    tag.add_argument("--output", required=True)
    tag.add_argument("--model-dir")
    tag.add_argument("--interval-seconds", type=_bounded_float(0.1, 3600), default=2.0)
    tag.add_argument("--threshold", type=_bounded_float(0.05, 1.0), default=0.6)
    tag.add_argument("--max-frames", type=_bounded_int(1, MAX_SAMPLED_FRAMES), default=300)
    tag.add_argument("--threads", type=_bounded_int(1, 16), default=min(4, os.cpu_count() or 1))
    tag.add_argument("--overwrite", action="store_true")
    tag.set_defaults(func=op_tag)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
