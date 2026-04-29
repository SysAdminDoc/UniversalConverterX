"""ClipWorker — lossless (or optional re-encode) trim of a single media file.

Runs ffmpeg with `-ss` / `-to` off the UI thread. Default mode uses
`-c copy` which is nearly instantaneous but cut-points snap to the nearest
keyframe. Opt-in re-encode mode gives frame-accurate trim at the cost of
a full transcode using the user's selected video codec.

Pattern mirrors ConvertWorker: snapshot settings at construction, restore
nothing (all params are passed in), emit progress/log/done signals.
"""

import os
import re
import subprocess
import tempfile

from PyQt6.QtCore import QThread, pyqtSignal

from ..paths import _CREATE_NO_WINDOW


class ClipWorker(QThread):
    """Trim a file to an in/out range and write to a new output path."""

    progress = pyqtSignal(int, str)      # percent, status
    log = pyqtSignal(str)
    done = pyqtSignal(bool, str)         # success, output_path

    def __init__(
        self,
        source_path,
        output_path,
        start_secs,
        end_secs,
        *,
        reencode=False,
        video_codec="libx264",
        audio_codec="aac",
        video_filter="",
    ):
        super().__init__()
        self.source_path = source_path
        self.output_path = output_path
        self.start_secs = float(start_secs or 0)
        self.end_secs = float(end_secs or 0)
        self.reencode = bool(reencode)
        self.video_codec = video_codec or "libx264"
        self.audio_codec = audio_codec or "aac"
        self.video_filter = video_filter or ""
        self._cancel = False
        self._proc = None

    def cancel(self):
        self._cancel = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def _build_cmd(self):
        """Build the ffmpeg command. `-ss` placement is deliberate:
        with `-c copy` we put `-ss` *before* `-i` for a fast keyframe
        seek. For re-encode we put `-ss` *after* `-i` for accurate seek
        (slower, but frame-exact)."""
        dur = max(0.0, self.end_secs - self.start_secs)
        if dur <= 0:
            return None
        if not self.reencode:
            return [
                "ffmpeg", "-hide_banner", "-loglevel", "info",
                "-ss", f"{self.start_secs:.3f}",
                "-i", self.source_path,
                "-t", f"{dur:.3f}",
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                "-y", self.output_path,
            ]
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "info",
            "-i", self.source_path,
            "-ss", f"{self.start_secs:.3f}",
            "-t", f"{dur:.3f}",
        ]
        if self.video_filter:
            cmd.extend(["-vf", self.video_filter])
        cmd.extend([
            "-c:v", self.video_codec,
            "-c:a", self.audio_codec,
            "-y", self.output_path,
        ])
        return cmd

    def run(self):
        cmd = self._build_cmd()
        if cmd is None:
            self.log.emit("[CLIP] Invalid range — end must be greater than start.")
            self.done.emit(False, "")
            return
        if not os.path.exists(self.source_path):
            self.log.emit(f"[CLIP] Source missing: {self.source_path}")
            self.done.emit(False, "")
            return
        out_dir = os.path.dirname(self.output_path)
        if out_dir:
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as e:
                self.log.emit(f"[CLIP] Cannot create output folder: {e}")
                self.done.emit(False, "")
                return
        dur = max(0.001, self.end_secs - self.start_secs)
        self.progress.emit(0, "Starting...")
        mode = "re-encode" if self.reencode else "stream-copy"
        self.log.emit(
            f"[CLIP] {os.path.basename(self.source_path)} "
            f"[{self.start_secs:.2f}s .. {self.end_secs:.2f}s] ({mode})"
        )
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                creationflags=_CREATE_NO_WINDOW,
            )
            output_lines = []
            for line in self._proc.stderr:
                line = line.strip()
                if not line:
                    continue
                output_lines.append(line)
                time_match = re.search(r'time=(\d+):(\d+):(\d+)\.(\d+)', line)
                if time_match:
                    try:
                        h = int(time_match.group(1))
                        m = int(time_match.group(2))
                        s = int(time_match.group(3))
                    except (ValueError, IndexError):
                        continue
                    elapsed = h * 3600 + m * 60 + s
                    pct = min(99, max(0, int((elapsed / dur) * 100)))
                    self.progress.emit(pct, f"{elapsed:.0f}s / {dur:.0f}s")
            self._proc.wait()
            if self._cancel:
                # Clean up partial output on cancel so the user doesn't end
                # up with a truncated file they might mistake for success.
                if os.path.exists(self.output_path):
                    try:
                        os.remove(self.output_path)
                    except OSError:
                        pass
                self.log.emit("[CLIP] Cancelled.")
                self.done.emit(False, "")
                return
            if (self._proc.returncode == 0
                    and os.path.exists(self.output_path)
                    and os.path.getsize(self.output_path) > 0):
                self.progress.emit(100, "Complete")
                self.log.emit(f"[CLIP] Wrote {self.output_path}")
                self.done.emit(True, self.output_path)
                return
            # Failure — remove zero-byte stub, surface the tail of stderr.
            if (os.path.exists(self.output_path)
                    and os.path.getsize(self.output_path) == 0):
                try:
                    os.remove(self.output_path)
                except OSError:
                    pass
            tail = "\n".join(output_lines[-5:]) or f"ffmpeg exit {self._proc.returncode}"
            self.log.emit(f"[CLIP] Failed:\n{tail}")
            self.done.emit(False, "")
        except FileNotFoundError:
            self.log.emit("[CLIP] ffmpeg not found in PATH.")
            self.done.emit(False, "")
        except Exception as e:
            self.log.emit(f"[CLIP] Error: {e}")
            self.done.emit(False, "")


