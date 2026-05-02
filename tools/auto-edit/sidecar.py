"""auto-edit sidecar — automatic silence-removal wrapper around `auto-editor`.

ROADMAP Item 73. Wraps the auto-editor CLI (Apache 2.0, written in Python +
Nim) which detects silence + low-motion regions in a video / audio file and
cuts them out (or speeds them up) using configurable thresholds.

Subcommands:
  silence-remove   Cut every region below the audio threshold.
  motion-edit      Use motion + audio thresholds together (videos).
  speedup-quiet    Keep silent regions but render them at a higher speed.
  probe            Report whether auto-editor is on PATH and its version.

Standard NDJSON contract: progress / log / complete / error events on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
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


# ── auto-editor discovery ────────────────────────────────────────────────────

def _find_auto_editor() -> str | None:
    """Return the auto-editor executable path. PATH wins; falls back to a
    bundled `auto-editor.exe` next to this sidecar."""
    candidates: list[str | None] = [
        os.environ.get("AUTO_EDITOR_PATH"),
        shutil.which("auto-editor"),
    ]
    here = Path(__file__).resolve().parent
    candidates += [
        str(here / "auto-editor.exe"),
        str(here.parent / "_bin" / "auto-editor.exe"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


# ── Bootstrap ────────────────────────────────────────────────────────────────

def _ensure_auto_editor() -> str | None:
    """Best-effort `pip install auto-editor` when missing. Frozen-PyInstaller
    short-circuits — pip-from-frozen-exe forks indefinitely."""
    if (binary := _find_auto_editor()):
        return binary

    if getattr(sys, "frozen", False):
        return None

    log("info", "auto-editor not found — installing...")
    for extra in [[], ["--user"], ["--break-system-packages"]]:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "auto-editor>=27.0.0", *extra],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return _find_auto_editor()
    return None


# ── Run wrapper ──────────────────────────────────────────────────────────────

_PROGRESS_RE = re.compile(r"(\d{1,3})%")


def _run_auto_editor(cmd: list[str], stage: str) -> int:
    """Invoke auto-editor and translate its stderr percent updates into
    NDJSON `progress` events. auto-editor uses a TTY-style progress bar
    so we parse the percentage and ignore the rest."""
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    last_pct = -1
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            m = _PROGRESS_RE.search(line)
            if m:
                pct = int(m.group(1))
                if pct - last_pct >= 1 and 0 <= pct <= 100:
                    last_pct = pct
                    emit("progress", percent=pct, stage=stage, eta_seconds=None)
                    continue
            log("info", line)
    finally:
        proc.wait()
    return proc.returncode


# ── Ops ──────────────────────────────────────────────────────────────────────

def op_silence_remove(args: argparse.Namespace) -> int:
    binary = _ensure_auto_editor()
    if not binary:
        return fail("missing_auto_editor",
                    "auto-editor is not installed. `pip install auto-editor`, or "
                    "drop auto-editor.exe next to this sidecar / under tools/_bin/.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    threshold = max(0.0, min(1.0, args.threshold))
    margin = args.margin or "0.2sec"
    cmd = [binary, str(src),
           "--edit", f"audio:threshold={threshold}",
           "--margin", margin,
           "--output", str(out_path)]
    if args.no_open:
        cmd.append("--no-open")
    log("info", f"silence-remove threshold={threshold} margin={margin}")
    emit("progress", percent=0, stage="silence-remove", eta_seconds=None)
    rc = _run_auto_editor(cmd, "silence-remove")
    if rc != 0:
        return fail("auto_editor_failed", f"auto-editor exited {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_motion_edit(args: argparse.Namespace) -> int:
    binary = _ensure_auto_editor()
    if not binary:
        return fail("missing_auto_editor",
                    "auto-editor is not installed. `pip install auto-editor`.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    audio_threshold = max(0.0, min(1.0, args.audio_threshold))
    motion_threshold = max(0.0, min(1.0, args.motion_threshold))
    expr = f"(or audio:threshold={audio_threshold} motion:threshold={motion_threshold})"
    cmd = [binary, str(src),
           "--edit", expr,
           "--margin", args.margin or "0.2sec",
           "--output", str(out_path)]
    if args.no_open:
        cmd.append("--no-open")
    log("info", f"motion-edit audio={audio_threshold} motion={motion_threshold}")
    emit("progress", percent=0, stage="motion-edit", eta_seconds=None)
    rc = _run_auto_editor(cmd, "motion-edit")
    if rc != 0:
        return fail("auto_editor_failed", f"auto-editor exited {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_speedup_quiet(args: argparse.Namespace) -> int:
    binary = _ensure_auto_editor()
    if not binary:
        return fail("missing_auto_editor",
                    "auto-editor is not installed. `pip install auto-editor`.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    threshold = max(0.0, min(1.0, args.threshold))
    silent_speed = max(1.0, min(99999.0, args.silent_speed))
    cmd = [binary, str(src),
           "--edit", f"audio:threshold={threshold}",
           "--silent-speed", str(silent_speed),
           "--output", str(out_path)]
    if args.no_open:
        cmd.append("--no-open")
    log("info", f"speedup-quiet threshold={threshold} silent_speed={silent_speed}x")
    emit("progress", percent=0, stage="speedup-quiet", eta_seconds=None)
    rc = _run_auto_editor(cmd, "speedup-quiet")
    if rc != 0:
        return fail("auto_editor_failed", f"auto-editor exited {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_probe(_args: argparse.Namespace) -> int:
    binary = _find_auto_editor()
    if not binary:
        emit("log", level="warn", message="auto-editor is not on PATH and not bundled.")
        emit("complete", output="", size_bytes=0,
             auto_editor_path=None, auto_editor_version=None)
        return 0
    try:
        result = subprocess.run([binary, "--version"],
                                capture_output=True, text=True, timeout=15)
        version = (result.stdout or result.stderr or "").strip()
    except Exception as ex:
        version = f"probe-failed: {type(ex).__name__}"
    log("info", f"auto-editor at {binary} ({version})")
    emit("complete", output=binary, size_bytes=0,
         auto_editor_path=binary, auto_editor_version=version)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="auto-edit-sidecar",
                                description="Automatic silence / motion removal wrapper around auto-editor.")
    sub = p.add_subparsers(dest="op", required=True)

    sr = sub.add_parser("silence-remove", help="Cut every region below the audio threshold.")
    sr.add_argument("--input", required=True)
    sr.add_argument("--output", required=True)
    sr.add_argument("--threshold", type=float, default=0.04,
                    help="Audio loudness threshold 0..1 (default 0.04).")
    sr.add_argument("--margin", default="0.2sec",
                    help="Pre/post-margin around kept regions (default 0.2sec). "
                         "Accepts auto-editor's time DSL (e.g. '5', '0.2sec', '1.5sec').")
    sr.add_argument("--no-open", action="store_true", default=True,
                    help="Skip auto-editor's auto-open behaviour (default true).")

    me = sub.add_parser("motion-edit",
                        help="Cut regions that are quiet AND have low visible motion.")
    me.add_argument("--input", required=True)
    me.add_argument("--output", required=True)
    me.add_argument("--audio-threshold", type=float, default=0.04, dest="audio_threshold")
    me.add_argument("--motion-threshold", type=float, default=0.02, dest="motion_threshold")
    me.add_argument("--margin", default="0.2sec")
    me.add_argument("--no-open", action="store_true", default=True)

    sp = sub.add_parser("speedup-quiet",
                        help="Keep silent regions but render them at a higher speed.")
    sp.add_argument("--input", required=True)
    sp.add_argument("--output", required=True)
    sp.add_argument("--threshold", type=float, default=0.04)
    sp.add_argument("--silent-speed", type=float, default=99999.0, dest="silent_speed",
                    help="Multiplier applied to silent regions (default 99999 = effectively cut).")
    sp.add_argument("--no-open", action="store_true", default=True)

    sub.add_parser("probe", help="Report whether auto-editor is installed and its version.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "silence-remove": return op_silence_remove(args)
        if args.op == "motion-edit":    return op_motion_edit(args)
        if args.op == "speedup-quiet":  return op_speedup_quiet(args)
        if args.op == "probe":          return op_probe(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
