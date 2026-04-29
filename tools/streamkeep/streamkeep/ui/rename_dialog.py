"""Batch Rename Studio — premium multi-recording rename flow."""

import json
import os
from datetime import datetime

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..theme import CAT
from .widgets import (
    make_dialog_hero,
    make_dialog_section,
    make_empty_state,
    make_status_banner,
    style_table,
    update_status_banner,
)


def _read_metadata(dir_path):
    """Read metadata.json from a recording directory."""
    p = os.path.join(dir_path, "metadata.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _safe_name(s, max_len=120):
    if not s:
        return ""
    bad = '<>:"/\\|?*'
    out = "".join(c if c not in bad else "_" for c in s.strip())[:max_len]
    out = out.rstrip(". ")
    # Prevent empty results — fall back to underscores
    return out if out else "_"


def _resolve_template(template, meta, seq):
    """Resolve template tokens against metadata dict + sequence number."""
    result = template
    result = result.replace(
        "{channel}",
        _safe_name(meta.get("vod_channel", "") or meta.get("platform", "")),
    )
    result = result.replace("{platform}", _safe_name(meta.get("platform", "")))
    result = result.replace("{title}", _safe_name(meta.get("title", "")))
    result = result.replace("{quality}", _safe_name(meta.get("quality", "")))
    result = result.replace("{date}", (meta.get("downloaded_at", "") or "")[:10])

    dur_secs = int(meta.get("total_secs", 0) or 0)
    hh = dur_secs // 3600
    mm = (dur_secs % 3600) // 60
    result = result.replace("{duration}", f"{hh}h{mm:02d}m")

    if "{seq:" in result:
        import re

        m = re.search(r"\{seq:(\d+)\}", result)
        if m:
            width = len(m.group(1))
            result = result.replace(m.group(0), str(seq).zfill(width))
    elif "{seq}" in result:
        result = result.replace("{seq}", str(seq))

    return result.strip() or f"recording_{seq}"


class RenameDialog(QDialog):
    """Batch rename dialog for History entries."""

    _PRESETS = [
        ("Balanced", "{channel} - {date} - {title}"),
        ("Archive", "{date} - {channel} - {title} - {quality}"),
        ("Minimal", "{title}"),
        ("Series", "{channel} - {seq:001} - {title}"),
    ]

    def __init__(self, parent, entries):
        super().__init__(parent)
        self.setWindowTitle("Batch Rename Studio")
        self.setMinimumSize(860, 580)
        self.setModal(True)
        self._entries = entries
        self._parent_win = parent

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        hero, _, _, self._hero_badge = make_dialog_hero(
            "Rename recordings with a live preview",
            "Build a consistent naming pattern before you commit changes. Preview updates instantly, duplicate names are flagged, and an undo log is written after the batch runs.",
            eyebrow="BATCH TOOLS",
            badge_text=f"{len(entries)} selected",
        )
        root.addWidget(hero)

        template_card, template_content = make_dialog_section(
            "Template",
            "Use tokens to build a naming pattern that stays readable across platforms, dates, and long recording libraries.",
        )
        token_hint = QLabel(
            "Tokens: {channel}  {date}  {title}  {quality}  {duration}  {platform}  {seq:001}"
        )
        token_hint.setObjectName("fieldHint")
        token_hint.setWordWrap(True)
        template_content.addWidget(token_hint)

        self.template_input = QLineEdit("{channel} - {date} - {title}")
        self.template_input.setClearButtonEnabled(True)
        self.template_input.textChanged.connect(self._refresh_preview)
        template_content.addWidget(self.template_input)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        preset_label = QLabel("Quick presets")
        preset_label.setObjectName("fieldLabel")
        preset_row.addWidget(preset_label)
        for label, template in self._PRESETS:
            btn = QPushButton(label)
            btn.setObjectName("ghost")
            btn.clicked.connect(lambda _checked=False, tpl=template: self._apply_template(tpl))
            preset_row.addWidget(btn)
        preset_row.addStretch(1)
        template_content.addLayout(preset_row)

        self.status_banner, self.status_title, self.status_body = make_status_banner()
        template_content.addWidget(self.status_banner)
        root.addWidget(template_card)

        preview_card, preview_content = make_dialog_section(
            "Preview",
            "Review the current folder names against the generated results before renaming anything on disk.",
        )
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Current name", "New name"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 340)
        style_table(self.table)
        preview_content.addWidget(self.table)

        self.empty_card, self.empty_title, self.empty_body = make_empty_state(
            "Nothing to rename",
            "Select one or more finished recordings from History, then reopen Batch Rename Studio.",
        )
        preview_content.addWidget(self.empty_card)
        root.addWidget(preview_card, 1)

        summary_row = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setObjectName("statusLabel")
        summary_row.addWidget(self.count_label)
        summary_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        summary_row.addWidget(cancel_btn)
        self.rename_btn = QPushButton("Rename selected")
        self.rename_btn.setObjectName("primary")
        self.rename_btn.clicked.connect(self._on_rename)
        summary_row.addWidget(self.rename_btn)
        root.addLayout(summary_row)

        self._metas = []
        for entry in entries:
            self._metas.append(_read_metadata(entry.path) if entry.path else {})

        self._refresh_preview()

    def _apply_template(self, template):
        self.template_input.setText(template)

    def _refresh_preview(self):
        tpl = self.template_input.text().strip()
        self.table.setRowCount(len(self._entries))
        names = []

        for i, (entry, meta) in enumerate(zip(self._entries, self._metas)):
            old_name = os.path.basename((entry.path or "").rstrip("\\/")) or "(unknown)"
            new_name = _resolve_template(tpl, meta, i + 1)
            names.append(new_name)
            self.table.setItem(i, 0, QTableWidgetItem(old_name))
            new_item = QTableWidgetItem(new_name)
            self.table.setItem(i, 1, new_item)

        seen = {}
        conflicts = 0
        for i, name in enumerate(names):
            lowered = name.lower()
            if lowered in seen:
                conflicts += 1
                for col in range(2):
                    self.table.item(i, col).setForeground(QColor(CAT["red"]))
                    self.table.item(seen[lowered], col).setForeground(QColor(CAT["red"]))
            else:
                seen[lowered] = i

        has_entries = bool(self._entries)
        self.table.setVisible(has_entries)
        self.empty_card.setVisible(not has_entries)
        self.rename_btn.setEnabled(has_entries and conflicts == 0)

        if not has_entries:
            self.count_label.setText("No recordings selected")
            update_status_banner(
                self.status_banner,
                self.status_title,
                self.status_body,
                title="Nothing selected",
                body="Choose one or more recordings from History to generate a rename preview.",
                tone="warning",
            )
            return

        if conflicts:
            self.count_label.setText(f"{conflicts} naming conflict(s) detected")
            update_status_banner(
                self.status_banner,
                self.status_title,
                self.status_body,
                title="Duplicate names detected",
                body="Conflicting rows are highlighted in red. Adjust the template before renaming.",
                tone="error",
            )
        else:
            self.count_label.setText(f"{len(self._entries)} recording(s) ready to rename")
            update_status_banner(
                self.status_banner,
                self.status_title,
                self.status_body,
                title="Preview looks good",
                body="Every selected recording has a unique destination name.",
                tone="success",
            )

    def _on_rename(self):
        tpl = self.template_input.text().strip()
        undo_log = []
        renamed = 0
        skipped = 0

        for i, (entry, meta) in enumerate(zip(self._entries, self._metas)):
            if not entry.path or not os.path.isdir(entry.path):
                skipped += 1
                continue
            parent = os.path.dirname(entry.path.rstrip("\\/"))
            old_name = os.path.basename(entry.path.rstrip("\\/"))
            new_name = _resolve_template(tpl, meta, i + 1)
            if new_name == old_name:
                skipped += 1
                continue
            new_path = os.path.join(parent, new_name)
            if os.path.exists(new_path):
                skipped += 1
                continue
            try:
                os.rename(entry.path, new_path)
                undo_log.append({"old": entry.path, "new": new_path})
                entry.path = new_path
                if getattr(entry, "db_id", 0):
                    from streamkeep import db as _db

                    _db.update_history_entry(entry.db_id, {"path": new_path})
                renamed += 1
            except OSError:
                skipped += 1
                continue

        if undo_log:
            from ..paths import CONFIG_DIR

            log_path = CONFIG_DIR / "rename_undo.json"
            try:
                existing = []
                if log_path.exists():
                    with open(log_path, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                existing.append({"ts": datetime.now().isoformat(), "ops": undo_log})
                with open(log_path, "w", encoding="utf-8") as f:
                    json.dump(existing[-20:], f, indent=2)
            except Exception:
                pass

        if self._parent_win:
            self._parent_win._refresh_history_table()
            self._parent_win._persist_config()

        update_status_banner(
            self.status_banner,
            self.status_title,
            self.status_body,
            title="Rename pass complete",
            body=(
                f"Renamed {renamed} recording(s)"
                + (f" and skipped {skipped}." if skipped else ".")
                + " An undo log was saved for recovery."
            ),
            tone="success" if renamed else "warning",
        )
        self.count_label.setText(
            f"Renamed {renamed} • Skipped {skipped}"
        )
        self.accept()