class HighlightWorker(QThread):
    """Concatenate multiple time ranges from a source file into one
    highlight reel using ffmpeg's concat demuxer (stream-copy by default).
    """

    progress = pyqtSignal(int, str)
    log = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, source_path, output_path, ranges, *,
                 reencode=False, video_codec="libx264", audio_codec="aac"):
        super().__init__()
        self.source_path = source_path
        self.output_path = output_path
        self.ranges = list(ranges)  # [(start_secs, end_secs), ...]
        self.reencode = bool(reencode)
        self.video_codec = video_codec or "libx264"
        self.audio_codec = audio_codec or "aac"
        self._cancel = False
        self._proc = None

    def cancel(self):
        self._cancel = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self):
        if not self.ranges:
            self.log.emit("[HIGHLIGHT] No ranges to export.")
            self.done.emit(False, "")
            return
        if not os.path.exists(self.source_path):
            self.log.emit(f"[HIGHLIGHT] Source missing: {self.source_path}")
            self.done.emit(False, "")
            return

        tmp_dir = tempfile.mkdtemp(prefix="streamkeep_hl_")
        parts = []
        n = len(self.ranges)
        mode = "re-encode" if self.reencode else "stream-copy"
        self.log.emit(f"[HIGHLIGHT] {n} range(s), {mode}")

        try:
            for i, (start, end) in enumerate(self.ranges):
                if self._cancel:
                    break
                dur = max(0.0, end - start)
                if dur <= 0:
                    continue
                part_path = os.path.join(tmp_dir, f"part_{i:03d}.mp4")
                if not self.reencode:
                    cmd = [
                        "ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-ss", f"{start:.3f}", "-i", self.source_path,
                        "-t", f"{dur:.3f}", "-c", "copy",
                        "-avoid_negative_ts", "make_zero",
                        "-y", part_path,
                    ]
                else:
                    cmd = [
                        "ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-i", self.source_path,
                        "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                        "-c:v", self.video_codec, "-c:a", self.audio_codec,
                        "-y", part_path,
                    ]
                self.log.emit(
                    f"[HIGHLIGHT] Extracting {i + 1}/{n} "
                    f"({start:.1f}s \u2192 {end:.1f}s)"
                )
                try:
                    self._proc = subprocess.Popen(
                        cmd, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=_CREATE_NO_WINDOW,
                    )
                    self._proc.wait()
                except (FileNotFoundError, OSError) as e:
                    self.log.emit(f"[HIGHLIGHT] ffmpeg error: {e}")
                    self.done.emit(False, "")
                    return
                if self._cancel:
                    break
                if self._proc.returncode != 0:
                    self.log.emit(f"[HIGHLIGHT] Range {i + 1} extraction failed.")
                    self.done.emit(False, "")
                    return
                parts.append(part_path)
                self.progress.emit(int((i + 1) / (n + 1) * 100),
                                   f"Extracted {i + 1}/{n}")

            if self._cancel or not parts:
                self.done.emit(False, "")
                return

            # Concat phase
            list_path = os.path.join(tmp_dir, "concat.txt")
            with open(list_path, "w", encoding="utf-8") as f:
                for p in parts:
                    f.write(f"file '{p.replace(chr(92), '/')}'\n")

            out_dir = os.path.dirname(self.output_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)

            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", list_path,
                "-c", "copy", "-y", self.output_path,
            ]
            self.log.emit(f"[HIGHLIGHT] Joining {len(parts)} segments...")
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
            )
            self._proc.wait()

            if self._cancel:
                self.done.emit(False, "")
                return

            if (self._proc.returncode == 0
                    and os.path.exists(self.output_path)
                    and os.path.getsize(self.output_path) > 0):
                self.progress.emit(100, "Complete")
                self.log.emit(f"[HIGHLIGHT] Wrote {self.output_path}")
                self.done.emit(True, self.output_path)
            else:
                self.log.emit("[HIGHLIGHT] Concat failed.")
                self.done.emit(False, "")
        finally:
            for p in parts:
                try:
                    os.remove(p)
                except OSError:
                    pass
            try:
                lp = os.path.join(tmp_dir, "concat.txt")
                if os.path.exists(lp):
                    os.remove(lp)
                os.rmdir(tmp_dir)
            except OSError:
                pass
