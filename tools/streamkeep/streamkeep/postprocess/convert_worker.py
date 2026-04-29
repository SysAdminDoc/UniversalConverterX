"""ConvertWorker — standalone batch converter for arbitrary files.

Runs the PostProcessor converter off the UI thread so the GUI stays
responsive when the user kicks off a batch on an existing folder.
Snapshots converter settings at construction time so mid-run edits
don't corrupt an in-flight batch.
"""

import os

from PyQt6.QtCore import QThread, pyqtSignal

from .codecs import VIDEO_EXTS, AUDIO_EXTS
from .processor import PostProcessor, PP_LOCK


class ConvertWorker(QThread):
    """Runs the video/audio converter on an arbitrary list of files."""

    progress = pyqtSignal(int, int, str)  # index, total, current filename
    file_done = pyqtSignal(str, bool)     # path, success
    log = pyqtSignal(str)
    all_done = pyqtSignal(int, int)       # success_count, fail_count

    def __init__(self, files, do_video, do_audio):
        super().__init__()
        self.files = list(files)
        self.do_video = do_video
        self.do_audio = do_audio
        self._cancel = False
        # Snapshot converter settings so mid-run edits don't corrupt the batch
        self._video_format = PostProcessor.convert_video_format
        self._video_codec = PostProcessor.convert_video_codec
        self._video_scale = PostProcessor.convert_video_scale
        self._video_fps = PostProcessor.convert_video_fps
        self._audio_format = PostProcessor.convert_audio_format
        self._audio_codec = PostProcessor.convert_audio_codec
        self._audio_bitrate = PostProcessor.convert_audio_bitrate
        self._audio_samplerate = PostProcessor.convert_audio_samplerate
        self._delete_source = PostProcessor.convert_delete_source

    def cancel(self):
        self._cancel = True

    def run(self):
        total = len(self.files)
        successes = 0
        failures = 0
        # Guard PostProcessor class-level state with a lock so concurrent
        # ConvertWorker / FinalizeWorker threads don't clobber each other.
        PP_LOCK.acquire()
        orig = {
            "convert_video_format": PostProcessor.convert_video_format,
            "convert_video_codec": PostProcessor.convert_video_codec,
            "convert_video_scale": PostProcessor.convert_video_scale,
            "convert_video_fps": PostProcessor.convert_video_fps,
            "convert_audio_format": PostProcessor.convert_audio_format,
            "convert_audio_codec": PostProcessor.convert_audio_codec,
            "convert_audio_bitrate": PostProcessor.convert_audio_bitrate,
            "convert_audio_samplerate": PostProcessor.convert_audio_samplerate,
            "convert_delete_source": PostProcessor.convert_delete_source,
        }
        PostProcessor.convert_video_format = self._video_format
        PostProcessor.convert_video_codec = self._video_codec
        PostProcessor.convert_video_scale = self._video_scale
        PostProcessor.convert_video_fps = self._video_fps
        PostProcessor.convert_audio_format = self._audio_format
        PostProcessor.convert_audio_codec = self._audio_codec
        PostProcessor.convert_audio_bitrate = self._audio_bitrate
        PostProcessor.convert_audio_samplerate = self._audio_samplerate
        PostProcessor.convert_delete_source = self._delete_source

        try:
            for i, path in enumerate(self.files):
                if self._cancel:
                    self.log.emit("Conversion cancelled.")
                    break
                name = os.path.basename(path)
                # Emit 1-based index so the UI shows "1 of N" for the first
                # file rather than "0 of N".
                self.progress.emit(i + 1, total, name)
                ext = os.path.splitext(path)[1].lower()
                # If the source file vanished between file-dialog and worker,
                # don't crash — skip and count as failure.
                if not os.path.exists(path):
                    self.log.emit(f"[CONVERT] Missing (skipped): {name}")
                    failures += 1
                    self.file_done.emit(path, False)
                    continue
                expected_ext = None
                if ext in VIDEO_EXTS and self.do_video:
                    expected_ext = (self._video_format or "mp4").lower()
                    PostProcessor._run_video_convert(path, lambda m: self.log.emit(m))
                elif ext in AUDIO_EXTS and self.do_audio:
                    expected_ext = (self._audio_format or "mp3").lower()
                    PostProcessor._run_audio_convert(path, lambda m: self.log.emit(m))
                else:
                    self.log.emit(f"[CONVERT] Skipped (unsupported ext): {name}")
                    continue

                base = os.path.splitext(path)[0]
                candidate1 = f"{base}.converted.{expected_ext}"
                candidate2 = f"{base}.converted2.{expected_ext}"
                ok = (
                    (os.path.exists(candidate1) and os.path.getsize(candidate1) > 0)
                    or (os.path.exists(candidate2) and os.path.getsize(candidate2) > 0)
                )
                if ok:
                    successes += 1
                else:
                    failures += 1
                self.file_done.emit(path, ok)
        finally:
            for k, v in orig.items():
                setattr(PostProcessor, k, v)
            PP_LOCK.release()

        if not self._cancel:
            self.progress.emit(total, total, "")
        self.all_done.emit(successes, failures)
