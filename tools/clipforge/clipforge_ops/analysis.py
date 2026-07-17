from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from .runtime import emit, fail, find_ffmpeg, find_ffprobe, probe, run_ffmpeg



def op_timeline(args: argparse.Namespace) -> int:
    """Extract a thumbnail strip + waveform image so the UI can paint a visual
    scrub bar above the seek slider. Output dir gets:
       tn_0001.jpg, tn_0002.jpg, ...   (1 fps thumbnails, scaled to ~120px wide)
       waveform.png                    (showwavespic-rendered audio waveform)
    Emits one `thumb` event per generated frame so the host can lazy-load."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0))
    if duration <= 0:
        return fail("probe_failed", "Zero / unknown duration.")

    fps = max(0.1, float(args.thumb_fps))
    thumb_height = int(args.thumb_height)
    expected = max(1, int(duration * fps))

    emit("log", level="info",
         message=f"Timeline: {expected} thumbs @ {fps} fps, scaled to h={thumb_height}px")
    emit("progress", percent=0, stage="thumbnails", eta_seconds=None)

    pattern = str(out_dir / "tn_%05d.jpg")
    cmd_tn = [
        ffmpeg, "-y",
        "-i", str(src),
        "-vf", f"fps={fps},scale=-2:{thumb_height}:flags=fast_bilinear",
        "-q:v", "5",   # JPEG quality 1-31, lower=better; 5 keeps strips crisp without bloat
        pattern,
    ]
    rc = run_ffmpeg(cmd_tn, duration, "thumbnails")
    if rc != 0:
        return fail("ffmpeg_failed", f"Thumbnail extraction failed (exit {rc})")

    # Enumerate the thumbs that actually landed and emit one event each.
    files = sorted(out_dir.glob("tn_*.jpg"))
    for i, f in enumerate(files):
        ts = i / fps
        emit("thumb",
             index=i,
             timestamp_seconds=round(ts, 3),
             path=str(f))

    # Waveform image (no failure if no audio track -- skip cleanly).
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    waveform = out_dir / "waveform.png"
    if has_audio:
        emit("progress", percent=0, stage="waveform", eta_seconds=None)
        cmd_wf = [
            ffmpeg, "-y",
            "-i", str(src),
            "-filter_complex",
            f"showwavespic=s={int(args.waveform_width)}x{int(args.waveform_height)}"
            f":colors={args.waveform_color}:split_channels=0",
            "-frames:v", "1",
            str(waveform),
        ]
        rc = run_ffmpeg(cmd_wf, duration, "waveform")
        if rc != 0:
            emit("log", level="warn",
                 message=f"Waveform render failed (exit {rc}); thumbnails still produced")

    emit("progress", percent=100, stage="timeline", eta_seconds=0)
    emit("complete",
         output=str(out_dir),
         size_bytes=sum(p.stat().st_size for p in out_dir.iterdir() if p.is_file()),
         thumb_count=len(files),
         duration_seconds=round(duration, 3),
         waveform_path=str(waveform) if waveform.is_file() else None,
         fps=fps)
    return 0


def op_keyframes(args: argparse.Namespace) -> int:
    """List the video keyframe timestamps so a lossless-cut UI can snap in/out
    points to a keyframe boundary. Stream-copy trims can only cut on keyframes,
    so exposing them lets the host show the exact frames a lossless cut will
    land on. Emits one `keyframes` event carrying the sorted timestamp list."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")

    cmd = [
        ffprobe, "-v", "quiet",
        "-select_streams", "v:0",
        "-skip_frame", "nokey",
        "-show_entries", "frame=pts_time,best_effort_timestamp_time",
        "-of", "json",
        str(src),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (subprocess.SubprocessError, OSError) as exc:
        return fail("ffprobe_failed", f"Keyframe probe failed: {exc}")
    if result.returncode != 0:
        return fail("ffprobe_failed", f"Keyframe probe exited {result.returncode}.")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return fail("ffprobe_failed", "Keyframe probe returned invalid JSON.")

    times: list[float] = []
    for frame in payload.get("frames", []):
        raw = frame.get("pts_time")
        if raw in (None, "N/A"):
            raw = frame.get("best_effort_timestamp_time")
        if raw in (None, "N/A"):
            continue
        try:
            times.append(round(float(raw), 3))
        except (TypeError, ValueError):
            continue

    times = sorted(set(times))
    emit("keyframes", input=str(src), count=len(times), timestamps=times)
    emit("complete", output=str(src), size_bytes=0, count=len(times))
    return 0


def op_proxy(args: argparse.Namespace) -> int:
    """Generate a fast, low-resolution preview proxy. Defaults to 480p at
    ~5 Mbps with the ultrafast x264 preset and +faststart so previews and
    quick VMAF passes run far faster than against a full-resolution master."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src))
    duration = 0.0
    try:
        duration = float((info or {}).get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0

    height = max(120, int(args.height))
    bitrate = str(args.bitrate)
    try:
        buf = f"{int(str(bitrate).rstrip('k') or 0) * 2}k"
    except ValueError:
        buf = bitrate

    cmd = [
        ffmpeg, "-y", "-i", str(src),
        "-vf", f"scale=-2:{height}",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", buf,
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    emit("progress", percent=0, stage="proxy", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "proxy")
    if rc != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        out_path.unlink(missing_ok=True)
        return fail("ffmpeg_failed", f"Proxy generation failed (exit {rc}).")

    emit("proxy", input=str(src), output=str(out_path),
         height=height, size_bytes=out_path.stat().st_size)
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_vmaf(args: argparse.Namespace) -> int:
    """VMAF quality comparison: distorted vs. reference. Runs ffmpeg `libvmaf`
    with JSON log output, parses the file, emits per-frame `vmaf` events plus a
    final `complete` event carrying mean / harmonic-mean / min scores."""
    import math
    import tempfile

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")

    ref = Path(args.reference)
    dist = Path(args.distorted)
    if not ref.is_file():
        return fail("missing_input", f"Reference not found: {args.reference}")
    if not dist.is_file():
        return fail("missing_input", f"Distorted not found: {args.distorted}")

    with tempfile.NamedTemporaryFile(prefix="ucx_vmaf_", suffix=".json",
                                     delete=False, mode="w") as tmp:
        log_path = tmp.name

    # libvmaf options: log_path uses Windows-friendly forward slashes; embedded
    # colons in log_fmt require escaping per ffmpeg filter quoting rules.
    safe_log = log_path.replace("\\", "/").replace(":", "\\:")
    cmd = [
        ffmpeg, "-y",
        "-i", str(dist),
        "-i", str(ref),
        "-lavfi", f"libvmaf=log_path='{safe_log}':log_fmt=json",
        "-f", "null", "-",
    ]
    emit("log", level="info",
         message=f"VMAF: distorted={dist.name} ref={ref.name}")
    emit("progress", percent=0, stage="vmaf", eta_seconds=None)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    # ffmpeg writes progress to stderr for libvmaf runs (no -progress here so we
    # just count frames -- best-effort, no ETA).
    if proc.stderr is not None:
        for line in proc.stderr:
            line = line.rstrip()
            if line.startswith("frame="):
                # Cheap progress: we don't know total frame count up front
                # without an extra probe pass, so just parrot the frame counter.
                emit("log", level="debug", message=line)
    rc = proc.wait()
    if rc != 0:
        try: os.unlink(log_path)
        except OSError: pass
        return fail("ffmpeg_failed", f"FFmpeg/libvmaf exited with code {rc}")

    try:
        with open(log_path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as ex:
        try: os.unlink(log_path)
        except OSError: pass
        return fail("vmaf_parse_failed", f"Could not read VMAF report: {ex}")
    finally:
        try: os.unlink(log_path)
        except OSError: pass

    frames = doc.get("frames", [])
    pooled = doc.get("pooled_metrics", {}).get("vmaf", {})
    scores: list[float] = []
    total = max(1, len(frames))
    sample_every = max(1, total // 200)  # cap to ~200 vmaf events for huge clips
    for i, frame in enumerate(frames):
        s = frame.get("metrics", {}).get("vmaf")
        if s is None:
            continue
        scores.append(float(s))
        if i % sample_every == 0:
            emit("vmaf", frame=i, score=round(float(s), 3))
            emit("progress",
                 percent=round(i / total * 100, 1),
                 stage="vmaf",
                 eta_seconds=None)

    if not scores:
        return fail("vmaf_no_scores", "VMAF report contained no frame scores.")

    mean = sum(scores) / len(scores)
    minv = min(scores)
    maxv = max(scores)
    # Harmonic mean is the metric Netflix recommends for pooled VMAF, since it
    # penalizes worst-frame outliers more than arithmetic mean does.
    eps = 1e-9
    harmonic = len(scores) / sum(1.0 / max(s, eps) for s in scores)
    pct_below_70 = 100.0 * sum(1 for s in scores if s < 70) / len(scores)
    summary = {
        "frames":            len(scores),
        "mean":              round(mean, 3),
        "harmonic_mean":     round(harmonic, 3),
        "min":               round(minv, 3),
        "max":               round(maxv, 3),
        "pooled_mean":       round(float(pooled.get("mean", mean)), 3) if pooled else None,
        "pooled_harmonic":   round(float(pooled.get("harmonic_mean", harmonic)), 3) if pooled else None,
        "below_70_percent":  round(pct_below_70, 2),
    }
    emit("vmaf_summary", **summary)
    emit("progress", percent=100, stage="vmaf", eta_seconds=0)
    emit("complete", output="", size_bytes=0, summary=summary)
    return 0
