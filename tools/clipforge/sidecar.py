"""ClipForge sidecar — NDJSON CLI shim for the UCX Editor module.

Supported ops:
  trim      Trim a clip by start/end seconds (lossless stream-copy or re-encode).
  crop      Crop video to W:H:X:Y via -vf crop.
  rotate    Rotate/flip video via -vf transpose / hflip / vflip.
  loudnorm  EBU R128 loudness normalisation via -af loudnorm.
  rewrap    Change container without re-encoding (-c copy stream copy).

Contract: see ../README.md (sidecar contract) and ../../README.md (parent).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def find_ffmpeg() -> str | None:
    here = Path(__file__).resolve().parent
    for c in [os.environ.get("FFMPEG_PATH"), shutil.which("ffmpeg"),
              str(here / "ffmpeg.exe"), str(here.parent / "_bin" / "ffmpeg.exe")]:
        if c and Path(c).is_file():
            return c
    return None


def find_ffprobe() -> str | None:
    here = Path(__file__).resolve().parent
    for c in [os.environ.get("FFPROBE_PATH"), shutil.which("ffprobe"),
              str(here / "ffprobe.exe"), str(here.parent / "_bin" / "ffprobe.exe")]:
        if c and Path(c).is_file():
            return c
    return None


def probe(ffprobe: str, path: str) -> dict | None:
    try:
        r = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None


_TIME_RE = re.compile(r"out_time_ms=(\d+)")


def run_ffmpeg(cmd: list[str], duration_sec: float, stage: str) -> int:
    proc = subprocess.Popen(
        cmd + ["-progress", "pipe:1", "-nostats"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1)
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
                    emit("progress", percent=round(pct, 1), stage=stage,
                         eta_seconds=int(eta) if eta and eta < 86400 else None)
            elif line.startswith("progress=end"):
                emit("progress", percent=100, stage=stage, eta_seconds=0)
    finally:
        proc.wait()
        if proc.returncode != 0 and proc.stderr is not None:
            for ln in proc.stderr.read().splitlines()[-15:]:
                emit("log", level="error", message=ln)
    return proc.returncode


def op_trim(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    src_dur = float(info.get("format", {}).get("duration", 0))
    if src_dur <= 0:
        return fail("probe_failed", "Could not determine input duration.")

    start = max(0.0, args.start)
    end = args.end if args.end is not None and args.end > 0 else src_dur
    end = min(end, src_dur)
    if end <= start:
        return fail("invalid_range", f"Trim end ({end:.2f}) must be greater than start ({start:.2f}).")
    span = end - start

    emit("log", level="info", message=f"Trim {start:.2f}-{end:.2f} ({span:.2f}s) of {src_dur:.2f}s")

    if args.lossless:
        # Stream-copy trim — fast but only cuts on keyframes; output may be slightly off.
        cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
               "-i", str(in_path), "-c", "copy",
               "-map_metadata", "0", "-movflags", "+faststart", str(out_path)]
        emit("progress", percent=0, stage="trim (lossless)", eta_seconds=None)
        rc = run_ffmpeg(cmd, span, "trim (lossless)")
    else:
        cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
               "-i", str(in_path),
               "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset]
        if args.audio_codec == "an":
            cmd += ["-an"]
        elif args.audio_codec == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", args.audio_codec, "-b:a", f"{args.audio_bitrate}k"]
        cmd += ["-movflags", "+faststart", str(out_path)]
        emit("progress", percent=0, stage="trim (re-encode)", eta_seconds=None)
        rc = run_ffmpeg(cmd, span, "trim (re-encode)")

    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_crop(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0))

    crop_filter = f"crop={args.width}:{args.height}:{args.x}:{args.y}"
    emit("log", level="info", message=f"Crop filter: {crop_filter}")

    cmd = [ffmpeg, "-y", "-i", str(in_path),
           "-vf", crop_filter,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy",
           "-movflags", "+faststart", str(out_path)]
    emit("progress", percent=0, stage="crop", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "crop")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# Mapping from human-readable angle/flip to FFmpeg filter
_ROTATE_FILTERS: dict[str, str] = {
    "90":     "transpose=1",        # 90° clockwise
    "180":    "transpose=2,transpose=2",  # 180°
    "270":    "transpose=2",        # 90° counter-clockwise (270° clockwise)
    "flip_h": "hflip",
    "flip_v": "vflip",
}


def op_rotate(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    vf = _ROTATE_FILTERS.get(args.angle)
    if not vf:
        return fail("invalid_args", f"Unknown angle: {args.angle}. Use 90, 180, 270, flip_h, or flip_v.")

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0))

    emit("log", level="info", message=f"Rotate filter: {vf}")

    cmd = [ffmpeg, "-y", "-i", str(in_path),
           "-vf", vf,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy",
           "-movflags", "+faststart", str(out_path)]
    emit("progress", percent=0, stage="rotate", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "rotate")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_loudnorm(args: argparse.Namespace) -> int:
    """Two-pass EBU R128 loudness normalisation.

    Pass 1 analyses the input and writes measured levels to a temp JSON.
    Pass 2 applies the linear normalisation filter with the measured values
    so the output has exactly the target integrated loudness.
    """
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0))

    il = args.integrated_lufs   # target integrated loudness (e.g. -14)
    tp = args.true_peak          # max true peak (e.g. -1.5)
    lra = args.lra               # loudness range (e.g. 11)

    # Pass 1: measure input levels
    emit("log", level="info", message="Loudnorm pass 1 — measuring levels")
    emit("progress", percent=0, stage="loudnorm (measure)", eta_seconds=None)
    p1_filter = f"loudnorm=I={il}:TP={tp}:LRA={lra}:print_format=json"
    p1_cmd = [ffmpeg, "-y", "-i", str(in_path),
              "-af", p1_filter,
              "-f", "null",
              "NUL" if sys.platform == "win32" else "/dev/null"]
    proc = subprocess.run(p1_cmd, capture_output=True, text=True)
    # loudnorm stats come on stderr as a JSON block
    measured: dict = {}
    try:
        stderr_text = proc.stderr or ""
        # Locate the JSON block in the stderr output
        start = stderr_text.rfind("{")
        end = stderr_text.rfind("}") + 1
        if start != -1 and end > start:
            measured = json.loads(stderr_text[start:end])
    except (json.JSONDecodeError, ValueError):
        pass

    if not measured:
        # Graceful fallback: single-pass without measured values
        emit("log", level="warning", message="Could not parse loudnorm measurements; falling back to single-pass.")
        p2_filter = f"loudnorm=I={il}:TP={tp}:LRA={lra}"
    else:
        p2_filter = (
            f"loudnorm=I={il}:TP={tp}:LRA={lra}"
            f":measured_I={measured.get('input_i', il)}"
            f":measured_TP={measured.get('input_tp', tp)}"
            f":measured_LRA={measured.get('input_lra', lra)}"
            f":measured_thresh={measured.get('input_thresh', -70)}"
            f":offset={measured.get('target_offset', 0)}"
            f":linear=true"
        )

    emit("log", level="info", message="Loudnorm pass 2 — applying normalisation")
    emit("progress", percent=50, stage="loudnorm (encode)", eta_seconds=None)
    p2_cmd = [ffmpeg, "-y", "-i", str(in_path),
              "-af", p2_filter,
              "-c:v", "copy",
              "-c:a", args.audio_codec, "-b:a", f"{args.audio_bitrate}k",
              "-ar", "48000",
              str(out_path)]
    rc = run_ffmpeg(p2_cmd, duration, "loudnorm (encode)")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_track_list(args: argparse.Namespace) -> int:
    """Enumerate every stream in a container. One `track` event per stream.

    Fields per event:
      stream_index  Container-level stream index (0,1,2,...)
      codec_type    video|audio|subtitle|data|attachment
      codec_name    h264, aac, ass, ...
      language      ISO-639 code if present, else null
      title         Stream title tag if present
      duration      Stream duration in seconds (best-effort)
      bit_rate      Per-stream bitrate (best-effort)
      width/height  For video streams
      channels      For audio streams
      default       Bool — disposition.default flag
    """
    ffprobe = find_ffprobe()
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")

    info = probe(ffprobe, str(src))
    if not info:
        return fail("probe_failed", "ffprobe could not read input.")

    streams = info.get("streams", [])
    for s in streams:
        tags = s.get("tags") or {}
        disp = s.get("disposition") or {}
        emit("track",
             stream_index=int(s.get("index", -1)),
             codec_type=str(s.get("codec_type") or ""),
             codec_name=str(s.get("codec_name") or ""),
             language=tags.get("language"),
             title=tags.get("title"),
             duration=float(s.get("duration") or 0) or None,
             bit_rate=int(s.get("bit_rate")) if s.get("bit_rate") else None,
             width=int(s.get("width") or 0) or None,
             height=int(s.get("height") or 0) or None,
             channels=int(s.get("channels") or 0) or None,
             default=bool(disp.get("default", 0)))
    emit("complete", output=str(src), size_bytes=src.stat().st_size,
         track_count=len(streams))
    return 0


def op_track_remove(args: argparse.Namespace) -> int:
    """Remove one or more streams without re-encoding.

    --remove takes a comma-separated list of container stream indices, e.g. "1,3,5".
    Builds an ffmpeg -map chain that includes every stream EXCEPT those, with -c copy
    so no re-encode happens. Output container is taken from --output's extension.
    """
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src))
    if not info:
        return fail("probe_failed", "ffprobe could not read input.")
    duration = float(info.get("format", {}).get("duration", 0)) or 0.0

    try:
        drop = {int(x.strip()) for x in args.remove.split(",") if x.strip()}
    except ValueError:
        return fail("bad_remove_arg",
                    "--remove must be a comma-separated list of integer stream indices.")
    if not drop:
        return fail("nothing_to_remove", "--remove was empty.")

    keep_count = 0
    cmd: list[str] = [ffmpeg, "-y", "-i", str(src)]
    for s in info.get("streams", []):
        idx = int(s.get("index", -1))
        if idx in drop:
            continue
        cmd += ["-map", f"0:{idx}"]
        keep_count += 1
    if keep_count == 0:
        return fail("nothing_to_keep",
                    f"--remove {sorted(drop)} would strip every stream; refusing.")

    cmd += ["-c", "copy", "-map_metadata", "0"]
    if out.suffix.lower() in (".mp4", ".m4v", ".mov"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(out))

    emit("log", level="info",
         message=f"Removing streams {sorted(drop)}; keeping {keep_count} of "
                 f"{len(info.get('streams', []))}.")
    emit("progress", percent=0, stage="track-remove", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "track-remove")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out.is_file():
        return fail("output_missing", f"Output not produced: {out}")
    emit("complete", output=str(out), size_bytes=out.stat().st_size)
    return 0


def op_track_add(args: argparse.Namespace) -> int:
    """Add an external audio (or subtitle) file as a new track without re-encoding.

    Stream-copies the original input plus all streams from --extra. Useful for:
      * attaching a dubbed audio language
      * adding an SRT/ASS subtitle into an MKV
      * attaching a commentary track to a finished cut
    """
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    extra = Path(args.extra)
    if not extra.is_file():
        return fail("missing_extra", f"Extra track file not found: {args.extra}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src))
    duration = float((info or {}).get("format", {}).get("duration", 0)) or 0.0

    cmd = [ffmpeg, "-y",
           "-i", str(src),
           "-i", str(extra),
           "-map", "0",          # everything from primary
           "-map", "1",          # everything from extra
           "-c", "copy",
           "-map_metadata", "0"]
    if args.language:
        # Apply language to NEW streams only -- the metadata index is the count
        # of streams in the primary input.
        new_idx = len((info or {}).get("streams", []))
        cmd += [f"-metadata:s:{new_idx}", f"language={args.language}"]
    if args.title:
        new_idx = len((info or {}).get("streams", []))
        cmd += [f"-metadata:s:{new_idx}", f"title={args.title}"]
    if out.suffix.lower() in (".mp4", ".m4v", ".mov"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(out))

    emit("log", level="info",
         message=f"Add track from {extra.name} -> {out.name}")
    emit("progress", percent=0, stage="track-add", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "track-add")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out.is_file():
        return fail("output_missing", f"Output not produced: {out}")
    emit("complete", output=str(out), size_bytes=out.stat().st_size)
    return 0


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


def op_rewrap(args: argparse.Namespace) -> int:
    """Stream-copy into a new container — no re-encode, instant remux."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0))

    in_ext = in_path.suffix.lower()
    out_ext = out_path.suffix.lower()
    emit("log", level="info", message=f"Rewrap {in_ext} -> {out_ext} (stream copy)")

    cmd = [ffmpeg, "-y", "-i", str(in_path),
           "-c", "copy",
           "-map_metadata", "0"]
    if out_ext in (".mp4", ".m4v", ".mov"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(out_path))

    emit("progress", percent=0, stage="rewrap", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "rewrap")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_concat(args: argparse.Namespace) -> int:
    """Stream-copy concatenate via ffmpeg's concat demuxer when codecs match;
    fall back to filter_complex concat for mixed sources."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Input(s) not found: {missing}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Probe codecs to decide stream-copy vs re-encode.
    codecs = []
    total_dur = 0.0
    for p in inputs:
        info = probe(ffprobe, str(p))
        if info:
            v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
            codecs.append(v.get("codec_name", ""))
            total_dur += float(info.get("format", {}).get("duration", 0))
    can_copy = len(set(codecs)) == 1 and not args.reencode

    if can_copy:
        # Concat demuxer: needs a list file with one "file 'path'" per line.
        list_path = Path(out_path.parent / f".concat_{os.getpid()}.txt")
        list_path.write_text(
            "\n".join(f"file '{str(p).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'"
                      for p in inputs),
            encoding="utf-8")
        try:
            cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0",
                   "-i", str(list_path), "-c", "copy", str(out_path)]
            emit("log", level="info", message=f"Concat (stream copy) of {len(inputs)} clip(s)")
            emit("progress", percent=0, stage="concat", eta_seconds=None)
            rc = run_ffmpeg(cmd, total_dur, "concat")
        finally:
            try: list_path.unlink()
            except OSError: pass
    else:
        # filter_complex concat -- normalises to one resolution / codec.
        emit("log", level="info", message=f"Concat (re-encode) of {len(inputs)} clip(s)")
        cmd = [ffmpeg, "-y"]
        for p in inputs: cmd += ["-i", str(p)]
        n = len(inputs)
        filter_str = "".join(f"[{i}:v:0][{i}:a:0?]" for i in range(n)) \
                   + f"concat=n={n}:v=1:a=1[v][a]"
        cmd += ["-filter_complex", filter_str,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                "-c:a", "aac", "-b:a", "192k", str(out_path)]
        emit("progress", percent=0, stage="concat", eta_seconds=None)
        rc = run_ffmpeg(cmd, total_dur, "concat")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         input_count=len(inputs))
    return 0


def op_speed(args: argparse.Namespace) -> int:
    """Speed-up / slow-down a clip via setpts (video) + atempo (audio)."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))
    factor = float(args.factor)
    if factor <= 0: return fail("bad_factor", "--factor must be > 0")

    # Video: setpts=PTS/factor (factor>1 = speed up, <1 = slow down).
    # Audio: atempo accepts 0.5-100; chain multiple stages for extreme factors.
    def _atempo_chain(f: float) -> str:
        chain = []
        while f > 100:
            chain.append("atempo=100"); f /= 100
        while f < 0.5:
            chain.append("atempo=0.5"); f /= 0.5
        chain.append(f"atempo={f}")
        return ",".join(chain)

    cmd = [ffmpeg, "-y", "-i", str(src),
           "-filter_complex",
           f"[0:v]setpts=PTS/{factor}[v];[0:a]{_atempo_chain(factor)}[a]",
           "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-crf", "20", "-preset", "medium",
           "-c:a", "aac", "-b:a", "192k", str(out_path)]
    emit("progress", percent=0, stage=f"speed x{factor}", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration / factor, f"speed x{factor}")
    if rc != 0: return fail("ffmpeg_failed", f"FFmpeg exited {rc}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_reverse(args: argparse.Namespace) -> int:
    """Reverse video and (optionally) audio."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", "reverse",
           "-af", "areverse" if args.reverse_audio else "anull",
           "-c:v", "libx264", "-crf", "20", "-preset", "medium",
           "-c:a", "aac", "-b:a", "192k", str(out_path)]
    emit("progress", percent=0, stage="reverse", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "reverse")
    if rc != 0: return fail("ffmpeg_failed", f"FFmpeg exited {rc}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_lut(args: argparse.Namespace) -> int:
    """Apply a 3D LUT (.cube) to a video via ffmpeg's lut3d filter."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input); lut = Path(args.lut)
    if not src.is_file(): return fail("missing_input", f"Input not found: {args.input}")
    if not lut.is_file(): return fail("missing_lut", f"LUT file not found: {args.lut}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    safe_lut = str(lut).replace("\\", "/").replace(":", "\\:")
    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", f"lut3d='{safe_lut}'",
           "-c:v", "libx264", "-crf", "20", "-preset", "medium",
           "-c:a", "copy", str(out_path)]
    emit("progress", percent=0, stage="lut3d", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "lut3d")
    if rc != 0: return fail("ffmpeg_failed", f"FFmpeg exited {rc}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_hdr_to_sdr(args: argparse.Namespace) -> int:
    """Tone-map HDR (BT.2020 / HLG / PQ) to SDR (BT.709) via libplacebo when
    available, falling back to zscale + tonemap when not."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    # zscale path is the most portable across ffmpeg builds.
    vf = ("zscale=t=linear:npl=100,format=gbrpf32le,"
          "zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
          "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", vf,
           "-c:v", "libx264", "-crf", "20", "-preset", "medium",
           "-c:a", "copy", str(out_path)]
    emit("progress", percent=0, stage="hdr->sdr", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "hdr->sdr")
    if rc != 0: return fail("ffmpeg_failed", f"FFmpeg exited {rc} (zscale not built? Try a "
                                              "newer ffmpeg with --enable-libzimg).")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clipforge-sidecar",
                                description="UCX ClipForge sidecar — video editor operations with NDJSON progress.")
    sub = p.add_subparsers(dest="op", required=True)

    # ── trim ──────────────────────────────────────────────────────────────────
    trim = sub.add_parser("trim", help="Trim a video clip")
    trim.add_argument("--input", required=True)
    trim.add_argument("--output", required=True)
    trim.add_argument("--start", type=float, default=0.0, help="Start time (seconds)")
    trim.add_argument("--end", type=float, help="End time (seconds); omit or 0 for end of clip")
    trim.add_argument("--lossless", action="store_true",
                      help="Stream-copy mode (fast, keyframe-bounded). Skips re-encode.")
    trim.add_argument("--codec", default="libx264", help="Video codec when re-encoding")
    trim.add_argument("--crf", type=int, default=18, help="CRF when re-encoding")
    trim.add_argument("--preset", default="medium", help="FFmpeg encoder preset")
    trim.add_argument("--audio-codec", default="aac")
    trim.add_argument("--audio-bitrate", type=int, default=192)

    # ── crop ──────────────────────────────────────────────────────────────────
    crop = sub.add_parser("crop", help="Crop video to a rectangle")
    crop.add_argument("--input", required=True)
    crop.add_argument("--output", required=True)
    crop.add_argument("--width", type=int, required=True, help="Output width in pixels")
    crop.add_argument("--height", type=int, required=True, help="Output height in pixels")
    crop.add_argument("--x", type=int, default=0, help="Left edge of crop (pixels from left)")
    crop.add_argument("--y", type=int, default=0, help="Top edge of crop (pixels from top)")
    crop.add_argument("--codec", default="libx264")
    crop.add_argument("--crf", type=int, default=18)
    crop.add_argument("--preset", default="medium")

    # ── rotate ────────────────────────────────────────────────────────────────
    rotate = sub.add_parser("rotate", help="Rotate or flip video")
    rotate.add_argument("--input", required=True)
    rotate.add_argument("--output", required=True)
    rotate.add_argument("--angle", required=True,
                        choices=list(_ROTATE_FILTERS.keys()),
                        help="90 | 180 | 270 | flip_h | flip_v")
    rotate.add_argument("--codec", default="libx264")
    rotate.add_argument("--crf", type=int, default=18)
    rotate.add_argument("--preset", default="medium")

    # ── loudnorm ──────────────────────────────────────────────────────────────
    loudnorm = sub.add_parser("loudnorm", help="EBU R128 loudness normalisation")
    loudnorm.add_argument("--input", required=True)
    loudnorm.add_argument("--output", required=True)
    loudnorm.add_argument("--integrated-lufs", type=float, default=-14.0,
                          dest="integrated_lufs",
                          help="Target integrated loudness in LUFS (default: -14)")
    loudnorm.add_argument("--true-peak", type=float, default=-1.5, dest="true_peak",
                          help="Max true peak in dBTP (default: -1.5)")
    loudnorm.add_argument("--lra", type=float, default=11.0,
                          help="Loudness range target in LU (default: 11)")
    loudnorm.add_argument("--audio-codec", default="aac", dest="audio_codec")
    loudnorm.add_argument("--audio-bitrate", type=int, default=192, dest="audio_bitrate")

    # ── rewrap ────────────────────────────────────────────────────────────────
    rewrap = sub.add_parser("rewrap", help="Remux into a different container without re-encoding")
    rewrap.add_argument("--input", required=True)
    rewrap.add_argument("--output", required=True)

    # ── tracks ────────────────────────────────────────────────────────────────
    track_list = sub.add_parser("track-list",
                                help="Enumerate every stream in a container")
    track_list.add_argument("--input", required=True)

    track_remove = sub.add_parser("track-remove",
                                  help="Remove specific streams without re-encoding")
    track_remove.add_argument("--input", required=True)
    track_remove.add_argument("--output", required=True)
    track_remove.add_argument("--remove", required=True,
                              help="Comma-separated list of stream indices to drop, e.g. '1,3'")

    track_add = sub.add_parser("track-add",
                               help="Add an external audio/subtitle file as a new track")
    track_add.add_argument("--input", required=True)
    track_add.add_argument("--extra", required=True,
                           help="Audio (.mp3/.aac/.flac/...) or subtitle (.srt/.ass) file to attach")
    track_add.add_argument("--output", required=True)
    track_add.add_argument("--language",
                           help="Optional ISO-639 language code for the new track (e.g. 'eng', 'jpn')")
    track_add.add_argument("--title",
                           help="Optional title metadata for the new track")

    # ── concat ────────────────────────────────────────────────────────────────
    concat = sub.add_parser("concat", help="Concatenate clips (stream-copy when codecs match, re-encode otherwise)")
    concat.add_argument("--input", nargs="+", required=True)
    concat.add_argument("--output", required=True)
    concat.add_argument("--reencode", action="store_true",
                        help="Force re-encode via filter_complex concat.")

    # ── speed ─────────────────────────────────────────────────────────────────
    speed = sub.add_parser("speed", help="Speed up / slow down (factor > 1 speeds up; < 1 slows)")
    speed.add_argument("--input", required=True)
    speed.add_argument("--output", required=True)
    speed.add_argument("--factor", required=True, help="0.25 = quarter speed, 2 = double speed")

    # ── reverse ───────────────────────────────────────────────────────────────
    reverse = sub.add_parser("reverse", help="Play video backwards")
    reverse.add_argument("--input", required=True)
    reverse.add_argument("--output", required=True)
    reverse.add_argument("--reverse-audio", action="store_true", dest="reverse_audio",
                         help="Also reverse the audio (default keeps audio forward).")

    # ── lut3d ─────────────────────────────────────────────────────────────────
    lut = sub.add_parser("lut3d", help="Apply a 3D LUT (.cube) for colour grading")
    lut.add_argument("--input", required=True)
    lut.add_argument("--output", required=True)
    lut.add_argument("--lut", required=True, help="Path to a .cube LUT file")

    # ── hdr-to-sdr ────────────────────────────────────────────────────────────
    h2s = sub.add_parser("hdr-to-sdr", help="Tone-map HDR (BT.2020/HLG/PQ) -> SDR (BT.709)")
    h2s.add_argument("--input", required=True)
    h2s.add_argument("--output", required=True)

    # ── timeline ──────────────────────────────────────────────────────────────
    timeline = sub.add_parser("timeline",
                              help="Extract a thumbnail strip + waveform image for the UI scrub bar")
    timeline.add_argument("--input", required=True)
    timeline.add_argument("--output-dir", required=True, dest="output_dir")
    timeline.add_argument("--thumb-fps", type=float, default=1.0, dest="thumb_fps",
                          help="Thumbnails per second (default 1.0).")
    timeline.add_argument("--thumb-height", type=int, default=72, dest="thumb_height",
                          help="Thumbnail height in pixels (default 72).")
    timeline.add_argument("--waveform-width", type=int, default=2400, dest="waveform_width",
                          help="Waveform image width in pixels (default 2400).")
    timeline.add_argument("--waveform-height", type=int, default=80, dest="waveform_height",
                          help="Waveform image height in pixels (default 80).")
    timeline.add_argument("--waveform-color", default="0x6dd3ff", dest="waveform_color",
                          help="Waveform fill colour (default brand cyan).")

    # ── vmaf ──────────────────────────────────────────────────────────────────
    vmaf = sub.add_parser("vmaf",
                          help="VMAF quality comparison: distorted vs. reference (libvmaf)")
    vmaf.add_argument("--reference", required=True,
                      help="Reference (high-quality master) video.")
    vmaf.add_argument("--distorted", required=True,
                      help="Distorted (compressed / re-encoded) video to score.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "trim":
            return op_trim(args)
        if args.op == "crop":
            return op_crop(args)
        if args.op == "rotate":
            return op_rotate(args)
        if args.op == "loudnorm":
            return op_loudnorm(args)
        if args.op == "rewrap":
            return op_rewrap(args)
        if args.op == "vmaf":
            return op_vmaf(args)
        if args.op == "timeline":
            return op_timeline(args)
        if args.op == "track-list":
            return op_track_list(args)
        if args.op == "track-remove":
            return op_track_remove(args)
        if args.op == "track-add":
            return op_track_add(args)
        if args.op == "concat":
            return op_concat(args)
        if args.op == "speed":
            return op_speed(args)
        if args.op == "reverse":
            return op_reverse(args)
        if args.op == "lut3d":
            return op_lut(args)
        if args.op == "hdr-to-sdr":
            return op_hdr_to_sdr(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
