"""FFmpeg encoder — streams progress via stderr parsing.

Supports:
  - any Encoder from core.encoders (hardware or CPU)
  - quality slider (mapped into codec-native units)
  - speed preset
  - trim window (-ss / -t)
  - optional burn-in subtitle path
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .caption_styles import CaptionPreset, force_style_string, resolve as resolve_caption_preset
from .encoders import Encoder, encoder_args, pick_default
from .preflight import Preflight, plan_preflight
from .presets import Preset
from .probe import VideoInfo
from .reframe import ReframePlan


_PROGRESS_RE = re.compile(
    r"(?:time=|out_time=)(\d+):(\d+):(\d+(?:\.\d+)?)"
)

# How long to wait for a cooperative ``terminate()`` before escalating to
# ``kill()``. FFmpeg normally responds to SIGTERM by finalising the output
# (flush + trailer) within a second or two; after this budget we give up
# on a clean output file rather than hanging the app.
_TERMINATE_TIMEOUT_SEC = 3.0


def ffmpeg_bin() -> str:
    bin_path = shutil.which("ffmpeg")
    if not bin_path:
        raise RuntimeError("ffmpeg not found on PATH. Install FFmpeg.")
    return bin_path


@dataclass
class EncodeJob:
    info: VideoInfo
    preset: Preset
    plan: ReframePlan
    out_path: Path
    trim_start: float = 0.0
    trim_end: float | None = None     # None = full duration
    encoder: Encoder | None = None    # None = auto-pick best available
    quality: int = 75                 # 1..100 quality slider
    speed_preset: str | None = None   # encoder preset ("medium","p5",...)
    subtitles_path: Path | None = None   # burn this SRT/ASS into the video
    burn_subtitles: bool = False
    caption_preset_id: str | None = None  # resolved via caption_styles.resolve()
    # Optional animated-caption overlay (e.g. a pycaps RGBA video). When
    # set, this composites over the reframed main stream at 0,0 via
    # -filter_complex. Takes precedence over ``subtitles_path`` burn-in
    # because the overlay already carries its own per-word animation.
    overlay_video: Path | None = None

    def build_command(self) -> list[str]:
        cmd = [ffmpeg_bin(), "-y", "-hide_banner", "-stats", "-progress", "pipe:2"]

        preflight = plan_preflight(self.info, self.preset.fps)

        has_overlay = bool(self.overlay_video and Path(self.overlay_video).exists())

        # ---- main input
        if self.trim_start > 0:
            cmd += ["-ss", f"{self.trim_start:.3f}"]
        cmd += list(preflight.input_args)
        cmd += ["-i", str(self.info.path)]
        if self.trim_end is not None:
            duration = max(0.0, self.trim_end - self.trim_start)
            cmd += ["-t", f"{duration:.3f}"]

        # ---- overlay input (second -i, with matching trim window so
        #      its timeline lines up with the trimmed main stream)
        if has_overlay:
            if self.trim_start > 0:
                cmd += ["-ss", f"{self.trim_start:.3f}"]
            cmd += ["-i", str(self.overlay_video)]
            if self.trim_end is not None:
                duration = max(0.0, self.trim_end - self.trim_start)
                cmd += ["-t", f"{duration:.3f}"]

        # ---- video filter chain
        # The overlay path renders subtitles as part of the RGBA input,
        # so we skip the libass burn-in when an overlay is provided —
        # double-rendering would stack two copies of the captions.
        vf = self.plan.video_filter
        if (
            not has_overlay
            and self.burn_subtitles
            and self.subtitles_path
            and Path(self.subtitles_path).exists()
        ):
            vf = vf + "," + _subtitles_filter(
                self.subtitles_path,
                resolve_caption_preset(self.caption_preset_id),
                self.preset.height,
            )

        if has_overlay:
            # -filter_complex pipeline:
            #   [0:v] → reframe/scale chain → [base]
            #   [base][1:v] → overlay at 0,0 (both are already at the
            #                 target resolution) → [v]
            # Map [v] + main audio to the output.
            filter_complex = (
                f"[0:v]{vf}[base];"
                f"[base][1:v]overlay=0:0:format=auto:eof_action=pass[v]"
            )
            cmd += ["-filter_complex", filter_complex, "-map", "[v]"]
            if self.info.has_audio:
                cmd += ["-map", "0:a"]
        else:
            cmd += ["-vf", vf]

        enc = self.encoder or pick_default(codec="h264")
        if enc is None:
            enc_args = ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
        else:
            enc_args = encoder_args(enc, self.quality, self.speed_preset)
        cmd += enc_args

        cmd += [
            "-b:v", self.preset.video_bitrate,
            "-maxrate", self.preset.video_bitrate,
            "-bufsize", _double_bitrate(self.preset.video_bitrate),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-r", str(self.preset.fps),
        ]

        if self.info.has_audio:
            cmd += ["-c:a", "aac", "-b:a", self.preset.audio_bitrate, "-ar", "48000"]
        else:
            cmd += ["-an"]

        cmd += list(preflight.output_args)

        cmd += [str(self.out_path)]
        return cmd


def run(job: EncodeJob, on_progress=None, on_log=None, cancel_cb=None) -> int:
    """Run the encode. Returns FFmpeg exit code.

    Cancel contract:
        ``cancel_cb`` is polled on every stderr line. When it flips True
        we issue ``proc.terminate()``, then ``wait(timeout)``, and finally
        ``proc.kill()`` if FFmpeg doesn't cooperate. This guarantees the
        call returns promptly; stuck FFmpeg subprocesses never outlive
        this function.
    """
    job.out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = job.build_command()
    if on_log:
        on_log("$ " + " ".join(_quote(c) for c in cmd))

    duration = _duration(job)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_no_window_flags(),
    )
    cancelled = False
    try:
        assert proc.stderr is not None
        for line in proc.stderr:
            line = line.rstrip()
            if not line:
                continue
            if cancel_cb and cancel_cb():
                cancelled = True
                _terminate(proc)
                break
            if on_log:
                on_log(line)
            if on_progress and duration > 0:
                m = _PROGRESS_RE.search(line)
                if m:
                    h, mnt, sec = m.groups()
                    t = int(h) * 3600 + int(mnt) * 60 + float(sec)
                    on_progress(min(1.0, t / duration))
    finally:
        rc = _reap(proc, cancelled)

    if on_progress:
        on_progress(1.0)
    return rc


# ---------------------------------------------------------- helpers

def _terminate(proc: subprocess.Popen) -> None:
    """Ask FFmpeg to stop. Idempotent — safe to call twice."""
    try:
        proc.terminate()
    except Exception:
        pass


def _reap(proc: subprocess.Popen, cancelled: bool) -> int:
    """Wait for the subprocess to exit, escalating to kill on timeout.

    Returns the final exit code. On cancel we force a non-zero return so
    the worker can distinguish cancelled-but-exited from successful exit.
    """
    try:
        if cancelled:
            # First give FFmpeg a chance to finalise cleanly.
            try:
                return proc.wait(timeout=_TERMINATE_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    return proc.wait(timeout=_TERMINATE_TIMEOUT_SEC)
                except subprocess.TimeoutExpired:
                    # Still stuck — abandon. Callers treat non-zero as
                    # failure; the zombie will be reaped by the OS when
                    # the app exits.
                    return -1
        return proc.wait()
    finally:
        # Close the stderr pipe to free its read end. Some platforms
        # keep the file descriptor alive until this is done.
        try:
            if proc.stderr is not None:
                proc.stderr.close()
        except Exception:
            pass


def _duration(job: EncodeJob) -> float:
    if job.trim_end is not None:
        return max(0.0, job.trim_end - job.trim_start)
    return max(0.0, job.info.duration - job.trim_start)


def _double_bitrate(rate: str) -> str:
    """Return the buffer-bitrate that pairs with `-b:v`. Falls through on
    unexpected input instead of raising, so a preset with a non-standard
    unit never breaks the encode command.
    """
    try:
        if rate.endswith("M"):
            return f"{int(float(rate[:-1]) * 2)}M"
        if rate.endswith("k"):
            return f"{int(float(rate[:-1]) * 2)}k"
    except (ValueError, IndexError):
        pass
    return rate


def _subtitles_filter(srt_path: Path, preset: CaptionPreset, out_height: int) -> str:
    """Build an FFmpeg ``subtitles=`` filter for burn-in.

    FFmpeg's filter-graph parser is fussy about path escaping:
      * the whole argument is inside a filter-graph, so colons inside
        the filename are treated as filter-option separators unless
        each one is escaped as ``\\:``;
      * single-quoted filenames must escape embedded quotes as ``'\\''``
        (close quote, escaped literal quote, reopen quote).

    The old implementation only escaped the Windows **drive** colon
    (``C:/foo``). A caption file at a path with a *second* colon
    (unusual on Windows but trivial on POSIX timestamped paths, or
    adversarial filenames) would slip an inner colon through and
    libavfilter would split the ``subtitles=...`` argument at that
    colon, interpreting the tail as additional filter options.
    Escaping every colon closes the hole; the drive-colon case falls
    out naturally.

    The ``force_style=`` block is generated from a resolution-relative
    ``CaptionPreset`` so the same preset renders correctly on 1080p,
    720p, 4K, etc.
    """
    s = str(srt_path.resolve()).replace("\\", "/")
    # Escape EVERY colon as \: so libavfilter doesn't split args at any
    # inner colon (Windows drive letter, timestamped path, filename).
    s = s.replace(":", r"\:")
    # Escape single quotes inside the filename so they don't close our
    # wrapping quote. The FFmpeg-documented idiom is 'abc'\''def'.
    s = s.replace("'", r"'\''")
    style = force_style_string(preset, out_height)
    return f"subtitles='{s}':force_style='{style}'"


def _quote(s: str) -> str:
    if " " in s or ":" in s or "'" in s:
        return f'"{s}"'
    return s


def _no_window_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0
