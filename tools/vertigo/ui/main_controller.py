"""Vertigo main-window controller — worker lifecycle and batch driver.

The controller owns every background job (detect / encode / transcribe /
scene-detect) together with the state those jobs produce or consume:

    workers         detect_worker, encode_worker, subtitle_worker,
                    scene_worker — the live QThread handles
    analysis        track_points, scenes, clip_subs — output from
                    DetectWorker / SceneWorker / SubtitleWorker that
                    later runs want to read
    batch           batch_running, batch_out_dir, suppress_auto_detect —
                    flags the batch driver flips
    export          last_output_path — the most recent export, used
                    when the user asks to "reveal export"

``MainWindow`` keeps everything that is genuinely UI-session state —
the loaded clip, the selected preset / mode / trim / overlays / output
choice — plus every widget and every refresh helper. The controller
reaches into the window for widget access (``self.win._toast``,
``self.win._detect_progress``, …) and for refresh helpers
(``self.win._refresh_overview``). This is deliberate coupling: the two
classes are designed together and live in the same package.

Public API (called from ``main_window._wire`` / panel signals / window
helpers):

    controller.run_transcribe(...)
    controller.on_subs_cleared()
    controller.run_detect()
    controller.start_export()
    controller.start_batch_export()
    controller.run_dry()
    controller.cancel_active()
    controller.open_last_output_folder()
    controller.kick_scene_detection(path)
    controller.shutdown(timeout_ms)
    controller.has_running_worker()

Everything else on this class starts with ``_`` and is an internal
detail (worker-signal handlers, dialog helpers, batch step).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFontMetrics
from PyQt6.QtWidgets import QMenu, QMessageBox

from core import crashlog
from core.encode import EncodeJob
from core.probe import VideoInfo, probe
from core.reframe import ReframeMode, build_plan
from core.subtitles import is_installed as subtitles_installed
from workers import WORKER_CANCELLED_MSG
from workers.detect_worker import DetectWorker
from workers.encode_worker import EncodeWorker
from workers.scene_worker import SceneWorker
from workers.subtitle_worker import SubtitleWorker
from workers.auto_edit_worker import AutoEditWorker
from workers.highlights_worker import HighlightsWorker
from workers.pycaps_worker import PycapsWorker
from workers.segment_proposals_worker import SegmentProposalsWorker
from workers.vad_worker import VadWorker

from .batch_queue import QueueEntry, QueueStatus

if TYPE_CHECKING:
    from .main_window import MainWindow


def _fmt_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes >= 60:
        hours = minutes // 60
        minutes = minutes % 60
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _fmt_segment_band(min_sec: float, max_sec: float, target_sec: float) -> str:
    return (
        f"{_fmt_duration(min_sec)}–{_fmt_duration(max_sec)}"
        f" · target {_fmt_duration(target_sec)}"
    )


class MainController(QObject):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.win = window

        # worker handles
        self.detect_worker: DetectWorker | None = None
        self.encode_worker: EncodeWorker | None = None
        self.subtitle_worker: SubtitleWorker | None = None
        self.scene_worker: SceneWorker | None = None
        self.vad_worker: VadWorker | None = None
        self.highlights_worker: HighlightsWorker | None = None
        self.auto_edit_worker: AutoEditWorker | None = None
        self.pycaps_worker: PycapsWorker | None = None
        self.segments_worker: SegmentProposalsWorker | None = None
        # Context captured when an export kicks off a pycaps pass, so
        # ``_on_pycaps_done`` can finish the export without the slot
        # needing to re-derive the original out path / entry id.
        self._pending_pycaps: dict | None = None

        # analysis results (consumed by export and UI refreshers)
        self.track_points: list = []
        self.scenes: list[tuple[float, float]] = []
        self.clip_subs: dict[int, Path] = {}
        # Per-clip parsed caption list + pycaps template id. When an
        # animated style is active we keep the caption list alongside
        # the template so the post-encode step can hand pycaps its
        # transcript without a second Whisper pass.
        self.clip_captions: dict[int, list] = {}
        # Parallel cache of the O(n) "has any non-whitespace caption text"
        # gate used by refresh_segments_button(). Computed once at write
        # time so per-UI-refresh reads are O(1) regardless of transcript
        # length (2-hour lectures produce ~20k captions on a fast model).
        self._captions_has_text: dict[int, bool] = {}
        self.animated_styles: dict[int, str] = {}

        # batch driver state
        self.batch_running: bool = False
        self.batch_out_dir: Path | None = None
        self.suppress_auto_detect: bool = False

        # export output tracking
        self.last_output_path: Path | None = None

    # --------------------------------------------------------------- wiring
    def wire(self) -> None:
        """Route the top-level hero / player / drop-zone signals.

        Signals emitted by widgets that are built inside the per-panel
        ``_build_*`` helpers (detect button, dry-run button, subtitles
        panel, open-output button) are still connected where the widgets
        are constructed — those are local concerns and moving them up
        here would force every build helper to expose another accessor.
        What this method handles is the chrome-level surfaces that are
        referenced by name on MainWindow.
        """
        w = self.win
        w._drop.file_dropped.connect(w._import_one)
        w._drop.files_dropped.connect(w._import_many)
        w._browse_btn.clicked.connect(w._browse_for_clips)
        w._hero_output_btn.clicked.connect(self.open_last_output_folder)
        w._export_btn.clicked.connect(self.start_export)
        w._export_all_btn.clicked.connect(self.start_batch_export)
        w._cancel_btn.clicked.connect(self.cancel_active)
        w._player.canvas.viewport_dragged.connect(w._on_manual_drag)
        w._player.position_changed.connect(w._sync_track_pos)
        w._player.trim_changed.connect(w._on_trim_changed)
        w._player.tighten_btn.clicked.connect(self.run_tighten_silences)
        w._player.highlights_btn.clicked.connect(self.run_find_highlights)
        w._player.segments_btn.clicked.connect(self.run_suggest_segments)
        w._player.trim_silences_btn.clicked.connect(self.run_trim_silences)
        w._export_thumbs_btn.clicked.connect(self.export_thumbnails)

    # --------------------------------------------------------------- status
    def has_running_worker(self) -> bool:
        for w in (
            self.detect_worker,
            self.encode_worker,
            self.subtitle_worker,
            self.vad_worker,
            self.highlights_worker,
            self.auto_edit_worker,
            self.pycaps_worker,
            self.segments_worker,
        ):
            if w is not None and w.isRunning():
                return True
        return False

    def shutdown(self, timeout_ms: int = 1500) -> None:
        """Cancel every in-flight worker and join for up to ``timeout_ms``.

        Called from MainWindow.closeEvent so the GUI process can exit
        cleanly even when a long-running encode or transcribe is in
        flight. Scene detection is fire-and-forget and is not cancelled
        by cancel_active(), so we stop it here explicitly. Workers that
        fail to finish within the timeout leave a breadcrumb via
        :func:`core.crashlog.append`, which survives the frozen-build
        stderr drop.
        """
        self.cancel_active()
        if self.scene_worker is not None and self.scene_worker.isRunning():
            self.scene_worker.cancel()
        for worker in (
            self.encode_worker,
            self.detect_worker,
            self.subtitle_worker,
            self.scene_worker,
            self.vad_worker,
            self.highlights_worker,
            self.auto_edit_worker,
            self.pycaps_worker,
            self.segments_worker,
        ):
            if worker is None or not worker.isRunning():
                continue
            if not worker.wait(timeout_ms):
                # Frozen PyInstaller builds discard stderr, so the old
                # print() here was effectively invisible. Route through
                # the persistent crash log instead — crashlog.append is
                # no-op safe and never raises.
                crashlog.append(
                    f"{type(worker).__name__} did not finish within "
                    f"{timeout_ms}ms on shutdown"
                )

    def drop_clip_subs(self, entry_id: int) -> None:
        """Release per-clip subtitle state for a removed queue entry.

        Unlinks the auto-generated SRT/ASS, forgets the cached caption
        list, and forgets any animated-style selection so the clip's
        removal leaves no lingering disk or memory state.
        """
        path = self.clip_subs.pop(entry_id, None)
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
        self.clip_captions.pop(entry_id, None)
        self._captions_has_text.pop(entry_id, None)
        self.animated_styles.pop(entry_id, None)

    def _set_cached_captions(self, entry_id: int, captions: list) -> None:
        """Write both the caption list and the ``has non-empty text`` flag.

        Everywhere captions land (subtitle worker, tests that pre-seed the
        cache) should route through here so the flag stays in sync. The
        scan is O(n) once at write time but short-circuits on the first
        non-empty caption — typical transcripts satisfy the gate inside
        the first dozen entries.
        """
        self.clip_captions[entry_id] = captions
        self._captions_has_text[entry_id] = any(
            getattr(c, "text", "").strip() for c in captions
        )

    # --------------------------------------------------------------- captions
    def on_subs_cleared(self) -> None:
        current = self.win._current_entry
        if current and current.id in self.clip_subs:
            path = self.clip_subs.pop(current.id)
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
        # Drop the cached caption list too, otherwise downstream consumers
        # (segment proposals, pycaps) keep operating on transcripts the
        # user just asked us to forget.
        if current:
            self.clip_captions.pop(current.id, None)
            self._captions_has_text.pop(current.id, None)
            self.animated_styles.pop(current.id, None)
        self.win._refresh_overview()
        self.refresh_segments_button()

    def run_transcribe(
        self,
        model: str,
        language: str | None,
        preset_id: str = "pop",
        face_aware: bool = False,
    ) -> None:
        w = self.win
        if not w._info or not w._current_entry:
            w._toast.show_toast("Load a clip first.", kind="warning")
            return
        if self.subtitle_worker and self.subtitle_worker.isRunning():
            return

        from core.caption_styles import resolve as resolve_caption_preset

        # Pycaps presets live in a separate namespace — the preset_id
        # arrives as ``pycaps:<template>``. We remember the template
        # per-entry so _on_export_done can run pycaps as a post-pass.
        # For the base transcription we just use a reasonable default
        # preset ("pop") so the libass path also has something to
        # render with if the user turns pycaps off later.
        animated_style: str | None = None
        if isinstance(preset_id, str) and preset_id.startswith("pycaps:"):
            animated_style = preset_id.split(":", 1)[1] or None
            base_preset_id = "pop"
        else:
            base_preset_id = preset_id
        preset = resolve_caption_preset(base_preset_id)

        is_letterbox = w._mode is ReframeMode.BLUR_LETTERBOX

        out_dir = w._info.path.parent
        w._subs_panel.set_running(True)
        face_note = "  \u00b7  face-aware" if face_aware and not is_letterbox else ""
        animated_note = (
            f"  \u00b7  animated ({animated_style})" if animated_style else ""
        )
        w._subs_panel.set_status(
            f"Transcribing {w._info.path.name} with whisper-{model} "
            f"\u2014 {preset.label} style{face_note}{animated_note}"
        )
        if not subtitles_installed():
            w._subs_panel.set_status("Installing faster-whisper (one-time, ~200 MB)\u2026")
        w._refresh_overview()

        entry_id = w._current_entry.id
        # Remember the animated style on the entry so _on_export_done
        # can run the pycaps post-pass after the main encode finishes.
        if animated_style:
            self.animated_styles[entry_id] = animated_style
        else:
            self.animated_styles.pop(entry_id, None)

        self.subtitle_worker = SubtitleWorker(
            w._info.path,
            out_dir,
            preset=preset,
            height_px=w._preset.height,
            model_name=model,
            language=language,
            face_aware=face_aware,
            letterbox=is_letterbox,
            force_word_level=bool(animated_style),
        )
        self.subtitle_worker.progress.connect(w._subs_panel.set_progress)
        self.subtitle_worker.status.connect(w._subs_panel.set_status)
        self.subtitle_worker.captions_ready.connect(
            lambda caps, eid=entry_id: self._set_cached_captions(eid, caps)
        )
        self.subtitle_worker.finished_ok.connect(
            lambda srt, eid=entry_id: self._on_subs_done(srt, eid)
        )
        self.subtitle_worker.failed.connect(self._on_subs_fail)
        self.subtitle_worker.start()

    def _on_subs_done(self, srt_str: str, entry_id: int) -> None:
        srt = Path(srt_str)
        self.clip_subs[entry_id] = srt
        w = self.win
        w._subs_panel.set_running(False)
        if w._current_entry and w._current_entry.id == entry_id:
            w._subs_panel.set_srt_path(srt)
        w._toast.show_toast(f"Captions ready: {srt.name}", kind="success")
        w._refresh_overview()
        # Captions for a long clip unlock Suggest segments.
        self.refresh_segments_button()

    def _on_subs_fail(self, msg: str) -> None:
        w = self.win
        w._subs_panel.set_running(False)
        w._subs_panel.set_status(f"Transcription failed: {msg}", tone="warning")
        w._toast.show_toast(msg, kind="error")
        w._refresh_overview()

    # --------------------------------------------------------------- thumbnails
    def export_thumbnails(self) -> None:
        """Write six representative thumbnails (PNG) from the loaded
        clip to a user-chosen folder.

        Uses ``core.keyframes`` — Katna when installed, evenly-spaced
        cv2 frames as the always-available fallback. The call runs on
        the GUI thread because the cv2 path is fast (<1 s for six
        frames on a 1080p clip); if Katna is installed and users hit
        long clips we can lift this onto a worker later.
        """
        from core import keyframes
        from .file_dialogs import get_existing_directory

        w = self.win
        if not w._info:
            w._toast.show_toast("Load a clip first.", kind="warning")
            return
        out_dir = get_existing_directory(w, "Folder for thumbnails")
        if not out_dir:
            return
        try:
            written = keyframes.save_thumbnails(
                w._info.path,
                Path(out_dir),
                n=6,
                prefix=w._info.path.stem,
            )
        except Exception as e:
            w._toast.show_toast(f"Thumbnail export failed: {e}", kind="error")
            return
        if not written:
            w._toast.show_toast(
                "Couldn't decode any frames from this clip.",
                kind="warning",
            )
            return
        w._toast.show_toast(
            f"Saved {len(written)} thumbnail{'' if len(written) == 1 else 's'}",
            kind="success",
        )

    # --------------------------------------------------------------- tighten
    def run_tighten_silences(self) -> None:
        """Run Silero VAD and pull the trim handles to the outer
        speech edges. Surfaces install/setup problems via toast so
        users know why the button did nothing.
        """
        from core import vad

        w = self.win
        if not w._info:
            w._toast.show_toast("Load a clip first.", kind="warning")
            return
        if self.vad_worker and self.vad_worker.isRunning():
            return
        if not vad.is_available():
            w._toast.show_toast(
                "Install silero-vad to enable speech tightening:"
                "  pip install silero-vad",
                kind="warning",
                duration_ms=4500,
            )
            return

        w._toast.show_toast("Analysing speech\u2026", kind="info")
        w._player.tighten_btn.setEnabled(False)

        worker = VadWorker(
            video_path=w._info.path,
            duration_sec=w._info.duration,
        )
        worker.trim_ready.connect(self._on_tighten_ready)
        worker.failed.connect(self._on_tighten_failed)
        self.vad_worker = worker
        worker.start()

    def _on_tighten_ready(self, low: float, high: float, coverage: float) -> None:
        self.vad_worker = None
        w = self.win
        w._player.set_trim_range(low, high)
        # _on_trim_changed fires from the scrubber already; we still
        # update window trim state directly so plan / refresh helpers
        # see the new values immediately.
        w._trim_low = low
        w._trim_high = high
        w._refresh_platform_notice()
        w._refresh_overview()
        pct = int(round(coverage * 100))
        w._toast.show_toast(
            f"Trimmed to speech \u00b7 {pct}% of the clip is voice",
            kind="success",
        )
        w._player.tighten_btn.setEnabled(True)

    def _on_tighten_failed(self, msg: str) -> None:
        self.vad_worker = None
        w = self.win
        w._player.tighten_btn.setEnabled(True)
        if msg == WORKER_CANCELLED_MSG:
            return
        w._toast.show_toast(msg, kind="warning")

    # --------------------------------------------------------------- highlights
    def run_find_highlights(self) -> None:
        """Score the clip for high-energy moments and pop a menu the
        user can pick from to drop the trim on the chosen span.

        Uses ``core.highlights.score_spans`` which transparently chooses
        Lighthouse (when installed) or a fallback sliding-window audio
        energy sweep. Either path runs on ``HighlightsWorker``.
        """
        w = self.win
        if not w._info:
            w._toast.show_toast("Load a clip first.", kind="warning")
            return
        if self.highlights_worker and self.highlights_worker.isRunning():
            return

        w._toast.show_toast("Scanning for highlights\u2026", kind="info")
        w._player.highlights_btn.setEnabled(False)

        worker = HighlightsWorker(video_path=w._info.path, top_n=5)
        worker.finished_ok.connect(self._on_highlights_ready)
        worker.failed.connect(self._on_highlights_failed)
        self.highlights_worker = worker
        worker.start()

    def _on_highlights_ready(self, highlights: list) -> None:
        self.highlights_worker = None
        w = self.win
        w._player.highlights_btn.setEnabled(True)
        if not highlights:
            w._toast.show_toast(
                "No clear highlights detected in this clip.",
                kind="warning",
            )
            return
        self._present_highlights_menu(highlights)

    def _on_highlights_failed(self, msg: str) -> None:
        self.highlights_worker = None
        w = self.win
        w._player.highlights_btn.setEnabled(True)
        if msg == WORKER_CANCELLED_MSG:
            return
        w._toast.show_toast(msg, kind="warning")

    def _present_highlights_menu(self, highlights: list) -> None:
        """Show a popup menu of ranked highlights anchored to the
        Find-highlights button. Clicking an entry drops the trim.

        Highlights are already sorted best-score-first by the
        controller; we display them that way but keep the timeline
        position in the label so users can see where they are.
        """
        w = self.win
        menu = QMenu(w)
        menu.setAccessibleName("Highlight moments")

        for h in highlights:
            label = self._format_highlight_label(h)
            action = menu.addAction(label)
            # Capture start/end per-action; lambdas in a loop would bind
            # to the last value otherwise.
            action.triggered.connect(
                lambda _checked=False, s=float(h.start), e=float(h.end):
                    self._apply_highlight_trim(s, e)
            )

        # Anchor the menu below the button that triggered it.
        btn = w._player.highlights_btn
        global_pos = btn.mapToGlobal(btn.rect().bottomLeft())
        menu.exec(global_pos)

    def _format_highlight_label(self, h) -> str:
        score_pct = int(round(max(0.0, min(1.0, float(h.score))) * 100))
        return (
            f"{_fmt_duration(max(0.0, float(h.start)))} \u2013 "
            f"{_fmt_duration(max(0.0, float(h.end)))}"
            f"   \u00b7   {score_pct}%   [{h.source}]"
        )

    def _apply_highlight_trim(self, start: float, end: float) -> None:
        w = self.win
        w._player.set_trim_range(start, end)
        w._trim_low = start
        w._trim_high = end
        w._refresh_platform_notice()
        w._refresh_overview()

    # --------------------------------------------------------------- segment proposals (T3b)
    def refresh_segments_button(self) -> None:
        """Enable ``Suggest segments`` only when the loaded clip is long
        enough (> 10 min) and a cached transcript exists for it.

        We keep the gate permissive on duration (``should_propose_for_duration``
        is the single source of truth) and strict on transcript — proposals
        are strictly derived from the caption stream, so surfacing the
        button without one would be a dead click.
        """
        from core.segment_proposals import should_propose_for_duration

        w = self.win
        btn = getattr(w._player, "segments_btn", None)
        if btn is None:
            return
        info = w._info
        entry = w._current_entry
        has_long_clip = bool(info) and should_propose_for_duration(float(info.duration or 0.0))
        # O(1) lookup against the flag cache populated by
        # _set_cached_captions — avoids scanning every caption on every
        # UI refresh (hot path: called on queue change, subs clear,
        # subs ready, trim change, duration probe).
        has_captions = bool(entry) and self._captions_has_text.get(entry.id, False)
        min_sec, max_sec, target_sec = w._player.segment_band()
        band = _fmt_segment_band(min_sec, max_sec, target_sec)
        btn.setEnabled(has_long_clip and has_captions)
        if has_long_clip and not has_captions:
            btn.setToolTip(
                "Generate AI captions in the Subtitles tab first \u2014 segment "
                f"proposals read from the cached transcript. Current band: {band}."
            )
        elif not has_long_clip and info:
            btn.setToolTip(
                "Segment proposals activate on clips longer than 10 minutes."
            )
        else:
            btn.setToolTip(
                f"Split long clips (> 10 min) into {band} segments "
                "using local TextTiling on the cached transcript. Pick a "
                "segment to drop the trim on it."
            )

    def run_suggest_segments(self) -> None:
        """Produce ranked 30-90 s segment candidates for the loaded clip
        and pop a menu the user can pick from."""
        from core.segment_proposals import should_propose_for_duration

        w = self.win
        if not w._info:
            w._toast.show_toast("Load a clip first.", kind="warning")
            return
        if self.segments_worker and self.segments_worker.isRunning():
            return
        if not should_propose_for_duration(float(w._info.duration or 0.0)):
            w._toast.show_toast(
                "Segment proposals activate on clips longer than 10 minutes.",
                kind="warning",
            )
            return
        entry = w._current_entry
        captions = self.clip_captions.get(entry.id) if entry else None
        if not captions:
            w._toast.show_toast(
                "Generate AI captions first, then try Suggest segments.",
                kind="warning",
                duration_ms=5000,
            )
            return

        min_sec, max_sec, target_sec = w._player.segment_band()
        band = _fmt_segment_band(min_sec, max_sec, target_sec)
        w._toast.show_toast(f"Scanning transcript for {band} segments\u2026", kind="info")
        w._player.segments_btn.setEnabled(False)
        worker = SegmentProposalsWorker(
            captions=list(captions),
            min_sec=min_sec,
            max_sec=max_sec,
            target_sec=target_sec,
        )
        worker.finished_ok.connect(self._on_segments_ready)
        worker.failed.connect(self._on_segments_failed)
        self.segments_worker = worker
        worker.start()

    def _on_segments_ready(self, proposals: list) -> None:
        self.segments_worker = None
        self.refresh_segments_button()
        w = self.win
        if not proposals:
            w._toast.show_toast(
                "No clear segment boundaries found in this transcript.",
                kind="warning",
            )
            return
        self._present_segments_menu(proposals)

    def _on_segments_failed(self, msg: str) -> None:
        self.segments_worker = None
        self.refresh_segments_button()
        if msg == WORKER_CANCELLED_MSG:
            return
        self.win._toast.show_toast(msg, kind="warning")

    def _present_segments_menu(self, proposals: list) -> None:
        """Popup menu of ranked segment proposals anchored to the button."""
        w = self.win
        menu = QMenu(w)
        menu.setAccessibleName("Candidate segments")
        min_sec, max_sec, target_sec = w._player.segment_band()
        band_action = menu.addAction(
            f"Length {_fmt_segment_band(min_sec, max_sec, target_sec)}"
        )
        band_action.setEnabled(False)
        menu.addSeparator()
        for p in proposals:
            label = self._format_segment_label(p)
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, s=float(p.start), e=float(p.end):
                    self._apply_segment_trim(s, e)
            )
        btn = w._player.segments_btn
        global_pos = btn.mapToGlobal(btn.rect().bottomLeft())
        menu.exec(global_pos)

    def _format_segment_label(self, p) -> str:
        score_pct = int(round(max(0.0, min(1.0, float(p.score))) * 100))
        hint = (p.title_hint or "").strip()
        if len(hint) > 52:
            hint = hint[:51].rstrip() + "\u2026"
        reasons = ", ".join(p.reasons) if p.reasons else "length fit"
        return (
            f"{_fmt_duration(max(0.0, float(p.start)))} \u2013 "
            f"{_fmt_duration(max(0.0, float(p.end)))}"
            f"   \u00b7   {score_pct}%   \u00b7   {hint}   [{reasons}]"
        )

    def _apply_segment_trim(self, start: float, end: float) -> None:
        w = self.win
        w._player.set_trim_range(start, end)
        w._trim_low = start
        w._trim_high = end
        w._refresh_platform_notice()
        w._refresh_overview()

    # --------------------------------------------------------------- trim silences
    def run_trim_silences(self) -> None:
        """Kick auto-editor and let the user pick a speech-contiguous
        span to trim to. The output set is ranked by duration so the
        longest continuous speech section shows up first.
        """
        from core import auto_edit

        w = self.win
        if not w._info:
            w._toast.show_toast("Load a clip first.", kind="warning")
            return
        if self.auto_edit_worker and self.auto_edit_worker.isRunning():
            return
        if not auto_edit.is_available():
            w._toast.show_toast(
                f"auto-editor not found on PATH. Install with: "
                f"{auto_edit.install_hint()}",
                kind="warning",
                duration_ms=5000,
            )
            return

        w._toast.show_toast("Scanning for silences\u2026", kind="info")
        w._player.trim_silences_btn.setEnabled(False)

        worker = AutoEditWorker(video_path=w._info.path)
        worker.finished_ok.connect(self._on_trim_silences_ready)
        worker.failed.connect(self._on_trim_silences_failed)
        self.auto_edit_worker = worker
        worker.start()

    def _on_trim_silences_ready(self, spans: list) -> None:
        self.auto_edit_worker = None
        w = self.win
        w._player.trim_silences_btn.setEnabled(True)
        if not spans:
            w._toast.show_toast(
                "Nothing to trim — no speech sections detected.",
                kind="warning",
            )
            return
        # Sort by duration descending; show the top 5 so the menu
        # stays legible on small displays. Ties are broken by the
        # earlier start time so the clip's opening beat wins.
        spans_ranked = sorted(
            spans, key=lambda s: (-s.duration, s.start)
        )[:5]
        self._present_trim_silence_menu(spans_ranked)

    def _on_trim_silences_failed(self, msg: str) -> None:
        self.auto_edit_worker = None
        w = self.win
        w._player.trim_silences_btn.setEnabled(True)
        if msg == WORKER_CANCELLED_MSG:
            return
        w._toast.show_toast(msg, kind="warning")

    def _present_trim_silence_menu(self, spans: list) -> None:
        w = self.win
        menu = QMenu(w)
        menu.setAccessibleName("Speech sections")
        for span in spans:
            label = self._format_silence_label(span)
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, s=float(span.start), e=float(span.end):
                    self._apply_highlight_trim(s, e)
            )
        btn = w._player.trim_silences_btn
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _format_silence_label(self, span) -> str:
        return (
            f"{_fmt_duration(span.start)} \u2013 "
            f"{_fmt_duration(span.end)}"
            f"   \u00b7   {_fmt_duration(span.duration)} of speech"
        )

    # --------------------------------------------------------------- detection
    def run_detect(self) -> None:
        w = self.win
        if not w._info:
            w._toast.show_toast("Load a clip before running Smart Track.", kind="warning")
            w._refresh_detection_actions()
            return
        if self.detect_worker and self.detect_worker.isRunning():
            return
        w._set_detect_status("Scanning for faces\u2026", tone="accent")
        w._detect_progress.setValue(0)
        w._detect_progress.setFormat("Analysis %p%")
        w._detect_progress.show()
        w._refresh_detection_actions()

        if self.scenes:
            n = len(self.scenes)
            w._scene_label.setText(f"{n} scene{'' if n == 1 else 's'} detected \u00b7 panning will respect cuts")
        elif self.scene_worker and self.scene_worker.isRunning():
            w._scene_label.setText("Scene cuts are still loading in the background.")
        else:
            w._scene_label.setText("Continuous take \u2014 no hard cuts detected")

        self.detect_worker = DetectWorker(
            w._info.path,
            sample_fps=2.0,
            smoothing=0.65,
            crop_width_frac=self._smart_track_crop_width_frac(),
        )
        self.detect_worker.progress.connect(
            lambda v: w._detect_progress.setValue(int(v * 100))
        )
        self.detect_worker.finished_ok.connect(self._on_detect_done)
        self.detect_worker.failed.connect(self._on_detect_fail)
        self.detect_worker.start()
        w._refresh_detection_actions()
        w._refresh_overview()

    def _on_detect_done(self, points: list) -> None:
        w = self.win
        self.track_points = points
        w._detect_progress.hide()
        if not points:
            w._set_detect_status(
                "No faces detected \u2014 export will fall back to a stable center crop.",
                tone="warning",
            )
        else:
            extra = f" across {len(self.scenes)} scenes" if self.scenes else ""
            w._set_detect_status(
                f"Tracking {len(points)} keyframes{extra}. Export will follow the subject.",
                tone="success",
            )
        if points:
            w._player.set_track_x(points[0].x)
        w._refresh_detection_actions()
        w._refresh_overview()

    def _on_detect_fail(self, msg: str) -> None:
        w = self.win
        w._detect_progress.hide()
        w._set_detect_status(f"Detection failed: {msg}", tone="warning")
        w._toast.show_toast("Smart Track failed. Try Center Crop or Manual.", kind="error")
        w._refresh_detection_actions()
        w._refresh_overview()

    # --------------------------------------------------------------- export
    def start_export(self) -> None:
        w = self.win
        if not w._info or not w._current_entry:
            return
        if not self._confirm_platform_duration():
            return
        from .file_dialogs import get_save_video_path
        suggested = self._default_output_path(w._info)
        path = get_save_video_path(w, suggested)
        if not path:
            return
        self._run_encode_job(w._info, Path(path), w._current_entry)

    def _confirm_platform_duration(self) -> bool:
        w = self.win
        if not w._info or not w._preset.max_duration:
            return True
        duration = max(0.0, (w._trim_high or w._info.duration) - (w._trim_low or 0.0))
        if duration <= w._preset.max_duration:
            return True
        answer = QMessageBox.warning(
            w,
            "Export above platform limit?",
            (
                f"The current trim is {_fmt_duration(duration)}, which is longer than "
                f"the {w._preset.label} limit of {_fmt_duration(w._preset.max_duration)}.\n\n"
                "Export anyway?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_batch_platform_durations(self, entries: list[QueueEntry]) -> bool:
        w = self.win
        if not w._preset.max_duration:
            return True

        over_limit: list[str] = []
        for entry in entries:
            try:
                info = probe(entry.path)
            except Exception:
                continue
            if info.duration > w._preset.max_duration:
                over_limit.append(f"{entry.path.name} ({_fmt_duration(info.duration)})")

        if not over_limit:
            return True

        preview = "\n".join(f"- {name}" for name in over_limit[:5])
        extra = "" if len(over_limit) <= 5 else f"\n...and {len(over_limit) - 5} more."
        answer = QMessageBox.warning(
            w,
            "Batch includes long clips",
            (
                f"{len(over_limit)} pending clip{'s' if len(over_limit) != 1 else ''} exceed "
                f"the {w._preset.label} limit of {_fmt_duration(w._preset.max_duration)}:\n\n"
                f"{preview}{extra}\n\nExport the batch anyway?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _run_encode_job(self, info: VideoInfo, out_path: Path, entry: QueueEntry | None) -> None:
        w = self.win
        if self.detect_worker and self.detect_worker.isRunning():
            w._toast.show_toast("Wait for analysis to finish before exporting.", kind="warning")
            return
        try:
            plan = build_plan(
                info,
                w._preset,
                w._mode,
                manual_x=w._manual_x,
                track_points=self.track_points,
                scenes=self.scenes,
                adjustments=w._adjustments,
                overlays=w._overlays,
            )
        except Exception as e:
            w._toast.show_toast(f"Could not prepare export: {e}", kind="error")
            return

        trim_end = w._trim_high if w._trim_high and w._trim_high < info.duration else None
        trim_start = w._trim_low or 0.0
        if trim_end is None and trim_start <= 0.001:
            trim_start = 0.0

        out_choice = w._output_choice
        sub_choice = w._subtitle_choice
        # prefer the SRT stored per-clip if one exists
        srt_path = None
        burn = False
        if entry and entry.id in self.clip_subs:
            srt_path = self.clip_subs[entry.id]
            burn = bool(sub_choice and sub_choice.burn_in)
        elif sub_choice and sub_choice.srt_path and sub_choice.burn_in:
            srt_path = sub_choice.srt_path
            burn = True

        # When an animated pycaps style is active for this entry, skip
        # libass burn-in during the main encode — pycaps will burn its
        # own captions in the post-encode pass and two stacks of
        # subtitles would collide.
        will_animate = bool(entry and self.animated_styles.get(entry.id))
        if will_animate:
            burn = False

        job = EncodeJob(
            info=info,
            preset=w._preset,
            plan=plan,
            out_path=out_path,
            trim_start=trim_start,
            trim_end=trim_end,
            encoder=out_choice.encoder if out_choice else None,
            quality=out_choice.quality if out_choice else 75,
            speed_preset=out_choice.speed_preset if out_choice else None,
            subtitles_path=srt_path,
            burn_subtitles=burn,
            caption_preset_id=(sub_choice.preset_id if sub_choice else None),
        )

        if entry:
            w._queue.update_status(entry.id, QueueStatus.ACTIVE, "encoding\u2026")

        w._log.clear()
        w._log.show()
        w._log.append(f"Mode: {w._mode.value}  \u00b7  {plan.notes}")
        w._export_progress.setValue(0)
        self.win._set_export_status("Encoding 0%", tone="accent")
        w._output_row.hide()
        w._export_btn.hide()
        w._cancel_btn.show()
        w._cancel_btn.setEnabled(True)
        w._export_all_btn.setEnabled(False)
        self._set_encode_busy(True)
        w._refresh_progress_hint()
        w._refresh_overview()

        self.encode_worker = EncodeWorker(job)
        self.encode_worker.progress.connect(self._on_export_progress)
        self.encode_worker.log.connect(self._append_log)
        self.encode_worker.finished_ok.connect(
            lambda out, eid=(entry.id if entry else None): self._on_export_done(out, eid)
        )
        self.encode_worker.failed.connect(
            lambda msg, eid=(entry.id if entry else None): self._on_export_fail(msg, eid)
        )
        self.encode_worker.start()

    def run_dry(self) -> None:
        w = self.win
        if not w._info:
            w._toast.show_toast("Load a clip first.", kind="warning")
            return
        from core.dryrun import build_report

        out_choice = w._output_choice
        try:
            report = build_report(
                info=w._info,
                preset=w._preset,
                mode=w._mode,
                track_points=self.track_points,
                scenes=self.scenes,
                adjustments=w._adjustments,
                encoder=out_choice.encoder if out_choice else None,
                quality=out_choice.quality if out_choice else 75,
                speed_preset=out_choice.speed_preset if out_choice else None,
                trim_start=w._trim_low or 0.0,
                trim_end=w._trim_high if w._trim_high and w._trim_high < w._info.duration else None,
                crop_width_frac=self._smart_track_crop_width_frac(),
            )
        except Exception as e:
            w._toast.show_toast(f"Dry-run failed: {e}", kind="error")
            return

        w._log.show()
        w._log.clear()
        w._log.append("Dry run \u2014 no files will be written")
        w._log.append("\u2500" * 58)
        for line in report.as_text().splitlines():
            w._log.append(line)
        self.win._set_export_status("Plan ready", tone="accent")
        w._refresh_progress_hint()
        w._toast.show_toast("Dry-run plan written to the export log.", kind="info")

    # --------------------------------------------------------------- scenes
    def kick_scene_detection(self, path: Path) -> None:
        """Fire-and-forget scene detection so the trim timeline can snap
        to real cuts. Cancels any in-flight scan from a previous clip."""
        if self.scene_worker and self.scene_worker.isRunning():
            self.scene_worker.cancel()

        worker = SceneWorker(path)
        worker.finished_ok.connect(self._on_scenes_ready)
        worker.failed.connect(lambda _msg: None)  # quiet failure — ticks are optional
        self.scene_worker = worker
        worker.start()

    def _on_scenes_ready(self, worker_path: str, scenes: list) -> None:
        w = self.win
        # Guard against stale results from a previous clip
        if not w._info:
            return
        current_path = Path(w._info.path)
        if Path(worker_path) != current_path:
            return
        self.scenes = scenes or []
        boundaries = [end for (_start, end) in self.scenes
                      if 0.0 < end < w._info.duration]
        w._player.set_shot_boundaries(boundaries)
        if hasattr(w, "_scene_label") and w._mode is ReframeMode.SMART_TRACK:
            if scenes:
                n = len(scenes)
                w._scene_label.setText(
                    f"{n} scene{'' if n == 1 else 's'} detected \u00b7 panning will respect cuts"
                )
            else:
                w._scene_label.setText("Continuous take \u2014 no hard cuts detected")
        w._refresh_overview()

    def _smart_track_crop_width_frac(self, *, info: VideoInfo | None = None) -> float | None:
        """Return the 9:16 viewport width as a fraction of source width,
        so the cameraman's safe-zone / big-jump thresholds scale
        correctly per clip. Returns None when geometry is unknown."""
        src = info or self.win._info
        if src is None or src.width <= 0 or src.height <= 0:
            return None
        target = self.win._preset.width / self.win._preset.height
        source = src.width / src.height
        if source >= target:
            crop_w = src.height * target
        else:
            crop_w = src.width
        return max(0.1, min(1.0, crop_w / src.width))

    def _default_output_path(self, info: VideoInfo) -> Path:
        stem = info.path.stem
        return info.path.with_name(f"{stem}_{self.win._preset.id}.mp4")

    # --------------------------------------------------------------- export UI
    def _append_log(self, line: str) -> None:
        log = self.win._log
        keep = line if len(line) <= 400 else line[:400] + "\u2026"
        log.append(keep)
        sb = log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _show_output_destination(self, path: Path) -> None:
        w = self.win
        w._output_label.setToolTip(str(path))
        label = f"Saved: {path.name}"
        width = max(180, w._output_label.width() or 280)
        w._output_label.setText(
            QFontMetrics(w._output_label.font()).elidedText(label, Qt.TextElideMode.ElideMiddle, width)
        )
        w._output_row.show()
        w._refresh_progress_hint()
        w._refresh_hero_header()

    def open_last_output_folder(self) -> None:
        if not self.last_output_path:
            return
        folder = (
            self.last_output_path
            if self.last_output_path.is_dir()
            else self.last_output_path.parent
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_export_progress(self, fraction: float) -> None:
        w = self.win
        pct = int(max(0.0, min(1.0, fraction)) * 100)
        w._export_progress.setValue(pct)
        self.win._set_export_status(f"Encoding {pct}%", tone="accent")
        w._refresh_overview()

    def _on_export_done(self, out: str, entry_id: int | None) -> None:
        out_path = Path(out)

        # Pycaps post-encode pass: when the entry had an animated
        # style selected AND the user generated a transcript, kick a
        # PycapsWorker that re-encodes the just-finished reframed
        # output onto a sibling file. The file swap + UI finalisation
        # run from _on_pycaps_done so the full composite pass stays off
        # the Qt event loop.
        animated_style = (
            self.animated_styles.get(entry_id) if entry_id is not None else None
        )
        if animated_style and entry_id is not None and self._start_pycaps_pass(
            out_path, entry_id, animated_style
        ):
            return

        self._finish_export_done(out_path, entry_id)

    def _start_pycaps_pass(
        self,
        reframed_out: Path,
        entry_id: int,
        template: str,
    ) -> bool:
        """Kick PycapsWorker for the animated-caption post-pass.

        Returns True when a worker was started (the caller must NOT
        finalise the export in that case — ``_on_pycaps_done`` or
        ``_on_pycaps_failed`` will take over). Returns False when the
        optional dep is missing or there's no transcript to feed it, in
        which case the caller should finalise the export as normal.
        """
        w = self.win
        from core import animated_captions

        if not animated_captions.is_available():
            self._append_log(
                "[warn] pycaps selected but not installed — skipping "
                "animated-caption pass."
            )
            return False
        captions = self.clip_captions.get(entry_id)
        if not captions:
            self._append_log(
                "[warn] pycaps pass skipped: no transcript cached. "
                "Generate captions before exporting."
            )
            return False

        tmp_out = reframed_out.with_name(
            f"{reframed_out.stem}.pycaps{reframed_out.suffix}"
        )
        self._pending_pycaps = {
            "reframed_out": reframed_out,
            "tmp_out": tmp_out,
            "entry_id": entry_id,
            "template": template,
        }
        self.win._set_export_status(
            "Rendering animated captions\u2026", tone="accent"
        )
        self._append_log(f"[pycaps] template={template}")
        # Keep cancel enabled so the user can back out of a long pycaps
        # render; the rest of the export-busy UI state (hidden export
        # button, disabled preset buttons) stays put through the pass.
        w._cancel_btn.setEnabled(True)

        worker = PycapsWorker(
            source_video=reframed_out,
            out_path=tmp_out,
            captions=captions,
            template=template,
        )
        worker.finished_ok.connect(self._on_pycaps_done)
        worker.failed.connect(self._on_pycaps_failed)
        self.pycaps_worker = worker
        worker.start()
        return True

    def _on_pycaps_done(self, tmp_out_str: str) -> None:
        """Swap the pycaps output into place and finalise the export."""
        self.pycaps_worker = None
        ctx = self._pending_pycaps or {}
        self._pending_pycaps = None
        reframed_out: Path = ctx.get("reframed_out") or Path(tmp_out_str)
        tmp_out = Path(tmp_out_str)
        entry_id = ctx.get("entry_id")

        final_path = reframed_out
        try:
            reframed_out.unlink(missing_ok=True)
            tmp_out.replace(reframed_out)
        except Exception as e:
            self._append_log(
                f"[pycaps warn] Couldn't swap output ({e}); leaving pycaps "
                f"copy at {tmp_out}."
            )
            final_path = tmp_out

        self._finish_export_done(final_path, entry_id)

    def _on_pycaps_failed(self, msg: str) -> None:
        """Fall back to the reframed export without animated captions.

        Safe when the user has already cleared the clip mid-export:
        ``self.win._info`` may be ``None`` on re-entry, so the fallback
        for ``reframed_out`` never dereferences it — we prefer the
        pending context, then the tmp path, then the last-known
        output. If none of those resolves to a file that actually
        exists we route through the failure finaliser so the UI
        doesn't falsely report ``Complete`` with an empty filename.
        """
        self.pycaps_worker = None
        ctx = self._pending_pycaps or {}
        self._pending_pycaps = None
        tmp_out_val = ctx.get("tmp_out")
        reframed_val = (
            ctx.get("reframed_out")
            or tmp_out_val
            or self.last_output_path
        )
        reframed_out: Path | None = Path(reframed_val) if reframed_val else None
        tmp_out: Path | None = Path(tmp_out_val) if tmp_out_val else reframed_out
        entry_id = ctx.get("entry_id")

        # Always scrub the partial pycaps output so the user doesn't see
        # a truncated sibling file next to their export.
        if tmp_out is not None:
            try:
                tmp_out.unlink(missing_ok=True)
            except Exception:
                pass

        cancelled = msg == WORKER_CANCELLED_MSG

        # No usable reframed file means pycaps failed before the main
        # encode produced anything — route through the honest-failure
        # path rather than claim "Complete" on an empty ``Path('.')``.
        usable = reframed_out is not None and reframed_out.exists()
        if not usable:
            reason = WORKER_CANCELLED_MSG if cancelled else f"{msg} (no reframed output to fall back to)"
            self._append_log(f"[pycaps error] {reason}")
            self._on_export_fail(reason, entry_id)
            return

        if cancelled:
            self._append_log("[pycaps] Cancelled \u2014 kept reframed export.")
        else:
            self._append_log(f"[pycaps error] {msg}")
            self.win._toast.show_toast(
                f"Animated captions failed: {msg}. Export kept without them.",
                kind="warning",
                duration_ms=5000,
            )
        self._finish_export_done(reframed_out, entry_id)

    def _finish_export_done(self, out_path: Path, entry_id: int | None) -> None:
        w = self.win
        self.last_output_path = out_path
        w._export_progress.setValue(100)
        self.win._set_export_status("Complete", tone="success")
        self._append_log(f"[done] Exported {out_path.name}")
        self._show_output_destination(out_path)
        w._toast.show_toast(f"Exported {out_path.name}", kind="success")
        if entry_id is not None:
            w._queue.update_status(entry_id, QueueStatus.DONE, "exported")
        w._refresh_queue_count()
        w._refresh_overview()
        if self.batch_running:
            self._advance_batch()
        else:
            self._reset_export_ui()

    def _on_export_fail(self, msg: str, entry_id: int | None) -> None:
        w = self.win
        self._append_log(f"[error] {msg}")
        cancelled = "cancel" in msg.lower()
        self.win._set_export_status("Cancelled" if cancelled else "Export failed", tone="warning")
        w._toast.show_toast(msg, kind="warning" if cancelled else "error")
        if entry_id is not None:
            w._queue.update_status(entry_id, QueueStatus.FAILED, msg)
        w._refresh_queue_count()
        w._refresh_overview()
        if self.batch_running:
            self._advance_batch()
        else:
            self._reset_export_ui()

    def cancel_active(self) -> None:
        w = self.win
        has_encode = bool(self.encode_worker and self.encode_worker.isRunning())
        has_detect = bool(self.detect_worker and self.detect_worker.isRunning())
        has_subs = bool(self.subtitle_worker and self.subtitle_worker.isRunning())
        has_vad = bool(self.vad_worker and self.vad_worker.isRunning())
        has_hl = bool(self.highlights_worker and self.highlights_worker.isRunning())
        has_ae = bool(self.auto_edit_worker and self.auto_edit_worker.isRunning())
        has_pc = bool(self.pycaps_worker and self.pycaps_worker.isRunning())
        has_seg = bool(self.segments_worker and self.segments_worker.isRunning())
        if not (has_encode or has_detect or has_subs or has_vad or has_hl or has_ae or has_pc or has_seg):
            return
        self.batch_running = False
        w._cancel_btn.setEnabled(False)
        self.win._set_export_status("Cancelling\u2026", tone="warning")
        if has_encode and self.encode_worker:
            self.encode_worker.cancel()
        if has_detect and self.detect_worker:
            self.detect_worker.cancel()
        if has_subs and self.subtitle_worker:
            self.subtitle_worker.cancel()
        if has_vad and self.vad_worker:
            self.vad_worker.cancel()
        if has_hl and self.highlights_worker:
            self.highlights_worker.cancel()
        if has_ae and self.auto_edit_worker:
            self.auto_edit_worker.cancel()
        if has_pc and self.pycaps_worker:
            self.pycaps_worker.cancel()
        if has_seg and self.segments_worker:
            self.segments_worker.cancel()
        w._refresh_overview()

    def _reset_export_ui(self) -> None:
        w = self.win
        w._export_btn.show()
        w._cancel_btn.hide()
        w._cancel_btn.setEnabled(True)
        self._set_encode_busy(False)
        w._refresh_queue_count()
        w._refresh_progress_hint()
        w._refresh_overview()

    def _set_encode_busy(self, busy: bool) -> None:
        w = self.win
        for btn in w._preset_buttons.values():
            btn.setEnabled(not busy)
        for card in w._mode_cards.values():
            card.setEnabled(not busy)
        w._drop.setEnabled(not busy)
        w._export_btn.setEnabled(not busy and w._info is not None)

    # --------------------------------------------------------------- batch
    def start_batch_export(self) -> None:
        from .file_dialogs import get_existing_directory
        w = self.win
        pending = w._queue.pending_entries()
        if not pending:
            return
        if not self._confirm_batch_platform_durations(pending):
            return
        out_dir = get_existing_directory(w, "Output folder for batch")
        if not out_dir:
            return
        self.batch_out_dir = Path(out_dir)
        self.batch_running = True
        w._toast.show_toast(f"Batch export started: {len(pending)} clips", kind="info")
        w._refresh_progress_hint()
        w._refresh_overview()
        self._advance_batch()

    def _advance_batch(self) -> None:
        w = self.win
        if not self.batch_running:
            self._reset_export_ui()
            return
        pending = w._queue.pending_entries()
        if not pending:
            self.batch_running = False
            self.win._set_export_status("Batch complete", tone="success")
            if self.batch_out_dir is not None:
                self.last_output_path = self.batch_out_dir
                self._show_output_destination(self.batch_out_dir)
            w._toast.show_toast("Batch export complete", kind="success")
            self._reset_export_ui()
            return
        entry = pending[0]
        self.suppress_auto_detect = True
        try:
            w._queue.select(entry.id)
        finally:
            self.suppress_auto_detect = False
        try:
            info = probe(entry.path)
        except Exception as e:
            w._queue.update_status(entry.id, QueueStatus.FAILED, f"probe: {e}")
            self._advance_batch()
            return
        w._info = info
        w._current_entry = entry
        w._trim_low = 0.0
        w._trim_high = info.duration
        w._refresh_platform_notice()
        w._refresh_overview()
        if w._mode is ReframeMode.SMART_TRACK:
            # For batch we re-detect per clip. Kick detect then encode when done.
            self.scenes = []
            self.track_points = []
            self._run_detect_then_encode(info, entry)
        else:
            assert self.batch_out_dir is not None  # set in start_batch_export
            out = self.batch_out_dir / f"{info.path.stem}_{w._preset.id}.mp4"
            self._run_encode_job(info, out, entry)

    def _run_detect_then_encode(self, info: VideoInfo, entry: QueueEntry) -> None:
        w = self.win
        w._set_detect_status(f"Batch analysis: {entry.path.name}", tone="accent")
        w._detect_progress.setValue(0)
        w._detect_progress.setFormat("Analysis %p%")
        w._detect_progress.show()
        w._refresh_detection_actions()
        w._refresh_overview()
        self.scenes = []
        self.kick_scene_detection(info.path)

        worker = DetectWorker(
            info.path,
            sample_fps=2.0,
            smoothing=0.65,
            crop_width_frac=self._smart_track_crop_width_frac(info=info),
        )
        worker.progress.connect(lambda v: w._detect_progress.setValue(int(v * 100)))

        def _done(points):
            self.track_points = points
            w._detect_progress.hide()
            w._refresh_detection_actions()
            w._refresh_overview()
            assert self.batch_out_dir is not None
            out = self.batch_out_dir / f"{info.path.stem}_{w._preset.id}.mp4"
            self._run_encode_job(info, out, entry)

        def _fail(msg):
            w._detect_progress.hide()
            w._queue.update_status(entry.id, QueueStatus.FAILED, f"detect: {msg}")
            w._refresh_detection_actions()
            w._refresh_overview()
            self._advance_batch()

        worker.finished_ok.connect(_done)
        worker.failed.connect(_fail)
        self.detect_worker = worker
        worker.start()
        w._refresh_detection_actions()
