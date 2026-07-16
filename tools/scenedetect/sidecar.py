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
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




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
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "detect":
            return detect_scenes(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
