"""Monitor-entry profile editor — polished per-channel override editor."""

from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSpinBox, QTimeEdit,
    QVBoxLayout, QWidget,
)

from .widgets import (
    make_dialog_hero,
    make_dialog_section,
    make_status_banner,
    update_status_banner,
)


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class MonitorEntryDialog(QDialog):
    """Edit overrides for a single MonitorEntry."""

    def __init__(self, parent, entry, *, globals_preview=None):
        super().__init__(parent)
        self.entry = entry
        self.setWindowTitle(f"Channel profile — {entry.channel_id or entry.url}")
        self.setMinimumSize(680, 760)
        self.setModal(True)
        self._globals_preview = globals_preview or {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        hero, _, _, self._hero_badge = make_dialog_hero(
            "Channel profile overrides",
            "Tune how this channel records without changing your global defaults. Leave any field blank to inherit the shared app-wide setting.",
            eyebrow="AUTO-RECORD",
            badge_text=entry.channel_id or "Custom profile",
        )
        root.addWidget(hero)

        self.summary_banner, self.summary_title, self.summary_body = make_status_banner()
        root.addWidget(self.summary_banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(0, 0, 0, 0)
        page_lay.setSpacing(12)

        self._build_output_section(page_lay)
        self._build_schedule_section(page_lay)
        self._build_filter_section(page_lay)
        self._build_processing_section(page_lay)
        self._build_retention_section(page_lay)
        page_lay.addStretch(1)

        scroll.setWidget(page)
        root.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("Save profile")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

        self._on_schedule_toggled(self.schedule_enabled.isChecked())
        self._update_summary()

    def _field_label(self, text):
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _build_output_section(self, root):
        section, content = make_dialog_section(
            "Output and naming",
            "Override where recordings land, how files are named, and which quality to prefer for this channel.",
        )

        content.addWidget(self._field_label("Output folder"))
        out_hint = QLabel(
            f"Leave blank to inherit the global folder: {self._globals_preview.get('output_dir') or '(not set)'}"
        )
        out_hint.setObjectName("fieldHint")
        out_hint.setWordWrap(True)
        content.addWidget(out_hint)

        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        self.out_input = QLineEdit(self.entry.override_output_dir or "")
        self.out_input.setPlaceholderText("Use global output folder")
        self.out_input.setClearButtonEnabled(True)
        self.out_input.textChanged.connect(self._update_summary)
        out_row.addWidget(self.out_input, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.setObjectName("secondary")
        browse_btn.clicked.connect(self._on_browse)
        out_row.addWidget(browse_btn)
        content.addLayout(out_row)

        content.addWidget(self._field_label("Filename template"))
        tpl_hint = QLabel(
            f"Leave blank to inherit the global template: {self._globals_preview.get('file_template') or '(not set)'}"
        )
        tpl_hint.setObjectName("fieldHint")
        tpl_hint.setWordWrap(True)
        content.addWidget(tpl_hint)
        self.template_input = QLineEdit(self.entry.override_filename_template or "")
        self.template_input.setPlaceholderText("Use global filename template")
        self.template_input.setClearButtonEnabled(True)
        self.template_input.textChanged.connect(self._update_summary)
        content.addWidget(self.template_input)

        content.addWidget(self._field_label("Quality preference"))
        quality_hint = QLabel(
            "If the exact match is unavailable, StreamKeep falls back gracefully to the best available option."
        )
        quality_hint.setObjectName("fieldHint")
        quality_hint.setWordWrap(True)
        content.addWidget(quality_hint)

        self.quality_combo = QComboBox()
        for key, label in [
            ("", "Use global default"),
            ("highest", "Highest available"),
            ("source", "Source / original"),
            ("1080p", "1080p"),
            ("720p", "720p"),
            ("480p", "480p"),
            ("360p", "360p"),
        ]:
            self.quality_combo.addItem(label, userData=key)
        current_idx = max(0, self.quality_combo.findData(self.entry.override_quality_pref or ""))
        self.quality_combo.setCurrentIndex(current_idx)
        self.quality_combo.currentIndexChanged.connect(self._update_summary)
        content.addWidget(self.quality_combo)

        root.addWidget(section)

    def _build_schedule_section(self, root):
        section, content = make_dialog_section(
            "Schedule and cadence",
            "Restrict when this channel is actively monitored and auto-recorded. Leave scheduling off for always-on monitoring.",
        )

        self.schedule_enabled = QCheckBox("Only monitor during a scheduled window")
        has_window = bool(self.entry.schedule_start_hhmm and self.entry.schedule_end_hhmm)
        self.schedule_enabled.setChecked(has_window)
        self.schedule_enabled.toggled.connect(self._on_schedule_toggled)
        self.schedule_enabled.toggled.connect(self._update_summary)
        content.addWidget(self.schedule_enabled)

        time_row = QHBoxLayout()
        time_row.setSpacing(8)
        time_row.addWidget(self._field_label("From"))
        self.start_time = QTimeEdit(self._parse_hhmm(self.entry.schedule_start_hhmm, 20, 0))
        self.start_time.setDisplayFormat("HH:mm")
        self.start_time.timeChanged.connect(self._update_summary)
        time_row.addWidget(self.start_time)
        time_row.addSpacing(8)
        time_row.addWidget(self._field_label("To"))
        self.end_time = QTimeEdit(self._parse_hhmm(self.entry.schedule_end_hhmm, 23, 0))
        self.end_time.setDisplayFormat("HH:mm")
        self.end_time.timeChanged.connect(self._update_summary)
        time_row.addWidget(self.end_time)
        time_row.addStretch(1)
        content.addLayout(time_row)

        days_hint = QLabel("Choose which days the schedule should apply to.")
        days_hint.setObjectName("fieldHint")
        content.addWidget(days_hint)
        days_row = QHBoxLayout()
        days_row.setSpacing(6)
        self.day_boxes = []
        mask = int(self.entry.schedule_days_mask or 0)
        all_days = mask == 0
        for i, name in enumerate(DAY_NAMES):
            cb = QCheckBox(name)
            cb.setChecked(all_days or bool(mask & (1 << i)))
            cb.toggled.connect(self._update_summary)
            days_row.addWidget(cb)
            self.day_boxes.append(cb)
        days_row.addStretch(1)
        content.addLayout(days_row)

        root.addWidget(section)

    def _build_filter_section(self, root):
        section, content = make_dialog_section(
            "Title filters",
            "Use keywords when only certain stream titles should trigger an auto-record.",
        )

        content.addWidget(self._field_label("Keywords"))
        hint = QLabel(
            "Enter comma-separated keywords such as `tournament, speedrun, collab`. Leave blank to record every stream title."
        )
        hint.setObjectName("fieldHint")
        hint.setWordWrap(True)
        content.addWidget(hint)

        self.keywords_input = QLineEdit(self.entry.filter_keywords or "")
        self.keywords_input.setPlaceholderText("speedrun, tournament, collab")
        self.keywords_input.setClearButtonEnabled(True)
        self.keywords_input.textChanged.connect(self._update_summary)
        content.addWidget(self.keywords_input)

        root.addWidget(section)

    def _build_processing_section(self, root):
        section, content = make_dialog_section(
            "Processing and upgrades",
            "Apply post-processing presets after recording, and optionally replace older captures when higher-quality VODs appear later.",
        )

        content.addWidget(self._field_label("Post-processing preset"))
        hint = QLabel(
            "Leave on the inherited default to keep this channel aligned with your global post-processing pipeline."
        )
        hint.setObjectName("fieldHint")
        hint.setWordWrap(True)
        content.addWidget(hint)

        self.pp_preset_combo = QComboBox()
        self.pp_preset_combo.addItem("Use global default", userData="")
        try:
            from .tabs.settings import BUILTIN_PRESETS, _get_user_presets

            for name in BUILTIN_PRESETS:
                self.pp_preset_combo.addItem(f"★ {name}", userData=name)
            if parent := self.parent():
                for name in _get_user_presets(parent):
                    self.pp_preset_combo.addItem(name, userData=name)
        except Exception:
            pass
        current_preset = self.entry.override_pp_preset or ""
        idx = max(0, self.pp_preset_combo.findData(current_preset))
        self.pp_preset_combo.setCurrentIndex(idx)
        self.pp_preset_combo.currentIndexChanged.connect(self._update_summary)
        content.addWidget(self.pp_preset_combo)

        self.auto_upgrade_check = QCheckBox("Auto-upgrade when a better quality VOD appears")
        self.auto_upgrade_check.setChecked(bool(self.entry.auto_upgrade))
        self.auto_upgrade_check.toggled.connect(self._update_summary)
        content.addWidget(self.auto_upgrade_check)

        upgrade_row = QHBoxLayout()
        upgrade_row.setSpacing(8)
        upgrade_row.addWidget(self._field_label("Upgrade threshold"))
        self.min_upgrade_combo = QComboBox()
        for key, label in [
            ("", "Any improvement"),
            ("480p", "480p or better"),
            ("720p", "720p or better"),
            ("1080p", "1080p or better"),
            ("source", "Source / original only"),
        ]:
            self.min_upgrade_combo.addItem(label, userData=key)
        cur_up_idx = max(0, self.min_upgrade_combo.findData(self.entry.min_upgrade_quality or ""))
        self.min_upgrade_combo.setCurrentIndex(cur_up_idx)
        self.min_upgrade_combo.currentIndexChanged.connect(self._update_summary)
        upgrade_row.addWidget(self.min_upgrade_combo)
        upgrade_row.addStretch(1)
        content.addLayout(upgrade_row)

        root.addWidget(section)

    def _build_retention_section(self, root):
        section, content = make_dialog_section(
            "Retention",
            "Trim older auto-recordings from this channel’s folder after a successful run, or keep everything indefinitely.",
        )

        ret_row = QHBoxLayout()
        ret_row.setSpacing(8)
        ret_row.addWidget(self._field_label("Keep last"))
        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(0, 999)
        self.retention_spin.setValue(int(self.entry.retention_keep_last or 0))
        self.retention_spin.setSpecialValueText("Keep everything")
        self.retention_spin.valueChanged.connect(self._update_summary)
        ret_row.addWidget(self.retention_spin)
        ret_row.addWidget(QLabel("recording(s)"))
        ret_row.addStretch(1)
        content.addLayout(ret_row)

        root.addWidget(section)

    def _parse_hhmm(self, text, default_h, default_m):
        if not text or ":" not in text:
            return QTime(default_h, default_m)
        try:
            h, m = text.split(":", 1)
            return QTime(int(h), int(m))
        except (ValueError, TypeError):
            return QTime(default_h, default_m)

    def _on_browse(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Channel output folder",
            self.out_input.text().strip() or "",
        )
        if path:
            self.out_input.setText(path)

    def _on_schedule_toggled(self, checked):
        for widget in [self.start_time, self.end_time] + self.day_boxes:
            widget.setEnabled(bool(checked))

    def _update_summary(self):
        parts = []
        if self.out_input.text().strip():
            parts.append("custom output")
        if self.template_input.text().strip():
            parts.append("custom naming")
        if (self.quality_combo.currentData() or ""):
            parts.append(f"quality {self.quality_combo.currentData()}")
        if self.schedule_enabled.isChecked():
            parts.append("scheduled monitoring")
        if self.keywords_input.text().strip():
            parts.append("keyword filtered")
        if (self.pp_preset_combo.currentData() or ""):
            parts.append(f"preset {self.pp_preset_combo.currentData()}")
        if self.auto_upgrade_check.isChecked():
            parts.append("auto-upgrade")
        if int(self.retention_spin.value() or 0) > 0:
            parts.append(f"keep last {self.retention_spin.value()}")

        if not parts:
            update_status_banner(
                self.summary_banner,
                self.summary_title,
                self.summary_body,
                title="This profile inherits global defaults",
                body="Leave it this way if you only need this channel to follow the shared app-wide settings.",
                tone="info",
            )
        else:
            update_status_banner(
                self.summary_banner,
                self.summary_title,
                self.summary_body,
                title="This channel has custom behavior",
                body=" • ".join(parts),
                tone="success",
            )

    def _on_save(self):
        entry = self.entry
        entry.override_output_dir = self.out_input.text().strip()
        entry.override_filename_template = self.template_input.text().strip()
        entry.override_quality_pref = self.quality_combo.currentData() or ""
        if self.schedule_enabled.isChecked():
            start = self.start_time.time()
            end = self.end_time.time()
            entry.schedule_start_hhmm = f"{start.hour():02d}:{start.minute():02d}"
            entry.schedule_end_hhmm = f"{end.hour():02d}:{end.minute():02d}"
        else:
            entry.schedule_start_hhmm = ""
            entry.schedule_end_hhmm = ""

        mask = 0
        for i, cb in enumerate(self.day_boxes):
            if cb.isChecked():
                mask |= 1 << i
        if mask == 0b1111111:
            mask = 0
        entry.schedule_days_mask = mask

        entry.filter_keywords = self.keywords_input.text().strip()
        entry.override_pp_preset = self.pp_preset_combo.currentData() or ""
        entry.auto_upgrade = self.auto_upgrade_check.isChecked()
        entry.min_upgrade_quality = self.min_upgrade_combo.currentData() or ""
        entry.retention_keep_last = int(self.retention_spin.value())
        self.accept()
