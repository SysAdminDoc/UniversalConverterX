"""Vertigo main window — premium composition, batch queue driver."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QCloseEvent, QFontMetrics
from PyQt6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QApplication,
    QSizePolicy,
    QSplitter,
    QStackedLayout,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.overlays import TextOverlay
from core.presets import PRESETS, Preset, default_preset
from core.probe import VideoInfo, probe
from core.reframe import Adjustments, ReframeMode

from .adjustments_panel import AdjustmentsPanel
from .batch_queue import BatchQueue, QueueEntry, QueueStatus
from .file_drop import FileDropZone
from .main_controller import MainController, _fmt_duration
from .output_panel import OutputChoice, OutputPanel
from .overlays_panel import OverlaysPanel
from .panels import add_overview_metric, build_tool_section
from .subtitles_panel import SubtitleChoice, SubtitlesPanel
from .theme import apply_app_theme, sanitize_theme_preference, theme_choices
from .titlebar import TitleBar
from .video_player import VideoPlayer
from .widgets import GlassPanel, ModeCard, Toast


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vertigo")
        self.setMinimumSize(1680, 940)
        self.resize(1760, 980)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

        # UI-session state (everything worker/batch-related lives on
        # self._ctl — see ui/main_controller.py). The split is clean:
        # the window owns what the user has selected or loaded, the
        # controller owns background jobs and the results they produce.
        self._settings = QSettings("Vertigo", "Vertigo")
        self._theme_preference = sanitize_theme_preference(
            self._settings.value("theme", "system", type=str)
        )
        self._info: VideoInfo | None = None
        self._current_entry: QueueEntry | None = None
        self._mode: ReframeMode = ReframeMode.CENTER
        self._preset: Preset = default_preset()
        self._manual_x: float = 0.5
        self._adjustments: Adjustments = Adjustments()
        self._trim_low: float = 0.0
        self._trim_high: float = 0.0
        self._output_choice: OutputChoice | None = None
        self._subtitle_choice: SubtitleChoice | None = None
        self._overlays: list[TextOverlay] = []

        # Controller owns workers, analysis results, batch state,
        # last-output path, per-clip subtitle paths.
        self._ctl = MainController(self)

        self._build_chrome()
        self._build_body()
        self._ctl.wire()
        self._wire_system_theme()
        self._apply_theme(self._theme_preference, persist=False)
        self._on_mode_changed(ReframeMode.CENTER)
        self._update_preset_ui()
        self._refresh_overview()
        self._refresh_progress_hint()
        self._refresh_hero_header()

    # --------------------------------------------- chrome
    def _build_chrome(self) -> None:
        self._root = QWidget(self)
        self._root.setObjectName("rootWidget")
        root_lay = QVBoxLayout(self._root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        self._titlebar = TitleBar(self._root)
        self._titlebar.set_theme_choices(theme_choices(), self._theme_preference)
        self._titlebar.theme_changed.connect(self._on_theme_changed)
        self._titlebar.minimize_requested.connect(self.showMinimized)
        self._titlebar.toggle_max_requested.connect(self._toggle_max)
        self._titlebar.close_requested.connect(self.close)
        root_lay.addWidget(self._titlebar)

        self._body_host = QWidget()
        root_lay.addWidget(self._body_host, 1)

        self.setCentralWidget(self._root)
        self._toast = Toast(self._root)

    def _toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _on_theme_changed(self, preference: str) -> None:
        self._apply_theme(preference, persist=True)

    def _apply_theme(self, preference: str, *, persist: bool) -> None:
        self._theme_preference = sanitize_theme_preference(preference)
        app = QApplication.instance()
        if app is not None:
            apply_app_theme(app, self._theme_preference)
        self._titlebar.set_theme(self._theme_preference)
        if persist:
            self._settings.setValue("theme", self._theme_preference)
        self._refresh_themed_widgets()

    def _refresh_themed_widgets(self) -> None:
        if hasattr(self, "_mode_cards"):
            for card in self._mode_cards.values():
                card.refresh_theme()
        if hasattr(self, "_queue"):
            self._queue.refresh_theme()
        if hasattr(self, "_player"):
            self._player.refresh_theme()
        if hasattr(self, "_toast"):
            self._toast.refresh_theme()
        if hasattr(self, "_platform_notice"):
            self._refresh_platform_notice()
        if hasattr(self, "_overview_notice"):
            self._refresh_overview()
        if hasattr(self, "_progress_hint"):
            self._refresh_progress_hint()
        if hasattr(self, "_browse_btn"):
            self._refresh_hero_header()

    def _wire_system_theme(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        signal = getattr(app.styleHints(), "colorSchemeChanged", None)
        if signal is not None:
            signal.connect(self._on_system_color_scheme_changed)

    def _on_system_color_scheme_changed(self, *args) -> None:
        if self._theme_preference == "system":
            self._apply_theme("system", persist=False)

    # --------------------------------------------- body
    def _build_body(self) -> None:
        body = QVBoxLayout(self._body_host)
        body.setContentsMargins(20, 20, 20, 20)
        body.setSpacing(14)

        self._workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._workspace_splitter.setChildrenCollapsible(False)
        self._workspace_splitter.setHandleWidth(10)
        self._workspace_splitter.addWidget(self._build_hero())
        self._workspace_splitter.addWidget(self._build_setup_workspace())
        self._workspace_splitter.setStretchFactor(0, 8)
        self._workspace_splitter.setStretchFactor(1, 7)
        self._workspace_splitter.setSizes([980, 760])
        body.addWidget(self._workspace_splitter, 5)
        body.addWidget(self._build_dashboard_board(), 4)

    def _build_hero(self) -> QWidget:
        hero = GlassPanel()
        hero.setObjectName("heroPanel")
        lay = hero.layout()
        lay.setContentsMargins(22, 20, 22, 22)
        lay.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Preview")
        title.setObjectName("bigTitle")
        title_col.addWidget(title)
        self._hero_hint = QLabel("Import footage to preview framing, trim moments, and export behavior in one place.")
        self._hero_hint.setObjectName("subtitle")
        self._hero_hint.setWordWrap(True)
        title_col.addWidget(self._hero_hint)
        header.addLayout(title_col, 1)
        header.addStretch(1)
        self._browse_btn = QPushButton("Import clips")
        self._browse_btn.setObjectName("ghostBtn")
        self._browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._browse_btn.setToolTip("Browse for one or more source clips")
        header.addWidget(self._browse_btn)
        self._hero_output_btn = QPushButton("Reveal export")
        self._hero_output_btn.setObjectName("ghostBtn")
        self._hero_output_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hero_output_btn.setToolTip("Open the folder containing the latest export")
        self._hero_output_btn.hide()
        header.addWidget(self._hero_output_btn)
        self._export_thumbs_btn = QPushButton("Export thumbnails")
        self._export_thumbs_btn.setObjectName("ghostBtn")
        self._export_thumbs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_thumbs_btn.setToolTip(
            "Save six representative PNG frames from the active clip "
            "(for thumbnails, A/B covers, or posting previews)."
        )
        self._export_thumbs_btn.setEnabled(False)
        header.addWidget(self._export_thumbs_btn)
        self._meta_label = QLabel("Waiting for a clip")
        self._meta_label.setObjectName("statusPill")
        self._meta_label.setMaximumWidth(560)
        self._meta_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        header.addWidget(self._meta_label, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(header)

        self._drop = FileDropZone()
        self._player = VideoPlayer()

        self._preview_stack = QStackedLayout()
        preview_host = QWidget()
        preview_host.setLayout(self._preview_stack)
        self._preview_stack.addWidget(self._drop)
        self._preview_stack.addWidget(self._player)
        lay.addWidget(preview_host, 1)

        return hero

    def _build_setup_workspace(self) -> QWidget:
        host = QWidget()
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        grid.addWidget(self._build_overview_panel(), 0, 0)
        grid.addWidget(self._build_export_workspace_panel(), 0, 1)
        grid.addWidget(self._build_preset_panel(), 1, 0)
        grid.addWidget(self._build_mode_panel(), 1, 1)
        grid.setColumnStretch(0, 4)
        grid.setColumnStretch(1, 5)
        grid.setRowStretch(0, 3)
        grid.setRowStretch(1, 4)
        return host

    def _build_dashboard_board(self) -> QWidget:
        host = QWidget()
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(0)
        grid.addWidget(self._build_queue_workspace_panel(), 0, 0)
        grid.addWidget(self._build_look_track_workspace_panel(), 0, 1)
        grid.addWidget(self._build_output_workspace_panel(), 0, 2)
        grid.addWidget(self._build_captions_text_workspace_panel(), 0, 3)
        grid.setColumnStretch(0, 4)
        grid.setColumnStretch(1, 5)
        grid.setColumnStretch(2, 5)
        grid.setColumnStretch(3, 7)
        return host

    def _build_queue_workspace_panel(self) -> QWidget:
        panel = GlassPanel("QUEUE")
        panel.add(self._build_queue_tab(compact=True))
        return panel

    def _build_look_track_workspace_panel(self) -> QWidget:
        panel = GlassPanel("LOOK & TRACK")
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(
            build_tool_section(
                "Look",
                "Tonal adjustments are baked directly into the export.",
                self._build_adjust_tab(compact=True),
            ),
            1,
        )
        row.addWidget(
            build_tool_section(
                "Track",
                "Analyze subjects locally when you want automated framing.",
                self._build_track_tab(compact=True),
            ),
            1,
        )
        panel.layout().addLayout(row)
        return panel

    def _build_output_workspace_panel(self) -> QWidget:
        panel = GlassPanel("OUTPUT")
        panel.add(self._build_output_tab(compact=True))
        return panel

    def _build_captions_text_workspace_panel(self) -> QWidget:
        panel = GlassPanel("CAPTIONS & TEXT")
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(
            build_tool_section(
                "Captions",
                "Generate, style, and optionally burn captions into the export.",
                self._build_subs_tab(compact=True),
            ),
            1,
        )
        row.addWidget(
            build_tool_section(
                "Text",
                "Add title cards, hooks, and lower thirds without leaving the main screen.",
                self._build_overlays_tab(compact=True),
            ),
            1,
        )
        panel.layout().addLayout(row)
        return panel

    def _build_overview_panel(self) -> QWidget:
        panel = GlassPanel("SESSION OVERVIEW")
        panel.layout().setSpacing(8)

        self._overview_title = QLabel("Ready for your first clip")
        self._overview_title.setObjectName("valueBright")
        self._overview_title.setWordWrap(True)
        panel.layout().addWidget(self._overview_title)

        self._overview_body = QLabel(
            "Import footage to preview framing, captions, trimming, and export in one calm workflow."
        )
        self._overview_body.setObjectName("subtitle")
        self._overview_body.setWordWrap(True)
        panel.layout().addWidget(self._overview_body)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(10)
        metrics.setVerticalSpacing(4)
        self._overview_preset = add_overview_metric(metrics,0, 0, "Preset")
        self._overview_mode = add_overview_metric(metrics,0, 1, "Mode")
        self._overview_trim = add_overview_metric(metrics,0, 2, "Trim")
        self._overview_queue = add_overview_metric(metrics,0, 3, "Queue")
        panel.layout().addLayout(metrics)

        self._overview_notice = QLabel("")
        self._overview_notice.setObjectName("inlineNotice")
        self._overview_notice.setWordWrap(True)
        panel.layout().addWidget(self._overview_notice)
        return panel

    def _build_preset_panel(self) -> QWidget:
        panel = GlassPanel("PLATFORM PRESET")
        self._preset_group = QButtonGroup(self)
        self._preset_group.setExclusive(True)
        chip_grid = QGridLayout()
        chip_grid.setHorizontalSpacing(8)
        chip_grid.setVerticalSpacing(8)
        self._preset_buttons: dict[str, QPushButton] = {}
        for index, (pid, p) in enumerate(PRESETS.items()):
            btn = QPushButton(p.label)
            btn.setObjectName("presetChip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(p.tagline)
            btn.setMinimumHeight(36)
            btn.setAccessibleName(f"{p.label} preset")
            btn.setAccessibleDescription(p.tagline)
            self._preset_group.addButton(btn)
            self._preset_buttons[pid] = btn
            chip_grid.addWidget(btn, index // 2, index % 2)
            btn.clicked.connect(lambda _=False, key=pid: self._choose_preset(key))
        panel.layout().addLayout(chip_grid)

        self._preset_detail = QLabel("")
        self._preset_detail.setObjectName("subtitle")
        self._preset_detail.setWordWrap(True)
        panel.layout().addWidget(self._preset_detail)

        self._platform_notice = QLabel("")
        self._platform_notice.setObjectName("inlineNotice")
        self._platform_notice.setWordWrap(True)
        self._platform_notice.hide()
        panel.layout().addWidget(self._platform_notice)
        self._preset_buttons["shorts"].setChecked(True)
        return panel

    def _build_mode_panel(self) -> QWidget:
        panel = GlassPanel("REFRAME MODE")
        panel.layout().setSpacing(10)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        self._mode_cards = {
            ReframeMode.CENTER: ModeCard(
                "center", "Center crop",
                "Static crop for footage that is already centered."
            ),
            ReframeMode.SMART_TRACK: ModeCard(
                "smart_track", "Smart track",
                "Tracks faces and respects hard scene cuts."
            ),
            ReframeMode.BLUR_LETTERBOX: ModeCard(
                "blur_letterbox", "Blur letterbox",
                "Keeps the full frame on a soft blurred backdrop."
            ),
            ReframeMode.MANUAL: ModeCard(
                "manual", "Manual crop",
                "Drag the crop frame yourself in the preview."
            ),
        }
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for index, (m, card) in enumerate(self._mode_cards.items()):
            self._mode_group.addButton(card)
            grid.addWidget(card, index // 2, index % 2)
            card.clicked.connect(lambda _=False, mode=m: self._on_mode_changed(mode))
        panel.layout().addLayout(grid)
        self._mode_cards[ReframeMode.CENTER].setChecked(True)
        return panel

    def _build_queue_tab(self, *, compact: bool = False) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(6)
        if not compact:
            intro = QLabel("Keep several clips queued, then export them with one consistent setup.")
            intro.setObjectName("subtitle")
            intro.setWordWrap(True)
            lay.addWidget(intro)
        hdr = QHBoxLayout()
        self._queue_count = QLabel("0 clips")
        self._queue_count.setObjectName("valueMuted")
        hdr.addWidget(self._queue_count)
        hdr.addStretch(1)
        clear = QPushButton("Clear queue")
        clear.setObjectName("ghostBtn")
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.clicked.connect(self._clear_queue)
        hdr.addWidget(clear)
        lay.addLayout(hdr)

        self._queue = BatchQueue()
        self._queue.entry_selected.connect(self._on_queue_select)
        self._queue.entry_removed.connect(self._on_queue_removed)
        lay.addWidget(self._queue, 1)
        return host

    def _build_adjust_tab(self, *, compact: bool = False) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        if not compact:
            intro = QLabel("Fine-tune the source before export. These adjustments are baked directly into the output.")
            intro.setObjectName("subtitle")
            intro.setWordWrap(True)
            lay.addWidget(intro)

        self._adjust_panel = AdjustmentsPanel()
        self._adjust_panel.changed.connect(self._on_adjust_changed)
        lay.addWidget(self._adjust_panel)
        lay.addStretch(1)
        return host

    def _build_track_tab(self, *, compact: bool = False) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8 if compact else 10)

        self._detect_status = QLabel("Load a clip to find faces and scene cuts.")
        self._detect_status.setObjectName("inlineNotice")
        self._detect_status.setWordWrap(True)
        lay.addWidget(self._detect_status)

        self._detect_progress = QProgressBar()
        self._detect_progress.setRange(0, 100)
        self._detect_progress.setValue(0)
        self._detect_progress.setTextVisible(False)
        self._detect_progress.hide()
        lay.addWidget(self._detect_progress)

        self._scene_label = QLabel("")
        self._scene_label.setObjectName("valueMuted")
        lay.addWidget(self._scene_label)

        self._detect_btn = QPushButton("Find subjects")
        self._detect_btn.setObjectName("primaryBtn")
        self._detect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._detect_btn.setToolTip("Run Smart Track analysis on the loaded clip")
        self._detect_btn.setEnabled(False)
        self._detect_btn.clicked.connect(self._ctl.run_detect)
        lay.addWidget(self._detect_btn)

        self._dryrun_btn = QPushButton("Show plan (dry run)")
        self._dryrun_btn.setObjectName("ghostBtn")
        self._dryrun_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dryrun_btn.setToolTip(
            "Print the per-scene reframe plan without encoding. No file is written."
        )
        self._dryrun_btn.setEnabled(False)
        self._dryrun_btn.clicked.connect(self._ctl.run_dry)
        lay.addWidget(self._dryrun_btn)

        self._detect_note = QLabel(
            "Smart Track runs locally. Scene cuts are respected so pans do not drift across hard edits."
        )
        self._detect_note.setObjectName("valueMuted")
        self._detect_note.setWordWrap(True)
        lay.addWidget(self._detect_note)
        lay.addStretch(1)
        return host

    def _build_output_tab(self, *, compact: bool = False) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        if not compact:
            intro = QLabel("Pick the encoder and quality balance that match your delivery needs. GPU codecs are fastest when available.")
            intro.setObjectName("subtitle")
            intro.setWordWrap(True)
            lay.addWidget(intro)
        self._output_panel = OutputPanel()
        self._output_panel.changed.connect(self._on_output_changed)
        self._output_choice = self._output_panel.current_selection()
        lay.addWidget(self._output_panel)
        lay.addStretch(1)
        return host

    def _build_overlays_tab(self, *, compact: bool = False) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._overlays_panel = OverlaysPanel()
        self._overlays_panel.overlays_changed.connect(self._on_overlays_changed)
        lay.addWidget(self._overlays_panel, 1)
        return host

    def _build_subs_tab(self, *, compact: bool = False) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._subs_panel = SubtitlesPanel()
        self._subs_panel.changed.connect(self._on_subs_changed)
        self._subs_panel.transcribe_requested.connect(self._ctl.run_transcribe)
        self._subs_panel.clear_requested.connect(self._ctl.on_subs_cleared)
        self._subtitle_choice = self._subs_panel.choice()
        lay.addWidget(self._subs_panel)
        return host

    def _build_action_bar(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self._export_btn = QPushButton("Export clip")
        self._export_btn.setObjectName("primaryBtn")
        self._export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_btn.setEnabled(False)
        self._export_btn.setToolTip("Export the selected clip using the current preset and mode")
        self._export_btn.setMinimumHeight(42)

        self._export_all_btn = QPushButton("Export queue")
        self._export_all_btn.setObjectName("ghostBtn")
        self._export_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_all_btn.setEnabled(False)
        self._export_all_btn.setToolTip("Export every pending clip in the queue")
        self._export_all_btn.setMinimumHeight(42)

        self._cancel_btn = QPushButton("Stop")
        self._cancel_btn.setObjectName("destructiveGhost")
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.setToolTip("Cancel the active analysis or export")
        self._cancel_btn.setMinimumHeight(42)
        self._cancel_btn.hide()

        actions.addWidget(self._export_btn, 2)
        actions.addWidget(self._export_all_btn, 1)
        actions.addWidget(self._cancel_btn, 1)
        return actions

    def _build_export_workspace_panel(self) -> QWidget:
        panel = GlassPanel("EXPORT")
        panel.layout().setSpacing(10)
        panel.layout().addLayout(self._build_action_bar())

        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        label = QLabel("Status")
        label.setObjectName("formLabel")
        hdr.addWidget(label)
        hdr.addStretch(1)
        self._export_status = QLabel("Idle")
        self._export_status.setObjectName("statusPill")
        hdr.addWidget(self._export_status)
        panel.layout().addLayout(hdr)

        self._export_progress = QProgressBar()
        self._export_progress.setRange(0, 100)
        self._export_progress.setValue(0)
        self._export_progress.setTextVisible(False)
        self._export_progress.setAccessibleName("Export progress")
        panel.layout().addWidget(self._export_progress)

        self._progress_hint = QLabel("")
        self._progress_hint.setObjectName("inlineNotice")
        self._progress_hint.setWordWrap(True)
        panel.layout().addWidget(self._progress_hint)

        self._log = QTextEdit()
        self._log.setObjectName("logPanel")
        self._log.setReadOnly(True)
        self._log.setFixedHeight(88)
        self._log.setPlaceholderText("FFmpeg output appears here during dry runs and live exports.")
        self._log.setAccessibleName("Export log")
        self._log.hide()
        panel.layout().addWidget(self._log)

        self._output_row = QWidget()
        output_lay = QHBoxLayout(self._output_row)
        output_lay.setContentsMargins(0, 0, 0, 0)
        output_lay.setSpacing(10)
        self._output_label = QLabel("")
        self._output_label.setObjectName("valueMuted")
        self._output_label.setWordWrap(False)
        output_lay.addWidget(self._output_label, 1)
        self._open_output_btn = QPushButton("Reveal in folder")
        self._open_output_btn.setObjectName("ghostBtn")
        self._open_output_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_output_btn.setToolTip("Open the folder containing the latest export")
        self._open_output_btn.clicked.connect(self._ctl.open_last_output_folder)
        output_lay.addWidget(self._open_output_btn)
        self._output_row.hide()
        panel.layout().addWidget(self._output_row)
        return panel

    # --------------------------------------------- wiring
    # Signals are routed in MainController.wire() — see ui/main_controller.py.
    # Window-side handlers (_import_one, _on_manual_drag, _sync_track_pos,
    # _on_trim_changed, _browse_for_clips) are reached from the controller
    # via self.win._foo; controller-side methods are reached via self.foo.

    # --------------------------------------------- preset
    def _choose_preset(self, pid: str) -> None:
        self._preset = PRESETS[pid]
        self._update_preset_ui()
        self._player.set_aspect(self._preset.width, self._preset.height)
        self._refresh_platform_notice()

    def _update_preset_ui(self) -> None:
        p = self._preset
        duration = (
            f"Trims longer than {p.max_duration}s will need approval"
            if p.max_duration
            else "No platform duration limit"
        )
        self._preset_detail.setText(
            f"{p.tagline}\n"
            f"{p.resolution_label} \u00b7 {p.fps}\u202ffps \u00b7 {p.video_bitrate} video \u00b7 {p.audio_bitrate} audio\n"
            f"{duration}."
        )
        self._refresh_platform_notice()

    def _refresh_platform_notice(self) -> None:
        if not hasattr(self, "_platform_notice"):
            return
        if not self._info:
            self._platform_notice.hide()
            self._refresh_overview()
            return

        duration = max(0.0, (self._trim_high or self._info.duration) - (self._trim_low or 0.0))
        limit = self._preset.max_duration
        if limit and duration > limit:
            self._platform_notice.setProperty("tone", "warning")
            self._platform_notice.setText(
                f"Trim is {_fmt_duration(duration)}, above the {self._preset.label} limit of {_fmt_duration(limit)}."
            )
            self._platform_notice.show()
            if hasattr(self, "_export_btn"):
                self._export_btn.setToolTip("This trim exceeds the selected platform limit. You can still export.")
        elif limit:
            remaining = max(0.0, limit - duration)
            self._platform_notice.setProperty("tone", "success")
            self._platform_notice.setText(
                f"Trim fits {self._preset.label}; {_fmt_duration(remaining)} of headroom remains."
            )
            self._platform_notice.show()
            if hasattr(self, "_export_btn"):
                self._export_btn.setToolTip("Export the selected clip using the current preset and mode")
        else:
            self._platform_notice.hide()
            if hasattr(self, "_export_btn"):
                self._export_btn.setToolTip("Export the selected clip using the current preset and mode")
        self._platform_notice.style().unpolish(self._platform_notice)
        self._platform_notice.style().polish(self._platform_notice)
        self._refresh_overview()

    def _refresh_overview(self) -> None:
        if not hasattr(self, "_overview_title"):
            return

        entries = self._queue.entries() if hasattr(self, "_queue") else []
        pending = len([e for e in entries if e.status is QueueStatus.PENDING])
        done = len([e for e in entries if e.status is QueueStatus.DONE])
        failed = len([e for e in entries if e.status is QueueStatus.FAILED])

        self._overview_preset.setText(self._preset.label)
        self._overview_mode.setText({
            ReframeMode.CENTER: "Center crop",
            ReframeMode.SMART_TRACK: "Smart track",
            ReframeMode.BLUR_LETTERBOX: "Blur letterbox",
            ReframeMode.MANUAL: "Manual crop",
        }[self._mode])

        if not entries:
            queue_text = "Empty"
        else:
            queue_text = f"{len(entries)} clip{'s' if len(entries) != 1 else ''}"
            if pending:
                queue_text += f" · {pending} pending"
            elif done:
                queue_text += " · ready"
            if failed:
                queue_text += f" · {failed} issue{'s' if failed != 1 else ''}"
        self._overview_queue.setText(queue_text)

        notice_tone: str | None = None
        if not self._info or not self._current_entry:
            self._overview_title.setText("Ready for your first clip")
            self._overview_body.setText(
                "Import footage to preview framing, trim moments, captions, and export settings in one calm workflow."
            )
            self._overview_trim.setText("No clip loaded")
            notice = "Next step: drop footage on the preview or click anywhere in the canvas to browse."
        else:
            self._overview_title.setText(self._current_entry.path.name)
            kept = max(0.0, (self._trim_high or self._info.duration) - (self._trim_low or 0.0))
            full_clip = abs((self._trim_low or 0.0)) < 0.01 and abs((self._trim_high or self._info.duration) - self._info.duration) < 0.01
            self._overview_trim.setText(
                f"Full clip · {_fmt_duration(self._info.duration)}"
                if full_clip
                else f"{_fmt_duration(self._trim_low)}–{_fmt_duration(self._trim_high or self._info.duration)}"
            )
            self._overview_body.setText(
                f"{self._info.width}x{self._info.height} · {_fmt_duration(self._info.duration)} source · "
                f"{self._preset.resolution_label} delivery · {_fmt_duration(kept)} kept."
            )

            if self._ctl.encode_worker and self._ctl.encode_worker.isRunning():
                notice = "Export is running now. Keep the window open and Vertigo will finish the clip or queue automatically."
                notice_tone = "accent"
            elif self._ctl.subtitle_worker and self._ctl.subtitle_worker.isRunning():
                notice = "Caption generation is running locally. Export will be ready again as soon as transcription finishes."
                notice_tone = "accent"
            elif self._ctl.detect_worker and self._ctl.detect_worker.isRunning():
                notice = "Smart Track is analyzing subjects and scene cuts locally."
                notice_tone = "accent"
            elif self._mode is ReframeMode.SMART_TRACK and not self._ctl.track_points:
                notice = "Next step: run Find subjects for guided framing, or switch to Center crop if you want the fastest export."
                notice_tone = "warning"
            elif self._mode is ReframeMode.MANUAL:
                notice = "Next step: drag the crop frame in the preview until the composition feels right, then export."
            elif (
                self._current_entry.id in self._ctl.clip_subs
                and self._subtitle_choice
                and self._subtitle_choice.burn_in
            ):
                notice = "Ready to export. Generated captions will be burned directly into the output."
                notice_tone = "success"
            else:
                notice = "Current setup is ready to export."
                notice_tone = "success"

        self._overview_notice.setText(notice)
        self._overview_notice.setProperty("tone", notice_tone)
        self._overview_notice.style().unpolish(self._overview_notice)
        self._overview_notice.style().polish(self._overview_notice)

    def _refresh_progress_hint(self) -> None:
        if not hasattr(self, "_progress_hint"):
            return
        if self._log.isVisible():
            self._progress_hint.hide()
            return

        self._progress_hint.show()
        tone: str | None = None
        if not self._info:
            text = "Load a clip to preview export progress, encoder notes, and the save destination here."
        elif self._ctl.batch_running:
            text = "Queue export is active. Each pending clip will run in order and report progress here."
            tone = "accent"
        elif self._ctl.last_output_path:
            text = "Your latest export is ready below. Reveal it in the folder or export again after making more adjustments."
            tone = "success"
        else:
            text = "When you export, Vertigo will stream live FFmpeg notes here and keep the latest output easy to reveal."

        self._progress_hint.setText(text)
        self._progress_hint.setProperty("tone", tone)
        self._progress_hint.style().unpolish(self._progress_hint)
        self._progress_hint.style().polish(self._progress_hint)

    def _refresh_hero_header(self) -> None:
        if not hasattr(self, "_browse_btn"):
            return
        if self._info and self._current_entry:
            if self._mode is ReframeMode.MANUAL:
                hint = "Space plays the preview. Drag the crop frame directly in the canvas to set composition."
            elif self._mode is ReframeMode.SMART_TRACK:
                hint = "Space plays the preview. Run subject detection when you want the crop to follow your subject."
            else:
                hint = "Space plays the preview. Use the trim timeline below the preview to choose the exported range."
            self._hero_hint.setText(hint)
            self._browse_btn.setText("Add clips")
            self._meta_label.setProperty("tone", "success")
        else:
            self._hero_hint.setText("Import footage to preview framing, trim moments, and export behavior in one place.")
            self._browse_btn.setText("Import clips")
            self._meta_label.setProperty("tone", None)

        has_output = self._ctl.last_output_path is not None
        self._hero_output_btn.setVisible(has_output)
        if has_output:
            self._hero_output_btn.setText(
                "Reveal queue folder" if self._ctl.last_output_path.is_dir() else "Reveal export"
            )

        self._meta_label.style().unpolish(self._meta_label)
        self._meta_label.style().polish(self._meta_label)

    def _browse_for_clips(self) -> None:
        self._drop.browse()

    def _set_detect_status(self, text: str, tone: str | None = None) -> None:
        self._detect_status.setText(text)
        self._detect_status.setProperty("tone", tone)
        self._detect_status.style().unpolish(self._detect_status)
        self._detect_status.style().polish(self._detect_status)

    # --------------------------------------------- mode
    def _on_mode_changed(self, mode: ReframeMode) -> None:
        self._mode = mode
        self._mode_cards[mode].setChecked(True)
        self._player.set_mode(mode.value)

        if mode is ReframeMode.SMART_TRACK:
            if self._info is None:
                self._set_detect_status("Load a clip to find faces and scene cuts.")
                self._scene_label.setText("")
                self._refresh_detection_actions()
                self._refresh_overview()
                return
            if not self._ctl.track_points:
                if self._ctl.suppress_auto_detect:
                    self._set_detect_status("Smart Track will analyze this clip during batch export.", tone="accent")
                else:
                    self._ctl.run_detect()
            else:
                self._set_detect_status(
                    f"Subject tracking ready: {len(self._ctl.track_points)} keyframes.",
                    tone="success",
                )
        else:
            self._detect_progress.hide()
            if mode is ReframeMode.MANUAL:
                self._set_detect_status("Manual mode: drag the crop frame in the preview.")
            elif mode is ReframeMode.BLUR_LETTERBOX:
                self._set_detect_status("Blur Letterbox keeps the full frame and fills the background.")
            else:
                self._set_detect_status("Center Crop is static and does not need analysis.")
        self._refresh_detection_actions()
        self._refresh_overview()
        self._refresh_hero_header()

    def _refresh_detection_actions(self) -> None:
        if not hasattr(self, "_detect_btn"):
            return
        running = bool(self._ctl.detect_worker and self._ctl.detect_worker.isRunning())
        can_analyze = self._info is not None and not running
        self._detect_btn.setEnabled(can_analyze)
        self._detect_btn.setText(
            "Finding subjects\u2026" if running else
            ("Run again" if self._ctl.track_points else "Find subjects")
        )
        if hasattr(self, "_dryrun_btn"):
            self._dryrun_btn.setEnabled(self._info is not None and not running)

    # --------------------------------------------- import
    def _import_one(self, path: str) -> None:
        entry = self._queue.add(Path(path))
        self._refresh_queue_count()
        self._queue.select(entry.id)

    def _import_many(self, paths: list[str]) -> None:
        first_id = None
        for p in paths:
            entry = self._queue.add(Path(p))
            if first_id is None:
                first_id = entry.id
        self._refresh_queue_count()
        n = len(paths)
        self._toast.show_toast(
            f"Queued {n} clip{'' if n == 1 else 's'}",
            kind="success",
        )
        if first_id is not None:
            self._queue.select(first_id)

    def _on_queue_select(self, entry: QueueEntry) -> None:
        self._current_entry = entry
        original_status = entry.status
        if original_status is QueueStatus.PENDING:
            self._queue.update_status(entry.id, QueueStatus.PENDING, "checking clip...")
        try:
            info = probe(entry.path)
        except Exception as e:
            self._queue.update_status(entry.id, QueueStatus.FAILED, "could not read clip")
            self._toast.show_toast(f"Could not read that clip \u2014 {e}", kind="error")
            return
        self._info = info
        self._ctl.track_points = []
        self._ctl.scenes = []
        self._scene_label.setText("")
        if original_status is QueueStatus.PENDING:
            self._queue.update_status(
                entry.id,
                QueueStatus.PENDING,
                f"ready · {_fmt_duration(info.duration)} · {info.width}x{info.height}",
            )
        self._set_meta_text(
            f"{entry.path.name} · {info.width}x{info.height} · {_fmt_duration(info.duration)} · {info.codec}"
        )
        self._player.load(entry.path)
        self._preview_stack.setCurrentWidget(self._player)
        self._player.set_shot_boundaries([])  # clear stale ticks from prior clip
        self._export_btn.setEnabled(True)
        self._export_thumbs_btn.setEnabled(True)
        self._titlebar.set_subtitle(f"Ready - {entry.path.name}")
        self._player.set_aspect(self._preset.width, self._preset.height)
        self._trim_low = 0.0
        self._trim_high = info.duration
        self._refresh_platform_notice()
        self._on_mode_changed(self._mode)
        if hasattr(self, "_subs_panel"):
            self._subs_panel.set_clip_loaded(True)
            self._subs_panel.set_srt_path(self._ctl.clip_subs.get(entry.id))
        self._ctl.kick_scene_detection(info.path)
        if hasattr(self, "_overlays_panel"):
            self._overlays_panel.set_duration(info.duration)
        self._refresh_progress_hint()
        self._refresh_overview()
        self._refresh_hero_header()
        self._ctl.refresh_segments_button()

    def _refresh_queue_count(self) -> None:
        n = self._queue.count()
        entries = self._queue.entries()
        pending = len([e for e in entries if e.status is QueueStatus.PENDING])
        done = len([e for e in entries if e.status is QueueStatus.DONE])
        failed = len([e for e in entries if e.status is QueueStatus.FAILED])
        parts = [f"{n} clip{'s' if n != 1 else ''}", f"{pending} pending"]
        if done:
            parts.append(f"{done} done")
        if failed:
            parts.append(f"{failed} failed")
        self._queue_count.setText("  \u00b7  ".join(parts))
        busy = bool(
            (self._ctl.encode_worker and self._ctl.encode_worker.isRunning()) or
            (self._ctl.detect_worker and self._ctl.detect_worker.isRunning()) or
            self._ctl.batch_running
        )
        self._export_all_btn.setEnabled(pending > 0 and not busy)
        self._refresh_overview()
        self._refresh_hero_header()

    def _set_meta_text(self, text: str) -> None:
        self._meta_label.setToolTip(text)
        width = max(260, self._meta_label.maximumWidth() - 18)
        elided = QFontMetrics(self._meta_label.font()).elidedText(text, Qt.TextElideMode.ElideMiddle, width)
        self._meta_label.setText(elided)

    def _on_queue_removed(self, entry_id: int) -> None:
        # Free the per-clip SRT/ASS the transcribe worker wrote for this
        # entry, if any — the file isn't useful without the source clip
        # in the queue and the dict entry would otherwise leak.
        self._ctl.drop_clip_subs(entry_id)
        self._refresh_queue_count()
        if self._current_entry and self._current_entry.id == entry_id:
            entries = self._queue.entries()
            if entries:
                self._queue.select(entries[0].id)
            else:
                self._clear_active_clip()

    def _clear_queue(self, *, confirm: bool = True) -> None:
        """Drop every queue entry and reset the active clip.

        ``confirm=True`` (default) pops a modal when the queue is non-empty
        — wired to the toolbar's clear button where undoing is a chore.
        ``confirm=False`` skips the dialog so automated tests can exercise
        the reset path without hanging on an offscreen modal.
        """
        if confirm and self._queue.count():
            answer = QMessageBox.question(
                self,
                "Clear queue?",
                "Remove all clips from the queue? Exported files are not affected.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._queue.clear()
        self._clear_active_clip()
        self._refresh_queue_count()

    def _clear_active_clip(self) -> None:
        self._current_entry = None
        self._info = None
        self._ctl.track_points = []
        self._ctl.scenes = []
        self._scene_label.setText("")
        self._set_detect_status("Load a clip to find faces and scene cuts.")
        if self._ctl.scene_worker and self._ctl.scene_worker.isRunning():
            self._ctl.scene_worker.cancel()
        self._player.set_shot_boundaries([])
        self._player.clear()
        self._preview_stack.setCurrentWidget(self._drop)
        self._set_meta_text("Waiting for a clip")
        self._export_btn.setEnabled(False)
        self._export_all_btn.setEnabled(False)
        self._export_thumbs_btn.setEnabled(False)
        self._titlebar.set_subtitle("Vertical video studio")
        self._export_progress.setValue(0)
        self._set_export_status("Idle")
        self._log.clear()
        self._log.hide()
        if not self._ctl.last_output_path:
            self._output_row.hide()
        self._refresh_platform_notice()
        self._refresh_detection_actions()
        self._refresh_progress_hint()
        if hasattr(self, "_subs_panel"):
            self._subs_panel.set_clip_loaded(False)
            self._subs_panel.set_srt_path(None)
        self._refresh_overview()
        self._refresh_hero_header()

    # --------------------------------------------- interactions
    def _on_manual_drag(self, x: float) -> None:
        self._manual_x = x

    def _sync_track_pos(self, t: float) -> None:
        if self._mode is not ReframeMode.SMART_TRACK or not self._ctl.track_points:
            return
        nearest = min(self._ctl.track_points, key=lambda p: abs(p.t - t))
        self._player.set_track_x(nearest.x)

    def _on_trim_changed(self, low: float, high: float) -> None:
        self._trim_low = low
        self._trim_high = high
        self._refresh_platform_notice()
        self._refresh_overview()

    def _on_adjust_changed(self, adj: Adjustments) -> None:
        self._adjustments = adj

    def _on_output_changed(self, choice: OutputChoice) -> None:
        self._output_choice = choice

    def _on_subs_changed(self, choice: SubtitleChoice) -> None:
        self._subtitle_choice = choice
        self._refresh_overview()

    def _on_overlays_changed(self, overlays: list) -> None:
        self._overlays = overlays

    # Worker lifecycle, batch driver, and per-worker signal handlers live
    # on self._ctl (ui/main_controller.py). Public API the window calls
    # into: run_transcribe, on_subs_cleared, run_detect, start_export,
    # run_dry, start_batch_export, cancel_active, kick_scene_detection,
    # open_last_output_folder, shutdown, has_running_worker.

    def _set_export_status(self, text: str, tone: str | None = None) -> None:
        """Status-pill label under the progress bar. UI helper used by
        the controller's worker callbacks and by _clear_active_clip."""
        if hasattr(self, "_export_status"):
            self._export_status.setText(text)
            self._export_status.setProperty("tone", tone)
            self._export_status.style().unpolish(self._export_status)
            self._export_status.style().polish(self._export_status)

    # --------------------------------------------- lifecycle
    def closeEvent(self, event: QCloseEvent) -> None:
        self._ctl.shutdown(1500)
        super().closeEvent(event)
