"""PostProcessor — ffmpeg post-processing presets on completed downloads.

Includes: audio extract, loudnorm, h265 re-encode, contact sheet, chapter
split, and the full format/codec/scale/fps converter for video and audio.
"""

import os
import subprocess
import threading

from ..paths import _CREATE_NO_WINDOW
from ..utils import safe_filename
from .codecs import (
    VIDEO_CONTAINERS, VIDEO_CODECS,
    AUDIO_CONTAINERS, AUDIO_CODECS,
    VIDEO_EXTS, AUDIO_EXTS,
    video_codec_extra_args,
)

# Lock that guards PostProcessor class-level state from concurrent mutation
# by FinalizeWorker and ConvertWorker threads.
PP_LOCK = threading.Lock()


class PostProcessor:
    """Runs ffmpeg post-processing presets on completed downloads."""

    extract_audio = False       # Extract audio as MP3
    normalize_loudness = False  # EBU R128 loudness normalization
    normalization_profile = "Podcast"  # Named profile for loudnorm (F62)
    reencode_h265 = False       # Re-encode to H.265/HEVC
    contact_sheet = False       # Generate 3x3 thumbnail grid
    split_by_chapter = False    # Split into per-chapter files
    remove_silence = False      # Auto-cut silence/dead air (F26)
    silence_noise_db = -30      # dB threshold for silence detection
    silence_min_duration = 3.0  # seconds of silence before cutting

    # Converter
    convert_video = False
    convert_video_format = "mp4"
    convert_video_codec = "h264"
    convert_video_scale = "original"
    convert_video_fps = "original"
    convert_audio = False
    convert_audio_format = "mp3"
    convert_audio_codec = "mp3"
    convert_audio_bitrate = "192k"
    convert_audio_samplerate = "original"
    convert_delete_source = False

    @classmethod
    def has_any_preset(cls):
        return (
            cls.extract_audio or cls.normalize_loudness
            or cls.reencode_h265 or cls.contact_sheet
            or cls.split_by_chapter or cls.remove_silence
            or cls.convert_video or cls.convert_audio
        )

    @classmethod
    def process_directory(cls, out_dir, log_fn=None, chapters=None):
        """Scan out_dir for media files and run configured presets on each."""
        if not cls.has_any_preset() or not out_dir or not os.path.isdir(out_dir):
            return
        try:
            entries = [
                f for f in os.listdir(out_dir)
                if os.path.isfile(os.path.join(out_dir, f))
            ]
        except OSError:
            return

        def _is_derived(name):
            n = name.lower()
            return (
                n.endswith(".h265.mp4") or n.endswith(".loudnorm.mp4")
                or ".converted." in n
            )

        video_files = [
            os.path.join(out_dir, f) for f in entries
            if os.path.splitext(f)[1].lower() in VIDEO_EXTS and not _is_derived(f)
        ]
        audio_files = [
            os.path.join(out_dir, f) for f in entries
            if os.path.splitext(f)[1].lower() in AUDIO_EXTS and not _is_derived(f)
        ]

        for src in video_files:
            if cls.extract_audio:
                cls._run_audio_extract(src, log_fn)
            if cls.normalize_loudness:
                cls._run_loudnorm(src, log_fn)
            if cls.reencode_h265:
                cls._run_h265(src, log_fn)
            if cls.contact_sheet:
                cls._run_contact_sheet(src, log_fn)
            if cls.split_by_chapter and chapters:
                cls._run_split_by_chapter(src, chapters, log_fn)
            if cls.remove_silence:
                cls._run_silence_removal(src, log_fn)
            if cls.convert_video:
                cls._run_video_convert(src, log_fn)

        for src in audio_files:
            if cls.convert_audio:
                cls._run_audio_convert(src, log_fn)

    @staticmethod
    def _ffmpeg_run(cmd, log_fn, label):
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=3600,
                creationflags=_CREATE_NO_WINDOW,
            )
            if r.returncode == 0:
                if log_fn:
                    log_fn(f"[POST] {label} OK")
                return True
            if log_fn:
                err = (
                    r.stderr.strip().split("\n")[-1]
                    if r.stderr else f"exit {r.returncode}"
                )
                log_fn(f"[POST] {label} failed: {err[:120]}")
            return False
        except Exception as e:
            if log_fn:
                log_fn(f"[POST] {label} error: {e}")
            return False

    @classmethod
    def _run_audio_extract(cls, src, log_fn):
        base = os.path.splitext(src)[0]
        dst = base + ".mp3"
        if os.path.exists(dst):
            return
        if log_fn:
            log_fn(f"[POST] Extracting audio to MP3: {os.path.basename(dst)}")
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", src, "-vn", "-acodec", "libmp3lame", "-q:a", "2", dst,
        ]
        cls._ffmpeg_run(cmd, log_fn, "audio extract")

    @classmethod
    def _run_loudnorm(cls, src, log_fn):
        base, ext = os.path.splitext(src)
        dst = base + ".loudnorm" + ext
        if os.path.exists(dst):
            return
        # Use two-pass normalization with named profile (F62)
        from .normalization import normalize_two_pass, get_profile
        profile = get_profile(cls.normalization_profile)
        if log_fn:
            log_fn(f"[POST] Normalizing loudness ({cls.normalization_profile}, "
                   f"{profile['I']} LUFS): {os.path.basename(dst)}")
        normalize_two_pass(
            src, dst,
            target_i=profile["I"],
            target_tp=profile["TP"],
            target_lra=profile["LRA"],
            log_fn=log_fn,
        )

    @classmethod
    def _run_h265(cls, src, log_fn):
        base, ext = os.path.splitext(src)
        dst = base + ".h265" + ext
        if os.path.exists(dst):
            return
        if log_fn:
            log_fn(f"[POST] Re-encoding to H.265: {os.path.basename(dst)}")
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", src, "-c:v", "libx265", "-crf", "23", "-preset", "medium",
            "-c:a", "copy", dst,
        ]
        cls._ffmpeg_run(cmd, log_fn, "H.265 re-encode")

    @classmethod
    def _run_video_convert(cls, src, log_fn):
        """Convert a video file to the user-selected container + codec.
        Uses stream copy when codec is 'copy' (fast remux); supports all
        installed hardware encoders (NVENC/QSV/AMF/VideoToolbox)."""
        fmt = (cls.convert_video_format or "mp4").lower()
        if fmt not in VIDEO_CONTAINERS:
            fmt = "mp4"
        codec_key = cls.convert_video_codec or "h264"
        ff_encoder = VIDEO_CODECS.get(codec_key, "libx264")

        # WebM only accepts VP8/VP9/AV1. Auto-rewrite to VP9 software when
        # the user picks an incompatible combo.
        webm_ok = {
            "libvpx", "libvpx-vp9", "libaom-av1",
            "av1_nvenc", "av1_qsv", "av1_amf",
        }
        if fmt == "webm" and ff_encoder not in webm_ok and ff_encoder != "copy":
            if log_fn:
                log_fn(f"[POST] webm requires VP9/AV1 — switching from {ff_encoder}")
            ff_encoder = "libvpx-vp9"
            codec_key = "vp9"

        base = os.path.splitext(src)[0]
        dst = f"{base}.converted.{fmt}"
        if os.path.abspath(dst) == os.path.abspath(src):
            dst = f"{base}.converted2.{fmt}"
        if os.path.exists(dst):
            return
        if log_fn:
            log_fn(
                f"[POST] Convert video -> {fmt}/{codec_key} ({ff_encoder}): "
                f"{os.path.basename(dst)}"
            )

        scale_targets = {
            "2160p": 2160, "1440p": 1440, "1080p": 1080,
            "720p": 720, "480p": 480, "360p": 360,
        }
        scale_h = scale_targets.get(cls.convert_video_scale or "")
        fps_cap = None
        try:
            fv = cls.convert_video_fps or "original"
            if fv != "original":
                fps_cap = int(fv)
        except (TypeError, ValueError):
            fps_cap = None
        needs_encode = scale_h is not None or fps_cap is not None
        if ff_encoder == "copy" and needs_encode:
            if log_fn:
                log_fn("[POST] Scale/fps set — upgrading from copy to h264")
            ff_encoder = "libx264"
            codec_key = "h264"

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src]
        if ff_encoder == "copy":
            cmd.extend(["-c", "copy"])
        else:
            cmd.extend(["-c:v", ff_encoder])
            cmd.extend(video_codec_extra_args(ff_encoder))
            if scale_h is not None:
                cmd.extend(["-vf", f"scale=-2:{scale_h}"])
            if fps_cap is not None:
                cmd.extend(["-r", str(fps_cap)])
            if fmt in ("webm", "ogg"):
                cmd.extend(["-c:a", "libvorbis"])
            else:
                cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        cmd.append(dst)

        ok = cls._ffmpeg_run(cmd, log_fn, f"video convert -> {fmt}/{codec_key}")
        if ok and cls.convert_delete_source:
            # Verify the converted file actually exists and is non-empty
            # before deleting the source — ffmpeg can return 0 in rare
            # edge cases (interrupted mux) with a zero-byte output.
            if os.path.exists(dst) and os.path.getsize(dst) > 0:
                try:
                    os.remove(src)
                    if log_fn:
                        log_fn(f"[POST] Deleted source: {os.path.basename(src)}")
                except OSError as e:
                    if log_fn:
                        log_fn(f"[POST] Delete source failed: {e}")
            else:
                if log_fn:
                    log_fn(
                        f"[POST] Output missing/empty — source preserved: "
                        f"{os.path.basename(src)}"
                    )

    @classmethod
    def _run_audio_convert(cls, src, log_fn):
        """Convert an audio file to the user-selected container + codec."""
        fmt = (cls.convert_audio_format or "mp3").lower()
        if fmt not in AUDIO_CONTAINERS:
            fmt = "mp3"
        codec_key = (cls.convert_audio_codec or "mp3").lower()
        ff_codec = AUDIO_CODECS.get(codec_key, "libmp3lame")

        base = os.path.splitext(src)[0]
        dst = f"{base}.converted.{fmt}"
        if os.path.abspath(dst) == os.path.abspath(src):
            dst = f"{base}.converted2.{fmt}"
        if os.path.exists(dst):
            return
        if log_fn:
            log_fn(f"[POST] Convert audio -> {fmt}/{codec_key}: {os.path.basename(dst)}")

        sample_rate = None
        sr = cls.convert_audio_samplerate or "original"
        if sr != "original":
            try:
                sample_rate = int(sr)
            except (TypeError, ValueError):
                sample_rate = None
        if ff_codec == "copy" and sample_rate is not None:
            if log_fn:
                log_fn("[POST] Sample rate set — upgrading from copy to target codec")
            codec_key = "mp3" if fmt == "mp3" else "aac"
            ff_codec = AUDIO_CODECS[codec_key]

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", src, "-vn",
        ]
        if ff_codec == "copy":
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", ff_codec])
            if ff_codec not in ("flac", "pcm_s16le") and cls.convert_audio_bitrate:
                cmd.extend(["-b:a", cls.convert_audio_bitrate])
            if sample_rate is not None:
                cmd.extend(["-ar", str(sample_rate)])
        cmd.append(dst)

        ok = cls._ffmpeg_run(cmd, log_fn, f"audio convert -> {fmt}/{codec_key}")
        if ok and cls.convert_delete_source:
            if os.path.exists(dst) and os.path.getsize(dst) > 0:
                try:
                    os.remove(src)
                    if log_fn:
                        log_fn(f"[POST] Deleted source: {os.path.basename(src)}")
                except OSError as e:
                    if log_fn:
                        log_fn(f"[POST] Delete source failed: {e}")
            else:
                if log_fn:
                    log_fn(
                        f"[POST] Output missing/empty — source preserved: "
                        f"{os.path.basename(src)}"
                    )

    @classmethod
    def _run_contact_sheet(cls, src, log_fn):
        """Generate a 3x3 grid of evenly-spaced thumbnails."""
        base = os.path.splitext(src)[0]
        dst = base + ".contact.jpg"
        if os.path.exists(dst):
            return
        if log_fn:
            log_fn(f"[POST] Building contact sheet: {os.path.basename(dst)}")
        try:
            r = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", src,
                ],
                capture_output=True, text=True, timeout=15,
                creationflags=_CREATE_NO_WINDOW,
            )
            dur = float((r.stdout or "0").strip() or 0)
        except Exception:
            dur = 0
        if dur <= 1:
            if log_fn:
                log_fn("[POST] Contact sheet skipped: unknown duration")
            return
        nb_frames = 9
        fps = nb_frames / max(dur - 2, 1)
        vf = f"fps={fps:.6f},scale=480:-1,tile=3x3:margin=8:padding=6"
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", "1", "-i", src,
            "-vf", vf, "-frames:v", "1", "-qscale:v", "3", dst,
        ]
        cls._ffmpeg_run(cmd, log_fn, "contact sheet")

    @classmethod
    def _run_split_by_chapter(cls, src, chapters, log_fn):
        """Split a video into one file per chapter using stream copy."""
        if not chapters:
            return
        base, ext = os.path.splitext(src)
        out_dir = base + "_chapters"
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            if log_fn:
                log_fn(f"[POST] Chapter split: cannot create folder: {e}")
            return
        if log_fn:
            log_fn(f"[POST] Splitting by chapter ({len(chapters)} chapters)...")
        for i, ch in enumerate(chapters):
            start = float(ch.get("start", 0) or 0)
            end = float(ch.get("end", 0) or 0)
            title = safe_filename(ch.get("title", f"Chapter {i+1}"), max_len=80)
            label = f"{i+1:02d} - {title}{ext}"
            dst = os.path.join(out_dir, label)
            if os.path.exists(dst):
                continue
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", str(start), "-i", src,
            ]
            if end > start:
                cmd.extend(["-to", str(end - start)])
            cmd.extend(["-c", "copy", dst])
            cls._ffmpeg_run(cmd, log_fn, f"chapter {i+1}")

    @classmethod
    def _run_silence_removal(cls, src, log_fn):
        """Detect silence with ffmpeg silencedetect, then re-mux with the
        silent segments removed (stream-copy, keyframe-aligned)."""
        import re as _re
        import tempfile
        base, ext = os.path.splitext(src)
        dst = base + ".nosilence" + ext
        if os.path.exists(dst):
            return
        noise_db = int(cls.silence_noise_db or -30)
        min_dur = float(cls.silence_min_duration or 3.0)
        if log_fn:
            log_fn(
                f"[POST] Detecting silence (threshold {noise_db}dB, "
                f"min {min_dur}s): {os.path.basename(src)}"
            )
        # Step 1: run silencedetect and parse timestamps
        detect_cmd = [
            "ffmpeg", "-hide_banner", "-i", src,
            "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
            "-f", "null", "-",
        ]
        try:
            r = subprocess.run(
                detect_cmd, capture_output=True, text=True, timeout=600,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            if log_fn:
                log_fn(f"[POST] Silence detection failed: {e}")
            return
        # Parse stderr for silence_start / silence_end pairs
        lines = r.stderr or ""
        starts = [float(m.group(1)) for m in _re.finditer(r'silence_start:\s*([\d.]+)', lines)]
        ends = [float(m.group(1)) for m in _re.finditer(r'silence_end:\s*([\d.]+)', lines)]
        if not starts:
            if log_fn:
                log_fn("[POST] No silence detected — skipping removal.")
            return
        # Build non-silent segments
        segments = []
        pos = 0.0
        for i, s_start in enumerate(starts):
            if s_start > pos:
                segments.append((pos, s_start))
            if i < len(ends):
                pos = ends[i]
            else:
                pos = s_start  # silence extends to end of file
        # Probe duration to add trailing segment
        try:
            dur_r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", src],
                capture_output=True, text=True, timeout=15,
                creationflags=_CREATE_NO_WINDOW,
            )
            total_dur = float((dur_r.stdout or "0").strip() or 0)
        except Exception:
            total_dur = 0
        if total_dur > 0 and pos < total_dur - 0.1:
            segments.append((pos, total_dur))
        if not segments:
            if log_fn:
                log_fn("[POST] Entire file is silence — skipping.")
            return
        removed = sum(e - s for s, e in zip(starts, ends[:len(starts)]))
        if log_fn:
            log_fn(
                f"[POST] Found {len(starts)} silent region(s) "
                f"({removed:.1f}s total). Building {len(segments)} segment(s)."
            )
        # Step 2: write a concat demuxer list and re-mux
        try:
            tmpdir = tempfile.mkdtemp(prefix="sk_silence_")
            concat_path = os.path.join(tmpdir, "concat.txt")
            seg_files = []
            for idx, (seg_start, seg_end) in enumerate(segments):
                seg_dst = os.path.join(tmpdir, f"seg_{idx:04d}{ext}")
                seg_cmd = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{seg_start:.3f}", "-to", f"{seg_end:.3f}",
                    "-i", src, "-c", "copy", seg_dst,
                ]
                ok = cls._ffmpeg_run(seg_cmd, None, f"silence seg {idx}")
                if ok and os.path.exists(seg_dst) and os.path.getsize(seg_dst) > 0:
                    seg_files.append(seg_dst)
            if not seg_files:
                if log_fn:
                    log_fn("[POST] No valid segments extracted — silence removal aborted.")
                return
            with open(concat_path, "w") as f:
                for sf in seg_files:
                    escaped = sf.replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")
            concat_cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", concat_path,
                "-c", "copy", dst,
            ]
            ok = cls._ffmpeg_run(concat_cmd, log_fn, "silence removal concat")
            if ok and log_fn:
                log_fn(f"[POST] Silence removed: {os.path.basename(dst)}")
        except Exception as e:
            if log_fn:
                log_fn(f"[POST] Silence removal error: {e}")
        finally:
            # Cleanup temp segments
            try:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass
