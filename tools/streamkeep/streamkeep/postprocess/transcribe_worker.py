"""TranscribeWorker — optional Whisper-based transcription + chapter
inference for finished downloads.

Backend priority (F29):
  1. WhisperX (word-level timestamps, optional speaker diarization)
  2. faster-whisper (fast, good quality, CPU + CUDA)
  3. whisper-cli / whisper.cpp / main binary in PATH

When no runtime is available, the worker emits a clear log message
and exits — never silent failure.

Outputs (next to the source media file):
  transcript.srt / transcript.vtt      (both, always)
  transcript.json                      (segment structure — starts/ends/text)
  chapters.auto.txt                    (simple "HH:MM:SS  heading" per inferred chapter)

Chapter inference: scan for the longest silences (no-speech segments)
longer than `silence_gap_secs`. Each gap starts a new chapter; the
chapter title is the first ~6 words of the next speech segment.
"""

import json
import os
import shutil
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal

from ..paths import _CREATE_NO_WINDOW


def _whisperx_available():
    """Check if WhisperX is importable."""
    try:
        __import__("whisperx")
        return True
    except ImportError:
        return False


def is_available():
    """Which Whisper runtime (if any) is usable right now."""
    if _whisperx_available():
        return "whisperx"
    try:
        import faster_whisper  # availability probe
    except ImportError:
        faster_whisper = None
    if faster_whisper is not None and hasattr(faster_whisper, "WhisperModel"):
        return "faster-whisper"
    for name in ("whisper-cli", "whisper.cpp", "main"):
        if shutil.which(name):
            return name
    return ""


def _format_srt_time(secs):
    secs = max(0.0, float(secs))
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = secs - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def _format_vtt_time(secs):
    return _format_srt_time(secs).replace(",", ".")


def _first_words(text, n=6):
    words = (text or "").strip().split()
    return " ".join(words[:n]).strip()


