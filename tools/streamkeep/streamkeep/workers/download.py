"""Download worker — ffmpeg-based segmented downloader with parallel
HTTP Range fallback and yt-dlp direct download mode."""

import os
import re
import subprocess
import time

from PyQt6.QtCore import QThread, pyqtSignal

from ..http import parallel_http_download
from ..paths import _CREATE_NO_WINDOW
from ..resume import (
    clear_resume_state, merge_completed, save_resume_state,
)
from ..utils import fmt_duration, fmt_size


class DownloadWorker(QThread):
    """Downloads segments using ffmpeg with speed/ETA tracking."""

    progress = pyqtSignal(int, int, str)   # seg_idx, percent, status
    segment_done = pyqtSignal(int, str)
    log = pyqtSignal(str)
    error = pyqtSignal(int, str)
    all_done = pyqtSignal()

    def __init__(self, playlist_url, segments, output_dir, format_type="hls"):
        super().__init__()
        self.playlist_url = playlist_url
        self.segments = segments
        self.output_dir = output_dir
        self.format_type = format_type
        self.audio_url = ""
        self.ytdlp_source = ""
        self.ytdlp_format = ""
        self.cookies_browser = ""
        self.rate_limit = ""
        self.proxy = ""
        self.download_subs = False
        self.sponsorblock = False
        self.download_sections = ""  # yt-dlp --download-sections value (F21)
        self.max_retries = 2
        self.parallel_connections = 4
        # When > 0 and the segment is a live capture (duration <= 0), the
        # ffmpeg command switches to the `segment` muxer so a long live
        # recording is written as `<label>_part%03d.mp4` chunks instead of
        # one monolithic 40+ GB file.
        self.chunk_length_secs = 0
        self._cancel = False
        self._proc = None
        self._proc_lock = __import__("threading").Lock()
        # Resume sidecar state. When set the worker keeps it fresh on
        # segment completion and clears it on a clean finish. Callers
        # (main_window) attach this via `attach_resume_state` just before
        # `start()` so the worker doesn't need to know about extractor
        # metadata.
        self._resume_state = None

    def attach_resume_state(self, state):
        """Attach a ResumeState. The worker will write it on start, refresh
        it on each segment_done, and clear it on clean all_done.

        `state.completed` is treated as authoritative on start — any segment
        already listed is considered complete and skipped (after verifying
        the file still exists on disk).
        """
        self._resume_state = state
        if state is not None:
            # Pull shape from the worker so the sidecar is self-contained.
            state.playlist_url = self.playlist_url
            state.format_type = self.format_type
            state.audio_url = self.audio_url or ""
            state.ytdlp_source = self.ytdlp_source or ""
            state.ytdlp_format = self.ytdlp_format or ""
            state.output_dir = self.output_dir
            state.segments = [list(s) for s in self.segments]
            save_resume_state(state)

    def cancel(self):
        self._cancel = True
        with self._proc_lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except OSError:
                    pass

    def _download_with_ytdlp(self, seg_idx, label, outfile):
        """Download via yt-dlp directly. Handles URL refresh, DASH merge,
        and format selection. Returns True on success."""
        cmd = [
            "yt-dlp",
            "-f", self.ytdlp_format,
            "--no-part",
            "--newline",
            "--progress",
            "-o", outfile,
            "--no-playlist",
        ]
        if self.cookies_browser:
            cmd.extend(["--cookies-from-browser", self.cookies_browser])
        # Inject cookies.txt for authenticated downloads (F47)
        if not self.cookies_browser:
            from ..cookies import cookies_file_path
            cpath = cookies_file_path()
            if cpath:
                cmd.extend(["--cookies", cpath])
        if self.rate_limit:
            cmd.extend(["--limit-rate", self.rate_limit])
        if self.proxy:
            cmd.extend(["--proxy", self.proxy])
        if self.download_subs:
            cmd.extend([
                "--write-subs", "--write-auto-subs",
                "--sub-langs", "en.*,en", "--embed-subs",
            ])
        if self.sponsorblock:
            cmd.extend(["--sponsorblock-remove", "sponsor,selfpromo,interaction"])
        if self.download_sections:
            cmd.extend(["--download-sections", self.download_sections])
        cmd.append(self.ytdlp_source)

        try:
            with self._proc_lock:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, encoding="utf-8", errors="replace",
                    creationflags=_CREATE_NO_WINDOW,
                )
            output_lines = []
            try:
                for line in self._proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    output_lines.append(line)
                    pct_match = re.search(r'(\d+\.\d+)%\s+of\s+(~?[\d.]+\w+)', line)
                    if pct_match:
                        pct = int(float(pct_match.group(1)))
                        size_str = pct_match.group(2)
                        speed_match = re.search(r'at\s+([\d.]+\w+/s)', line)
                        eta_match = re.search(r'ETA\s+([\d:]+)', line)
                        extra = ""
                        if speed_match:
                            extra += f" | {speed_match.group(1)}"
                        if eta_match:
                            extra += f" | ETA {eta_match.group(1)}"
                        self.progress.emit(seg_idx, min(99, pct), f"{size_str}{extra}")
                    elif "[Merger]" in line or "Merging" in line:
                        self.progress.emit(seg_idx, 99, "Merging video+audio")
            finally:
                if self._proc.stdout:
                    self._proc.stdout.close()

            self._proc.wait()
            if self._cancel:
                if os.path.exists(outfile):
                    try:
                        os.remove(outfile)
                    except OSError:
                        pass
                return False

            if (self._proc.returncode == 0 and os.path.exists(outfile)
                    and os.path.getsize(outfile) > 0):
                size = os.path.getsize(outfile)
                self.progress.emit(seg_idx, 100, "Complete")
                self.segment_done.emit(seg_idx, fmt_size(size))
                self._mark_segment_done(seg_idx)
                self.log.emit(f"[DONE] {label} - {fmt_size(size)}")
                return True

            if os.path.exists(outfile) and os.path.getsize(outfile) == 0:
                try:
                    os.remove(outfile)
                except OSError:
                    pass
            err_tail = "\n".join(output_lines[-5:])
            self.log.emit(f"[FAIL] {label}\n{err_tail}")
            return False

        except FileNotFoundError:
            self.log.emit(f"[ERROR] {label}: yt-dlp not in PATH")
            return False
        except Exception as e:
            self.log.emit(f"[ERROR] {label}: {e}")
            return False

    def _mark_segment_done(self, seg_idx):
        """Merge the segment into the resume sidecar and persist it."""
        if self._resume_state is None:
            return
        merge_completed(self._resume_state, seg_idx)
        save_resume_state(self._resume_state)

    def run(self):
        for seg_idx, label, start, duration in self.segments:
            if self._cancel:
                self.log.emit("Download cancelled.")
                # Leave the sidecar in place — the user may resume.
                return

            outfile = os.path.join(self.output_dir, f"{label}.mp4")
            is_live_capture = duration <= 0
            if os.path.exists(outfile):
                size = os.path.getsize(outfile)
                # Use 64 KB minimum threshold — 1 KB was too small and would
                # treat corrupt/truncated files as complete.
                if size > 65536:
                    self.log.emit(f"[SKIP] {label} ({fmt_size(size)})")
                    self.segment_done.emit(seg_idx, fmt_size(size))
                    self._mark_segment_done(seg_idx)
                    continue

            duration_label = "live" if is_live_capture else f"{duration}s"
            self.log.emit(f"[DL] {label} - start: {start}s, duration: {duration_label}")
            self.progress.emit(seg_idx, 0, "Starting...")

            # yt-dlp direct download mode
            if self.format_type == "ytdlp_direct" and self.ytdlp_source and self.ytdlp_format:
                success = self._download_with_ytdlp(seg_idx, label, outfile)
                if self._cancel:
                    return
                if not success:
                    self.error.emit(seg_idx, "yt-dlp download failed")
                continue

            # Multi-connection parallel download for direct MP4 URLs
            if (self.format_type == "mp4" and not self.audio_url
                    and self.parallel_connections > 1):
                worker_ref = self

                def _cb(done, total, speed):
                    pct = min(99, int((done / total) * 100)) if total > 0 else 0
                    spd = f"{fmt_size(speed)}/s" if speed > 0 else ""
                    eta = ""
                    if speed > 0 and total > done:
                        try:
                            eta = f" | ETA {fmt_duration((total - done) / speed)}"
                        except (ValueError, ZeroDivisionError, OverflowError):
                            eta = ""
                    status = f"{fmt_size(done)} / {fmt_size(total)} | {spd}{eta}"
                    worker_ref.progress.emit(seg_idx, pct, status)

                def _cancel():
                    return worker_ref._cancel

                try:
                    parallel_ok = parallel_http_download(
                        self.playlist_url, outfile,
                        connections=self.parallel_connections,
                        progress_cb=_cb, cancel_check=_cancel,
                        log_fn=lambda m: self.log.emit(m),
                    )
                except Exception as e:
                    self.log.emit(f"[PARALLEL ERR] {label}: {e}")
                    parallel_ok = False

                if self._cancel:
                    if os.path.exists(outfile):
                        try:
                            os.remove(outfile)
                        except OSError:
                            pass
                    return

                if (parallel_ok and os.path.exists(outfile)
                        and os.path.getsize(outfile) > 0):
                    size = os.path.getsize(outfile)
                    self.progress.emit(seg_idx, 100, "Complete")
                    self.segment_done.emit(seg_idx, fmt_size(size))
                    self._mark_segment_done(seg_idx)
                    self.log.emit(
                        f"[DONE] {label} - {fmt_size(size)} "
                        f"(parallel x{self.parallel_connections})"
                    )
                    continue
                else:
                    self.log.emit(f"[INFO] {label}: falling back to ffmpeg")

            # Live-only: split long captures into chunks via ffmpeg segment
            # muxer. The outfile pattern `<base>_part%03d.mp4` gives us
            # `live_recording_part000.mp4`, `_part001.mp4`, ... aligned
            # roughly to `chunk_length_secs`. Only applies to live captures
            # (duration <= 0) with no extra audio merge and no mp4 direct
            # branch — otherwise fall through to the normal cmd build.
            chunk_mode = (
                is_live_capture
                and self.chunk_length_secs > 0
                and not self.audio_url
                and self.format_type != "ytdlp_direct"
            )
            if chunk_mode:
                base = os.path.join(self.output_dir, f"{label}_part%03d.mp4")
                cmd = [
                    "ffmpeg", "-hide_banner", "-loglevel", "info",
                    "-i", self.playlist_url,
                    "-c", "copy",
                    "-f", "segment",
                    "-segment_time", str(int(self.chunk_length_secs)),
                    "-reset_timestamps", "1",
                    "-strftime", "0",
                    "-y", base,
                ]
                self.log.emit(
                    f"[CHUNK] Live capture will be split every "
                    f"{self.chunk_length_secs}s into {label}_partNNN.mp4"
                )
                # Live chunked capture — single attempt (no retry on lives),
                # then fall through to the outer for-loop's next segment
                # (lives always have just one segment, so we'll exit).
                try:
                    self._proc = subprocess.Popen(
                        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        text=True, bufsize=1, encoding="utf-8",
                        errors="replace",
                        creationflags=_CREATE_NO_WINDOW,
                    )
                    for line in self._proc.stderr:
                        line = line.strip()
                        if not line:
                            continue
                        time_match = re.search(r'time=(\d+):(\d+):(\d+)\.(\d+)', line)
                        if time_match:
                            try:
                                h = int(time_match.group(1))
                                m = int(time_match.group(2))
                                s = int(time_match.group(3))
                            except (ValueError, IndexError):
                                continue
                            elapsed = h * 3600 + m * 60 + s
                            self.progress.emit(
                                seg_idx, 0,
                                f"{elapsed}s captured (chunked)",
                            )
                    self._proc.wait()
                    # On cancel / normal exit, count how many chunks got
                    # written so the UI can emit `segment_done` with a
                    # meaningful size.
                    total_size = 0
                    chunk_count = 0
                    try:
                        prefix = f"{label}_part"
                        for entry in os.scandir(self.output_dir):
                            if entry.is_file() and entry.name.startswith(prefix):
                                total_size += entry.stat().st_size
                                chunk_count += 1
                    except OSError:
                        pass
                    if chunk_count > 0:
                        self.segment_done.emit(seg_idx, fmt_size(total_size))
                        self.log.emit(
                            f"[DONE] {label} - {chunk_count} chunk(s), "
                            f"{fmt_size(total_size)} total"
                        )
                        self._mark_segment_done(seg_idx)
                    elif self._cancel:
                        pass
                    else:
                        self.error.emit(seg_idx, "Chunked capture produced no files")
                except FileNotFoundError:
                    self.error.emit(seg_idx, "ffmpeg not found in PATH")
                    self.log.emit(f"[ERROR] {label}: ffmpeg not in PATH")
                    return
                except Exception as e:
                    self.log.emit(f"[ERROR] {label}: {e}")
                if self._cancel:
                    return
                continue  # next segment (but live is always single-seg)

            # Build ffmpeg command with optional audio merge
            if self.audio_url:
                if self.format_type == "mp4":
                    cmd = [
                        "ffmpeg", "-hide_banner", "-loglevel", "info",
                        "-i", self.playlist_url, "-i", self.audio_url,
                        "-map", "0:v:0", "-map", "1:a:0",
                        "-c", "copy", "-y", outfile,
                    ]
                else:
                    cmd = [
                        "ffmpeg", "-hide_banner", "-loglevel", "info",
                        "-ss", str(start), "-i", self.playlist_url,
                        "-ss", str(start), "-i", self.audio_url,
                        "-map", "0:v:0", "-map", "1:a:0",
                        "-c", "copy",
                    ]
                    if not is_live_capture:
                        cmd.extend(["-t", str(duration)])
                    cmd.extend(["-y", outfile])
            elif self.format_type == "mp4":
                cmd = [
                    "ffmpeg", "-hide_banner", "-loglevel", "info",
                    "-i", self.playlist_url, "-c", "copy", "-y", outfile,
                ]
            else:
                cmd = [
                    "ffmpeg", "-hide_banner", "-loglevel", "info",
                    "-ss", str(start), "-i", self.playlist_url, "-c", "copy",
                ]
                if not is_live_capture:
                    cmd.extend(["-t", str(duration)])
                cmd.extend(["-y", outfile])

            # Retry loop for transient ffmpeg failures
            attempts = self.max_retries + 1
            last_error = ""
            segment_done_flag = False
            for attempt in range(attempts):
                if self._cancel:
                    return
                if attempt > 0:
                    backoff = min(2 ** attempt, 60)  # cap at 60s
                    self.log.emit(
                        f"[RETRY {attempt}/{self.max_retries}] {label} "
                        f"(waiting {backoff}s)"
                    )
                    for _ in range(backoff * 2):
                        if self._cancel:
                            return
                        time.sleep(0.5)
                try:
                    # stdout is discarded — ffmpeg writes all progress to
                    # stderr. If stdout were piped without being drained,
                    # a ffmpeg mode that emits data to stdout (e.g. -f null
                    # mux reports) would deadlock on the pipe buffer.
                    with self._proc_lock:
                        self._proc = subprocess.Popen(
                            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, bufsize=1, encoding="utf-8",
                            errors="replace",
                            creationflags=_CREATE_NO_WINDOW,
                        )
                    output_lines = []
                    try:
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
                                pct = (
                                    0 if is_live_capture
                                    else min(99, int((elapsed / max(duration, 1)) * 100))
                                )
                                speed_m = re.search(r'speed=\s*([\d.]+)x', line)
                                size_m = re.search(r'size=\s*(\d+\w+)', line)
                                extra = ""
                                if speed_m:
                                    spd = float(speed_m.group(1))
                                    extra += f" | {spd:.1f}x"
                                    if spd > 0 and duration > 0:
                                        remaining = (duration - elapsed) / spd
                                        extra += f" | ETA {fmt_duration(remaining)}"
                                if size_m:
                                    extra += f" | {size_m.group(1)}"
                                status = (
                                    f"{elapsed}s captured{extra}" if is_live_capture
                                    else f"{elapsed}s / {duration}s{extra}"
                                )
                                self.progress.emit(seg_idx, pct, status)
                    finally:
                        if self._proc.stderr:
                            self._proc.stderr.close()

                    self._proc.wait()
                    if self._cancel:
                        if is_live_capture and os.path.exists(outfile):
                            size = os.path.getsize(outfile)
                            if size > 1024:
                                self.segment_done.emit(seg_idx, fmt_size(size))
                                self.log.emit(
                                    f"[STOP] Kept partial live capture {label} - "
                                    f"{fmt_size(size)}"
                                )
                        elif os.path.exists(outfile):
                            try:
                                os.remove(outfile)
                            except OSError:
                                pass
                        return

                    if (self._proc.returncode == 0 and os.path.exists(outfile)
                            and os.path.getsize(outfile) > 0):
                        size = os.path.getsize(outfile)
                        self.progress.emit(seg_idx, 100, "Complete")
                        self.segment_done.emit(seg_idx, fmt_size(size))
                        self._mark_segment_done(seg_idx)
                        self.log.emit(f"[DONE] {label} - {fmt_size(size)}")
                        segment_done_flag = True
                        break
                    else:
                        if os.path.exists(outfile) and os.path.getsize(outfile) == 0:
                            try:
                                os.remove(outfile)
                            except OSError:
                                pass
                        last_error = "\n".join(output_lines[-5:]) or f"ffmpeg exit {self._proc.returncode}"
                        self.log.emit(f"[FAIL attempt {attempt + 1}/{attempts}] {label}")
                        if is_live_capture:
                            break

                except FileNotFoundError:
                    self.error.emit(seg_idx, "ffmpeg not found in PATH")
                    self.log.emit(f"[ERROR] {label}: ffmpeg not in PATH")
                    return
                except PermissionError as e:
                    self.error.emit(seg_idx, f"Permission denied: {e}")
                    self.log.emit(f"[ERROR] {label}: {e}")
                    break
                except Exception as e:
                    last_error = str(e)
                    self.log.emit(f"[ERROR attempt {attempt + 1}/{attempts}] {label}: {e}")

            if not segment_done_flag and not self._cancel and not is_live_capture:
                self.error.emit(
                    seg_idx,
                    f"Failed after {attempts} attempt(s): {last_error[:120]}",
                )
                self.log.emit(f"[GIVE UP] {label} — all retries exhausted")

        if not self._cancel:
            # Only clear the resume sidecar and signal completion if every
            # segment actually succeeded.  When some segments failed, leave
            # the sidecar in place so the user can resume later.
            all_succeeded = True
            if self._resume_state is not None:
                expected = {s[0] for s in self.segments}
                completed = set(self._resume_state.completed)
                if expected != completed:
                    all_succeeded = False
            if all_succeeded:
                if self._resume_state is not None:
                    clear_resume_state(self.output_dir)
                self.all_done.emit()
            else:
                self.log.emit(
                    "[PARTIAL] Some segments failed — resume sidecar kept "
                    "for retry."
                )
