"""Vertigo sidecar — NDJSON Auto-Reframe for the UCX Auto Reframe module.

Reframes horizontal video to vertical (9:16) / square (1:1) / portrait social
(4:5) aspect ratios. Two modes:

  --mode static   Center-crop to target aspect. Pure FFmpeg, no AI.
  --mode smart    Sample frames at 1 Hz with MediaPipe face/body detection,
                  build a smoothed centre-of-interest track, drive an FFmpeg
                  `crop` filter with a piecewise-linear x position over time.
                  Falls back to static if MediaPipe / OpenCV not installed.

Subcommands:
  reframe        run a reframe job
  list-aspects   emit the supported aspect-ratio presets

Standard NDJSON contract: progress / log / complete / error / aspect events.

Note: this sidecar deliberately implements only the reframe operation. The
upstream Vertigo project (~/repos/Vertigo) ships a much wider editor pipeline
(animated captions, B-roll, hook scoring, scene detection). Item M in the
ROADMAP tracks broader vendoring as a separate decision.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
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


# ── ffmpeg discovery + probe ─────────────────────────────────────────────────

def find_ffmpeg() -> str | None:
    here = Path(__file__).resolve().parent
    for candidate in [
        os.environ.get("FFMPEG_PATH"),
        shutil.which("ffmpeg"),
        str(here / "ffmpeg.exe"),
        str(here.parent / "_bin" / "ffmpeg.exe"),
    ]:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def probe_video(ffmpeg: str, path: Path) -> tuple[int, int, float, float]:
    """Return (width, height, duration_sec, fps) via `ffmpeg -i`."""
    result = subprocess.run(
        [ffmpeg, "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, timeout=20,
    )
    txt = result.stderr
    w = h = 0
    duration = 0.0
    fps = 25.0
    m = re.search(r",\s+(\d{2,5})x(\d{2,5})[\s,\[]", txt)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", txt)
    if m:
        hh, mm, ss = float(m.group(1)), float(m.group(2)), float(m.group(3))
        duration = hh * 3600 + mm * 60 + ss
    m = re.search(r"(\d+(?:\.\d+)?)\s+fps", txt)
    if m:
        fps = float(m.group(1))
    return w, h, duration, fps


# ── Aspect presets ───────────────────────────────────────────────────────────

ASPECTS: dict[str, tuple[int, int, str]] = {
    "9x16": (9, 16, "Vertical (Reels / Shorts / TikTok)"),
    "1x1":  (1, 1,  "Square (Instagram feed)"),
    "4x5":  (4, 5,  "Portrait social (Instagram feed)"),
    "3x4":  (3, 4,  "Portrait social (alt)"),
}


def op_list_aspects(_: argparse.Namespace) -> int:
    for tag, (num, den, label) in ASPECTS.items():
        emit("aspect", id=tag, num=num, den=den, label=label,
             ratio=round(num / den, 4))
    emit("complete", count=len(ASPECTS))
    return 0


# ── Smart tracking (MediaPipe face detection) ────────────────────────────────

def _smart_track_centers(in_path: Path, sample_hz: float = 1.0) -> list[tuple[float, float]] | None:
    """Sample frames at `sample_hz` Hz and return list of (timestamp_s, x_norm)
    normalised face-centre x positions. Returns None if cv2/mediapipe missing.

    Output coordinates are normalised (0.0..1.0) against source width.
    """
    try:
        import cv2  # type: ignore
        import mediapipe as mp  # type: ignore
    except ImportError:
        return None

    cap = cv2.VideoCapture(str(in_path))
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total_frames <= 0:
        cap.release()
        return None

    step = max(1, int(round(fps / sample_hz)))
    detector = mp.solutions.face_detection.FaceDetection(  # type: ignore
        model_selection=1, min_detection_confidence=0.4)

    points: list[tuple[float, float]] = []
    fnum = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if fnum % step == 0:
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = detector.process(rgb)
            if res.detections:
                # take the largest face by bounding-box area
                best = max(res.detections,
                           key=lambda d: (d.location_data.relative_bounding_box.width *
                                          d.location_data.relative_bounding_box.height))
                bb = best.location_data.relative_bounding_box
                x_norm = max(0.0, min(1.0, bb.xmin + bb.width / 2.0))
                t = fnum / fps
                points.append((t, x_norm))
        fnum += 1
        if fnum % (step * 30) == 0 and total_frames:
            progress(5.0 + 15.0 * fnum / total_frames,
                     f"sampling face track ({len(points)} hits, {fnum}/{total_frames})")

    detector.close()
    cap.release()
    return points


def _smooth(points: list[tuple[float, float]], window: int = 5) -> list[tuple[float, float]]:
    """Trailing moving-average smoother on x positions."""
    if not points:
        return points
    out: list[tuple[float, float]] = []
    xs: list[float] = []
    for t, x in points:
        xs.append(x)
        if len(xs) > window:
            xs.pop(0)
        out.append((t, sum(xs) / len(xs)))
    return out


# ── Reframe core ─────────────────────────────────────────────────────────────

_TIME_RE = re.compile(r"out_time_ms=(\d+)")


def run_ffmpeg(cmd: list[str], duration_sec: float, stage: str) -> int:
    proc = subprocess.Popen(
        cmd + ["-progress", "pipe:1", "-nostats"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    started = time.monotonic()
    last_pct = -1.0
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            m = _TIME_RE.search(line)
            if m and duration_sec > 0:
                cur = int(m.group(1)) / 1_000_000
                pct = max(0.0, min(100.0, cur / duration_sec * 100.0))
                if pct - last_pct >= 0.5:
                    last_pct = pct
                    elapsed = time.monotonic() - started
                    local = pct / 100.0
                    eta = (elapsed / local - elapsed) if local > 0.01 else None
                    progress(pct, stage,
                             int(eta) if eta and eta < 86400 else None)
            elif line.startswith("progress=end"):
                progress(100, stage, 0)
    finally:
        proc.wait()
        if proc.returncode != 0 and proc.stderr is not None:
            for ln in proc.stderr.read().splitlines()[-20:]:
                log("error", ln)
    return proc.returncode


def _crop_filter_static(src_w: int, src_h: int, num: int, den: int) -> tuple[str, int, int]:
    """Build a static centre-crop filter. Returns (filter_string, out_w, out_h)."""
    # Target aspect
    target = num / den
    src = src_w / src_h
    if target < src:
        # Source is wider — crop horizontally
        out_h = src_h
        out_w = int(round(out_h * target))
        out_w -= out_w % 2  # even for h264
        filt = f"crop={out_w}:{out_h}:({src_w}-{out_w})/2:0"
    else:
        # Source is narrower — crop vertically (rare for landscape→vertical)
        out_w = src_w
        out_h = int(round(out_w / target))
        out_h -= out_h % 2
        filt = f"crop={out_w}:{out_h}:0:({src_h}-{out_h})/2"
    return filt, out_w, out_h


def _crop_filter_smart_track(
    src_w: int, src_h: int, num: int, den: int,
    points: list[tuple[float, float]],
) -> tuple[str, int, int]:
    """Build a moving-crop filter using FFmpeg `between` expressions over time.

    For each adjacent pair of sampled points, generate a piecewise-linear x
    expression. Falls back to the centred crop if `points` is empty.
    """
    target = num / den
    src = src_w / src_h
    if target >= src or not points:
        return _crop_filter_static(src_w, src_h, num, den)

    out_h = src_h
    out_w = int(round(out_h * target))
    out_w -= out_w % 2

    # We need x(t) in source pixels, clamped so the crop window stays inside.
    max_x = max(0, src_w - out_w)
    half_window = out_w / 2.0

    # Convert normalised face-centre to crop-window x (top-left corner).
    xs_px: list[tuple[float, float]] = [
        (t, max(0.0, min(max_x, x_norm * src_w - half_window)))
        for t, x_norm in points
    ]

    # Build an FFmpeg expression: chained `between(t, t0, t1) * lerp + ...`
    # Cap segment count to keep the expression sane (~50 samples).
    if len(xs_px) > 50:
        stride = math.ceil(len(xs_px) / 50)
        xs_px = xs_px[::stride]

    if len(xs_px) == 1:
        x_expr = f"{xs_px[0][1]:.1f}"
    else:
        # piecewise: for each segment t in [t0, t1], x = x0 + (x1-x0) * (t-t0)/(t1-t0)
        # else last value past the final timestamp.
        parts: list[str] = []
        for i in range(len(xs_px) - 1):
            t0, x0 = xs_px[i]
            t1, x1 = xs_px[i + 1]
            if t1 - t0 < 1e-3:
                continue
            slope = (x1 - x0) / (t1 - t0)
            parts.append(
                f"if(between(t\\,{t0:.3f}\\,{t1:.3f})\\,"
                f"{x0:.1f}+({slope:.3f})*(t-{t0:.3f})"
            )
        # Tail value after last sampled point
        tail = xs_px[-1][1]
        # close the chained ifs and provide tail
        x_expr = "".join(parts) + f"{tail:.1f}" + (")" * len(parts))

    filt = f"crop={out_w}:{out_h}:'{x_expr}':0"
    return filt, out_w, out_h


def op_reframe(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input not found: {in_path}")

    aspect = args.aspect.lower()
    if aspect not in ASPECTS:
        return fail("invalid_aspect",
                    f"Unknown aspect {aspect!r}. Choose one of: "
                    f"{', '.join(ASPECTS)}")
    num, den, _label = ASPECTS[aspect]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    progress(1.0, "probing source")
    w, h, duration, fps = probe_video(ffmpeg, in_path)
    if w <= 0 or h <= 0:
        return fail("probe_failed", f"Could not read dimensions from {in_path.name}")
    log("info", f"Source: {w}x{h}  duration={duration:.1f}s  fps={fps:.2f}")

    mode = args.mode
    points: list[tuple[float, float]] | None = None
    if mode == "smart":
        progress(3.0, "sampling face track")
        points = _smart_track_centers(in_path, sample_hz=1.0)
        if points is None:
            log("warn", "MediaPipe / OpenCV not installed — falling back to static centre-crop.")
            mode = "static"
        elif not points:
            log("warn", "No faces detected — falling back to static centre-crop.")
            mode = "static"
        else:
            points = _smooth(points, window=5)
            log("info", f"Tracked {len(points)} face samples; building moving crop.")

    if mode == "smart" and points:
        crop_expr, out_w, out_h = _crop_filter_smart_track(w, h, num, den, points)
    else:
        crop_expr, out_w, out_h = _crop_filter_static(w, h, num, den)

    log("info", f"Output: {out_w}x{out_h}  filter={crop_expr[:80]}{'...' if len(crop_expr) > 80 else ''}")

    cmd = [
        ffmpeg, "-y",
        "-i", str(in_path),
        "-vf", crop_expr,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "copy",
        str(out_path),
    ]

    rc = run_ffmpeg(cmd, duration, f"reframing {aspect}")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")

    emit("complete",
         output=str(out_path),
         size_bytes=out_path.stat().st_size,
         aspect=aspect,
         mode=mode,
         out_width=out_w,
         out_height=out_h)
    return 0


# ── argparse + main ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vertigo-sidecar",
        description="UCX Vertigo Auto-Reframe sidecar — FFmpeg crop with optional MediaPipe face tracking.",
    )
    sub = p.add_subparsers(dest="op", required=True)

    rf = sub.add_parser("reframe", help="Reframe video to a target aspect")
    rf.add_argument("--input",  required=True)
    rf.add_argument("--output", required=True)
    rf.add_argument("--aspect", required=True,
                    help=f"Target aspect: one of {', '.join(ASPECTS)}")
    rf.add_argument("--mode", choices=["static", "smart"], default="static",
                    help="static = centred crop, smart = MediaPipe face track")
    rf.add_argument("--crf", type=int, default=20,
                    help="x264 CRF for the re-encode (0–51, default 20)")

    sub.add_parser("list-aspects", help="Emit aspect-ratio presets")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "reframe":
            return op_reframe(args)
        if args.op == "list-aspects":
            return op_list_aspects(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
