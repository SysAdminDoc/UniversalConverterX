"""Audio normalization profiles — LUFS-based two-pass loudnorm (F62).

Named profiles with target integrated loudness (LUFS), true peak (dBTP),
and loudness range (LRA). Two-pass processing: first pass measures, second
pass applies with measured values for optimal results.

Profiles:
  - Broadcast:  -24 LUFS, -2.0 dBTP (EBU R128)
  - Podcast:    -16 LUFS, -1.5 dBTP
  - YouTube:    -14 LUFS, -1.0 dBTP
  - Streaming:  -18 LUFS, -1.5 dBTP
  - Custom:     user-specified values
"""

import json
import os
import re
import subprocess

from ..paths import _CREATE_NO_WINDOW

BUILTIN_PROFILES = {
    "Broadcast (EBU R128)": {"I": -24, "TP": -2.0, "LRA": 7},
    "Podcast": {"I": -16, "TP": -1.5, "LRA": 11},
    "YouTube": {"I": -14, "TP": -1.0, "LRA": 11},
    "Streaming": {"I": -18, "TP": -1.5, "LRA": 11},
}


def normalize_two_pass(src, dst, *, target_i=-16, target_tp=-1.5,
                       target_lra=11, log_fn=None):
    """Two-pass EBU R128 loudness normalization.

    Pass 1: measure the source file's loudness characteristics.
    Pass 2: apply loudnorm with measured values for optimal normalization.

    Returns True on success.
    """
    if os.path.exists(dst):
        return True

    # Pass 1: measure
    if log_fn:
        log_fn(f"[NORM] Pass 1/2: measuring loudness of {os.path.basename(src)}")
    cmd1 = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", src,
        "-af", f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json",
        "-f", "null", "-",
    ]
    measured = _run_measure(cmd1)
    if not measured:
        # Fallback to single-pass
        if log_fn:
            log_fn("[NORM] Measurement failed, falling back to single-pass")
        return _single_pass(src, dst, target_i, target_tp, target_lra, log_fn)

    # Pass 2: apply with measured values
    if log_fn:
        log_fn(f"[NORM] Pass 2/2: normalizing to {target_i} LUFS")
    af = (
        f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}"
        f":measured_I={measured['input_i']}"
        f":measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}"
        f":measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}"
        f":linear=true"
    )
    cmd2 = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", src,
        "-af", af,
        "-c:v", "copy",
        dst,
    ]
    try:
        r = subprocess.run(
            cmd2, capture_output=True, timeout=600,
            creationflags=_CREATE_NO_WINDOW,
        )
        if r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0:
            if log_fn:
                log_fn(f"[NORM] Done: {os.path.basename(dst)}")
            return True
        if log_fn:
            log_fn(f"[NORM] Pass 2 failed: {r.stderr.decode('utf-8', errors='replace')[:200]}")
    except (subprocess.TimeoutExpired, OSError) as e:
        if log_fn:
            log_fn(f"[NORM] Pass 2 error: {e}")
    return False


def _run_measure(cmd):
    """Run ffmpeg loudnorm measurement and parse the JSON output."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=300,
            creationflags=_CREATE_NO_WINDOW,
        )
        stderr = r.stderr.decode("utf-8", errors="replace")
        # Find the JSON block in stderr
        json_match = re.search(r"\{[^}]*input_i[^}]*\}", stderr, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "input_i": float(data.get("input_i", -24)),
                "input_tp": float(data.get("input_tp", -2)),
                "input_lra": float(data.get("input_lra", 7)),
                "input_thresh": float(data.get("input_thresh", -34)),
                "target_offset": float(data.get("target_offset", 0)),
            }
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def _single_pass(src, dst, target_i, target_tp, target_lra, log_fn):
    """Fallback single-pass normalization."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", src,
        "-af", f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}",
        "-c:v", "copy",
        dst,
    ]
    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=600,
            creationflags=_CREATE_NO_WINDOW,
        )
        ok = r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0
        if ok and log_fn:
            log_fn(f"[NORM] Single-pass done: {os.path.basename(dst)}")
        return ok
    except (subprocess.TimeoutExpired, OSError):
        return False


def get_profile(name):
    """Return ``{I, TP, LRA}`` dict for a named profile."""
    return dict(BUILTIN_PROFILES.get(name, BUILTIN_PROFILES["Podcast"]))