class TranscribeWorker(QThread):
    """Transcribe one media file; emit progress + done.

    Signals:
        progress(int pct, str status)
        done(bool success, str out_dir_or_err)
    """

    progress = pyqtSignal(int, str)
    done = pyqtSignal(bool, str)

    def __init__(self, media_path, *, model_name="tiny", language=None,
                 silence_gap_secs=12.0, enable_diarization=False,
                 hf_token=""):
        super().__init__()
        self.media_path = media_path
        self.model_name = model_name
        self.language = language    # None = auto-detect
        self.silence_gap_secs = float(silence_gap_secs)
        self.enable_diarization = bool(enable_diarization)
        self.hf_token = hf_token or ""
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        if not self.media_path or not os.path.exists(self.media_path):
            self.done.emit(False, "Source file missing.")
            return
        runtime = is_available()
        if not runtime:
            self.done.emit(
                False,
                "No Whisper runtime found. Install with "
                "`pip install faster-whisper` or place whisper.cpp in PATH.",
            )
            return
        try:
            if runtime == "whisperx":
                segments = self._run_whisperx()
            elif runtime == "faster-whisper":
                segments = self._run_faster_whisper()
            else:
                segments = self._run_whisper_cpp(runtime)
        except Exception as e:
            self.done.emit(False, f"Transcription failed: {e}")
            return
        if self._cancel:
            self.done.emit(False, "Cancelled.")
            return
        if not segments:
            self.done.emit(False, "No speech detected.")
            return
        base, _ = os.path.splitext(self.media_path)
        self._write_outputs(base, segments)
        self.progress.emit(100, "Complete")
        self.done.emit(True, base)

    def _run_faster_whisper(self):
        """Returns a list of {start, end, text} dicts."""
        from faster_whisper import WhisperModel   # lazy — optional dep
        self.progress.emit(1, f"Loading {self.model_name} model...")
        # int8 keeps RAM low on CPU-only boxes; accepts both CPU and CUDA.
        model = WhisperModel(self.model_name, compute_type="int8")
        self.progress.emit(5, "Transcribing...")
        segments_iter, info = model.transcribe(
            self.media_path,
            language=self.language,
            vad_filter=True,
            beam_size=5,
        )
        total = max(1.0, float(getattr(info, "duration", 0) or 0))
        out = []
        for seg in segments_iter:
            if self._cancel:
                break
            out.append({
                "start": float(seg.start),
                "end": float(seg.end),
                "text": (seg.text or "").strip(),
            })
            pct = min(99, int((seg.end / total) * 100))
            self.progress.emit(pct, f"{seg.end:.0f}s / {total:.0f}s")
        return out

    def _run_whisperx(self):
        """WhisperX backend — word-level timestamps + optional diarization."""
        import torch
        import whisperx

        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute = "float16" if device == "cuda" else "int8"
        self.progress.emit(1, f"Loading WhisperX {self.model_name} on {device}...")
        model = whisperx.load_model(
            self.model_name, device, compute_type=compute,
            language=self.language,
        )
        self.progress.emit(5, "Transcribing with VAD...")
        audio = whisperx.load_audio(self.media_path)
        result = model.transcribe(audio, batch_size=16)
        if self._cancel:
            return []

        # Forced alignment for word-level timestamps
        detected_lang = result.get("language") or self.language or "en"
        self.progress.emit(50, "Aligning word timestamps...")
        try:
            align_model, align_meta = whisperx.load_align_model(
                language_code=detected_lang, device=device,
            )
            result = whisperx.align(
                result["segments"], align_model, align_meta,
                audio, device, return_char_alignments=False,
            )
        except Exception:
            pass  # alignment failed — keep segment-level timestamps
        if self._cancel:
            return []

        # Optional speaker diarization
        if self.enable_diarization and self.hf_token:
            self.progress.emit(70, "Running speaker diarization...")
            try:
                diarize_model = whisperx.DiarizationPipeline(
                    use_auth_token=self.hf_token, device=device,
                )
                diarize_segments = diarize_model(audio)
                result = whisperx.assign_word_speakers(diarize_segments, result)
            except Exception:
                pass  # diarization failed — continue without speakers

        self.progress.emit(90, "Building output...")
        segments = result.get("segments", [])
        out = []
        for seg in segments:
            entry = {
                "start": float(seg.get("start", 0)),
                "end": float(seg.get("end", 0)),
                "text": (seg.get("text") or "").strip(),
            }
            # Word-level details
            words = seg.get("words", [])
            if words:
                entry["words"] = [
                    {
                        "word": w.get("word", ""),
                        "start": float(w.get("start", 0)),
                        "end": float(w.get("end", 0)),
                    }
                    for w in words
                ]
            # Speaker label from diarization
            speaker = seg.get("speaker")
            if speaker:
                entry["speaker"] = speaker
            if entry["text"]:
                out.append(entry)
        return out

    def _run_whisper_cpp(self, binary):
        """Returns a list of {start, end, text} dicts parsed from whisper.cpp
        SRT output. We pass `-osrt` and then parse the generated file."""
        self.progress.emit(5, "Running whisper.cpp...")
        base, _ = os.path.splitext(self.media_path)
        srt_out = base + ".wspcpp.srt"
        cmd = [
            binary,
            "-m", os.environ.get("WHISPER_MODEL", f"models/ggml-{self.model_name}.bin"),
            "-f", self.media_path,
            "-osrt",
            "-of", srt_out.rsplit(".srt", 1)[0],
        ]
        if self.language:
            cmd.extend(["-l", self.language])
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                creationflags=_CREATE_NO_WINDOW, timeout=60 * 60,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip()[:200] or "non-zero exit")
        except FileNotFoundError:
            raise RuntimeError(f"{binary} not found in PATH")
        # Parse the .srt.
        out = []
        try:
            with open(srt_out, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            raise RuntimeError(f"Could not read {srt_out}: {e}")
        finally:
            try:
                os.remove(srt_out)
            except OSError:
                pass
        for chunk in text.strip().split("\n\n"):
            lines = chunk.strip().splitlines()
            if len(lines) < 3:
                continue
            # "HH:MM:SS,mmm --> HH:MM:SS,mmm"
            try:
                left, right = lines[1].split(" --> ", 1)
                start = _srt_to_secs(left.strip())
                end = _srt_to_secs(right.strip())
            except (ValueError, IndexError):
                continue
            body = " ".join(lines[2:]).strip()
            out.append({"start": start, "end": end, "text": body})
        return out

    def _write_outputs(self, base, segments):
        """Write .srt, .vtt, .json, and chapters.auto.txt."""
        # .srt — use word-level timestamps for tighter cues when available
        with open(base + ".srt", "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, start=1):
                speaker = seg.get("speaker", "")
                prefix = f"[{speaker}] " if speaker else ""
                f.write(f"{i}\n")
                f.write(f"{_format_srt_time(seg['start'])} --> {_format_srt_time(seg['end'])}\n")
                f.write(f"{prefix}{seg['text']}\n\n")
        # .vtt — include speaker labels
        with open(base + ".vtt", "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")
            for seg in segments:
                speaker = seg.get("speaker", "")
                prefix = f"<v {speaker}>" if speaker else ""
                f.write(f"{_format_vtt_time(seg['start'])} --> {_format_vtt_time(seg['end'])}\n")
                f.write(f"{prefix}{seg['text']}\n\n")
        # .json — full structure including words + speakers
        with open(base + ".transcript.json", "w", encoding="utf-8") as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)
        # chapters.auto.txt — emit one chapter at every silence gap > threshold.
        chapters = [(0.0, _first_words(segments[0]["text"]) or "Start")]
        for prev, nxt in zip(segments, segments[1:]):
            gap = nxt["start"] - prev["end"]
            if gap >= self.silence_gap_secs:
                heading = _first_words(nxt["text"]) or f"Chapter at {int(nxt['start'])}s"
                chapters.append((nxt["start"], heading))
        with open(base + ".chapters.auto.txt", "w", encoding="utf-8") as f:
            for secs, title in chapters:
                h = int(secs // 3600)
                m = int((secs % 3600) // 60)
                s = int(secs % 60)
                f.write(f"{h:02d}:{m:02d}:{s:02d}  {title}\n")


def _srt_to_secs(stamp):
    # "HH:MM:SS,mmm" or "HH:MM:SS.mmm" (whisper.cpp uses dot)
    hhmmss, _, ms = stamp.partition(",")
    if not ms:
        hhmmss, _, ms = stamp.partition(".")
    h, m, s = hhmmss.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s) + (int(ms or 0) / 1000.0)
