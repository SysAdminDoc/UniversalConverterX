"""MpvWidget — QWidget wrapping libmpv via python-mpv (F52).

Embeds an mpv player inside a Qt widget by passing the native window
handle (``wid``) to mpv.  Falls back gracefully if ``mpv`` is not
available — ``is_mpv_available()`` checks before any instantiation.

Usage::

    widget = MpvWidget(parent)
    widget.play("/path/to/video.mp4")
    widget.seek(120.5)
    widget.toggle_pause()
"""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

_MPV_AVAILABLE = None


def is_mpv_available():
    """Return True if python-mpv can import and find libmpv."""
    global _MPV_AVAILABLE
    if _MPV_AVAILABLE is not None:
        return _MPV_AVAILABLE
    try:
        __import__("mpv")
        _MPV_AVAILABLE = True
    except (ImportError, OSError):
        _MPV_AVAILABLE = False
    return _MPV_AVAILABLE


class MpvWidget(QWidget):
    """Qt widget hosting an embedded mpv player.

    Signals:
        position_changed(float)  — current playback position in seconds
        duration_changed(float)  — total duration in seconds
        eof_reached()            — playback finished
        file_loaded()            — file metadata available
    """

    position_changed = pyqtSignal(float)
    duration_changed = pyqtSignal(float)
    eof_reached = pyqtSignal()
    file_loaded = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        native_guard = getattr(Qt.WidgetAttribute, "WA_DontCreateNativeWidget", None)
        if native_guard is not None:
            self.setAttribute(native_guard, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setMinimumSize(320, 180)
        self.setStyleSheet("background: #000;")

        self._mpv = None
        self._duration = 0.0
        self._position = 0.0
        self._file_path = ""

        # Poll mpv properties via timer (safer than callbacks across threads)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._poll_state)

    def _ensure_mpv(self):
        """Create the mpv instance on first use, binding to this widget's
        native window handle."""
        if self._mpv is not None:
            return True
        if not is_mpv_available():
            return False
        try:
            import mpv
            wid = int(self.winId())
            self._mpv = mpv.MPV(
                wid=str(wid),
                log_handler=lambda *a: None,
                ytdl=False,
                input_default_bindings=True,
                input_vo_keyboard=True,
                osc=False,
                osd_level=0,
                keep_open="yes",
                hwdec="auto-safe",
            )
            self._mpv.observe_property("eof-reached", self._on_eof)
            self._poll_timer.start()
            return True
        except Exception:
            self._mpv = None
            return False

    def play(self, file_path, start_secs=0.0):
        """Load and play *file_path*, optionally starting at *start_secs*."""
        if not self._ensure_mpv():
            return False
        self._file_path = file_path
        try:
            if start_secs and start_secs > 0:
                self._mpv.start = str(start_secs)
            else:
                self._mpv.start = ""
            self._mpv.play(file_path)
            self.file_loaded.emit()
            return True
        except Exception:
            return False

    def stop(self):
        if self._mpv:
            try:
                self._mpv.stop()
            except Exception:
                pass

    def toggle_pause(self):
        if self._mpv:
            try:
                self._mpv.pause = not self._mpv.pause
            except Exception:
                pass

    @property
    def paused(self):
        if self._mpv:
            try:
                return bool(self._mpv.pause)
            except Exception:
                pass
        return True

    def seek(self, secs):
        if self._mpv:
            try:
                self._mpv.seek(secs, "absolute")
            except Exception:
                pass

    def seek_relative(self, delta):
        if self._mpv:
            try:
                self._mpv.seek(delta, "relative")
            except Exception:
                pass

    @property
    def position(self):
        return self._position

    @property
    def duration(self):
        return self._duration

    @property
    def volume(self):
        if self._mpv:
            try:
                return int(self._mpv.volume or 100)
            except Exception:
                pass
        return 100

    @volume.setter
    def volume(self, val):
        if self._mpv:
            try:
                self._mpv.volume = max(0, min(150, int(val)))
            except Exception:
                pass

    @property
    def speed(self):
        if self._mpv:
            try:
                return float(self._mpv.speed or 1.0)
            except Exception:
                pass
        return 1.0

    @speed.setter
    def speed(self, val):
        if self._mpv:
            try:
                self._mpv.speed = float(val)
            except Exception:
                pass

    def set_eq(self, bands):
        """Set 5-band EQ. *bands* is [bass, lo_mid, mid, hi_mid, treble] in dB (F56)."""
        if not self._mpv or len(bands) < 5:
            return
        try:
            # mpv superequalizer: 10 bands, we map 5 to the most useful ones
            # Bands 0-1 (bass), 2-3 (lo-mid), 4-5 (mid), 6-7 (hi-mid), 8-9 (treble)
            self._eq_af = (
                f"superequalizer="
                f"1={bands[0]}:2={bands[0]}:"
                f"3={bands[1]}:4={bands[1]}:"
                f"5={bands[2]}:6={bands[2]}:"
                f"7={bands[3]}:8={bands[3]}:"
                f"9={bands[4]}:10={bands[4]}"
            )
            self._apply_audio_filters()
        except Exception:
            pass

    def set_normalize(self, enabled):
        """Toggle dynamic audio normalization (F56)."""
        if not self._mpv:
            return
        try:
            self._norm_af = "dynaudnorm" if enabled else ""
            self._apply_audio_filters()
        except Exception:
            pass

    def _apply_audio_filters(self):
        """Compose EQ + normalize filters into a single af chain."""
        if not self._mpv:
            return
        parts = []
        eq = getattr(self, "_eq_af", "")
        norm = getattr(self, "_norm_af", "")
        if eq:
            parts.append(eq)
        if norm:
            parts.append(norm)
        try:
            self._mpv.af = ",".join(parts) if parts else ""
        except Exception:
            pass

    def set_mono(self, enabled):
        """Toggle mono downmix (F56)."""
        if not self._mpv:
            return
        try:
            self._mpv.audio_channels = "mono" if enabled else "auto"
        except Exception:
            pass

    @property
    def subtitle_tracks(self):
        """Return list of (track_id, title_or_lang) for subtitle tracks."""
        if not self._mpv:
            return []
        try:
            tracks = self._mpv.track_list or []
            return [
                (t["id"], t.get("title") or t.get("lang") or f"Track {t['id']}")
                for t in tracks if t.get("type") == "sub"
            ]
        except Exception:
            return []

    def set_subtitle_track(self, track_id):
        """Set active subtitle track. 0 or False disables subtitles."""
        if self._mpv:
            try:
                self._mpv.sid = track_id if track_id else False
            except Exception:
                pass

    @property
    def chapter_list(self):
        """Return list of (title, start_secs) from mpv chapter metadata."""
        if not self._mpv:
            return []
        try:
            chapters = self._mpv.chapter_list or []
            return [
                (ch.get("title", f"Chapter {i+1}"), float(ch.get("time", 0)))
                for i, ch in enumerate(chapters)
            ]
        except Exception:
            return []

    def _poll_state(self):
        if not self._mpv:
            return
        try:
            pos = self._mpv.time_pos
            dur = self._mpv.duration
            if pos is not None:
                self._position = float(pos)
                self.position_changed.emit(self._position)
            if dur is not None and dur != self._duration:
                self._duration = float(dur)
                self.duration_changed.emit(self._duration)
        except Exception:
            pass

    def _on_eof(self, _name, val):
        if val:
            self.eof_reached.emit()

    def destroy_mpv(self):
        """Cleanly shut down the mpv instance."""
        self._poll_timer.stop()
        if self._mpv:
            try:
                self._mpv.terminate()
            except Exception:
                pass
            self._mpv = None

    def closeEvent(self, event):
        self.destroy_mpv()
        super().closeEvent(event)
