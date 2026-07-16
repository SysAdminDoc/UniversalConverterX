"""SceneDetect sidecar -- NDJSON CLI shim for the UCX scene-detection workflow.

Wraps PySceneDetect 0.6.x. Emits one `scene` event per detected cut, plus
optional CSV / EDL CMX 3600 / OTIO export so the result can drop straight into
DaVinci Resolve, Premiere Pro, or ClipForge batch trim.

Detectors:
  content   ContentDetector (HSV + edge thresholding -- the default; fast and
            tuned for general scene cuts).
  threshold ThresholdDetector (raw pixel-difference -- catches fades + black
            frames the content detector misses).

Frozen-guard: this sidecar does NOT call pip at runtime. PyInstaller bundles
PySceneDetect at build time -- so the fork-bomb pattern that bit lipsight et al
during the v2.3 audit can't recur here.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import (
    emit,
    find_ffmpeg,
    find_ffprobe,
    probe_media,
    run_ffmpeg as shared_run_ffmpeg,
)




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def detect_scenes(args: argparse.Namespace) -> int:
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector, ThresholdDetector
    except ImportError:
        return fail(
            "missing_scenedetect",
            "PySceneDetect is not installed. Run pwsh tools/scenedetect/build.ps1 to set up the sidecar.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")

    emit("log", level="info", message=f"Open video: {src.name}")
    try:
        video = open_video(str(src))
    except Exception as ex:  # PySceneDetect raises specific exceptions; re-emit cleanly.
        return fail("open_failed", f"Could not open video: {ex}")

    mgr = SceneManager()
    if args.detector == "threshold":
        mgr.add_detector(ThresholdDetector(threshold=args.threshold,
                                           min_scene_len=args.min_scene_len))
    else:
        mgr.add_detector(ContentDetector(threshold=args.threshold,
                                         min_scene_len=args.min_scene_len))

    started = time.monotonic()
    last_pct = -1.0

    def _progress_callback(frame_im, frame_num):
        nonlocal last_pct
        try:
            total = video.duration.get_frames() or 1
        except Exception:
            total = 1
        pct = max(0.0, min(100.0, frame_num / total * 100.0))
        if pct - last_pct >= 0.5:
            last_pct = pct
            elapsed = time.monotonic() - started
            local = pct / 100.0
            eta = (elapsed / local - elapsed) if local > 0.01 else None
            emit("progress",
                 percent=round(pct, 1),
                 stage="detect",
                 eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("progress", percent=0, stage="detect", eta_seconds=None)
    mgr.detect_scenes(video=video, callback=_progress_callback,
                      show_progress=False)
    scenes = mgr.get_scene_list()

    rows = []
    for i, (start, end) in enumerate(scenes):
        rec = {
            "index":         i,
            "start_seconds": round(start.get_seconds(), 3),
            "end_seconds":   round(end.get_seconds(), 3),
            "start_frame":   start.get_frames(),
            "end_frame":     end.get_frames(),
            "start_tc":      start.get_timecode(),
            "end_tc":        end.get_timecode(),
        }
        rows.append(rec)
        emit("scene", **rec)

    emit("progress", percent=100, stage="detect", eta_seconds=0)

    # Optional persistent exports
    if args.output_csv:
        out_csv = Path(args.output_csv)
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        with out_csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["index", "start_tc", "end_tc",
                        "start_seconds", "end_seconds",
                        "start_frame", "end_frame"])
            for r in rows:
                w.writerow([r["index"], r["start_tc"], r["end_tc"],
                            r["start_seconds"], r["end_seconds"],
                            r["start_frame"], r["end_frame"]])
        emit("log", level="info", message=f"CSV: {out_csv}")

    if args.output_edl:
        out_edl = Path(args.output_edl)
        out_edl.parent.mkdir(parents=True, exist_ok=True)
        # Minimal CMX 3600 EDL -- one event per scene, V (video) only.
        with out_edl.open("w", encoding="utf-8") as fh:
            fh.write(f"TITLE: {src.stem}\n")
            fh.write("FCM: NON-DROP FRAME\n\n")
            for r in rows:
                idx = f"{r['index'] + 1:03d}"
                fh.write(f"{idx}  AX       V     C        "
                         f"{r['start_tc']} {r['end_tc']} "
                         f"{r['start_tc']} {r['end_tc']}\n")
                fh.write(f"* FROM CLIP NAME: {src.name}\n\n")
        emit("log", level="info", message=f"EDL: {out_edl}")

    out_path = args.output_csv or args.output_edl or ""
    out_size = Path(out_path).stat().st_size if out_path and Path(out_path).is_file() else 0
    emit("complete",
         output=out_path,
         size_bytes=out_size,
         scenes=len(rows))
    return 0


def rank_highlight_candidates(
    scenes: list[dict],
    motion_by_frame: dict[int, float],
    *,
    fps: float,
    duration: float,
    clip_length: float,
    top_n: int,
    min_gap: float,
) -> list[dict]:
    """Rank frame-aligned windows using cut strength and visible motion."""
    if not scenes or fps <= 0 or duration <= 0:
        return []
    clip_length = max(1.0, min(float(clip_length), duration))
    unique: dict[tuple[int, int], dict] = {}
    anchors = [
        (
            (float(scene["start_seconds"]) + float(scene["end_seconds"])) / 2.0,
            float(scene.get("cut_peak", 0.0)),
        )
        for scene in scenes
    ]
    strongest_motion = sorted(
        motion_by_frame.items(), key=lambda item: (-item[1], item[0]))[
            : max(10, min(len(motion_by_frame), top_n * 8))
        ]
    anchors.extend((frame / fps, 0.0) for frame, energy in strongest_motion if energy > 0)
    for anchor, fallback_peak in anchors:
        start = max(0.0, min(anchor - clip_length / 2.0, duration - clip_length))
        start_frame = max(0, int(round(start * fps)))
        end_frame = min(int(round(duration * fps)), start_frame + max(1, int(round(clip_length * fps))))
        if end_frame <= start_frame:
            continue
        start = start_frame / fps
        end = min(duration, end_frame / fps)
        peaks = [
            float(item.get("cut_peak", 0.0))
            for item in scenes
            if start_frame <= int(item["start_frame"]) < end_frame
        ]
        motion = [
            value for frame, value in motion_by_frame.items()
            if start_frame <= frame < end_frame
        ]
        candidate = {
            "start_seconds": start,
            "end_seconds": end,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "scene_peak": max(peaks, default=fallback_peak),
            "motion_energy": sum(motion) / len(motion) if motion else 0.0,
        }
        key = (start_frame, end_frame)
        previous = unique.get(key)
        if previous is None or candidate["scene_peak"] > previous["scene_peak"]:
            unique[key] = candidate

    candidates = list(unique.values())
    max_peak = max((item["scene_peak"] for item in candidates), default=0.0)
    max_motion = max((item["motion_energy"] for item in candidates), default=0.0)
    if max_peak <= 0 and max_motion <= 0:
        return []
    for item in candidates:
        peak_norm = item["scene_peak"] / max_peak if max_peak > 0 else 0.0
        motion_norm = item["motion_energy"] / max_motion if max_motion > 0 else 0.0
        item["score"] = round((0.55 * peak_norm + 0.45 * motion_norm) * 100.0, 1)
        if peak_norm >= 0.6 and motion_norm >= 0.6:
            item["reason"] = "Strong transition and high motion"
        elif motion_norm >= peak_norm:
            item["reason"] = "High visible motion"
        else:
            item["reason"] = "Strong scene transition"

    candidates.sort(key=lambda item: (-item["score"], item["start_frame"]))
    selected: list[dict] = []
    gap_frames = max(0, int(round(min_gap * fps)))
    for candidate in candidates:
        if candidate["score"] <= 0:
            continue
        if any(
            candidate["start_frame"] < picked["end_frame"] + gap_frames
            and candidate["end_frame"] > picked["start_frame"] - gap_frames
            for picked in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= max(1, min(int(top_n), 20)):
            break
    for rank, item in enumerate(selected, 1):
        item["rank"] = rank
        for key in ("start_seconds", "end_seconds", "scene_peak", "motion_energy"):
            item[key] = round(float(item[key]), 6)
    return selected


def measure_motion_energy(source: Path, cv2, *, fps: float, total_frames: int) -> dict[int, float]:
    """Sample visible frame deltas at up to 10 fps on a tiny grayscale raster."""
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        return {}
    sample_step = max(1, int(round(fps / 10.0)))
    motion: dict[int, float] = {}
    previous_gray = None
    frame_number = 0
    last_percent = -1.0
    try:
        while True:
            available, frame = capture.read()
            if not available:
                break
            if frame_number % sample_step == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                small = cv2.resize(gray, (96, 54), interpolation=cv2.INTER_AREA)
                motion[frame_number] = 0.0 if previous_gray is None \
                    else float(cv2.absdiff(previous_gray, small).mean() / 255.0)
                previous_gray = small
            percent = 42.0 + min(40.0, frame_number / max(1, total_frames) * 40.0)
            if percent - last_percent >= 1.0:
                last_percent = percent
                emit(
                    "progress", percent=round(percent, 1), stage="measuring motion energy",
                    eta_seconds=None,
                )
            frame_number += 1
    finally:
        capture.release()
    return motion


def _timecode_from_frame(frame: int, fps: float) -> str:
    nominal = max(1, int(round(fps)))
    frames = max(0, int(frame))
    hours, frames = divmod(frames, nominal * 3600)
    minutes, frames = divmod(frames, nominal * 60)
    seconds, frames = divmod(frames, nominal)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def write_highlight_edl(path: Path, source: Path, highlights: list[dict], fps: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record_frame = 0
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(f"TITLE: {source.stem}_highlights\n")
        stream.write("FCM: NON-DROP FRAME\n\n")
        for index, item in enumerate(sorted(highlights, key=lambda row: row["start_frame"]), 1):
            source_in = int(item["start_frame"])
            source_out = int(item["end_frame"])
            duration = max(1, source_out - source_in)
            record_out = record_frame + duration
            stream.write(
                f"{index:03d}  AX       V     C        "
                f"{_timecode_from_frame(source_in, fps)} {_timecode_from_frame(source_out, fps)} "
                f"{_timecode_from_frame(record_frame, fps)} {_timecode_from_frame(record_out, fps)}\n"
            )
            stream.write(f"* FROM CLIP NAME: {source.name}\n")
            stream.write(f"* UCX HIGHLIGHT SCORE: {float(item.get('score', 0.0)):.1f}\n\n")
            record_frame = record_out


def write_highlight_otio(path: Path, source: Path, highlights: list[dict], fps: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    children = []
    for item in sorted(highlights, key=lambda row: row["start_frame"]):
        start_frame = int(item["start_frame"])
        duration_frames = max(1, int(item["end_frame"]) - start_frame)
        children.append({
            "OTIO_SCHEMA": "Clip.2",
            "name": f"Highlight {int(item.get('rank', len(children) + 1))}",
            "metadata": {
                "ucx_highlight_score": float(item.get("score", 0.0)),
                "ucx_highlight_reason": str(item.get("reason", "")),
            },
            "source_range": {
                "OTIO_SCHEMA": "TimeRange.1",
                "start_time": {"OTIO_SCHEMA": "RationalTime.1", "value": start_frame, "rate": fps},
                "duration": {"OTIO_SCHEMA": "RationalTime.1", "value": duration_frames, "rate": fps},
            },
            "media_reference": {
                "OTIO_SCHEMA": "ExternalReference.1",
                "name": source.name,
                "metadata": {},
                "target_url": source.resolve().as_uri(),
                "available_range": None,
            },
            "effects": [],
            "markers": [],
            "enabled": True,
        })
    payload = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": f"{source.stem} Highlights",
        "metadata": {"generator": "UniversalConverterX Auto Highlight"},
        "global_start_time": None,
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "metadata": {},
            "effects": [],
            "markers": [],
            "children": [{
                "OTIO_SCHEMA": "Track.1",
                "name": "Highlights",
                "metadata": {},
                "effects": [],
                "markers": [],
                "kind": "Video",
                "children": children,
            }],
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _parse_rate(value: str | None, fallback: float = 30.0) -> float:
    try:
        if value and "/" in value:
            numerator, denominator = value.split("/", 1)
            rate = float(numerator) / float(denominator)
        else:
            rate = float(value or fallback)
        return rate if math.isfinite(rate) and rate > 0 else fallback
    except (TypeError, ValueError, ZeroDivisionError):
        return fallback


def _probe_source(source: Path) -> tuple[dict | None, float, float, bool]:
    ffprobe = find_ffprobe(Path(__file__).resolve().parent)
    if not ffprobe:
        return None, 30.0, 0.0, False
    payload = probe_media(ffprobe, source)
    if not payload:
        return None, 30.0, 0.0, False
    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    rate = _parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    try:
        duration = float((payload.get("format") or {}).get("duration") or video.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    has_audio = any(item.get("codec_type") == "audio" for item in streams)
    return payload, rate, duration, has_audio


def parse_highlight_ranges(raw: str, *, fps: float, duration: float) -> list[dict]:
    if len(raw) > 65_536:
        raise ValueError("Highlight range payload is too large")
    payload = json.loads(raw)
    if not isinstance(payload, list) or not payload or len(payload) > 100:
        raise ValueError("Highlight ranges must be a non-empty list of at most 100 items")
    result = []
    for index, item in enumerate(payload, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Highlight range {index} is not an object")
        start = float(item.get("start_seconds", item.get("start", -1)))
        end = float(item.get("end_seconds", item.get("end", -1)))
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError(f"Highlight range {index} is invalid")
        if duration > 0 and end > duration + 0.05:
            raise ValueError(f"Highlight range {index} exceeds the source duration")
        start_frame = int(item.get("start_frame", round(start * fps)))
        end_frame = int(item.get("end_frame", round(end * fps)))
        if start_frame < 0 or end_frame <= start_frame:
            raise ValueError(f"Highlight range {index} has invalid frame bounds")
        if duration > 0 and end_frame / fps > duration + 0.05:
            raise ValueError(f"Highlight range {index} exceeds the source duration")
        result.append({
            "rank": int(item.get("rank", index)),
            "start_seconds": start_frame / fps,
            "end_seconds": end_frame / fps,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "score": float(item.get("score", 0.0)),
            "reason": str(item.get("reason", "Selected highlight"))[:200],
        })
    return result


def extract_highlight_reel(source: Path, output: Path, highlights: list[dict], has_audio: bool) -> tuple[bool, str]:
    ffmpeg = find_ffmpeg(Path(__file__).resolve().parent)
    if not ffmpeg:
        return False, "FFmpeg is not installed; it is required to render a highlight reel."
    if source.resolve() == output.resolve():
        return False, "Highlight output must not overwrite the source video."
    output.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(highlights, key=lambda item: item["start_seconds"])
    filters: list[str] = []
    labels: list[str] = []
    for index, item in enumerate(ordered):
        start = float(item["start_seconds"])
        end = float(item["end_seconds"])
        filters.append(f"[0:v:0]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{index}]")
        labels.append(f"[v{index}]")
        if has_audio:
            filters.append(f"[0:a:0]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{index}]")
            labels.append(f"[a{index}]")
    if has_audio:
        filters.append("".join(labels) + f"concat=n={len(ordered)}:v=1:a=1[outv][outa]")
    else:
        filters.append("".join(labels) + f"concat=n={len(ordered)}:v=1:a=0[outv]")
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-filter_complex", ";".join(filters), "-map", "[outv]",
    ]
    if has_audio:
        command += ["-map", "[outa]"]
    command += [
        "-map_metadata", "0", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
    ]
    if has_audio:
        command += ["-c:a", "aac", "-b:a", "192k"]
    command += ["-movflags", "+faststart", str(output)]
    total_duration = sum(float(item["end_seconds"]) - float(item["start_seconds"]) for item in ordered)
    code = shared_run_ffmpeg(
        command, total_duration, "render highlights", event_emitter=emit,
        start_percent=90.0, end_percent=100.0, completion_stage="highlight reel ready")
    if code != 0:
        output.unlink(missing_ok=True)
        return False, f"FFmpeg highlight rendering exited with code {code}."
    if not output.is_file() or output.stat().st_size <= 0:
        return False, "FFmpeg did not produce the highlight reel."
    return True, ""


def export_highlights(
    source: Path,
    highlights: list[dict],
    *,
    fps: float,
    has_audio: bool,
    output_reel: str | None = None,
    output_edl: str | None = None,
    output_otio: str | None = None,
    output_json: str | None = None,
) -> tuple[bool, str, str]:
    outputs: list[Path] = []
    if output_edl:
        path = Path(output_edl)
        write_highlight_edl(path, source, highlights, fps)
        outputs.append(path)
    if output_otio:
        path = Path(output_otio)
        write_highlight_otio(path, source, highlights, fps)
        outputs.append(path)
    if output_json:
        path = Path(output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(highlights, indent=2) + "\n", encoding="utf-8")
        outputs.append(path)
    if output_reel:
        path = Path(output_reel)
        success, diagnostic = extract_highlight_reel(source, path, highlights, has_audio)
        if not success:
            return False, diagnostic, ""
        outputs.append(path)
    output = str(outputs[-1]) if outputs else ""
    return True, "", output


def detect_highlights(args: argparse.Namespace) -> int:
    source = Path(args.input)
    if not source.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    try:
        import cv2
        from scenedetect import open_video, SceneManager, StatsManager
        from scenedetect.detectors import ContentDetector
    except ImportError:
        return fail(
            "missing_scenedetect",
            "PySceneDetect with OpenCV is not installed. Run pwsh tools/scenedetect/build.ps1.",
        )
    try:
        video = open_video(str(source))
    except Exception as exc:
        return fail("open_failed", f"Could not open video: {exc}")
    fps = float(video.frame_rate)
    duration = float(video.duration.get_seconds())
    stats = StatsManager()
    manager = SceneManager(stats_manager=stats)
    manager.add_detector(ContentDetector(threshold=args.threshold, min_scene_len=args.min_scene_len))
    started = time.monotonic()
    last_percent = -1.0

    def callback(frame_image, frame_number):
        nonlocal last_percent
        number = frame_number.get_frames() if hasattr(frame_number, "get_frames") else int(frame_number)
        total = max(1, int(video.duration.get_frames()))
        percent = min(40.0, number / total * 40.0)
        if percent - last_percent >= 0.5:
            last_percent = percent
            elapsed = time.monotonic() - started
            local = percent / 40.0
            eta = elapsed / local - elapsed if local > 0.01 else None
            emit(
                "progress", percent=round(percent, 1), stage="detecting scene changes",
                eta_seconds=int(eta) if eta and eta < 86400 else None,
            )

    emit("progress", percent=0.0, stage="detecting scene changes", eta_seconds=None)
    manager.detect_scenes(video=video, callback=callback, show_progress=False)
    detected = manager.get_scene_list(start_in_scene=True)
    scenes = []
    for start, end in detected:
        frame = int(start.get_frames())
        try:
            metrics = stats.get_metrics(frame, ["content_val"])
            cut_peak = float(metrics[0] or 0.0) if metrics else 0.0
        except Exception:
            cut_peak = 0.0
        scenes.append({
            "start_seconds": float(start.get_seconds()),
            "end_seconds": float(end.get_seconds()),
            "start_frame": frame,
            "end_frame": int(end.get_frames()),
            "cut_peak": cut_peak,
        })
    motion_by_frame = measure_motion_energy(
        source, cv2, fps=fps, total_frames=max(1, int(video.duration.get_frames())))
    emit("progress", percent=86.0, stage="ranking highlight windows", eta_seconds=None)
    highlights = rank_highlight_candidates(
        scenes, motion_by_frame, fps=fps, duration=duration,
        clip_length=args.clip_length, top_n=args.top_n, min_gap=args.min_gap)
    if not highlights:
        return fail(
            "no_highlights",
            "No strong scene-change or motion candidates were found. Try a lower threshold or longer clip.",
        )
    for item in highlights:
        emit("highlight", **item)
    probe_payload, _, _, has_audio = _probe_source(source)
    if args.output_reel and probe_payload is None:
        return fail("missing_ffprobe", "FFprobe could not inspect the source video before rendering.")
    success, diagnostic, output = export_highlights(
        source, highlights, fps=fps, has_audio=has_audio,
        output_reel=args.output_reel, output_edl=args.output_edl,
        output_otio=args.output_otio, output_json=args.output_json)
    if not success:
        return fail("render_failed", diagnostic)
    emit("progress", percent=100.0, stage="done", eta_seconds=0)
    size = Path(output).stat().st_size if output and Path(output).is_file() else 0
    emit("complete", output=output, size_bytes=size, highlights=len(highlights))
    return 0


def render_highlights(args: argparse.Namespace) -> int:
    source = Path(args.input)
    if not source.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    if not any((args.output_reel, args.output_edl, args.output_otio, args.output_json)):
        return fail("missing_output", "Choose a reel, EDL, OTIO, or JSON output path.")
    payload, fps, duration, has_audio = _probe_source(source)
    if payload is None:
        return fail("missing_ffprobe", "FFprobe could not inspect the source video.")
    try:
        highlights = parse_highlight_ranges(args.ranges_json, fps=fps, duration=duration)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return fail("invalid_ranges", str(exc))
    success, diagnostic, output = export_highlights(
        source, highlights, fps=fps, has_audio=has_audio,
        output_reel=args.output_reel, output_edl=args.output_edl,
        output_otio=args.output_otio, output_json=args.output_json)
    if not success:
        return fail("render_failed", diagnostic)
    size = Path(output).stat().st_size if output and Path(output).is_file() else 0
    emit("complete", output=output, size_bytes=size, highlights=len(highlights))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scenedetect-sidecar",
                                description="UCX scene detection sidecar (PySceneDetect).")
    sub = p.add_subparsers(dest="op", required=True)

    det = sub.add_parser("detect", help="Detect scene cuts in a video")
    det.add_argument("--input", required=True)
    det.add_argument("--detector", choices=["content", "threshold"],
                     default="content",
                     help="content (default) = HSV+edge; threshold = raw pixel diff")
    det.add_argument("--threshold", type=float, default=27.0,
                     help="Detector sensitivity. Lower = more cuts (default 27).")
    det.add_argument("--min-scene-len", type=int, default=15, dest="min_scene_len",
                     help="Minimum scene length in frames (default 15).")
    det.add_argument("--output-csv",
                     help="Optional CSV export path.")
    det.add_argument("--output-edl",
                     help="Optional CMX 3600 EDL export path (DaVinci Resolve / Premiere Pro).")

    highlights = sub.add_parser(
        "highlights", help="Rank scene-change and motion-energy windows and optionally render them.")
    highlights.add_argument("--input", required=True)
    highlights.add_argument("--threshold", type=float, default=27.0)
    highlights.add_argument("--min-scene-len", type=int, default=15, dest="min_scene_len")
    highlights.add_argument("--clip-length", type=float, default=12.0, dest="clip_length")
    highlights.add_argument("--top-n", type=int, choices=range(1, 21), default=5, dest="top_n")
    highlights.add_argument("--min-gap", type=float, default=2.0, dest="min_gap")
    highlights.add_argument("--output", "--output-reel", dest="output_reel")
    highlights.add_argument("--output-edl")
    highlights.add_argument("--output-otio")
    highlights.add_argument("--output-json")

    render = sub.add_parser("render", help="Export reviewed highlight ranges without re-analysis.")
    render.add_argument("--input", required=True)
    render.add_argument("--ranges-json", required=True)
    render.add_argument("--output", "--output-reel", dest="output_reel")
    render.add_argument("--output-edl")
    render.add_argument("--output-otio")
    render.add_argument("--output-json")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "detect":
            return detect_scenes(args)
        if args.op == "highlights":
            return detect_highlights(args)
        if args.op == "render":
            return render_highlights(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
