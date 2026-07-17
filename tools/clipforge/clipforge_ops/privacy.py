from __future__ import annotations

import argparse
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .runtime import emit, fail, find_ffmpeg, find_ffprobe, probe, run_ffmpeg



def _expand_face_box(
    box: tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
    padding_percent: int,
) -> tuple[int, int, int, int]:
    x, y, width, height = (int(value) for value in box)
    padding_x = round(width * padding_percent / 100)
    padding_y = round(height * padding_percent / 100)
    left = max(0, x - padding_x)
    top = max(0, y - padding_y)
    right = min(frame_width, x + width + padding_x)
    bottom = min(frame_height, y + height + padding_y)
    return left, top, max(0, right - left), max(0, bottom - top)


def _blur_face_regions(frame, boxes, strength: int, padding_percent: int):
    """Blur every detected region in-place and return expanded coordinates."""
    import cv2  # type: ignore

    expanded = []
    frame_height, frame_width = frame.shape[:2]
    for raw_box in boxes:
        left, top, width, height = _expand_face_box(
            tuple(raw_box), frame_width, frame_height, padding_percent)
        if width < 2 or height < 2:
            continue
        region = frame[top:top + height, left:left + width]
        kernel = max(3, round(min(width, height) * strength / 100))
        if kernel % 2 == 0:
            kernel += 1
        kernel = min(kernel, 99)
        blurred = cv2.GaussianBlur(region, (kernel, kernel), sigmaX=0)
        # A low-resolution round trip prevents residual identity detail even
        # when the detected face is large relative to the blur kernel.
        block = max(2, round(2 + strength / 8))
        small = cv2.resize(
            blurred,
            (max(1, width // block), max(1, height // block)),
            interpolation=cv2.INTER_AREA,
        )
        frame[top:top + height, left:left + width] = cv2.resize(
            small, (width, height), interpolation=cv2.INTER_NEAREST)
        expanded.append((left, top, width, height))
    return expanded


def _load_face_detector():
    import cv2  # type: ignore

    if not hasattr(cv2, "CascadeClassifier"):
        raise RuntimeError(
            "OpenCV native bindings are unavailable "
            f"(module={getattr(cv2, '__file__', None)!r}, "
            f"version={getattr(cv2, '__version__', None)!r}).")
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    if detector.empty():
        raise RuntimeError(f"Could not load OpenCV face cascade: {cascade_path}")
    return detector


def op_face_blur(args: argparse.Namespace, detector_override=None) -> int:
    """Detect and irreversibly obscure frontal faces in every video frame."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    try:
        import cv2  # type: ignore
    except ImportError:
        return fail(
            "missing_opencv",
            "Face blur requires the managed opencv-python-headless dependency. "
            "Rebuild or reinstall the ClipForge sidecar.",
        )

    source = Path(args.input)
    if not source.is_file():
        return fail("missing_input", f"Input file does not exist: {source}")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not 1 <= args.strength <= 100:
        return fail("invalid_strength", "--strength must be between 1 and 100.")
    if not 0 <= args.padding <= 100:
        return fail("invalid_padding", "--padding must be between 0 and 100.")
    if not 1.01 <= args.scale_factor <= 2.0:
        return fail("invalid_scale_factor", "--scale-factor must be between 1.01 and 2.0.")
    if not 1 <= args.min_neighbors <= 20 or not 8 <= args.min_face <= 4096:
        return fail("invalid_detector_settings", "Face detector settings are out of range.")

    info = probe(ffprobe, str(source))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0) or 0)

    try:
        detector = detector_override or _load_face_detector()
    except Exception as exc:
        return fail("detector_unavailable", str(exc))

    import tempfile
    descriptor, temporary_name = tempfile.mkstemp(prefix="ucx-face-blur-", suffix=".avi")
    os.close(descriptor)
    temporary_video = Path(temporary_name)
    staged_output: Path | None = None
    try:
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            return fail("decode_failed", f"OpenCV could not decode {source.name}.")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0 or width <= 0 or height <= 0:
            capture.release()
            return fail("decode_failed", "Video dimensions or frame rate are unavailable.")

        writer = cv2.VideoWriter(
            str(temporary_video),
            cv2.VideoWriter_fourcc(*"MJPG"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            capture.release()
            return fail("temporary_encoder_failed", "Could not open the private frame encoder.")

        frame_index = 0
        faces_detected = 0
        frames_with_faces = 0
        emit("progress", percent=0, stage="detecting faces", eta_seconds=None)
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                grayscale = cv2.equalizeHist(grayscale)
                boxes = detector.detectMultiScale(
                    grayscale,
                    scaleFactor=args.scale_factor,
                    minNeighbors=args.min_neighbors,
                    minSize=(args.min_face, args.min_face),
                )
                blurred = _blur_face_regions(frame, boxes, args.strength, args.padding)
                if blurred:
                    faces_detected += len(blurred)
                    frames_with_faces += 1
                writer.write(frame)
                frame_index += 1
                if total_frames > 0 and (frame_index == 1 or frame_index % 5 == 0):
                    emit(
                        "progress",
                        percent=round(min(100.0, frame_index / total_frames * 100), 1),
                        stage="detecting faces",
                        eta_seconds=None,
                    )
        finally:
            capture.release()
            writer.release()

        if frame_index == 0:
            return fail("decode_failed", "No video frames could be decoded.")
        if faces_detected == 0:
            return fail(
                "no_faces_detected",
                "No frontal faces were detected, so no privacy-labelled output was written.",
            )

        emit(
            "log",
            level="info",
            message=(
                f"Blurred {faces_detected} face region(s) across "
                f"{frames_with_faces}/{frame_index} frames."
            ),
        )
        staged_output = output.with_name(
            f".{output.stem}-{os.getpid()}-{time.time_ns()}.tmp{output.suffix}")
        command = [
            ffmpeg, "-y",
            "-i", str(temporary_video),
            "-i", str(source),
            "-map", "0:v:0", "-map", "1:a?",
            "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
            "-c:a", "aac", "-b:a", "192k",
            "-map_metadata", "1",
            "-movflags", "+faststart",
            str(staged_output),
        ]
        rc = run_ffmpeg(command, duration, "encoding privacy filter")
        if rc != 0:
            return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}.")
        if not staged_output.is_file() or staged_output.stat().st_size == 0:
            return fail("output_missing", f"Output not produced: {staged_output}")
        os.replace(staged_output, output)
        emit(
            "complete",
            output=str(output),
            size_bytes=output.stat().st_size,
            frames=frame_index,
            faces_detected=faces_detected,
            frames_with_faces=frames_with_faces,
        )
        return 0
    finally:
        try: temporary_video.unlink(missing_ok=True)
        except OSError: pass
        if staged_output is not None:
            try: staged_output.unlink(missing_ok=True)
            except OSError: pass
