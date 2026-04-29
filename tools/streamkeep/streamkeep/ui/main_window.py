"""StreamKeep main window — the full QMainWindow class, tabs, and handlers.

Phase 2 of the modularization moved this out of the root-level
StreamKeep.py. The class is still a god object (~3670 lines, 235 methods);
Phase 3 will carve it into per-tab widgets. For now the split wins us a
predictable file layout and keeps the runtime unchanged.
"""

import copy
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidgetItem, QProgressBar,
    QFileDialog, QFrame, QStackedWidget, QSystemTrayIcon,
    QCheckBox, QMenu, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPixmap, QPainter,
    QBrush, QShortcut,
)

# Package re-exports under legacy underscore-prefixed names so the existing
# method bodies below don't need modification.
from streamkeep import VERSION
from streamkeep.paths import _CREATE_NO_WINDOW
from streamkeep.config import (
    load_config as _load_config,
    save_config as _save_config,
    write_log_line as _write_log_line,
)
from streamkeep.theme import CAT
from streamkeep.models import HistoryEntry, ResumeState
from streamkeep.resume import (
    clear_resume_state,
    remaining_segments,
    save_resume_state,
    scan_for_orphan_sidecars,
)
from streamkeep.storage import scan_storage
from streamkeep.chat import ChatWorker
from streamkeep.local_server import LocalCompanionServer
from streamkeep.notifications import NotificationCenter
from streamkeep.updater import (
    UpdateCheckWorker, DownloadUpdateWorker, arm_self_replace,
)
from streamkeep.utils import (
    fmt_size as _fmt_size,
    fmt_duration as _fmt_duration,
    safe_filename as _safe_filename,
    default_output_dir as _default_output_dir,
    render_template as _render_template,
    build_template_context as _build_template_context,
    scan_browser_cookies as _scan_browser_cookies,
    free_space_bytes as _free_space_bytes,
    estimate_download_bytes as _estimate_download_bytes,
    DEFAULT_FOLDER_TEMPLATE,
    DEFAULT_FILE_TEMPLATE,
)
from streamkeep.http import set_native_proxy as _set_native_proxy
from streamkeep.extractors import (
    Extractor,
    TwitchExtractor,
    YtDlpExtractor,
)
from streamkeep.workers import (
    FetchWorker,
    VodPageWorker,
    DownloadWorker,
    FinalizeWorker,
    PlaylistExpandWorker as _PlaylistExpandWorker,
    PageScrapeWorker as _PageScrapeWorker,
    SeedArchiveWorker,
    AutoRecordResolveWorker,
)
from streamkeep.postprocess import (
    PostProcessor,
    ConvertWorker,
    VIDEO_CONTAINERS,
    AUDIO_CONTAINERS,
    AUDIO_CODECS,
    VIDEO_EXTS,
    AUDIO_EXTS,
    available_video_codec_keys as _available_video_codec_keys,
)
from streamkeep.monitor import ChannelMonitor, entry_in_schedule_window
from streamkeep.clipboard import ClipboardMonitor
from streamkeep import db as _db

# Legacy NATIVE_PROXY compatibility — some UI code below assigns this.
NATIVE_PROXY = ""


# ── Main Window ───────────────────────────────────────────────────────────

# Platform badges, tab CSS, and widget builders live in streamkeep.ui.widgets.
# Imported here under legacy underscored names so the method bodies below
# (which still use `self._make_field_block(...)` etc. in 50+ places) keep
# working until a future pass switches each call site.
from .widgets import (
    PLATFORM_BADGES,
    TAB_STYLE,
    ask_premium_confirmation,
    ask_premium_text_input,
    path_label as _path_label,
    make_metric_card,
    make_field_block,
    show_premium_message,
    update_status_banner,
    wrap_scroll_page,
    style_table,
    set_metric,
)
from .tabs.download import build_download_tab
from .tabs.history import build_history_tab
from .tabs.monitor import build_monitor_tab
from .tabs.settings import build_settings_tab
from .tabs.storage import (
    build_storage_tab, populate_storage_table, prompt_confirm_delete,
)


class StreamKeep(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"StreamKeep v{VERSION}")
        self.setMinimumSize(1020, 800)
        self.resize(1120, 900)
        self.setAcceptDrops(True)  # Enable drag-and-drop URL support
        self.stream_info = None
        self.download_worker = None
        self._vod_list = []
        self._vod_checks = []
        self._vod_next_cursor = None
        self._vod_source_url = ""
        self._vod_page_worker = None
        self._segment_checks = []
        self._segment_progress = []
        self._last_auto_output = ""
        self._history = []
        self._config = _load_config()
        self._tray_icon = None
        self._folder_template = DEFAULT_FOLDER_TEMPLATE
        self._file_template = DEFAULT_FILE_TEMPLATE
        self._webhook_url = ""
        self._check_duplicates = True
        self._download_queue = []  # list of dicts: url, title, platform, status
        self._write_nfo = False
        self._dl_overrides = {}  # Per-download settings overrides (F18)
        self._parallel_connections = 4  # Multi-connection splits per direct MP4
        self._recent_urls = []  # most-recent-first list of distinct URLs
        self._last_fetch_request = {
            "url": "",
            "vod_source": "",
            "vod_platform": "",
            "vod_title": "",
            "vod_channel": "",
        }
        self._active_output_dir = ""
        self._active_quality_name = ""
        self._active_history_url = ""
        self._active_stream_info = None
        self._download_had_errors = False
        self._queue_active_item = None
        self._queue_autostart = False
        # Concurrent queue workers (F1). Each active queue item gets its own
        # fetch + download pipeline, keyed by id(item).
        self._queue_workers = {}          # id(item) -> DownloadWorker
        self._queue_fetch_workers = {}    # id(item) -> FetchWorker
        self._queue_contexts = {}         # id(item) -> dict
        self._max_concurrent_downloads = 3
        self._pending_auto_records = []
        self._batch_active = False
        self._monitor_seed_workers = {}
        # Legacy singletons retained for back-compat with the closeEvent
        # teardown path; the new parallel auto-record dicts below are the
        # source of truth.
        self._auto_record_resolve_worker = None
        self._active_auto_record_channel = ""
        # Parallel auto-record pool (v4.15.0). Foreground DownloadWorker
        # remains the singular `self.download_worker`; auto-records live
        # here keyed by channel_id so multiple lives can be captured at
        # the same time without blocking each other on the foreground.
        self._autorecord_resolvers = {}     # channel_id -> AutoRecordResolveWorker
        self._autorecord_workers = {}       # channel_id -> DownloadWorker
        self._autorecord_contexts = {}      # channel_id -> dict (out_dir, info, q_name, history_url)
        self._chat_workers = {}              # channel_id -> ChatWorker (live capture)
        self._companion_server = None        # LocalCompanionServer instance
        self._companion_last_error = ""
        self._notifications = NotificationCenter(capacity=50)
        self._parallel_autorecords = 2      # cap; overridden from config below
        self._chunk_long_captures = False
        self._chunk_length_secs = 7200      # 2 hours default
        self._finalize_tasks = []
        self._finalize_worker = None
        self._finalize_active_title = ""
        self._finalize_active_label = ""
        self._finalize_active_step = 0
        self._finalize_active_total = 0
        self._bandwidth_rule = {
            "enabled": False,
            "start_hour": 9,
            "end_hour": 17,
            "limit": "500K",
        }
        self.monitor = ChannelMonitor()
        self.monitor.status_changed.connect(self._refresh_monitor_table)
        self.monitor.channel_went_live.connect(self._on_channel_live)
        self.monitor.new_vods_found.connect(self._on_new_vods_found)
        self.monitor.log.connect(self._log)
        # Load monitor channels from DB first; fall back to config for
        # pre-migration installs (F41).
        self.monitor.load_from_db()
        if not self.monitor.entries:
            self.monitor.load_from_config(self._config)
        self.clipboard_monitor = ClipboardMonitor()
        self.clipboard_monitor.url_detected.connect(self._on_clipboard_url)
        self._init_ui()
        self._config_save_timer = QTimer(self)
        self._config_save_timer.setSingleShot(True)
        self._config_save_timer.timeout.connect(self._persist_config)
        self._apply_config()
        self._refresh_companion_ui()
        self._init_tray_icon()
        # Scheduler tick: checks scheduled queue items and bandwidth rules every 30s
        self._scheduler_timer = QTimer(self)
        self._scheduler_timer.timeout.connect(self._scheduler_tick)
        self._scheduler_timer.start(30_000)
        self._scheduler_tick()  # Apply bandwidth rule immediately on startup
        # Hook history-table context menu (right-click → Trim / Open / Remove).
        try:
            self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.history_table.customContextMenuRequested.connect(self._on_history_context_menu)
        except Exception:
            pass
        try:
            if hasattr(self, "queue_table"):
                self.queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                self.queue_table.customContextMenuRequested.connect(self._on_queue_context_menu)
        except Exception:
            pass
        try:
            if hasattr(self, "storage_table"):
                self.storage_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                self.storage_table.customContextMenuRequested.connect(self._on_storage_context_menu)
        except Exception:
            pass
        try:
            if hasattr(self, "monitor_table"):
                self.monitor_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
                self.monitor_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                self.monitor_table.setDragEnabled(True)
                self.monitor_table.setAcceptDrops(True)
                self.monitor_table.setDropIndicatorShown(True)
                self.monitor_table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
                self.monitor_table.setDefaultDropAction(Qt.DropAction.MoveAction)
                self.monitor_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                self.monitor_table.customContextMenuRequested.connect(self._on_monitor_context_menu)
                self.monitor_table.model().rowsMoved.connect(self._on_monitor_rows_moved)
        except Exception:
            pass
        # Thumbnail loaders for History and Storage tables (lazy-filled).
        from .thumb_loader import ThumbLoader, PreviewLoader
        self._history_thumb_loader = ThumbLoader(self, max_concurrent=2, size=(160, 90))
        self._history_thumb_loader.thumb_ready.connect(self._on_history_thumb_ready)
        self._storage_thumb_loader = ThumbLoader(self, max_concurrent=2, size=(160, 90))
        self._storage_thumb_loader.thumb_ready.connect(self._on_storage_thumb_ready)
        # Hover preview loader (F46)
        self._preview_loader = PreviewLoader(self)
        self._preview_loader.frame_ready.connect(self._on_preview_frame)
        self._resume_candidates = []
        # Deferred startup scan for orphan resume sidecars — run on the
        # Qt event loop so the main window paints before we hit disk I/O.
        QTimer.singleShot(800, self._scan_for_resumable_downloads)
        # Auto-update check — opt-in, deferred so the UI paints first and
        # so the release-API call doesn't block startup.
        self._update_check_worker = None
        self._update_download_worker = None
        self._latest_update_payload = None
        QTimer.singleShot(2500, self._maybe_check_for_updates)
        # Start the browser-companion local server if the user opted in.
        # Deferred so the UI paints before we open a socket.
        QTimer.singleShot(1000, self._maybe_start_companion_server)
        # Keyboard shortcuts (F11)
        self._setup_shortcuts()

    # ── Keyboard Shortcuts ────────────────────────────────────────────

    def _setup_shortcuts(self):
        """Register global keyboard shortcuts for power-user operation."""
        # Tab switching: Ctrl+1..5
        for i in range(min(5, self._stack.count())):
            sc = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            sc.activated.connect(lambda idx=i: self._switch_tab(idx))
        # Fetch / download: Enter triggers fetch when URL input has focus,
        # otherwise starts download if the button is enabled.
        sc_enter = QShortcut(QKeySequence(Qt.Key.Key_Return), self)
        sc_enter.activated.connect(self._shortcut_enter)
        # Stop: Escape
        sc_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        sc_esc.activated.connect(self._on_stop)
        # Focus search on History: Ctrl+F
        sc_find = QShortcut(QKeySequence("Ctrl+F"), self)
        sc_find.activated.connect(self._shortcut_focus_search)
        # Delete selected items (tab-aware): Delete key
        sc_del = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        sc_del.activated.connect(self._shortcut_delete_selected)
        # Select all rows in the active table: Ctrl+A
        sc_sel = QShortcut(QKeySequence("Ctrl+A"), self)
        sc_sel.activated.connect(self._shortcut_select_all)
        # Update tooltips to show shortcut hints
        self._annotate_shortcut_tooltips()

    def _annotate_shortcut_tooltips(self):
        for i, btn in enumerate(self._tab_btns):
            existing = btn.toolTip() or btn.text()
            btn.setToolTip(f"{existing}  (Ctrl+{i + 1})")
        if hasattr(self, "fetch_btn"):
            self.fetch_btn.setToolTip("Fetch stream info  (Enter)")
        if hasattr(self, "download_btn"):
            self.download_btn.setToolTip("Start download  (Enter)")
        if hasattr(self, "stop_btn"):
            self.stop_btn.setToolTip("Stop  (Esc)")
        if hasattr(self, "history_search"):
            self.history_search.setToolTip("Search history  (Ctrl+F)")

    def _shortcut_enter(self):
        """Enter key: fetch if URL input focused/non-empty, else start download."""
        if hasattr(self, "url_input") and self.url_input.hasFocus():
            self._on_fetch()
            return
        tab = self._stack.currentIndex()
        if tab == 0:
            if hasattr(self, "url_input") and self.url_input.text().strip():
                if hasattr(self, "download_btn") and self.download_btn.isEnabled():
                    self._on_download()
                elif hasattr(self, "fetch_btn") and self.fetch_btn.isEnabled():
                    self._on_fetch()

    def _shortcut_focus_search(self):
        """Ctrl+F: switch to History tab and focus the search box."""
        self._switch_tab(2)  # History is tab index 2
        if hasattr(self, "history_search"):
            self.history_search.setFocus()
            self.history_search.selectAll()

    def _shortcut_delete_selected(self):
        """Delete key: remove selected items from the active tab's table."""
        tab = self._stack.currentIndex()
        if tab == 1 and hasattr(self, "monitor_table"):
            # Monitor tab: remove selected channels
            sel = sorted(
                {idx.row() for idx in self.monitor_table.selectionModel().selectedRows()},
                reverse=True,
            )
            for row in sel:
                if 0 <= row < len(self.monitor.entries):
                    self._on_monitor_remove(row)
        elif tab == 2 and hasattr(self, "history_table"):
            # History tab: remove selected history entries
            sel = sorted(
                {idx.row() for idx in self.history_table.selectionModel().selectedRows()},
                reverse=True,
            )
            view = getattr(self, "_history_view", list(reversed(self._history)))
            db_ids_to_delete = []
            for row in sel:
                if 0 <= row < len(view):
                    try:
                        h = view[row]
                        real = self._history.index(h)
                        self._history.pop(real)
                        if getattr(h, "db_id", 0):
                            db_ids_to_delete.append(h.db_id)
                    except ValueError:
                        pass
            if db_ids_to_delete:
                _db.delete_history_entries(db_ids_to_delete)
            if sel:
                self._refresh_history_table()
                self._persist_config()
        elif tab == 0 and hasattr(self, "queue_table"):
            # Download tab queue: remove selected queue items
            sel = sorted(
                {idx.row() for idx in self.queue_table.selectionModel().selectedRows()},
                reverse=True,
            )
            for row in sel:
                if 0 <= row < len(self._download_queue):
                    item = self._download_queue[row]
                    if item.get("status") != "downloading":
                        self._download_queue.pop(row)
            if sel:
                self._refresh_queue_table()
                self._persist_config()

    def _shortcut_select_all(self):
        """Ctrl+A: select all rows in the current tab's table."""
        tab = self._stack.currentIndex()
        table = None
        if tab == 0 and hasattr(self, "queue_table"):
            table = self.queue_table
        elif tab == 1 and hasattr(self, "monitor_table"):
            table = self.monitor_table
        elif tab == 2 and hasattr(self, "history_table"):
            table = self.history_table
        elif tab == 3 and hasattr(self, "storage_table"):
            table = self.storage_table
        if table:
            table.selectAll()

    def _scheduler_tick(self):
        """Periodic check: start any queue items whose scheduled time has
        arrived, and update rate_limit based on bandwidth scheduler rules."""
        self._apply_bandwidth_schedule()
        # Check for ready scheduled items
        worker = getattr(self, "download_worker", None)
        if worker is not None and worker.isRunning():
            return
        has_ready = any(
            q.get("status") == "queued" and self._queue_item_ready(q)
            for q in self._download_queue
        )
        if has_ready:
            self._advance_queue()

    def _queue_item_ready(self, q):
        """Return True if the queue item is ready to download now."""
        start_at = q.get("start_at", "")
        if not start_at:
            return True
        try:
            ts = datetime.fromisoformat(start_at)
            return ts <= datetime.now()
        except Exception:
            return True

    def _apply_bandwidth_schedule(self):
        """Apply the active bandwidth rule based on current time-of-day."""
        rule = self._bandwidth_rule
        if not rule or not rule.get("enabled"):
            return
        try:
            start_h = int(rule.get("start_hour", 9))
            end_h = int(rule.get("end_hour", 17))
            limit = str(rule.get("limit", "") or "")
            now = datetime.now()
            hour = now.hour
            # Handle wrap-around (e.g. 22..6 = overnight)
            if start_h <= end_h:
                active = start_h <= hour < end_h
            else:
                active = hour >= start_h or hour < end_h
            if active:
                if YtDlpExtractor.rate_limit != limit:
                    YtDlpExtractor.rate_limit = limit
                    self._log(f"[BANDWIDTH] Active window ({start_h:02d}-{end_h:02d}): limit = {limit or 'unlimited'}")
            else:
                baseline = self._config.get("rate_limit", "") or ""
                if YtDlpExtractor.rate_limit != baseline:
                    YtDlpExtractor.rate_limit = baseline
                    self._log(f"[BANDWIDTH] Outside window: baseline = {baseline or 'unlimited'}")
        except Exception as e:
            self._log(f"[BANDWIDTH] Rule error: {e}")
        # F51 speed schedule override
        try:
            from streamkeep.scheduler import get_active_limit
            sched_limit = get_active_limit()
            if sched_limit and sched_limit != YtDlpExtractor.rate_limit:
                YtDlpExtractor.rate_limit = sched_limit
        except Exception:
            pass

    # ── Drag and Drop ─────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        _media_exts = VIDEO_EXTS | AUDIO_EXTS
        # ── Collect URLs and local file paths from the drop ──────────
        http_url = ""
        local_file = ""
        if mime.hasUrls():
            for u in mime.urls():
                if u.isLocalFile():
                    path = u.toLocalFile()
                    if Path(path).suffix.lower() in _media_exts:
                        local_file = path
                        break
                else:
                    s = u.toString()
                    if s.startswith("http"):
                        http_url = s
                        break
        if not http_url and not local_file and mime.hasText():
            text = mime.text().strip().splitlines()[0].strip() if mime.text().strip() else ""
            if text.startswith("http") and len(text) <= 2048:
                http_url = text
            elif os.path.isfile(text) and Path(text).suffix.lower() in _media_exts:
                local_file = text
        # ── Route: local media file → Clip / Trim dialog ────────────
        if local_file:
            self._log(f"[DRAG] Opened local file: {local_file}")
            from .clip_dialog import ClipDialog
            dlg = ClipDialog(self, local_file)
            dlg.exec()
            event.acceptProposedAction()
            return
        # ── Route: HTTP(S) URL → fetch pipeline ─────────────────────
        if http_url:
            if "\n" in http_url or "\r" in http_url or len(http_url) > 2048:
                self._set_status("Dropped content is not a valid URL.", "warning")
                event.ignore()
                return
            self._log(f"[DRAG] Loaded URL: {http_url[:120]}")
            self.url_input.setText(http_url)
            self._switch_tab(0)
            self._on_fetch()
            event.acceptProposedAction()
            return
        # ── Reject everything else ──────────────────────────────────
        if mime.hasUrls():
            exts = ", ".join(sorted(e.lstrip(".") for e in _media_exts)[:8]) + " ..."
            self._set_status(
                f"Dropped file is not a recognized media type ({exts}).",
                "warning",
            )
        event.ignore()

    def _apply_config(self):
        cfg = self._config
        if cfg.get("output_dir"):
            self.output_input.setText(cfg["output_dir"])
            self.settings_output.setText(cfg["output_dir"])
        seg_idx = cfg.get("segment_idx")
        if isinstance(seg_idx, int) and 0 <= seg_idx < self.segment_combo.count():
            self.segment_combo.setCurrentIndex(seg_idx)
        # Templates
        self._folder_template = cfg.get("folder_template") or DEFAULT_FOLDER_TEMPLATE
        self._file_template = cfg.get("file_template") or DEFAULT_FILE_TEMPLATE
        if hasattr(self, "folder_template_input"):
            self.folder_template_input.setText(self._folder_template)
        if hasattr(self, "file_template_input"):
            self.file_template_input.setText(self._file_template)
        # Webhook
        self._webhook_url = cfg.get("webhook_url", "") or ""
        if hasattr(self, "webhook_input"):
            self.webhook_input.setText(self._webhook_url)
        # Duplicate detection
        self._check_duplicates = bool(cfg.get("check_duplicates", True))
        if hasattr(self, "dup_check"):
            self.dup_check.setChecked(self._check_duplicates)
        # NFO export
        self._write_nfo = bool(cfg.get("write_nfo", False))
        if hasattr(self, "nfo_check"):
            self.nfo_check.setChecked(self._write_nfo)
        # Parallel connections per direct mp4
        try:
            conns = int(cfg.get("parallel_connections", 4))
        except (TypeError, ValueError):
            conns = 4
        self._parallel_connections = max(1, min(16, conns))
        if hasattr(self, "parallel_spin"):
            self.parallel_spin.setValue(self._parallel_connections)
        # v4.15.0: parallel auto-records + chunked live captures.
        try:
            par_ar = int(cfg.get("parallel_autorecords", 2))
        except (TypeError, ValueError):
            par_ar = 2
        self._parallel_autorecords = max(1, min(4, par_ar))
        if hasattr(self, "parallel_autorecords_spin"):
            self.parallel_autorecords_spin.setValue(self._parallel_autorecords)
        # Concurrent queue downloads (v4.19.0 — F1).
        try:
            cq = int(cfg.get("max_concurrent_downloads", 3))
        except (TypeError, ValueError):
            cq = 3
        self._max_concurrent_downloads = max(1, min(8, cq))
        if hasattr(self, "concurrent_queue_spin"):
            self.concurrent_queue_spin.setValue(self._max_concurrent_downloads)
        self._chunk_long_captures = bool(cfg.get("chunk_long_captures", False))
        try:
            self._chunk_length_secs = int(cfg.get("chunk_length_secs", 7200) or 7200)
        except (TypeError, ValueError):
            self._chunk_length_secs = 7200
        if hasattr(self, "chunk_check"):
            self.chunk_check.setChecked(self._chunk_long_captures)
        if hasattr(self, "chunk_length_spin"):
            self.chunk_length_spin.setValue(self._chunk_length_secs)
        # Twitch chat download
        TwitchExtractor.download_chat_enabled = bool(cfg.get("download_twitch_chat", False))
        if hasattr(self, "chat_check"):
            self.chat_check.setChecked(TwitchExtractor.download_chat_enabled)
        # Post-processing presets
        PostProcessor.extract_audio = bool(cfg.get("pp_extract_audio", False))
        PostProcessor.normalize_loudness = bool(cfg.get("pp_normalize_loudness", False))
        PostProcessor.reencode_h265 = bool(cfg.get("pp_reencode_h265", False))
        PostProcessor.contact_sheet = bool(cfg.get("pp_contact_sheet", False))
        PostProcessor.split_by_chapter = bool(cfg.get("pp_split_by_chapter", False))
        PostProcessor.remove_silence = bool(cfg.get("pp_remove_silence", False))
        try:
            PostProcessor.silence_noise_db = int(cfg.get("pp_silence_noise_db", -30))
        except (TypeError, ValueError):
            PostProcessor.silence_noise_db = -30
        try:
            PostProcessor.silence_min_duration = float(cfg.get("pp_silence_min_duration", 3.0))
        except (TypeError, ValueError):
            PostProcessor.silence_min_duration = 3.0
        # Converter
        PostProcessor.convert_video = bool(cfg.get("pp_convert_video", False))
        PostProcessor.convert_video_format = cfg.get("pp_convert_video_format") or "mp4"
        PostProcessor.convert_video_codec = cfg.get("pp_convert_video_codec") or "h264"
        PostProcessor.convert_video_scale = cfg.get("pp_convert_video_scale") or "original"
        PostProcessor.convert_video_fps = cfg.get("pp_convert_video_fps") or "original"
        PostProcessor.convert_audio = bool(cfg.get("pp_convert_audio", False))
        PostProcessor.convert_audio_format = cfg.get("pp_convert_audio_format") or "mp3"
        PostProcessor.convert_audio_codec = cfg.get("pp_convert_audio_codec") or "mp3"
        PostProcessor.convert_audio_bitrate = cfg.get("pp_convert_audio_bitrate") or "192k"
        PostProcessor.convert_audio_samplerate = cfg.get("pp_convert_audio_samplerate") or "original"
        PostProcessor.convert_delete_source = bool(cfg.get("pp_convert_delete_source", False))
        if hasattr(self, "pp_audio_check"):
            self.pp_audio_check.setChecked(PostProcessor.extract_audio)
            self.pp_loud_check.setChecked(PostProcessor.normalize_loudness)
            self.pp_h265_check.setChecked(PostProcessor.reencode_h265)
            self.pp_contact_check.setChecked(PostProcessor.contact_sheet)
            self.pp_split_check.setChecked(PostProcessor.split_by_chapter)
        if hasattr(self, "pp_convert_video_check"):
            self.pp_convert_video_check.setChecked(PostProcessor.convert_video)
            if PostProcessor.convert_video_format in VIDEO_CONTAINERS:
                self.pp_convert_video_format.setCurrentIndex(
                    VIDEO_CONTAINERS.index(PostProcessor.convert_video_format))
            vc_keys = _available_video_codec_keys()
            if PostProcessor.convert_video_codec in vc_keys:
                self.pp_convert_video_codec.setCurrentIndex(
                    vc_keys.index(PostProcessor.convert_video_codec))
            scale_items = ["original", "2160p", "1440p", "1080p", "720p", "480p", "360p"]
            if PostProcessor.convert_video_scale in scale_items:
                self.pp_convert_video_scale.setCurrentIndex(
                    scale_items.index(PostProcessor.convert_video_scale))
            fps_items = ["original", "60", "30", "24"]
            if PostProcessor.convert_video_fps in fps_items:
                self.pp_convert_video_fps.setCurrentIndex(
                    fps_items.index(PostProcessor.convert_video_fps))
            self.pp_convert_audio_check.setChecked(PostProcessor.convert_audio)
            if PostProcessor.convert_audio_format in AUDIO_CONTAINERS:
                self.pp_convert_audio_format.setCurrentIndex(
                    AUDIO_CONTAINERS.index(PostProcessor.convert_audio_format))
            ac_keys = list(AUDIO_CODECS.keys())
            if PostProcessor.convert_audio_codec in ac_keys:
                self.pp_convert_audio_codec.setCurrentIndex(
                    ac_keys.index(PostProcessor.convert_audio_codec))
            br_items = ["96k", "128k", "192k", "256k", "320k"]
            if PostProcessor.convert_audio_bitrate in br_items:
                self.pp_convert_audio_bitrate.setCurrentIndex(
                    br_items.index(PostProcessor.convert_audio_bitrate))
            sr_items = ["original", "48000", "44100", "22050"]
            if PostProcessor.convert_audio_samplerate in sr_items:
                self.pp_convert_audio_samplerate.setCurrentIndex(
                    sr_items.index(PostProcessor.convert_audio_samplerate))
            self.pp_convert_delete_check.setChecked(PostProcessor.convert_delete_source)
        # ── SQLite library init + migration (F41) ──
        _db.init_db()
        migrated = _db.migrate_from_config(cfg)
        if migrated:
            _save_config(cfg)
            self._log("[DB] Migrated history/monitor/queue from config.json to library.db")
        # Restore queue from DB
        queue_items = []
        for q in _db.load_queue():
            normalized = self._normalize_queue_item(q)
            if normalized is not None:
                queue_items.append(normalized)
        self._download_queue = queue_items
        # Restore recent URLs
        recents = cfg.get("recent_urls", [])
        if isinstance(recents, list):
            self._recent_urls = [str(u) for u in recents if u][:30]
            if hasattr(self, "_recent_url_model"):
                self._recent_url_model.setStringList(self._recent_urls)
        # Bandwidth schedule rule
        bw = cfg.get("bandwidth_rule")
        if isinstance(bw, dict):
            self._bandwidth_rule.update({
                "enabled": bool(bw.get("enabled", False)),
                "start_hour": int(bw.get("start_hour", 9) or 9),
                "end_hour": int(bw.get("end_hour", 17) or 17),
                "limit": str(bw.get("limit", "500K") or ""),
            })
        if hasattr(self, "bw_enable_check"):
            self.bw_enable_check.setChecked(self._bandwidth_rule["enabled"])
            self.bw_start_spin.setValue(self._bandwidth_rule["start_hour"])
            self.bw_end_spin.setValue(self._bandwidth_rule["end_hour"])
            self.bw_limit_input.setText(self._bandwidth_rule["limit"])
        # Restore history from DB (F41)
        for h in _db.load_history():
            try:
                entry = HistoryEntry.from_dict(h)
                self._history.append(entry)
            except Exception:
                continue
        self._refresh_history_table()
        self._refresh_download_summary()
        self._refresh_monitor_summary()
        self._refresh_history_summary()
        # Build transcript search index in background (F27)
        from ..search import index_all_async
        index_all_async(self._history, log_fn=self._log)

    def _persist_config(self):
        cfg = self._config
        cfg["output_dir"] = self.output_input.text().strip()
        cfg["segment_idx"] = self.segment_combo.currentIndex()
        # History is persisted to SQLite (F41) — not saved to config.json.
        # Per-entry updates (favorite, watched, bookmarks, path) are written
        # incrementally via _db.update_history_entry(); full list save is only
        # needed on clear/bulk-delete.
        cfg["folder_template"] = self._folder_template
        cfg["file_template"] = self._file_template
        cfg["webhook_url"] = self._webhook_url
        cfg["check_duplicates"] = self._check_duplicates
        # Queue is persisted to SQLite (F41)
        _db.save_queue(list(self._download_queue))
        cfg["write_nfo"] = self._write_nfo
        cfg["parallel_connections"] = self._parallel_connections
        cfg["max_concurrent_downloads"] = self._max_concurrent_downloads
        cfg["download_twitch_chat"] = TwitchExtractor.download_chat_enabled
        cfg["pp_extract_audio"] = PostProcessor.extract_audio
        cfg["pp_normalize_loudness"] = PostProcessor.normalize_loudness
        cfg["pp_reencode_h265"] = PostProcessor.reencode_h265
        cfg["pp_contact_sheet"] = PostProcessor.contact_sheet
        cfg["pp_split_by_chapter"] = PostProcessor.split_by_chapter
        cfg["pp_remove_silence"] = PostProcessor.remove_silence
        cfg["pp_silence_noise_db"] = PostProcessor.silence_noise_db
        cfg["pp_silence_min_duration"] = PostProcessor.silence_min_duration
        cfg["pp_convert_video"] = PostProcessor.convert_video
        cfg["pp_convert_video_format"] = PostProcessor.convert_video_format
        cfg["pp_convert_video_codec"] = PostProcessor.convert_video_codec
        cfg["pp_convert_video_scale"] = PostProcessor.convert_video_scale
        cfg["pp_convert_video_fps"] = PostProcessor.convert_video_fps
        cfg["pp_convert_audio"] = PostProcessor.convert_audio
        cfg["pp_convert_audio_format"] = PostProcessor.convert_audio_format
        cfg["pp_convert_audio_codec"] = PostProcessor.convert_audio_codec
        cfg["pp_convert_audio_bitrate"] = PostProcessor.convert_audio_bitrate
        cfg["pp_convert_audio_samplerate"] = PostProcessor.convert_audio_samplerate
        cfg["pp_convert_delete_source"] = PostProcessor.convert_delete_source
        cfg["recent_urls"] = list(self._recent_urls)
        cfg["bandwidth_rule"] = dict(self._bandwidth_rule)
        self.monitor.save_to_config(cfg)
        # Persist monitor channels + queue to SQLite (F41)
        self.monitor.save_to_db()
        _save_config(cfg)

    def _schedule_persist_config(self, delay_ms=500):
        timer = getattr(self, "_config_save_timer", None)
        if timer is None:
            self._persist_config()
            return
        timer.start(max(0, int(delay_ms)))

    def _init_tray_icon(self):
        """Create a system tray icon with badge overlay and live dropdown (F28).
        Falls back gracefully if tray isn't supported."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray_base_pix = QPixmap(32, 32)
        self._tray_base_pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self._tray_base_pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor(CAT["green"])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(2, 2, 28, 28, 6, 6)
        painter.end()
        self._tray_icon = QSystemTrayIcon(QIcon(self._tray_base_pix), self)
        self._tray_icon.setToolTip(f"StreamKeep v{VERSION}")
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()
        self._update_tray_badge()

    def _update_tray_badge(self):
        """Redraw the tray icon with a badge showing the count of live
        channels + active downloads. Called whenever monitor status or
        download state changes."""
        if self._tray_icon is None:
            return
        live = sum(1 for e in self.monitor.entries if e.last_status == "live")
        active_dl = 1 if (self.download_worker and self.download_worker.isRunning()) else 0
        active_dl += len([w for w in self._autorecord_workers.values() if w.isRunning()])
        count = live + active_dl
        pix = self._tray_base_pix.copy()
        if count > 0:
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            # Red badge circle in the top-right corner
            painter.setBrush(QBrush(QColor(CAT["red"])))
            painter.setPen(Qt.PenStyle.NoPen)
            badge_size = 16
            painter.drawEllipse(pix.width() - badge_size, 0, badge_size, badge_size)
            # White count text
            painter.setPen(QColor("#ffffff"))
            font = QFont("Arial", 8, QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(
                pix.width() - badge_size, 0, badge_size, badge_size,
                Qt.AlignmentFlag.AlignCenter, str(min(count, 9)),
            )
            painter.end()
        self._tray_icon.setIcon(QIcon(pix))
        parts = []
        if live:
            parts.append(f"{live} live")
        if active_dl:
            parts.append(f"{active_dl} downloading")
        tip = f"StreamKeep v{VERSION}"
        if parts:
            tip += " — " + ", ".join(parts)
        self._tray_icon.setToolTip(tip)

    def _present_main_window(self, tab_idx=None):
        """Reveal the main window and optionally switch to a specific tab."""
        self.showNormal()
        if tab_idx is not None:
            self._switch_tab(tab_idx)
        self.activateWindow()
        self.raise_()

    def _build_tray_context_menu(self):
        """Build the tray icon right-click dropdown with actionable sections."""
        menu = QMenu(self)
        action_map = {}
        live_entries = [e for e in self.monitor.entries if e.last_status == "live"]
        dl_lines = []
        if self.download_worker and self.download_worker.isRunning():
            done = getattr(self, "_completed_segments", 0)
            total = getattr(self, "_total_segments", 0)
            info = getattr(self, "_active_stream_info", None)
            name = info.title[:40] if info and info.title else "Download"
            pct_str = f"{done}/{total}" if total else "Working"
            dl_lines.append(f"{name} | {pct_str}")
        for ch_id, w in self._autorecord_workers.items():
            if w.isRunning():
                dl_lines.append(f"Auto-record | {ch_id}")
        recent = self._notifications.items()[:5]
        unread = getattr(self._notifications, "unread", 0)

        title_act = menu.addAction(f"StreamKeep v{VERSION}")
        title_act.setEnabled(False)
        summary_act = menu.addAction(
            f"{len(live_entries)} live | {len(dl_lines)} active | {unread} unread"
        )
        summary_act.setEnabled(False)
        menu.addSeparator()

        open_downloads = menu.addAction("Open Downloads")
        action_map[open_downloads] = ("tab", 0)
        open_monitor = menu.addAction("Open Monitor")
        action_map[open_monitor] = ("tab", 1)
        open_history = menu.addAction("Open Archive")
        action_map[open_history] = ("tab", 2)
        open_alerts = menu.addAction("Open Alert Log")
        action_map[open_alerts] = ("alerts", None)
        if self._companion_local_url():
            open_remote = menu.addAction("Open Web Remote")
            action_map[open_remote] = ("remote", None)
        menu.addSeparator()

        if live_entries:
            header = menu.addAction("Live Now")
            header.setEnabled(False)
            for e in live_entries[:8]:
                action = menu.addAction(f"{e.channel_id} | {e.platform}")
                action_map[action] = ("tab", 1)
            menu.addSeparator()

        if dl_lines:
            header = menu.addAction("Active Captures")
            header.setEnabled(False)
            for line in dl_lines[:5]:
                action = menu.addAction(line)
                action_map[action] = ("tab", 0)
            menu.addSeparator()

        if recent:
            header = menu.addAction("Recent Alerts")
            header.setEnabled(False)
            for item in recent:
                ts = item.get("time", "")
                text = item.get("text", "")[:50]
                action = menu.addAction(f"{ts} | {text}")
                action_map[action] = ("alerts", None)
            menu.addSeparator()

        show_act = menu.addAction("Show StreamKeep")
        action_map[show_act] = ("show", None)
        quit_act = menu.addAction("Quit")
        action_map[quit_act] = ("quit", None)
        return menu, action_map

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._present_main_window()
        elif reason == QSystemTrayIcon.ActivationReason.Context:
            menu, action_map = self._build_tray_context_menu()
            chosen = menu.exec(self._tray_icon.geometry().bottomLeft())
            if chosen is None:
                return
            action = action_map.get(chosen)
            if not action:
                return
            kind, value = action
            if kind == "tab":
                self._present_main_window(value)
            elif kind == "alerts":
                self._present_main_window()
                self._on_show_notification_log()
            elif kind == "remote":
                self._on_open_companion_remote()
            elif kind == "show":
                self._present_main_window()
            elif kind == "quit":
                self.close()

    def _notify(self, title, message, icon=QSystemTrayIcon.MessageIcon.Information):
        """Show a tray notification if the window is not focused."""
        if self._tray_icon is None:
            return
        if self.isActiveWindow():
            return  # don't bother user if they're already looking at the app
        try:
            self._tray_icon.showMessage(title, message, icon, 5000)
        except Exception:
            pass

    def _send_webhook(self, event, title, details=""):
        """POST a webhook notification. Auto-detects Discord, Slack,
        Telegram, and ntfy URLs and formats the payload accordingly."""
        url = (self._webhook_url or "").strip()
        if not url:
            return
        platform = self.stream_info.platform if self.stream_info else "unknown"
        src_url = self.url_input.text().strip() if hasattr(self, "url_input") else ""

        if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
            color_map = {"complete": 5763719, "failed": 15548997, "started": 3447003}
            payload = {
                "username": "StreamKeep",
                "embeds": [{
                    "title": f"StreamKeep: {event}",
                    "description": f"**{title[:200]}**",
                    "color": color_map.get(event, 5763719),
                    "fields": [
                        {"name": "Platform", "value": platform or "\u2014", "inline": True},
                        {"name": "Source", "value": (src_url or "\u2014")[:1000], "inline": False},
                    ] + ([{"name": "Details", "value": details[:1000]}] if details else []),
                    "footer": {"text": f"StreamKeep v{VERSION}"},
                }],
            }
            self._fire_webhook_json(url, payload)

        elif "hooks.slack.com" in url:
            blocks = [
                {"type": "header", "text": {"type": "plain_text",
                                            "text": f"StreamKeep: {event}"}},
                {"type": "section", "text": {"type": "mrkdwn",
                                             "text": f"*{title[:200]}*"}},
            ]
            if details:
                blocks.append({"type": "context", "elements": [
                    {"type": "mrkdwn", "text": details[:2000]}]})
            blocks.append({"type": "context", "elements": [
                {"type": "mrkdwn",
                 "text": f"Platform: {platform} | v{VERSION}"}]})
            payload = {"text": f"StreamKeep: {event} \u2014 {title}",
                       "blocks": blocks}
            self._fire_webhook_json(url, payload)

        elif "api.telegram.org/bot" in url:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            chat_id = (qs.get("chat_id") or [""])[0]
            base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            text = f"*StreamKeep: {event}*\n{title}"
            if details:
                text += f"\n_{details}_"
            text += f"\n`{platform} | v{VERSION}`"
            payload = {"chat_id": chat_id, "text": text,
                       "parse_mode": "Markdown"}
            self._fire_webhook_json(base_url, payload)

        elif "ntfy.sh" in url or "/ntfy/" in url:
            body = f"{title}\n{details}".strip() if details else title
            try:
                cmd = ["curl", "-s", "-X", "POST",
                       "-H", f"Title: StreamKeep: {event}",
                       "-H", "Priority: default",
                       "-H", f"Tags: {platform}",
                       "-d", body, "--max-time", "10", url]
                subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_CREATE_NO_WINDOW)
            except Exception as e:
                self._log(f"[WEBHOOK] Send failed: {e}")

        else:
            payload = {"app": "StreamKeep", "version": VERSION,
                       "event": event, "title": title,
                       "platform": platform, "source": src_url,
                       "details": details}
            self._fire_webhook_json(url, payload)

    def _fire_hook(self, event, **context):
        """Fire configured event hook, if any."""
        hooks_cfg = self._config.get("hooks", {})
        if hooks_cfg:
            from ..hooks import fire_hook
            fire_hook(event, context, hooks_cfg, log_fn=self._log)

    def _media_server_import(self, out_dir, info=None):
        """Auto-import recording into media server library (F33)."""
        ms_cfg = self._config.get("media_server", {})
        if ms_cfg.get("enabled") and out_dir:
            from ..integrations.media_server import import_to_media_server
            import_to_media_server(ms_cfg, out_dir, info=info, log_fn=self._log)

    def _fire_webhook_json(self, url, payload):
        """Fire-and-forget JSON POST via curl."""
        try:
            cmd = ["curl", "-s", "-X", "POST",
                   "-H", "Content-Type: application/json",
                   "-d", json.dumps(payload),
                   "--max-time", "10", url]
            subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW)
        except Exception as e:
            self._log(f"[WEBHOOK] Send failed: {e}")

    def closeEvent(self, event):
        # Stop active download worker cleanly
        dw = getattr(self, "download_worker", None)
        if dw is not None and dw.isRunning():
            try:
                dw.cancel()
                if not dw.wait(3000):
                    dw.terminate()
                    dw.wait(1000)
            except Exception:
                pass
        fw = getattr(self, "_fetch_worker", None)
        if fw is not None and fw.isRunning():
            try:
                fw.requestInterruption()
                fw.wait(1500)
            except Exception:
                pass
        vpw = getattr(self, "_vod_page_worker", None)
        if vpw is not None and vpw.isRunning():
            try:
                vpw.requestInterruption()
                vpw.wait(1500)
            except Exception:
                pass
        bfw = getattr(self, "_batch_fetch_worker", None)
        if bfw is not None and bfw.isRunning():
            try:
                bfw.requestInterruption()
                bfw.wait(1500)
            except Exception:
                pass
        arw = getattr(self, "_auto_record_resolve_worker", None)
        if arw is not None and arw.isRunning():
            try:
                arw.requestInterruption()
                arw.wait(1500)
            except Exception:
                pass
        # Tear down every parallel auto-record resolver + worker.
        for key, worker in list(getattr(self, "_autorecord_resolvers", {}).items()):
            try:
                if worker is not None and worker.isRunning():
                    worker.requestInterruption()
                    worker.wait(1500)
            except Exception:
                pass
            self._autorecord_resolvers.pop(key, None)
        for key, worker in list(getattr(self, "_autorecord_workers", {}).items()):
            try:
                if worker is not None and worker.isRunning():
                    worker.cancel()
                    if not worker.wait(3000):
                        worker.terminate()
                        worker.wait(500)
            except Exception:
                pass
            self._autorecord_workers.pop(key, None)
        # Tear down concurrent queue fetch workers.
        for key, worker in list(getattr(self, "_queue_fetch_workers", {}).items()):
            try:
                if worker is not None and worker.isRunning():
                    worker.requestInterruption()
                    worker.wait(1500)
            except Exception:
                pass
            self._queue_fetch_workers.pop(key, None)
        # Tear down concurrent queue download workers.
        for key, worker in list(getattr(self, "_queue_workers", {}).items()):
            try:
                if worker is not None and worker.isRunning():
                    worker.cancel()
                    if not worker.wait(3000):
                        worker.terminate()
                        worker.wait(500)
            except Exception:
                pass
            self._queue_workers.pop(key, None)
        self._queue_contexts.clear()
        for key, worker in list(getattr(self, "_chat_workers", {}).items()):
            try:
                if worker is not None and worker.isRunning():
                    worker.cancel()
                    worker.wait(2000)
            except Exception:
                pass
            self._chat_workers.pop(key, None)
        # Tear down the browser-companion HTTP server.
        srv = getattr(self, "_companion_server", None)
        if srv is not None:
            try:
                srv.stop()
            except Exception:
                pass
            self._companion_server = None
        for key, worker in list(getattr(self, "_monitor_seed_workers", {}).items()):
            try:
                if worker is not None and worker.isRunning():
                    worker.requestInterruption()
                    worker.wait(1500)
            except Exception:
                pass
            self._monitor_seed_workers.pop(key, None)
        fwk = getattr(self, "_finalize_worker", None)
        if fwk is not None and fwk.isRunning():
            try:
                fwk.cancel()
                if not fwk.wait(1500):
                    fwk.terminate()
                    fwk.wait(500)
            except Exception:
                pass
        ew = getattr(self, "_expand_worker", None)
        if ew is not None and ew.isRunning():
            try:
                ew.requestInterruption()
                ew.wait(1500)
            except Exception:
                pass
        sw = getattr(self, "_scan_worker", None)
        if sw is not None and sw.isRunning():
            try:
                sw.requestInterruption()
                sw.wait(1500)
            except Exception:
                pass
        self._finalize_tasks = []
        # Stop convert worker if running (standalone file/folder batch)
        cw = getattr(self, "_convert_worker", None)
        if cw is not None and cw.isRunning():
            try:
                cw.cancel()
                if not cw.wait(3000):
                    cw.terminate()
                    cw.wait(1000)
            except Exception:
                pass
        # Stop transcribe / chat-render / bundle workers (F27/F22 audit fix)
        for attr in ("_transcribe_worker", "_chat_render_worker", "_bundle_worker"):
            w = getattr(self, attr, None)
            if w is not None and w.isRunning():
                try:
                    if hasattr(w, "cancel"):
                        w.cancel()
                    if not w.wait(2000):
                        w.terminate()
                        w.wait(500)
                except Exception:
                    pass
        # Stop monitor timer
        try:
            self.monitor._timer.stop()
        except Exception:
            pass
        try:
            self._scheduler_timer.stop()
        except Exception:
            pass
        try:
            self._config_save_timer.stop()
        except Exception:
            pass
        # Stop clipboard monitor
        try:
            self.clipboard_monitor.stop()
        except Exception:
            pass
        # Hide + remove tray icon so Windows doesn't leak a dead icon slot
        # until explorer.exe is restarted.
        try:
            if self._tray_icon is not None:
                self._tray_icon.hide()
                self._tray_icon.deleteLater()
                self._tray_icon = None
        except Exception:
            pass
        self._persist_config()
        super().closeEvent(event)

    # Widget builders are thin forwarders to streamkeep.ui.widgets so the
    # 50+ `self._make_*` call sites below don't need to be rewritten.
    def _make_metric_card(self, *a, **kw):
        return make_metric_card(*a, **kw)

    def _make_field_block(self, *a, **kw):
        return make_field_block(*a, **kw)

    def _wrap_scroll_page(self, *a, **kw):
        return wrap_scroll_page(*a, **kw)

    def _style_table(self, *a, **kw):
        return style_table(*a, **kw)

    def _set_metric(self, *a, **kw):
        return set_metric(*a, **kw)

    def _can_autofill_output(self):
        current = self.output_input.text().strip() if hasattr(self, "output_input") else ""
        default_output = str(_default_output_dir())
        return not current or current == default_output or current == self._last_auto_output

    def _apply_auto_output(self, path_text):
        self._last_auto_output = path_text
        self.output_input.setText(path_text)

    def _set_status(self, message, tone="idle"):
        tones = {
            "idle": ("Standby", CAT["panelSoft"], CAT["subtext1"], CAT["stroke"]),
            "working": ("Working", CAT["accent"], "#081120", CAT["accent"]),
            "processing": ("Finalizing", CAT["accentSoft"], "#081120", CAT["accent"]),
            "success": ("Ready", CAT["accentSoft"], "#081120", CAT["accentSoft"]),
            "warning": ("Alert", CAT["gold"], "#081120", CAT["gold"]),
            "error": ("Error", CAT["red"], "#081120", CAT["red"]),
        }
        pill, bg, fg, border = tones.get(tone, tones["idle"])
        self.status_pill.setText(pill)
        self.status_pill.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border: 1px solid {border}; "
            "border-radius: 999px; padding: 6px 10px; font-size: 11px; font-weight: 700;"
        )
        self.status_label.setText(message)
        self.status_label.setToolTip(message)
        self._refresh_shell_overview()

    def _refresh_shell_overview(self):
        """Update the compact shell snapshot in the app header."""
        if not hasattr(self, "shell_snapshot_value"):
            return

        queued = len(self._download_queue)
        monitored = len(getattr(self.monitor, "entries", []))
        archived = len(self._history)
        active_jobs = sum(
            1 for q in self._download_queue
            if q.get("status") in ("fetching", "downloading")
        )
        worker = getattr(self, "download_worker", None)
        if worker is not None and worker.isRunning():
            active_jobs += 1
        live_now = sum(
            1 for entry in getattr(self.monitor, "entries", [])
            if getattr(entry, "last_status", "") == "live"
        )

        if active_jobs:
            headline = "Capture in progress"
            detail = f"{active_jobs} active job(s) running right now."
        elif queued:
            headline = "Queue ready"
            detail = f"{queued} item(s) lined up for the next pass."
        elif live_now:
            headline = "Live channels detected"
            detail = f"{live_now} monitored channel(s) are live now."
        elif archived:
            headline = "Archive in shape"
            detail = f"{archived} saved download(s) are ready to revisit."
        else:
            headline = "Ready to capture"
            detail = "Paste a URL, monitor a channel, or scan the archive."

        self.shell_snapshot_value.setText(headline)
        self.shell_snapshot_detail.setText(detail)
        self.shell_snapshot_meta.setText(
            f"Desktop v{VERSION} • {queued} queued • {monitored} monitored • {archived} archived"
        )

    def _refresh_download_summary(self):
        if not hasattr(self, "download_hero_title"):
            return

        url = self.url_input.text().strip() if hasattr(self, "url_input") else ""
        if self.stream_info:
            title = self.stream_info.title or "Source ready"
            summary_parts = []
            if self.stream_info.platform:
                summary_parts.append(self.stream_info.platform)
            if self.stream_info.channel:
                summary_parts.append(self.stream_info.channel)
            if self.stream_info.duration_str:
                summary_parts.append(self.stream_info.duration_str)
            if self.stream_info.is_live:
                summary_parts.append("Live capture")
            body = " | ".join(summary_parts) if summary_parts else "Metadata loaded and ready for download."
        elif url:
            ext = Extractor.detect(url)
            title = "Source detected" if ext else "Paste a supported URL"
            if ext:
                body = f"{ext.NAME} recognized. Click Fetch to inspect quality options and segment timing."
            else:
                body = "Kick, Twitch, Rumble, podcasts, audio sources, and yt-dlp compatible links are supported."
        else:
            title = "Capture streams and VODs with cleaner control"
            body = "Paste a source URL to inspect quality options, split recordings into segments, and keep output folders tidy."

        self.download_hero_title.setText(title)
        self.download_hero_body.setText(body)

        platform_value = self.stream_info.platform if self.stream_info else "Auto detect"
        platform_sub = "Detected after fetch" if self.stream_info else "Waiting for a supported URL"
        duration_value = self.stream_info.duration_str if self.stream_info and self.stream_info.duration_str else "Waiting"
        duration_sub = "Stream length" if self.stream_info else "Metadata not loaded yet"

        total_segments = len(self._segment_checks)
        checked_segments = sum(1 for cb in self._segment_checks if cb.isChecked())
        if total_segments:
            selection_value = f"{checked_segments}/{total_segments}"
            selection_sub = "segments selected"
        elif self.stream_info and self.stream_info.total_secs <= 0:
            selection_value = "Live"
            selection_sub = "capture runs until you stop it"
        else:
            selection_value = "Not ready"
            selection_sub = "segments appear after fetch"

        output_path = self.output_input.text().strip() if hasattr(self, "output_input") else ""
        output_sub = output_path if len(output_path) <= 50 else f"...{output_path[-47:]}"
        finalize_active = bool(self._finalize_worker is not None and self._finalize_worker.isRunning())
        finalize_queued = len(self._finalize_tasks)
        if finalize_active:
            if self._finalize_active_total:
                finalize_value = f"{self._finalize_active_step}/{self._finalize_active_total}"
            else:
                finalize_value = "Starting"
            finalize_parts = []
            if self._finalize_active_title:
                finalize_parts.append(self._finalize_active_title[:42])
            if self._finalize_active_label:
                finalize_parts.append(self._finalize_active_label)
            finalize_sub = " | ".join(finalize_parts) or "Preparing background cleanup"
            if finalize_queued:
                finalize_sub = f"{finalize_sub} | {finalize_queued} queued"
        elif finalize_queued:
            finalize_value = f"{finalize_queued} queued"
            finalize_sub = "Waiting for the current background cleanup"
        else:
            finalize_value = "Idle"
            finalize_sub = "Metadata and post-processing will queue here"

        self._set_metric(self.download_platform_value, self.download_platform_sub, platform_value, platform_sub)
        self._set_metric(self.download_duration_value, self.download_duration_sub, duration_value, duration_sub)
        self._set_metric(self.download_selection_value, self.download_selection_sub, selection_value, selection_sub)
        # Append free-disk hint to the output card subline so users see
        # what they have to work with before starting a long download.
        free_bytes = _free_space_bytes(output_path) if output_path else None
        free_label = f"{_fmt_size(free_bytes)} free" if free_bytes else ""
        output_sub_with_free = output_sub or "Choose a destination folder"
        if free_label:
            output_sub_with_free = f"{free_label} \u2022 {output_sub_with_free}"
        self._set_metric(
            self.download_output_value,
            self.download_output_sub,
            _path_label(output_path),
            output_sub_with_free,
        )
        if hasattr(self, "download_finalize_value"):
            self._set_metric(
                self.download_finalize_value,
                self.download_finalize_sub,
                finalize_value,
                finalize_sub,
            )
        self.download_output_value.setToolTip(output_path)
        self.download_output_sub.setToolTip(output_path)
        if hasattr(self, "download_finalize_sub"):
            self.download_finalize_sub.setToolTip(finalize_sub)

        if hasattr(self, "segment_summary_label"):
            if total_segments:
                self.segment_summary_label.setText(f"{checked_segments} of {total_segments} segment(s) selected")
            else:
                self.segment_summary_label.setText("Segments will appear after metadata is loaded.")

    def _refresh_vod_summary(self):
        if not hasattr(self, "vod_summary_label"):
            return
        total = len(self._vod_checks)
        checked_indices = [i for i, cb in enumerate(self._vod_checks) if cb.isChecked()]
        checked = len(checked_indices)
        if total and checked:
            # Sum duration of selected VODs
            total_ms = 0
            for i in checked_indices:
                if i < len(self._vod_list):
                    total_ms += self._vod_list[i].duration_ms or 0
            dur_str = ""
            if total_ms > 0:
                secs = total_ms // 1000
                h, m = divmod(secs // 60, 60)
                dur_str = f" · {h}h {m}m" if h else f" · {m}m"
            self.vod_summary_label.setText(f"{checked} of {total} selected{dur_str}")
        elif total:
            self.vod_summary_label.setText(f"0 of {total} selected")
        else:
            self.vod_summary_label.setText("Inspect a channel to browse available VODs.")

    def _refresh_monitor_summary(self):
        if not hasattr(self, "monitor_count_value"):
            return
        entries = self.monitor.entries
        total = len(entries)
        auto = sum(1 for e in entries if e.auto_record)
        live = sum(1 for e in entries if e.last_status == "live")
        recording = sum(1 for e in entries if e.is_recording)
        pending = len(getattr(self, "_pending_auto_records", []))

        self._set_metric(self.monitor_count_value, self.monitor_count_sub, str(total), "active entries")
        self._set_metric(self.monitor_auto_value, self.monitor_auto_sub, str(auto), "auto-record enabled")
        self._set_metric(self.monitor_live_value, self.monitor_live_sub, str(live), "currently live")

        if total:
            summary_parts = [
                f"Watching {total} channel(s)",
                f"{auto} armed for auto-record",
            ]
            if live:
                summary_parts.append(f"{live} live")
            if recording:
                summary_parts.append(f"{recording} recording")
            if pending:
                summary_parts.append(f"{pending} queued to retry")
            self.monitor_summary_label.setText(" • ".join(summary_parts))
        else:
            self.monitor_summary_label.setText("Add a channel URL to start passive live monitoring.")

        if hasattr(self, "monitor_table_hint"):
            calendar_on = bool(
                hasattr(self, "monitor_view_toggle")
                and self.monitor_view_toggle.isChecked()
            )
            if calendar_on:
                if total:
                    self.monitor_table_hint.setText(
                        "Calendar view shows cached schedule windows for the channels in your watch list."
                    )
                else:
                    self.monitor_table_hint.setText(
                        "Calendar view will show cached schedule windows after you add monitored channels."
                    )
            elif total:
                if live or recording:
                    self.monitor_table_hint.setText(
                        f"Watch list updates automatically. {live} live now and {recording} currently recording."
                    )
                else:
                    self.monitor_table_hint.setText(
                        "Entries refresh automatically and stay ready to trigger auto-record when a stream goes live."
                    )
            else:
                self.monitor_table_hint.setText(
                    "Entries refresh automatically and can trigger auto-recording when a stream goes live."
                )
        self._refresh_shell_overview()

    def _refresh_history_summary(self):
        if not hasattr(self, "history_count_value"):
            return
        total = len(self._history)
        latest = self._history[-1] if self._history else None
        visible = len(getattr(self, "_history_view", self._history))
        query = self.history_search.text().strip() if hasattr(self, "history_search") else ""
        transcript_mode = (
            hasattr(self, "transcript_search_check")
            and self.transcript_search_check.isChecked()
        )
        transcript_hits = sum(
            len(items) for items in getattr(self, "_transcript_hits", {}).values()
        )

        self._set_metric(self.history_count_value, self.history_count_sub, str(total), "saved downloads")
        latest_value = latest.date if latest else "No entries"
        latest_sub = (latest.title if latest else "Completed downloads appear here")[:40]
        self._set_metric(self.history_latest_value, self.history_latest_sub, latest_value, latest_sub)

        # Compute top platform and top channel from history
        if hasattr(self, "history_platform_value"):
            if total:
                from collections import Counter
                plat_counts = Counter(h.platform for h in self._history if h.platform)
                top_plat, top_plat_n = (plat_counts.most_common(1) or [("—", 0)])[0]
                plat_share = f"{top_plat_n} / {total} downloads" if top_plat_n else "no data"
                self._set_metric(self.history_platform_value, self.history_platform_sub,
                                 top_plat or "—", plat_share)
                # Top channel: prefer stored creator/channel metadata, then fall back
                # to a conservative URL-derived guess for older history rows.
                ch_counts = Counter()
                for h in self._history:
                    key = self._history_channel_label(h)
                    if key:
                        ch_counts[key] += 1
                if ch_counts:
                    top_ch, top_ch_n = ch_counts.most_common(1)[0]
                    self._set_metric(self.history_channel_value, self.history_channel_sub,
                                     top_ch[:24], f"{top_ch_n} download(s)")
                else:
                    self._set_metric(self.history_channel_value, self.history_channel_sub,
                                     "—", "no channel data")
            else:
                self._set_metric(self.history_platform_value, self.history_platform_sub,
                                 "—", "appears most in history")
                self._set_metric(self.history_channel_value, self.history_channel_sub,
                                 "—", "most downloaded")
        self._refresh_shell_overview()

        if total:
            if query and transcript_mode:
                if hasattr(self, "history_filter_summary"):
                    self.history_filter_summary.setText(
                        f"{visible} matching download(s) • {transcript_hits} transcript hit(s)"
                    )
                if visible:
                    self.history_summary_label.setText(
                        "Transcript search matches indexed dialogue. Hover a title to preview matching lines, then double-click to open the folder."
                    )
                else:
                    self.history_summary_label.setText(
                        "No indexed transcript text matched that phrase. Clear the query or switch back to metadata search."
                    )
            elif query:
                if hasattr(self, "history_filter_summary"):
                    self.history_filter_summary.setText(
                        f"Showing {visible} of {total} download(s)"
                    )
                if visible:
                    self.history_summary_label.setText(
                        "Metadata search matches title, platform, channel, folder path, and source URL."
                    )
                else:
                    self.history_summary_label.setText(
                        "No downloads matched that search. Try a broader title, platform, channel, or folder term."
                    )
            else:
                if hasattr(self, "history_filter_summary"):
                    self.history_filter_summary.setText(f"Showing all {total} download(s)")
                self.history_summary_label.setText(
                    "Double-click a row to open the saved folder in Explorer. Use search to filter by title, platform, channel, folder, or source URL."
                )
        else:
            if hasattr(self, "history_filter_summary"):
                self.history_filter_summary.setText("History fills in automatically")
            self.history_summary_label.setText("Download history builds automatically after each completed job.")

    def _init_ui(self):
        central = QWidget()
        central.setObjectName("chrome")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(16)

        header_card = QFrame()
        header_card.setObjectName("shellCard")
        header_lay = QVBoxLayout(header_card)
        header_lay.setContentsMargins(22, 20, 22, 20)
        header_lay.setSpacing(16)

        header_top = QHBoxLayout()
        header_top.setSpacing(20)
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        eyebrow = QLabel("Capture Suite")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("StreamKeep")
        title.setObjectName("title")
        subtitle = QLabel(
            "Archive live streams, queue batches, and keep every capture organized from one desktop workspace."
        )
        subtitle.setObjectName("heroBody")
        subtitle.setWordWrap(True)
        title_col.addWidget(eyebrow)
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header_top.addLayout(title_col, 1)

        shell_meta = QFrame()
        shell_meta.setObjectName("shellMetaCard")
        shell_meta.setMaximumWidth(310)
        shell_meta_lay = QVBoxLayout(shell_meta)
        shell_meta_lay.setContentsMargins(16, 14, 16, 14)
        shell_meta_lay.setSpacing(6)

        shell_meta_top = QHBoxLayout()
        shell_meta_top.setSpacing(8)
        shell_meta_label = QLabel("Live Snapshot")
        shell_meta_label.setObjectName("fieldLabel")
        shell_meta_top.addWidget(shell_meta_label)
        shell_meta_top.addStretch(1)

        self.notif_button = QPushButton("Alerts 0")
        self.notif_button.setObjectName("secondary")
        self.notif_button.setMinimumWidth(104)
        self.notif_button.setToolTip("Recent notifications")
        self.notif_button.clicked.connect(self._on_show_notifications)
        shell_meta_top.addWidget(self.notif_button)
        shell_meta_lay.addLayout(shell_meta_top)

        self.shell_snapshot_value = QLabel("Ready to capture")
        self.shell_snapshot_value.setObjectName("shellStatValue")
        self.shell_snapshot_detail = QLabel(f"Desktop build v{VERSION}")
        self.shell_snapshot_detail.setObjectName("shellStatBody")
        self.shell_snapshot_detail.setWordWrap(True)
        self.shell_snapshot_meta = QLabel("0 queued • 0 monitored • 0 archived")
        self.shell_snapshot_meta.setObjectName("shellStatMeta")
        self.shell_snapshot_meta.setWordWrap(True)
        shell_meta_lay.addWidget(self.shell_snapshot_value)
        shell_meta_lay.addWidget(self.shell_snapshot_detail)
        shell_meta_lay.addWidget(self.shell_snapshot_meta)
        header_top.addWidget(shell_meta)
        header_lay.addLayout(header_top)

        shell_controls = QHBoxLayout()
        shell_controls.setSpacing(12)

        tab_shell = QFrame()
        tab_shell.setObjectName("toolbar")
        tab_lay = QHBoxLayout(tab_shell)
        tab_lay.setContentsMargins(12, 10, 12, 10)
        tab_lay.setSpacing(10)

        self._tab_btns = []
        self._tab_names = ["Download", "Monitor", "History", "Storage", "Analytics", "Settings"]
        for i, name in enumerate(self._tab_names):
            btn = QPushButton(name)
            btn.setObjectName("tabActive" if i == 0 else "tab")
            btn.setStyleSheet(TAB_STYLE())
            btn.clicked.connect(lambda checked, idx=i: self._switch_tab(idx))
            tab_lay.addWidget(btn)
            self._tab_btns.append(btn)
        tab_lay.addStretch(1)
        shell_controls.addWidget(tab_shell, 1)

        search_shell = QFrame()
        search_shell.setObjectName("toolbar")
        search_shell.setMinimumWidth(320)
        search_lay = QVBoxLayout(search_shell)
        search_lay.setContentsMargins(14, 12, 14, 12)
        search_lay.setSpacing(8)
        search_label = QLabel("Search Everything")
        search_label.setObjectName("fieldLabel")
        search_lay.addWidget(search_label)

        self._global_search = QLineEdit()
        self._global_search.setPlaceholderText(
            "Search history, queue, storage, monitor, and transcripts…"
        )
        self._global_search.setClearButtonEnabled(True)
        self._global_search.setObjectName("shellSearch")
        self._global_search.setMinimumHeight(40)
        self._global_search_timer = QTimer(self)
        self._global_search_timer.setSingleShot(True)
        self._global_search_timer.setInterval(300)
        self._global_search_timer.timeout.connect(self._on_global_search)
        self._global_search.textChanged.connect(
            lambda: self._global_search_timer.start()
        )
        self._global_search.returnPressed.connect(self._on_global_search)
        search_lay.addWidget(self._global_search)
        shell_controls.addWidget(search_shell, 0)

        header_lay.addLayout(shell_controls)
        root.addWidget(header_card)

        # Global search results dropdown (hidden until needed)
        from PyQt6.QtWidgets import QListWidget
        self._global_results = QListWidget(self)
        self._global_results.setObjectName("globalResults")
        self._global_results.setMaximumHeight(280)
        self._global_results.setVisible(False)
        self._global_results.itemActivated.connect(self._on_global_result_click)
        root.addWidget(self._global_results)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._wrap_scroll_page(build_download_tab(self)))
        self._stack.addWidget(self._wrap_scroll_page(build_monitor_tab(self)))
        self._stack.addWidget(self._wrap_scroll_page(build_history_tab(self)))
        self._stack.addWidget(self._wrap_scroll_page(build_storage_tab(self)))
        from .tabs.analytics import build_analytics_tab
        self._stack.addWidget(self._wrap_scroll_page(build_analytics_tab(self)))
        self._stack.addWidget(self._wrap_scroll_page(build_settings_tab(self)))
        root.addWidget(self._stack, 1)

        footer = QFrame()
        footer.setObjectName("footerBar")
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(16, 12, 16, 12)
        footer_lay.setSpacing(12)

        self.status_pill = QLabel("Standby")
        footer_lay.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignTop)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        footer_lay.addWidget(self.status_label, 1)

        self.overall_progress = QProgressBar()
        self.overall_progress.setFixedWidth(220)
        self.overall_progress.setFixedHeight(10)
        self.overall_progress.setVisible(False)
        footer_lay.addWidget(self.overall_progress, 0, Qt.AlignmentFlag.AlignVCenter)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setFixedWidth(88)
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._on_stop)
        footer_lay.addWidget(self.stop_btn)

        self.open_folder_btn = QPushButton("Open Folder")
        self.open_folder_btn.setObjectName("secondary")
        self.open_folder_btn.setVisible(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        footer_lay.addWidget(self.open_folder_btn)

        self.trim_btn = QPushButton("Trim...")
        self.trim_btn.setObjectName("secondary")
        self.trim_btn.setVisible(False)
        self.trim_btn.clicked.connect(self._on_trim_last)
        footer_lay.addWidget(self.trim_btn)
        root.addWidget(footer)

        self._set_status("Paste a URL to inspect a stream or VOD.", "idle")

    def _switch_tab(self, idx):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tab_btns):
            btn.setObjectName("tabActive" if i == idx else "tab")
            btn.setStyleSheet(TAB_STYLE())
        # Auto-scan Storage the first time the user opens the tab in a
        # session, and on every subsequent visit (cheap on small archives,
        # user can stop by switching away). Deferred so the tab paints
        # before the scan runs.
        try:
            storage_idx = self._tab_names.index("Storage")
        except ValueError:
            storage_idx = -1
        if idx == storage_idx and storage_idx >= 0:
            QTimer.singleShot(200, self._on_storage_rescan)
        # Refresh Analytics tab on visit (F63)
        try:
            analytics_idx = self._tab_names.index("Analytics")
        except ValueError:
            analytics_idx = -1
        if idx == analytics_idx and analytics_idx >= 0:
            from .tabs.analytics import _refresh_analytics
            QTimer.singleShot(100, lambda: _refresh_analytics(self))

    # ── Download Tab ──────────────────────────────────────────────────

    def _on_batch_url_import(self):
        """Import URLs from a text file or clipboard paste and queue them (F44)."""
        from PyQt6.QtWidgets import (
            QDialog, QDialogButtonBox, QFileDialog, QPlainTextEdit,
            QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        )
        import re as _re

        dlg = QDialog(self)
        dlg.setWindowTitle("Batch URL Import")
        dlg.setMinimumSize(600, 400)
        layout = QVBoxLayout(dlg)

        hint = QLabel(
            "Paste URLs below (one per line) or load from a text file.\n"
            "Lines starting with # are comments and will be skipped."
        )
        layout.addWidget(hint)

        text_edit = QPlainTextEdit()
        text_edit.setPlaceholderText("https://twitch.tv/videos/123456\nhttps://kick.com/channel\n# this is a comment")
        layout.addWidget(text_edit)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("Load from file...")
        load_btn.setObjectName("secondary")

        def _on_load_file():
            path, _ = QFileDialog.getOpenFileName(
                dlg, "Open URL list", "",
                "Text files (*.txt);;All files (*)",
            )
            if path:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        text_edit.setPlainText(f.read())
                except Exception as e:
                    self._set_status(f"Failed to read file: {e}", "error")

        load_btn.clicked.connect(_on_load_file)
        btn_row.addWidget(load_btn)

        status_label = QLabel("")
        btn_row.addWidget(status_label, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_row.addWidget(buttons)
        layout.addLayout(btn_row)

        _url_re = _re.compile(r"^https?://\S+$", _re.IGNORECASE)

        def _update_count():
            lines = text_edit.toPlainText().strip().splitlines()
            valid = sum(1 for ln in lines if _url_re.match(ln.strip()))
            total = sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))
            invalid = total - valid
            parts = [f"{valid} valid URL(s)"]
            if invalid:
                parts.append(f"{invalid} invalid")
            status_label.setText("  ".join(parts))

        text_edit.textChanged.connect(_update_count)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        lines = text_edit.toPlainText().strip().splitlines()
        added = 0
        skipped = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not _url_re.match(line):
                skipped += 1
                continue
            ok = self._queue_add(url=line)
            if ok:
                added += 1
            else:
                skipped += 1

        self._refresh_queue_table()
        self._persist_config()
        msg = f"Queued {added} URL(s)"
        if skipped:
            msg += f", skipped {skipped} (invalid or duplicate)"
        self._set_status(msg, "success" if added else "warning")
        self._log(f"[BATCH] {msg}")

    def _on_expand_playlist(self):
        """Probe the URL for playlist/channel entries and queue them all."""
        url = self.url_input.text().strip()
        if not url:
            self._set_status("Paste a URL first.", "warning")
            return
        self.expand_btn.setEnabled(False)
        self._set_status("Probing for playlist/channel entries...", "working")
        self._log(f"[PLAYLIST] Probing: {url}")
        # Run in a throwaway thread to avoid blocking the UI
        worker = _PlaylistExpandWorker(url)
        worker.finished.connect(lambda entries, u=url: self._on_expand_done(u, entries))
        worker.error.connect(self._on_expand_error)
        worker.log.connect(self._log)
        self._expand_worker = worker
        worker.start()

    def _on_expand_done(self, source_url, entries):
        self.expand_btn.setEnabled(True)
        if not entries:
            self._set_status(
                "No playlist entries found. This URL may be a single video — use Fetch instead.",
                "warning",
            )
            return
        added = 0
        for e in entries:
            if self._queue_add(e.get("url", ""), title=e.get("title", ""), platform="yt-dlp"):
                added += 1
        self._log(f"[PLAYLIST] Queued {added} new of {len(entries)} total entries")
        self._set_status(
            f"Playlist expanded. Queued {added} new entries "
            f"({len(entries) - added} already in the queue).",
            "success",
        )
        # Kick off the queue if nothing's downloading
        worker = getattr(self, "download_worker", None)
        if worker is None or not worker.isRunning():
            self._advance_queue()

    def _on_expand_error(self, err):
        self.expand_btn.setEnabled(True)
        self._log(f"[PLAYLIST] {err}")
        self._set_status(f"Playlist probe failed: {err}", "error")

    def _on_scan_page(self):
        """Scrape a webpage for video/media links and queue them."""
        url = self.url_input.text().strip()
        if not url:
            self._set_status("Paste a webpage URL first.", "warning")
            return
        if not url.startswith("http"):
            self._set_status("Scan Page expects a full http(s) URL.", "warning")
            return
        self.scan_btn.setEnabled(False)
        self._set_status("Scanning page for media links...", "working")
        self._log(f"[SCRAPE] Scanning {url}")
        worker = _PageScrapeWorker(url)
        worker.finished.connect(self._on_scan_done)
        worker.error.connect(self._on_scan_error)
        worker.log.connect(self._log)
        self._scan_worker = worker
        worker.start()

    def _on_scan_done(self, links):
        self.scan_btn.setEnabled(True)
        if not links:
            self._set_status(
                "No media links found. Try Fetch or Expand Playlist instead.",
                "warning",
            )
            return
        added = 0
        for url, hint in links:
            if self._queue_add(url, title=url[:80], platform=hint):
                added += 1
        self._log(f"[SCRAPE] Queued {added} new link(s) of {len(links)} found")
        self._set_status(
            f"Found {len(links)} link(s). Queued {added} new ({len(links) - added} already in queue).",
            "success",
        )
        worker = getattr(self, "download_worker", None)
        if worker is None or not worker.isRunning():
            self._advance_queue()

    def _on_scan_error(self, err):
        self.scan_btn.setEnabled(True)
        self._log(f"[SCRAPE] {err}")
        self._set_status(f"Scan failed: {err}", "error")

    def _on_recover_vod(self):
        """Open the Deleted VOD Recovery Wizard dialog (F23)."""
        from .recover_dialog import RecoverDialog
        dlg = RecoverDialog(self, log_fn=self._log)
        dlg.download_requested.connect(self._on_recover_download)
        dlg.exec()

    def _on_recover_download(self, url):
        """Handle a recovered VOD URL — paste into input and trigger fetch."""
        self.url_input.setText(url)
        self._on_fetch()

    def _on_queue_url(self):
        """Add the current URL input to the persistent queue."""
        url = self.url_input.text().strip()
        if not url:
            self._set_status("Paste a URL first.", "warning")
            return
        req = getattr(self, "_last_fetch_request", {})
        vod_source = str(req.get("vod_source", "") or "")
        vod_platform = str(req.get("vod_platform", "") or "")
        vod_title = str(req.get("vod_title", "") or "")
        vod_channel = str(req.get("vod_channel", "") or "")
        title = ""
        platform = ""
        if self.stream_info:
            title = self.stream_info.title or ""
            platform = self.stream_info.platform or ""
        queue_url = vod_source or url
        added = self._queue_add(
            queue_url,
            title=title,
            platform=platform,
            vod_source=vod_source,
            vod_platform=vod_platform,
            vod_title=vod_title or title,
            vod_channel=vod_channel or (self.stream_info.channel if self.stream_info else ""),
        )
        if added:
            self._set_status(f"Queued: {title or queue_url[:60]}", "success")
        else:
            self._set_status("URL already in the queue.", "warning")

    def _on_schedule_url(self):
        """Queue the current URL with a deferred start time."""
        url = self.url_input.text().strip()
        if not url:
            self._set_status("Paste a URL first.", "warning")
            return
        req = getattr(self, "_last_fetch_request", {})
        vod_source = str(req.get("vod_source", "") or "")
        vod_platform = str(req.get("vod_platform", "") or "")
        vod_title = str(req.get("vod_title", "") or "")
        vod_channel = str(req.get("vod_channel", "") or "")

        def _validate_offset(value):
            try:
                minutes = int(value)
            except (TypeError, ValueError):
                return False, "Enter a whole number of minutes."
            if not 1 <= minutes <= 60 * 24 * 30:
                return False, "Choose a delay between 1 minute and 30 days."
            return True, ""

        offset_text, ok = ask_premium_text_input(
            self,
            title="Schedule this download",
            body="Delay the next capture so it starts later without leaving the queue unmanaged.",
            eyebrow="DOWNLOAD",
            badge_text="Scheduled",
            tone="info",
            summary_title="Use minutes for the delay.",
            summary_body="Examples: 60 for one hour, 180 for three hours, or 1440 for one day.",
            field_label="Start delay (minutes)",
            field_hint="The item will stay queued until its scheduled start time arrives.",
            placeholder="60",
            text="60",
            primary_label="Schedule download",
            secondary_label="Cancel",
            validator=_validate_offset,
        )
        if not ok:
            return
        offset_min = int(offset_text)
        start_at = (datetime.now() + timedelta(minutes=offset_min)).replace(microsecond=0)
        title = ""
        platform = ""
        if self.stream_info:
            title = self.stream_info.title or ""
            platform = self.stream_info.platform or ""
        queue_url = vod_source or url
        added = self._queue_add(
            queue_url,
            title=title,
            platform=platform,
            start_at=start_at.isoformat(),
            vod_source=vod_source,
            vod_platform=vod_platform,
            vod_title=vod_title or title,
            vod_channel=vod_channel or (self.stream_info.channel if self.stream_info else ""),
        )
        if added:
            self._set_status(
                f"Scheduled for {start_at.strftime('%Y-%m-%d %H:%M')}: {title or queue_url[:60]}",
                "success",
            )
        else:
            self._set_status("URL already in the queue.", "warning")

    def _on_clear_queue(self):
        active = self._queue_active_item
        self._download_queue = [q for q in self._download_queue if q is active]
        self._persist_config()
        self._refresh_queue_table()
        self._set_status("Queue cleared.", "success")

    # ── Monitor Tab ───────────────────────────────────────────────────

    # ── Settings Tab ──────────────────────────────────────────────────

    def _on_convert_files_clicked(self):
        """Open a multi-select file picker and kick off the converter."""
        if getattr(self, "_convert_worker", None) is not None and self._convert_worker.isRunning():
            self._set_status("A conversion is already running.", "warning")
            return
        # Apply current settings first so the worker picks them up
        self._on_save_settings()
        exts = sorted(VIDEO_EXTS | AUDIO_EXTS)
        filter_str = "Media files (" + " ".join(f"*{e}" for e in exts) + ");;All files (*)"
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select files to convert", str(_default_output_dir()), filter_str
        )
        if not paths:
            return
        self._start_convert_worker(list(paths))

    def _on_convert_folder_clicked(self):
        """Recursively collect media files from a chosen folder and convert."""
        if getattr(self, "_convert_worker", None) is not None and self._convert_worker.isRunning():
            self._set_status("A conversion is already running.", "warning")
            return
        self._on_save_settings()
        folder = QFileDialog.getExistingDirectory(
            self, "Select folder to convert", str(_default_output_dir())
        )
        if not folder:
            return
        files = []
        try:
            for root, _dirs, fnames in os.walk(folder):
                for f in fnames:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in VIDEO_EXTS or ext in AUDIO_EXTS:
                        # Skip files we produced ourselves
                        low = f.lower()
                        if ".converted." in low:
                            continue
                        files.append(os.path.join(root, f))
        except OSError as e:
            self._set_status(f"Folder scan failed: {e}", "error")
            return
        if not files:
            self._set_status("No media files found in that folder.", "warning")
            return
        self._log(f"[CONVERT] Found {len(files)} file(s) in {folder}")
        self._start_convert_worker(files)

    def _start_convert_worker(self, files):
        """Launch a ConvertWorker for the given list and wire up signals."""
        do_video = self.pp_convert_video_check.isChecked()
        do_audio = self.pp_convert_audio_check.isChecked()
        if not (do_video or do_audio):
            self._set_status(
                "Enable 'Convert video' or 'Convert audio' in Post-Processing first.",
                "warning"
            )
            return
        self._convert_worker = ConvertWorker(files, do_video, do_audio)
        self._convert_worker.progress.connect(self._on_convert_progress)
        self._convert_worker.log.connect(self._log)
        self._convert_worker.file_done.connect(self._on_convert_file_done)
        self._convert_worker.all_done.connect(self._on_convert_all_done)
        self.convert_files_btn.setEnabled(False)
        self.convert_folder_btn.setEnabled(False)
        self.convert_cancel_btn.setVisible(True)
        self._log(f"[CONVERT] Starting batch conversion ({len(files)} file(s))")
        self._set_status(f"Converting 0/{len(files)}...", "working")
        self._convert_worker.start()

    def _on_convert_progress(self, idx, total, name):
        if total:
            status = f"Converting {idx + 1}/{total}: {name}" if name else f"Converted {total}/{total}"
            self._set_status(status, "working" if idx < total else "success")

    def _on_convert_file_done(self, path, ok):
        marker = "[OK]" if ok else "[FAIL]"
        self._log(f"[CONVERT] {marker} {os.path.basename(path)}")

    def _on_convert_all_done(self, successes, failures):
        self.convert_files_btn.setEnabled(True)
        self.convert_folder_btn.setEnabled(True)
        self.convert_cancel_btn.setVisible(False)
        total = successes + failures
        if failures == 0:
            self._set_status(f"Conversion complete: {successes}/{total} succeeded.", "success")
        else:
            self._set_status(
                f"Conversion finished: {successes} ok, {failures} failed. See log.",
                "warning"
            )
        self._notify("StreamKeep", f"Converted {successes}/{total} file(s)")

    def _on_convert_cancel(self):
        w = getattr(self, "_convert_worker", None)
        if w is not None and w.isRunning():
            w.cancel()
            self._log("[CONVERT] Cancel requested — finishing current file first")
            self._set_status("Cancelling conversion...", "warning")

    def _on_export_config(self):
        """Write current config to a user-chosen JSON file."""
        self._persist_config()  # sync latest UI state first
        default_name = f"StreamKeep-config-{datetime.now().strftime('%Y%m%d')}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export StreamKeep Config",
            str(Path.home() / default_name),
            "JSON files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2)
            self._log(f"[CONFIG] Exported to {path}")
            self._set_status(f"Config exported to {path}", "success")
        except Exception as e:
            self._log(f"[CONFIG] Export failed: {e}")
            self._set_status(f"Export failed: {e}", "error")

    def _on_import_config(self):
        """Replace current config with the contents of a chosen JSON file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import StreamKeep Config",
            str(Path.home()),
            "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                new_cfg = json.load(f)
            if not isinstance(new_cfg, dict):
                self._set_status("Import failed: not a valid config file.", "error")
                return
        except Exception as e:
            self._log(f"[CONFIG] Import failed: {e}")
            self._set_status(f"Import failed: {e}", "error")
            return
        # Replace config and re-apply
        self._config = new_cfg
        _save_config(new_cfg)
        # Clear mutable state that _apply_config appends to
        self._history.clear()
        self.monitor.entries.clear()
        # If the imported config has monitor_channels, migrate and load
        _db.migrate_from_config(new_cfg)
        self.monitor.load_from_db()
        if not self.monitor.entries:
            self.monitor.load_from_config(new_cfg)
        # Re-apply config to all UI elements
        self._apply_config()
        # Refresh derived views
        self._refresh_history_table()
        self._refresh_download_summary()
        self._refresh_monitor_table()
        self._refresh_monitor_summary()
        self._refresh_history_summary()
        if hasattr(self, "queue_table"):
            self._refresh_queue_table()
        self._log(f"[CONFIG] Imported from {path}")
        self._set_status(f"Config imported from {path}. Some changes may require a restart.", "success")

    def _settings_browse(self, line_edit):
        d = QFileDialog.getExistingDirectory(self, "Select Folder", line_edit.text())
        if d:
            line_edit.setText(d)

    def _scan_browsers(self):
        """Scan for installed browsers by checking cookie database locations."""
        return _scan_browser_cookies()

    def _scan_browsers_silent(self):
        """Populate combo with scanned browsers without UI feedback."""
        found = self._scan_browsers()
        self.cookies_combo.clear()
        self.cookies_combo.addItem("None")
        seen = set()
        for display, ytdlp_name, path in found:
            label = f"{display} ({ytdlp_name})"
            if label not in seen:
                self.cookies_combo.addItem(label, ytdlp_name)
                seen.add(label)
        # Also add manual entries for common browsers not found
        for name in ["chrome", "chromium", "firefox", "edge", "brave", "opera", "vivaldi", "safari"]:
            manual_label = f"{name} (manual)"
            if not any(name == ytdlp for _, ytdlp, _ in found):
                self.cookies_combo.addItem(manual_label, name)

    def _on_scan_browsers(self):
        found = self._scan_browsers()
        self.cookies_combo.clear()
        self.cookies_combo.addItem("None")
        seen = set()
        for display, ytdlp_name, path in found:
            label = f"{display} ({ytdlp_name})"
            if label not in seen:
                self.cookies_combo.addItem(label, ytdlp_name)
                seen.add(label)
        # Manual fallbacks
        for name in ["chrome", "chromium", "firefox", "edge", "brave"]:
            manual_label = f"{name} (manual)"
            if not any(name == ytdlp for _, ytdlp, _ in found):
                self.cookies_combo.addItem(manual_label, name)

        if found:
            details = "\n".join(f"  {d} -> {p}" for d, _, p in found)
            self.cookies_scan_label.setText(f"Found {len(found)} browser(s):\n{details}")
            self._log(f"[SCAN] Found {len(found)} browser cookie stores:")
            for d, y, p in found:
                self._log(f"  {d} ({y}) -> {p}")
            self._set_status(f"Found {len(found)} browser cookie store(s).", "success")
        else:
            self.cookies_scan_label.setText("No browser cookie stores found.")
            self._set_status("No browser cookie stores were found on this machine.", "warning")

    def _on_browse_cookies_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select Cookies File", str(Path.home()),
            "Cookie files (*.txt *.sqlite);;All files (*)"
        )
        if f:
            self.cookies_file_input.setText(f)
            # Also import to StreamKeep's cookies.txt (F47)
            from streamkeep.cookies import import_from_file
            ok, msg = import_from_file(f)
            self._update_cookies_status()
            if ok:
                self._set_status(msg, "success")
            else:
                self._set_status(msg, "warning")

    def _on_import_browser_cookies(self):
        """Extract cookies from the selected browser to cookies.txt (F47)."""
        from streamkeep.cookies import import_from_browser
        browser_text = self.cookies_combo.currentText()
        browser_data = self.cookies_combo.currentData()
        if browser_text == "None" or not browser_data:
            self._set_status("Select a browser first, then click Import.", "warning")
            return
        ytdlp_name = str(browser_data)
        ok, msg = import_from_browser(ytdlp_name)
        self._update_cookies_status()
        if ok:
            self._set_status(msg, "success")
            self._log(f"[COOKIES] {msg}")
        else:
            self._set_status(msg, "error")
            self._log(f"[COOKIES] Error: {msg}")

    def _on_clear_cookies(self):
        """Delete the cookies.txt file (F47)."""
        from streamkeep.cookies import clear_cookies
        ok, msg = clear_cookies()
        self._update_cookies_status()
        self._set_status(msg, "success" if ok else "error")

    def _update_cookies_status(self):
        """Refresh the cookies status label (F47)."""
        from streamkeep.cookies import cookies_file_path, cookies_file_age_secs
        label = getattr(self, "cookies_status_label", None)
        if label is None:
            return
        cpath = cookies_file_path()
        if not cpath:
            label.setText("No cookies.txt — authenticated content may fail.")
            return
        age = cookies_file_age_secs()
        if age < 0:
            label.setText("cookies.txt present.")
        elif age < 3600:
            label.setText(f"cookies.txt present (updated {age // 60}m ago).")
        elif age < 86400:
            label.setText(f"cookies.txt present (updated {age // 3600}h ago).")
        else:
            days = age // 86400
            label.setText(f"cookies.txt present ({days}d old — consider refreshing).")

    def _on_save_account_tokens(self):
        """Persist platform tokens to encrypted storage (F48)."""
        from streamkeep.accounts import set_credential, credential_status
        inputs = getattr(self, "_account_inputs", {})
        saved = 0
        for plat_key, (inp, status_label) in inputs.items():
            val = inp.text().strip()
            if val:
                set_credential(plat_key, val)
                inp.clear()
                saved += 1
            status_label.setText(credential_status(plat_key))
        if saved:
            self._set_status(f"Saved {saved} token(s).", "success")
            self._log(f"[ACCOUNTS] Saved {saved} platform token(s)")

    def _on_clear_account_tokens(self):
        """Delete all stored platform tokens (F48)."""
        from streamkeep.accounts import delete_credential, PLATFORMS, credential_status
        inputs = getattr(self, "_account_inputs", {})
        for plat_key in PLATFORMS:
            delete_credential(plat_key)
            if plat_key in inputs:
                inputs[plat_key][0].clear()
                inputs[plat_key][1].setText(credential_status(plat_key))
        self._set_status("All platform tokens cleared.", "success")

    def _save_proxy_pool(self):
        """Parse the proxy pool text and persist (F49)."""
        from streamkeep.proxy import set_pool
        edit = getattr(self, "proxy_pool_edit", None)
        if edit is None:
            return
        entries = []
        for line in edit.toPlainText().strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            url = parts[0].strip()
            if not url:
                continue
            platforms = [p.strip() for p in (parts[1] if len(parts) > 1 else "").split(",") if p.strip()]
            label = parts[2].strip() if len(parts) > 2 else ""
            entries.append({
                "url": url, "platforms": platforms,
                "label": label, "enabled": True,
            })
        set_pool(entries)
        self._config["proxy_pool"] = entries

    def _on_test_proxies(self):
        """Run health checks on all proxy pool entries (F49)."""
        self._save_proxy_pool()
        from streamkeep.proxy import health_check_all
        results = health_check_all(timeout=8)
        if not results:
            self._set_status("No proxies configured to test.", "warning")
            return
        lines = []
        for label, ok, ms in results:
            if ok:
                lines.append(f"  {label}: {ms}ms")
            else:
                lines.append(f"  {label}: FAILED")
        self._log("[PROXY] Health check results:\n" + "\n".join(lines))
        ok_count = sum(1 for _, ok, _ in results if ok)
        self._set_status(
            f"Proxy test: {ok_count}/{len(results)} reachable.",
            "success" if ok_count == len(results) else "warning",
        )

    def _on_save_settings(self):
        self.output_input.setText(self.settings_output.text())
        # Apply browser cookies setting
        browser_text = self.cookies_combo.currentText()
        browser_data = self.cookies_combo.currentData()
        if browser_text == "None":
            YtDlpExtractor.cookies_browser = ""
            self._config["cookies_browser"] = ""
        else:
            ytdlp_name = browser_data if browser_data else browser_text
            YtDlpExtractor.cookies_browser = ytdlp_name
            self._config["cookies_browser"] = ytdlp_name
        # Apply cookies file
        cookies_file = self.cookies_file_input.text().strip()
        YtDlpExtractor.cookies_file = cookies_file
        self._config["cookies_file"] = cookies_file
        # Apply rate limit
        rate_limit = self.rate_limit_input.text().strip()
        YtDlpExtractor.rate_limit = rate_limit
        self._config["rate_limit"] = rate_limit
        # Apply proxy (also routes native extractor curl calls through it)
        proxy = self.proxy_input.text().strip()
        YtDlpExtractor.proxy = proxy
        self._config["proxy"] = proxy
        _set_native_proxy(proxy)
        global NATIVE_PROXY
        NATIVE_PROXY = proxy
        # Save proxy pool (F49)
        self._save_proxy_pool()
        # Save speed schedule (F51)
        if hasattr(self, "sched_enable_check"):
            sched = {
                "enabled": self.sched_enable_check.isChecked(),
                "day_start": self.sched_day_start.value(),
                "day_end": self.sched_day_end.value(),
                "day_limit": self.sched_day_limit.text().strip(),
                "night_limit": self.sched_night_limit.text().strip(),
                "weekend_limit": self.sched_weekend_limit.text().strip(),
            }
            self._config["speed_schedule"] = sched
            from streamkeep.scheduler import configure as _sched_configure
            _sched_configure(sched, rate_limit)
        # Apply parallel connections (affects direct MP4 downloads)
        self._parallel_connections = max(1, min(16, self.parallel_spin.value()))
        # Parallel auto-records + chunked live captures (v4.15.0).
        if hasattr(self, "parallel_autorecords_spin"):
            self._parallel_autorecords = max(1, min(4, self.parallel_autorecords_spin.value()))
            self._config["parallel_autorecords"] = self._parallel_autorecords
        if hasattr(self, "concurrent_queue_spin"):
            self._max_concurrent_downloads = max(1, min(8, self.concurrent_queue_spin.value()))
            self._config["max_concurrent_downloads"] = self._max_concurrent_downloads
        if hasattr(self, "chunk_check"):
            self._chunk_long_captures = self.chunk_check.isChecked()
            self._config["chunk_long_captures"] = self._chunk_long_captures
        if hasattr(self, "chunk_length_spin"):
            self._chunk_length_secs = int(self.chunk_length_spin.value())
            self._config["chunk_length_secs"] = self._chunk_length_secs
        if hasattr(self, "companion_check"):
            prev_enabled = bool(self._config.get("companion_server_enabled", False))
            prev_bind_lan = bool(self._config.get("companion_bind_lan", False))
            new_enabled = bool(self.companion_check.isChecked())
            new_bind_lan = bool(self.companion_lan_check.isChecked())
            self._config["companion_server_enabled"] = new_enabled
            self._config["companion_bind_lan"] = new_bind_lan
            if new_enabled != prev_enabled or new_bind_lan != prev_bind_lan:
                self._maybe_start_companion_server(
                    force_restart=prev_enabled and new_enabled and new_bind_lan != prev_bind_lan
                )
            else:
                self._refresh_companion_ui()
        if hasattr(self, "update_check_check"):
            self._config["check_for_updates"] = bool(self.update_check_check.isChecked())
        if hasattr(self, "capture_chat_check"):
            self._config["capture_live_chat"] = bool(self.capture_chat_check.isChecked())
        if hasattr(self, "render_chat_ass_check"):
            self._config["render_chat_ass"] = bool(self.render_chat_ass_check.isChecked())
        if hasattr(self, "quality_defaults_combos"):
            self._config["quality_defaults"] = {
                plat: (combo.currentData() or "")
                for plat, combo in self.quality_defaults_combos.items()
            }
        if hasattr(self, "whisper_model_combo"):
            self._config["whisper_model"] = str(self.whisper_model_combo.currentData() or "tiny")
        if hasattr(self, "diarize_check"):
            self._config["enable_diarization"] = bool(self.diarize_check.isChecked())
        if hasattr(self, "hf_token_input"):
            self._config["hf_token"] = self.hf_token_input.text().strip()
        # Chat render settings (F22)
        if hasattr(self, "chat_render_width_spin"):
            self._config["chat_render_width"] = self.chat_render_width_spin.value()
            self._config["chat_render_height"] = self.chat_render_height_spin.value()
            self._config["chat_render_font_size"] = self.chat_render_font_spin.value()
            self._config["chat_render_msg_duration"] = self.chat_render_duration_spin.value()
            self._config["chat_render_bg_opacity"] = self.chat_render_opacity_spin.value()
        if hasattr(self, "notif_sound_check"):
            self._config["notif_sound"] = bool(self.notif_sound_check.isChecked())
        # Apply bandwidth schedule rule
        self._bandwidth_rule = {
            "enabled": self.bw_enable_check.isChecked(),
            "start_hour": self.bw_start_spin.value(),
            "end_hour": self.bw_end_spin.value(),
            "limit": self.bw_limit_input.text().strip(),
        }
        self._apply_bandwidth_schedule()
        # Apply YouTube extras
        YtDlpExtractor.download_subs = self.subs_check.isChecked()
        self._config["download_subs"] = YtDlpExtractor.download_subs
        YtDlpExtractor.sponsorblock = self.sponsorblock_check.isChecked()
        self._config["sponsorblock"] = YtDlpExtractor.sponsorblock
        # Apply filename templates
        self._folder_template = self.folder_template_input.text().strip() or DEFAULT_FOLDER_TEMPLATE
        self._file_template = self.file_template_input.text().strip() or DEFAULT_FILE_TEMPLATE
        # Apply webhook
        self._webhook_url = self.webhook_input.text().strip()
        # Apply event hooks (F24)
        if hasattr(self, "hooks_table"):
            hooks = {}
            for i in range(self.hooks_table.rowCount()):
                evt = self.hooks_table.item(i, 0).text()
                cmd = (self.hooks_table.item(i, 1).text() or "").strip()
                if cmd:
                    hooks[evt] = cmd
            self._config["hooks"] = hooks
        # Apply duplicate detection
        self._check_duplicates = self.dup_check.isChecked()
        # Apply lifecycle policies (F32)
        if hasattr(self, "lc_enable_check"):
            self._config["lifecycle"] = {
                "enabled": self.lc_enable_check.isChecked(),
                "max_days": self.lc_max_days_spin.value(),
                "max_total_gb": self.lc_max_gb_spin.value(),
                "delete_watched": self.lc_watched_check.isChecked(),
                "favorites_exempt": self.lc_fav_exempt_check.isChecked(),
            }
        # Apply library/NFO + chat
        self._write_nfo = self.nfo_check.isChecked()
        TwitchExtractor.download_chat_enabled = self.chat_check.isChecked()
        # Apply media server auto-import (F33)
        if hasattr(self, "ms_enable_check"):
            from ..integrations.media_server import SERVER_TYPES
            self._config["media_server"] = {
                "enabled": self.ms_enable_check.isChecked(),
                "server_type": SERVER_TYPES[self.ms_type_combo.currentIndex()],
                "url": self.ms_url_input.text().strip(),
                "token": self.ms_token_input.text().strip(),
                "library_id": self.ms_library_id_input.text().strip(),
                "library_path": self.ms_path_input.text().strip(),
            }
        # Apply post-processing presets
        PostProcessor.extract_audio = self.pp_audio_check.isChecked()
        PostProcessor.normalize_loudness = self.pp_loud_check.isChecked()
        PostProcessor.reencode_h265 = self.pp_h265_check.isChecked()
        PostProcessor.contact_sheet = self.pp_contact_check.isChecked()
        PostProcessor.split_by_chapter = self.pp_split_check.isChecked()
        if hasattr(self, "pp_silence_check"):
            PostProcessor.remove_silence = self.pp_silence_check.isChecked()
            PostProcessor.silence_noise_db = self.pp_silence_db_spin.value()
            PostProcessor.silence_min_duration = float(self.pp_silence_dur_spin.value())
        # Converter settings
        PostProcessor.convert_video = self.pp_convert_video_check.isChecked()
        PostProcessor.convert_video_format = self.pp_convert_video_format.currentText()
        PostProcessor.convert_video_codec = self.pp_convert_video_codec.currentText()
        PostProcessor.convert_video_scale = self.pp_convert_video_scale.currentText()
        PostProcessor.convert_video_fps = self.pp_convert_video_fps.currentText()
        PostProcessor.convert_audio = self.pp_convert_audio_check.isChecked()
        PostProcessor.convert_audio_format = self.pp_convert_audio_format.currentText()
        PostProcessor.convert_audio_codec = self.pp_convert_audio_codec.currentText()
        PostProcessor.convert_audio_bitrate = self.pp_convert_audio_bitrate.currentText()
        PostProcessor.convert_audio_samplerate = self.pp_convert_audio_samplerate.currentText()
        PostProcessor.convert_delete_source = self.pp_convert_delete_check.isChecked()
        self._persist_config()
        self._refresh_download_summary()
        self._set_status("Settings saved and applied to future downloads.", "success")

    # ── Actions ───────────────────────────────────────────────────────

    # Soft cap on in-memory log panel lines. A long monitor/queue session
    # can accumulate hundreds of MB of text over time — trim from the top
    # in batches to keep append+scroll O(1) amortized.
    _LOG_SOFT_MAX_BLOCKS = 5000
    _LOG_TRIM_BLOCKS = 1000

    def _log(self, msg):
        self.log_text.append(msg)
        doc = self.log_text.document()
        if doc.blockCount() > self._LOG_SOFT_MAX_BLOCKS:
            try:
                from PyQt6.QtGui import QTextCursor
                cursor = QTextCursor(doc)
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                for _ in range(self._LOG_TRIM_BLOCKS):
                    cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                    cursor.removeSelectedText()
                    cursor.deleteChar()  # drop the now-empty block separator
            except Exception:
                pass
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())
        _write_log_line(msg)

    def _update_badge(self, platform_name=None):
        if platform_name and platform_name in PLATFORM_BADGES:
            badge = PLATFORM_BADGES[platform_name]
            self.platform_badge.setText(f" {badge['text']} ")
            self.platform_badge.setStyleSheet(
                f"background-color: {badge['color']}; color: {CAT['crust']}; "
                f"border-radius: 999px; font-weight: bold; font-size: 11px; padding: 4px 12px;"
            )
            self.platform_badge.setVisible(True)
        else:
            self.platform_badge.setVisible(False)

    def _on_url_changed(self, text):
        ext = Extractor.detect(text.strip())
        if ext:
            self._update_badge(ext.NAME)
            ch = ext.extract_channel_id(text.strip())
            if ch and self._can_autofill_output():
                self._apply_auto_output(str(_default_output_dir() / _safe_filename(ch)))
        else:
            self._update_badge(None)
        self._refresh_download_summary()

    def _on_toggle_clipboard(self, checked):
        if checked:
            self.clipboard_monitor.start()
            self._log("[CLIPBOARD] Monitoring started - copy a URL to auto-load")
            self._set_status("Clipboard monitoring active. Copy a supported URL to load it automatically.", "working")
        else:
            self.clipboard_monitor.stop()
            self._log("[CLIPBOARD] Monitoring stopped")
            self._set_status("Clipboard monitoring stopped.", "idle")

    def _on_clipboard_url(self, url):
        # Don't interrupt an active download
        existing = getattr(self, "download_worker", None)
        if existing is not None and existing.isRunning():
            self._log(f"[CLIPBOARD] Ignored {url[:60]}... (download in progress)")
            return
        # Basic URL sanity — reject newlines/control chars
        if "\n" in url or "\r" in url or len(url) > 2048:
            self._log("[CLIPBOARD] Rejected malformed URL")
            return
        # Dedup: ignore if already in the input box (avoids re-fetching on focus switches)
        if url == self.url_input.text().strip():
            return
        # Dedup: ignore if it's the same as the last clipboard URL we accepted
        if url == getattr(self, "_last_clipboard_url", ""):
            return
        self._last_clipboard_url = url
        self._log(f"[CLIPBOARD] Detected: {url}")
        self.url_input.setText(url)
        self._switch_tab(0)  # Switch to Download tab
        self._on_fetch()

    def _remember_url(self, url):
        """Add URL to the top of the recent URLs list (most-recent-first)."""
        if not url:
            return
        previous = list(self._recent_urls)
        # Dedup: move to front if already present
        if url in self._recent_urls:
            self._recent_urls.remove(url)
        self._recent_urls.insert(0, url)
        # Keep the last 30
        self._recent_urls = self._recent_urls[:30]
        if hasattr(self, "_recent_url_model"):
            self._recent_url_model.setStringList(self._recent_urls)
        if self._recent_urls != previous:
            self._schedule_persist_config()

    def _infer_history_channel(self, url="", platform="", channel=""):
        channel = (channel or "").strip()
        if channel and not channel.lower().startswith("vod_"):
            return channel
        if not url:
            return ""
        try:
            ext = Extractor.detect(url)
            if ext is not None:
                detected = (ext.extract_channel_id(url) or "").strip()
                if (
                    detected
                    and not detected.lower().startswith("vod_")
                    and not detected.isdigit()
                    and getattr(ext, "NAME", "") in {"Kick", "Twitch", "SoundCloud", "Audius", "Podcast"}
                ):
                    return detected
            parsed = urllib.parse.urlparse(url)
            parts = [p for p in parsed.path.strip("/").split("/") if p]
            blocked = {
                "videos", "video", "embed", "watch", "shorts",
                "playlist", "live", "vod", "v",
            }
            for part in parts:
                if part.lower() not in blocked and not part.isdigit():
                    return part
        except Exception:
            return ""
        return ""

    def _history_channel_label(self, entry):
        channel = self._infer_history_channel(
            url=getattr(entry, "url", ""),
            platform=getattr(entry, "platform", ""),
            channel=getattr(entry, "channel", ""),
        )
        if not channel:
            return ""
        platform = (getattr(entry, "platform", "") or "").strip()
        if platform:
            return f"{platform}/{channel}"
        return channel

    @staticmethod
    def _title_token_overlap(a, b):
        """Return the fraction of shared tokens between two titles (0..1)."""
        ta = set(a.strip().lower().split())
        tb = set(b.strip().lower().split())
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / max(len(ta), len(tb))

    def _find_duplicate(self, url, title="", platform="", duration_secs=0):
        """Check history for a matching URL (exact), exact title, or fuzzy
        metadata match (channel + title token overlap >= 70%). Returns
        matching HistoryEntry or None."""
        if not self._check_duplicates:
            return None
        if url:
            for h in self._history:
                if h.url == url and h.path:
                    return h
        if title:
            norm = title.strip().lower()
            for h in self._history:
                if (platform and h.platform
                        and h.platform.strip().lower() != platform.strip().lower()):
                    continue
                if h.title and h.title.strip().lower() == norm and h.path:
                    return h
            # Fuzzy title-token overlap (F40)
            for h in self._history:
                if not h.title or not h.path:
                    continue
                if (platform and h.platform
                        and h.platform.strip().lower() != platform.strip().lower()):
                    continue
                if self._title_token_overlap(title, h.title) >= 0.70:
                    return h
        return None

    def _set_download_context(self, out_dir="", quality_name="", history_url="", info=None):
        self._active_output_dir = out_dir
        self._active_quality_name = quality_name
        self._active_history_url = history_url
        self._active_stream_info = info or self.stream_info

    # ── Resume sidecar integration ───────────────────────────────────

    def _attach_resume_to_worker(self, worker, *, resume_existing=None, context=None):
        """Wire a ResumeState into a DownloadWorker just before start().

        If `resume_existing` is provided (from the startup-banner "Resume"
        action), its completed-segments list is preserved and re-used.
        Otherwise a fresh state is built from `context` (dict with
        source_url/platform/title/channel/quality_name keys) or, if None,
        from `self._active_*` for backwards-compat with the foreground path.
        Silent on failure — a resume sidecar is nice-to-have, never required.
        """
        try:
            if context is None:
                info = self._active_stream_info or self.stream_info
                source_url = self._active_history_url or ""
                platform = (info.platform if info else "") or ""
                title = (info.title if info else "") or ""
                channel = (info.channel if info else "") or ""
                quality_name = self._active_quality_name or ""
            else:
                info = context.get("info")
                source_url = context.get("source_url") or ""
                platform = context.get("platform") or (info.platform if info else "") or ""
                title = context.get("title") or (info.title if info else "") or ""
                channel = context.get("channel") or (info.channel if info else "") or ""
                quality_name = context.get("quality_name") or ""
            if resume_existing is not None:
                state = resume_existing
                # Refresh the parts of the sidecar that can have changed
                # between the interrupted run and now (new token URLs, etc.).
                state.playlist_url = worker.playlist_url
                state.format_type = worker.format_type
                state.audio_url = worker.audio_url or ""
                state.ytdlp_source = worker.ytdlp_source or ""
                state.ytdlp_format = worker.ytdlp_format or ""
                state.output_dir = worker.output_dir
                state.segments = [list(s) for s in worker.segments]
            else:
                state = ResumeState(
                    source_url=source_url,
                    platform=platform,
                    title=title,
                    channel=channel,
                    quality_name=quality_name,
                    output_dir=worker.output_dir,
                )
            worker.attach_resume_state(state)
        except Exception as e:
            self._log(f"[RESUME] Could not write sidecar: {e}")

    def _collect_resume_scan_roots(self):
        """Directories worth scanning for orphan resume sidecars.

        Includes the active output-field value, the persisted default in
        config, and any per-channel monitor override dirs.
        """
        roots = []
        seen = set()

        def _push(path):
            if not path:
                return
            real = os.path.realpath(path)
            if real in seen:
                return
            seen.add(real)
            roots.append(path)

        try:
            _push(self.output_input.text().strip())
        except Exception:
            pass
        _push(self._config.get("output_dir", ""))
        _push(str(_default_output_dir()))
        for entry in getattr(self.monitor, "entries", []) or []:
            _push(getattr(entry, "override_output_dir", "") or "")
        return roots

    def _scan_for_resumable_downloads(self):
        """Called once at startup — shows the resume banner if any orphan
        sidecars look resumable."""
        try:
            roots = self._collect_resume_scan_roots()
            found = scan_for_orphan_sidecars(roots)
        except Exception as e:
            self._log(f"[RESUME] Scan failed: {e}")
            return
        self._resume_candidates = found
        self._refresh_resume_banner()

    def _refresh_resume_banner(self):
        """Show/hide the resume banner based on candidate count."""
        banner = getattr(self, "resume_banner", None)
        if banner is None:
            return
        count = len(getattr(self, "_resume_candidates", []) or [])
        if count <= 0:
            banner.setVisible(False)
            return
        label = getattr(self, "resume_banner_label", None)
        if label is not None:
            if count == 1:
                state = self._resume_candidates[0]
                total = len(state.segments or [])
                done = len(state.completed or [])
                title = (state.title or os.path.basename(state.output_dir) or "download")[:80]
                if total:
                    progress = f" ({done}/{total} segments done)"
                else:
                    progress = ""
                label.setText(f"Interrupted download ready to resume: {title}{progress}")
            else:
                label.setText(f"{count} interrupted downloads are ready to resume.")
        banner.setVisible(True)

    def _on_resume_all(self):
        """Resume the first candidate immediately; leave the rest queued for
        after it finishes so we don't try to run N downloads in parallel."""
        if not getattr(self, "_resume_candidates", None):
            self._refresh_resume_banner()
            return
        if self.download_worker is not None and self.download_worker.isRunning():
            self._set_status(
                "Finish or stop the active download before resuming.",
                "warning",
            )
            return
        state = self._resume_candidates[0]
        self._kick_off_resume(state)

    def _on_resume_discard(self):
        """Drop all resume candidates — remove their sidecars from disk."""
        count = 0
        for state in (getattr(self, "_resume_candidates", None) or []):
            try:
                clear_resume_state(state.output_dir)
                count += 1
            except Exception:
                pass
        self._resume_candidates = []
        self._refresh_resume_banner()
        if count:
            self._log(f"[RESUME] Discarded {count} pending resume sidecar(s).")
            self._set_status(
                f"Discarded {count} interrupted download(s). They will not be resumed.",
                "idle",
            )

    def _kick_off_resume(self, state):
        """Re-resolve the source URL and start a DownloadWorker that picks
        up from the saved segment list. Short-lived tokens get refreshed
        through the extractor system."""
        try:
            self._resume_candidates = [
                s for s in (self._resume_candidates or [])
                if s.output_dir != state.output_dir
            ]
            self._refresh_resume_banner()
            # Re-resolve when we have a usable source URL so that expired
            # playlist tokens (common on Kick/Twitch, which rotate roughly
            # every 24h) get refreshed before ffmpeg hits them with a 403.
            refreshed_url = state.playlist_url
            refreshed_audio = state.audio_url
            if state.source_url:
                ext = Extractor.detect(state.source_url)
                if ext:
                    try:
                        info = ext.resolve(state.source_url, log_fn=self._log)
                    except Exception as e:
                        self._log(f"[RESUME] Re-resolve failed, trying saved URL: {e}")
                        info = None
                    if info and info.qualities:
                        # Prefer a quality matching the saved name; fall back
                        # to the top listed quality.
                        chosen = info.qualities[0]
                        for q in info.qualities:
                            if q.name == state.quality_name:
                                chosen = q
                                break
                        refreshed_url = chosen.url or refreshed_url
                        refreshed_audio = chosen.audio_url or refreshed_audio
                        state.playlist_url = refreshed_url
                        state.audio_url = refreshed_audio
                        save_resume_state(state)
            remaining = remaining_segments(state)
            if not remaining:
                self._log(f"[RESUME] Nothing to resume in {state.output_dir} — clearing sidecar.")
                clear_resume_state(state.output_dir)
                return
            self._log(
                f"[RESUME] Resuming {state.title or state.output_dir} — "
                f"{len(state.completed or [])}/{len(state.segments or [])} already done."
            )
            # Minimal context — the on_all_done path tolerates a missing
            # info object and reads title/channel from self._active_stream_info
            # only when present.
            self._set_download_context(
                out_dir=state.output_dir,
                quality_name=state.quality_name,
                history_url=state.source_url,
                info=None,
            )
            worker = DownloadWorker(
                refreshed_url or state.playlist_url,
                remaining,
                state.output_dir,
                format_type=state.format_type or "hls",
            )
            worker.audio_url = refreshed_audio or ""
            worker.ytdlp_source = state.ytdlp_source or ""
            worker.ytdlp_format = state.ytdlp_format or ""
            worker.cookies_browser = YtDlpExtractor.cookies_browser
            worker.rate_limit = YtDlpExtractor.rate_limit
            worker.proxy = YtDlpExtractor.proxy
            worker.download_subs = YtDlpExtractor.download_subs
            worker.sponsorblock = YtDlpExtractor.sponsorblock
            worker.parallel_connections = self._parallel_connections
            worker.progress.connect(self._on_dl_progress)
            worker.segment_done.connect(self._on_segment_done)
            worker.error.connect(self._on_dl_error)
            worker.log.connect(self._log)
            worker.all_done.connect(self._on_all_done)
            self.download_worker = worker
            self._attach_resume_to_worker(worker, resume_existing=state)
            self._set_status(
                f"Resuming {(state.title or 'download')[:60]}...",
                "processing",
            )
            worker.start()
        except Exception as e:
            self._log(f"[RESUME] Could not resume: {e}")
            self._set_status("Resume failed — see log for details.", "error")

    def _output_contains_media(self, out_dir):
        if not out_dir or not os.path.isdir(out_dir):
            return False
        media_exts = {ext.lower() for ext in (VIDEO_EXTS | AUDIO_EXTS)}
        try:
            for entry in os.scandir(out_dir):
                if entry.is_file() and Path(entry.name).suffix.lower() in media_exts:
                    return True
        except OSError:
            return False
        return False

    def _output_size_label(self, out_dir):
        if not out_dir or not os.path.isdir(out_dir):
            return ""
        total = 0
        try:
            for root, _dirs, files in os.walk(out_dir):
                for name in files:
                    path = os.path.join(root, name)
                    try:
                        total += os.path.getsize(path)
                    except OSError:
                        continue
        except OSError:
            return ""
        return _fmt_size(total) if total > 0 else ""

    def _postprocess_snapshot(self):
        keys = [
            "extract_audio",
            "normalize_loudness",
            "reencode_h265",
            "contact_sheet",
            "split_by_chapter",
            "convert_video",
            "convert_video_format",
            "convert_video_codec",
            "convert_video_scale",
            "convert_video_fps",
            "convert_audio",
            "convert_audio_format",
            "convert_audio_codec",
            "convert_audio_bitrate",
            "convert_audio_samplerate",
            "convert_delete_source",
        ]
        snap = {k: getattr(PostProcessor, k) for k in keys}
        # Apply per-download PP preset override (F18)
        overrides = getattr(self, "_dl_overrides", {})
        preset_name = overrides.get("pp_preset", "")
        if preset_name:
            from .tabs.settings import BUILTIN_PRESETS, _get_user_presets
            all_presets = dict(BUILTIN_PRESETS)
            all_presets.update(_get_user_presets(self))
            if preset_name in all_presets:
                snap.update(all_presets[preset_name])
        return snap

    def _foreground_busy(self):
        if getattr(self, "_batch_active", False):
            return True
        for name in (
            "download_worker",
            "_fetch_worker",
            "_batch_fetch_worker",
            "_auto_record_resolve_worker",
            "_expand_worker",
            "_scan_worker",
        ):
            worker = getattr(self, name, None)
            if worker is not None and worker.isRunning():
                return True
        return False

    def _queue_status_changed(self):
        self._persist_config()
        if hasattr(self, "queue_table"):
            self._refresh_queue_table()

    def _set_queue_item_status(self, item, status, note=""):
        if item is None:
            return
        item["status"] = status
        item["note"] = note
        self._queue_status_changed()

    def _release_queue_item(self, status=None, note=""):
        item = self._queue_active_item
        self._queue_active_item = None
        self._queue_autostart = False
        if item is None:
            return
        if status == "done":
            # Recurring items re-schedule themselves for the next window
            # instead of being removed — this is what turns the queue into
            # "DVR my weekly show" instead of "one-off".
            recurrence = (item.get("recurrence") or "").strip().lower()
            next_fire = self._compute_next_fire(recurrence, item.get("start_at", ""))
            if next_fire:
                item["status"] = "queued"
                item["start_at"] = next_fire.isoformat(timespec="minutes")
                item["note"] = f"recurring ({recurrence}) — next fire {next_fire.strftime('%a %H:%M')}"
                self._log(
                    f"[QUEUE] Recurring item rescheduled for "
                    f"{next_fire.strftime('%Y-%m-%d %H:%M')}: "
                    f"{(item.get('title') or item.get('url', ''))[:60]}"
                )
                self._queue_status_changed()
                return
            try:
                self._download_queue.remove(item)
            except ValueError:
                pass
            self._queue_status_changed()
            return
        if status:
            self._set_queue_item_status(item, status, note)

    def _compute_next_fire(self, recurrence, start_at_iso):
        """Return the datetime of the next fire for a recurring queue
        item, or None for one-shot / unparseable recurrence strings.

        Accepted shapes (case-insensitive):
          "daily"          every 24h from last fire
          "weekly"         every 7 days from last fire
          "mon,wed,fri"    next occurrence on one of the named days
        Days use first 3 letters; any subset of mon/tue/wed/thu/fri/sat/sun.
        """
        if not recurrence:
            return None
        try:
            last = datetime.fromisoformat(start_at_iso) if start_at_iso else datetime.now()
        except Exception:
            last = datetime.now()
        now = datetime.now()
        # If the last fire was in the past we pivot off "now" so we never
        # backfill missed windows.
        base = max(last, now)
        if recurrence == "daily":
            return base + timedelta(days=1)
        if recurrence == "weekly":
            return base + timedelta(days=7)
        day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        wanted = []
        for part in recurrence.replace(" ", "").split(","):
            if part in day_map:
                wanted.append(day_map[part])
        if not wanted:
            return None
        wanted.sort()
        # Keep the wall-clock time of day from the original start_at.
        target_time = last.time() if start_at_iso else now.time()
        today_wd = now.weekday()
        for offset in range(1, 8):
            candidate_wd = (today_wd + offset) % 7
            if candidate_wd in wanted:
                target_date = now.date() + timedelta(days=offset)
                return datetime.combine(target_date, target_time)
        return None

    def _resolve_history_url(self):
        if self._active_history_url:
            return self._active_history_url
        req = getattr(self, "_last_fetch_request", {})
        vod_source = req.get("vod_source", "")
        if vod_source:
            return vod_source
        if self._queue_active_item is not None:
            return self._queue_active_item.get("url", "")
        if hasattr(self, "url_input"):
            return self.url_input.text().strip()
        return ""

    def _start_next_background_job(self):
        resolver = getattr(self, "_auto_record_resolve_worker", None)
        if resolver is not None and resolver.isRunning():
            return
        if self._drain_pending_auto_records():
            return
        self._advance_queue()

    def _start_finalize_worker(self):
        worker = getattr(self, "_finalize_worker", None)
        if worker is not None and worker.isRunning():
            return
        if not self._finalize_tasks:
            self._finalize_active_title = ""
            self._finalize_active_label = ""
            self._finalize_active_step = 0
            self._finalize_active_total = 0
            self._refresh_download_summary()
            return
        task = self._finalize_tasks.pop(0)
        self._finalize_active_title = task.get("title", "")
        self._finalize_active_label = "Preparing background cleanup"
        self._finalize_active_step = 0
        self._finalize_active_total = 0
        worker = FinalizeWorker(task)
        worker.log.connect(self._log)
        worker.progress.connect(self._on_finalize_progress)
        worker.done.connect(self._on_finalize_done)
        self._finalize_worker = worker
        worker.start()
        self._refresh_download_summary()
        if not self._foreground_busy():
            extra = f" {len(self._finalize_tasks)} more queued." if self._finalize_tasks else ""
            self._set_status(
                f"Finalizing {task.get('title', 'download')[:60]} in the background.{extra}",
                "processing",
            )

    def _enqueue_finalize_task(self, task):
        self._finalize_tasks.append(task)
        if len(self._finalize_tasks) > 1 or (
                self._finalize_worker is not None and self._finalize_worker.isRunning()):
            self._log(f"[FINALIZE] Queued background finalization for {task.get('title', 'download')[:60]}")
        self._refresh_download_summary()
        self._start_finalize_worker()

    def _on_finalize_progress(self, label, step_no, total_steps):
        self._finalize_active_label = label or ""
        self._finalize_active_step = max(0, int(step_no or 0))
        self._finalize_active_total = max(self._finalize_active_step, int(total_steps or 0))
        self._refresh_download_summary()
        if not self._foreground_busy():
            count = ""
            if self._finalize_active_total:
                count = f" ({self._finalize_active_step}/{self._finalize_active_total})"
            extra = f" {len(self._finalize_tasks)} more queued." if self._finalize_tasks else ""
            title = self._finalize_active_title[:60] or "download"
            step_text = f"{self._finalize_active_label}{count}" if self._finalize_active_label else f"step{count}"
            self._set_status(f"Finalizing {title}: {step_text}.{extra}", "processing")

    def _on_finalize_done(self, result):
        worker = getattr(self, "_finalize_worker", None)
        if worker is not None and not worker.isRunning():
            try:
                worker.wait(200)
            except Exception:
                pass
        self._finalize_worker = None
        self._finalize_active_title = ""
        self._finalize_active_label = ""
        self._finalize_active_step = 0
        self._finalize_active_total = 0
        finished_title = result.get("title", "download")
        if not result.get("cancelled"):
            self._add_history(
                result.get("platform", "?"),
                result.get("title", "?"),
                result.get("quality_name", ""),
                result.get("size_label", self._output_size_label(result.get("out_dir", ""))),
                result.get("out_dir", ""),
                channel=result.get("channel", ""),
                url=result.get("history_url", ""),
            )
        remaining = len(self._finalize_tasks)
        self._refresh_download_summary()
        if not self._foreground_busy():
            if result.get("cancelled"):
                self._set_status("Background finalization was cancelled.", "warning")
            elif remaining:
                self._set_status(
                    f"Finished finalizing {finished_title[:60]}. {remaining} background job(s) remaining.",
                    "processing",
                )
            else:
                self._set_status(
                    f"Background finalization complete for {finished_title[:60]}.",
                    "success",
                )
        self._start_finalize_worker()

    def _cancel_batch_fetch_worker(self):
        worker = getattr(self, "_batch_fetch_worker", None)
        if worker is None:
            return
        try:
            worker.requestInterruption()
        except Exception:
            pass
        if worker.isRunning():
            try:
                worker.wait(1500)
            except Exception:
                pass
        self._batch_fetch_worker = None

    def _start_monitor_seed_worker(self, url, channel_id):
        existing = self._monitor_seed_workers.get(channel_id)
        if existing is not None and existing.isRunning():
            return
        worker = SeedArchiveWorker(url, channel_id)
        worker.log.connect(self._log)
        worker.finished.connect(self._on_monitor_seed_done)
        worker.error.connect(self._on_monitor_seed_error)
        self._monitor_seed_workers[channel_id] = worker
        worker.start()

    def _clear_monitor_seed_worker(self, channel_id):
        worker = self._monitor_seed_workers.pop(channel_id, None)
        if worker is not None and worker.isRunning():
            try:
                worker.wait(200)
            except Exception:
                pass

    def _on_fetch(self, vod_source=None, vod_platform=None, vod_title=None, vod_channel=None):
        url = self.url_input.text().strip()
        if not url:
            return
        self._last_fetch_request = {
            "url": url,
            "vod_source": vod_source or "",
            "vod_platform": vod_platform or "",
            "vod_title": vod_title or "",
            "vod_channel": vod_channel or "",
        }
        # Track recent URLs for the autocomplete dropdown
        if not vod_source:
            self._remember_url(url)
        # Check for URL-based duplicate before hitting the network
        if not vod_source:
            dup = self._find_duplicate(url)
            if dup:
                self._log(f"[DUPLICATE] Already downloaded on {dup.date} to {dup.path}")
                self._set_status(
                    f"Already downloaded {dup.date} to {dup.path}. Fetching anyway.",
                    "warning",
                )
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("Fetching")
        self.download_btn.setEnabled(False)
        self.open_folder_btn.setVisible(False)
        if hasattr(self, "trim_btn"):
            self.trim_btn.setVisible(False)
        self.overall_progress.setVisible(False)
        self.quality_combo.clear()
        self.quality_combo.setEnabled(False)
        self.table.setRowCount(0)
        self._segment_checks = []
        self._segment_progress = []
        self.info_label.setVisible(False)
        self.stream_info = None
        if not vod_source:
            self.vod_widget.setVisible(False)
            self._vod_checks = []
            self._refresh_vod_summary()
        self._refresh_download_summary()
        self._set_status("Fetching stream info and available playback options...", "working")

        # Disconnect any existing fetch worker to prevent stale signals
        prev_worker = getattr(self, "_fetch_worker", None)
        if prev_worker is not None:
            try:
                prev_worker.log.disconnect()
                prev_worker.finished.disconnect()
                prev_worker.vods_found.disconnect()
                prev_worker.error.disconnect()
            except (TypeError, RuntimeError):
                pass
            if prev_worker.isRunning():
                prev_worker.requestInterruption()

        self._fetch_worker = FetchWorker(
            url,
            vod_source=vod_source,
            vod_platform=vod_platform,
            vod_title=vod_title,
            vod_channel=vod_channel,
        )
        self._fetch_worker.log.connect(self._log)
        self._fetch_worker.finished.connect(self._on_fetch_done)
        self._fetch_worker.vods_found.connect(self._on_vods_found)
        self._fetch_worker.error.connect(self._on_fetch_error)
        self._fetch_worker.start()

    def _on_fetch_done(self, info):
        if info is None:
            self._on_fetch_error("Extractor returned no stream info")
            return
        self.stream_info = info
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("Fetch")
        self._update_badge(info.platform)

        # Populate qualities
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        qualities = info.qualities or []
        for q in qualities:
            bw_mbps = q.bandwidth / 1_000_000 if q.bandwidth else 0
            ft_tag = f" [{q.format_type.upper()}]" if q.format_type != "hls" else ""
            label = f"{q.name} ({q.resolution}, {bw_mbps:.1f} Mbps){ft_tag}"
            self.quality_combo.addItem(label, q)
        if qualities:
            selected_idx = self._choose_default_quality_index(
                qualities, info.platform or ""
            )
            self.quality_combo.setCurrentIndex(selected_idx)
        self.quality_combo.setEnabled(len(qualities) > 0)
        self.quality_combo.blockSignals(False)
        if not qualities:
            self._log("[WARN] No playable qualities found for this URL.")

        # Stream info
        parts = [f"Platform: {info.platform}", f"Duration: {info.duration_str}"]
        if info.title:
            parts.insert(1, f"Title: {info.title[:60]}")
        if info.start_time:
            try:
                dt = datetime.fromisoformat(info.start_time.replace("Z", "+00:00"))
                parts.append(f"Started: {dt.strftime('%Y-%m-%d %I:%M %p UTC')}")
            except Exception:
                pass
        if info.segment_count:
            parts.append(f"Segments: {info.segment_count}")
        self.info_label.setText("  |  ".join(parts))
        self.info_label.setVisible(True)

        # Update output folder to use the title for non-channel content (yt-dlp, Direct, etc.)
        if info.title and info.platform in ("yt-dlp", "Direct", "Rumble", "SoundCloud",
                                            "Reddit", "Audius", "Podcast"):
            current_out = self.output_input.text().strip()
            parent = os.path.dirname(current_out)
            if parent and self._can_autofill_output():
                new_out = os.path.join(parent, _safe_filename(info.title))
                self._apply_auto_output(new_out)

        self._build_segments(info.total_secs)
        self.download_btn.setEnabled(True)
        self._refresh_download_summary()

        # Metadata-based duplicate check after resolve (F40 — fuzzy matching)
        dup = self._find_duplicate(
            "", info.title, platform=info.platform,
            duration_secs=info.total_secs,
        )
        if dup:
            self._log(f"[DUPLICATE] Match: already downloaded {dup.date} to {dup.path}")
            self._set_status(
                f"Possible duplicate of \"{dup.title}\" ({dup.date}). Download anyway if intentional.",
                "warning",
            )
            # Advisory dialog — non-blocking for queue/batch, shown for manual fetches
            if not self._queue_autostart:
                details = (
                    f"Title: {dup.title}\n"
                    f"Downloaded: {dup.date}\n"
                    f"Quality: {dup.quality}\n"
                    f"Size: {dup.size}\n"
                    f"Location: {dup.path}"
                )
                if not ask_premium_confirmation(
                    self,
                    title="Possible duplicate found",
                    body="StreamKeep found a recording in your library that closely matches what you are about to download.",
                    eyebrow="DOWNLOAD",
                    badge_text="Potential match",
                    tone="warning",
                    summary_title="Downloading again may waste storage and clutter history.",
                    summary_body="Continue only if you intentionally want another copy or a better variant.",
                    details_title="Existing recording",
                    details_body=details,
                    primary_label="Download anyway",
                    secondary_label="Skip download",
                    default_action="secondary",
                    min_width=640,
                ):
                    self._set_status("Download skipped — duplicate detected.", "idle")
                    return
        elif info.is_live or info.total_secs <= 0:
            self._set_status("Live source ready. Start recording and stop it when you have enough footage.", "success")
        else:
            self._set_status("Source ready. Review the segments and start the download when you are happy.", "success")

        if self._queue_autostart and self._queue_active_item is not None:
            self._set_queue_item_status(self._queue_active_item, "downloading")
            if not self._on_download():
                self._release_queue_item("failed", "Could not start the queued download")
                self._start_next_background_job()

    def _on_fetch_error(self, err):
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("Fetch")
        self._log(f"[ERROR] {err}")
        self._refresh_download_summary()
        self._set_status(f"Fetch failed: {err}", "error")
        if self._queue_active_item is not None:
            self._release_queue_item("failed", err[:120])
            self._start_next_background_job()

    def _on_vods_found(self, vod_list, platform_name, next_cursor=None):
        self._vod_next_cursor = next_cursor
        self._vod_source_url = self.url_input.text().strip()
        if self._queue_autostart and self._queue_active_item is not None:
            added = 0
            for vod in vod_list:
                if self._queue_add(
                        vod.source,
                        title=vod.title,
                        platform=vod.platform or platform_name,
                        vod_source=vod.source,
                        vod_platform=vod.platform or platform_name,
                        vod_title=vod.title,
                        vod_channel=vod.channel):
                    added += 1
            source_label = self._queue_active_item.get("title") or self._queue_active_item.get("url", "")
            self._release_queue_item("done")
            self._log(f"[QUEUE] Expanded {source_label[:60]} into {added} queued VOD(s)")
            tone = "success" if added else "warning"
            self._set_status(
                f"Expanded queued source into {added} VOD(s).",
                tone,
            )
            self._start_next_background_job()
            return

        self._vod_list = vod_list
        self._vod_checks = []
        self.vod_table.setRowCount(len(vod_list))
        self._update_badge(platform_name)

        for i, v in enumerate(vod_list):
            cb = QCheckBox()
            cb.stateChanged.connect(lambda _state, row=i: self._on_vod_cb_toggled(row))
            cb_widget = QWidget()
            cb_lay = QHBoxLayout(cb_widget)
            cb_lay.addWidget(cb)
            cb_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lay.setContentsMargins(0, 0, 0, 0)
            self.vod_table.setCellWidget(i, 0, cb_widget)
            self._vod_checks.append(cb)

            # Platform badge
            badge = PLATFORM_BADGES.get(v.platform, {})
            plat_item = QTableWidgetItem(v.platform)
            plat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if badge.get("color"):
                plat_item.setForeground(QColor(badge["color"]))
            self.vod_table.setItem(i, 1, plat_item)

            # Title
            live = " [LIVE]" if v.is_live else ""
            title_item = QTableWidgetItem(f"{v.title}{live}")
            if v.is_live:
                title_item.setForeground(QColor(CAT["green"]))
            self.vod_table.setItem(i, 2, title_item)

            date_item = QTableWidgetItem(v.date)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.vod_table.setItem(i, 3, date_item)

            dur_item = QTableWidgetItem(v.duration if v.duration else "Live")
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.vod_table.setItem(i, 4, dur_item)

            views_str = f"{v.viewers:,}" if v.viewers else "—"
            views_item = QTableWidgetItem(views_str)
            views_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.vod_table.setItem(i, 5, views_item)

        self._vod_last_checked_row = -1  # shift-click anchor
        self.vod_widget.setVisible(True)
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("Fetch")
        self._refresh_vod_summary()
        if hasattr(self, "vod_load_more_btn"):
            self.vod_load_more_btn.setVisible(bool(next_cursor))
            self.vod_load_more_btn.setEnabled(bool(next_cursor))
            self.vod_load_more_btn.setText("Load More VODs")
        self._set_status(f"Found {len(vod_list)} VOD(s). Select one to inspect or batch download.", "success")

    def _on_vod_cb_toggled(self, row):
        """Handle a VOD checkbox toggle — supports shift-click range select."""
        from PyQt6.QtWidgets import QApplication
        modifiers = QApplication.keyboardModifiers()
        anchor = getattr(self, "_vod_last_checked_row", -1)
        if modifiers & Qt.KeyboardModifier.ShiftModifier and 0 <= anchor < len(self._vod_checks):
            lo, hi = min(anchor, row), max(anchor, row)
            target_state = self._vod_checks[row].isChecked()
            for r in range(lo, hi + 1):
                if r < len(self._vod_checks):
                    self._vod_checks[r].blockSignals(True)
                    self._vod_checks[r].setChecked(target_state)
                    self._vod_checks[r].blockSignals(False)
        self._vod_last_checked_row = row
        self._refresh_vod_summary()

    def _on_vod_select_all(self, state):
        checked = state == Qt.CheckState.Checked.value
        for cb in self._vod_checks:
            cb.setChecked(checked)
        self._refresh_vod_summary()

    def _on_vod_queue_selected(self):
        """Add all checked VODs to the download queue."""
        checked = [self._vod_list[i] for i, cb in enumerate(self._vod_checks) if cb.isChecked()]
        if not checked:
            self._set_status("Select at least one VOD to queue.", "warning")
            return
        added = 0
        for vod in checked:
            ok = self._queue_add(
                vod.source,
                title=vod.title,
                platform=vod.platform,
                vod_source=vod.source,
                vod_platform=vod.platform,
                vod_title=vod.title,
                vod_channel=vod.channel,
            )
            if ok:
                added += 1
        self._log(f"[QUEUE] Added {added} of {len(checked)} checked VOD(s) to queue")
        self._set_status(
            f"Queued {added} VOD(s) for download." if added else "All selected VODs are already queued.",
            "success" if added else "info",
        )
        if added:
            self._advance_queue()

    def _on_vod_load_single(self):
        for i, cb in enumerate(self._vod_checks):
            if cb.isChecked():
                vod = self._vod_list[i]
                self._log(f"\nLoading VOD: {vod.title} ({vod.date})")
                self._on_fetch(
                    vod_source=vod.source,
                    vod_platform=vod.platform,
                    vod_title=vod.title,
                    vod_channel=vod.channel,
                )
                return
        self._log("No VOD checked.")
        self._set_status("Select at least one VOD before loading it.", "warning")

    def _on_vod_load_more(self):
        """Fetch the next page of VODs and append to the table."""
        cursor = getattr(self, "_vod_next_cursor", None)
        url = getattr(self, "_vod_source_url", "")
        if not cursor or not url:
            return
        # Cancel any previous page worker
        pw = getattr(self, "_vod_page_worker", None)
        if pw is not None and pw.isRunning():
            pw.requestInterruption()
            pw.wait(1500)
        if hasattr(self, "vod_load_more_btn"):
            self.vod_load_more_btn.setEnabled(False)
            self.vod_load_more_btn.setText("Loading…")
        self._log(f"[VOD] Fetching next page (cursor: {str(cursor)[:20]}…)")
        worker = VodPageWorker(url, cursor)
        worker.log.connect(self._log)
        worker.page_ready.connect(self._on_vod_page_ready)
        worker.error.connect(self._on_vod_page_error)
        self._vod_page_worker = worker
        worker.start()

    def _on_vod_page_ready(self, new_vods, next_cursor):
        """Append a page of VODs to the existing table."""
        self._vod_next_cursor = next_cursor
        if not new_vods:
            self._log("[VOD] No more VODs on the next page.")
            self._set_status("No additional VODs found.", "info")
            if hasattr(self, "vod_load_more_btn"):
                self.vod_load_more_btn.setVisible(False)
            return
        # Append to the existing list
        start_row = len(self._vod_list)
        self._vod_list.extend(new_vods)
        self.vod_table.setRowCount(len(self._vod_list))
        for i, v in enumerate(new_vods, start=start_row):
            cb = QCheckBox()
            cb.stateChanged.connect(lambda _state, row=i: self._on_vod_cb_toggled(row))
            cb_widget = QWidget()
            cb_lay = QHBoxLayout(cb_widget)
            cb_lay.addWidget(cb)
            cb_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lay.setContentsMargins(0, 0, 0, 0)
            self.vod_table.setCellWidget(i, 0, cb_widget)
            self._vod_checks.append(cb)
            badge = PLATFORM_BADGES.get(v.platform, {})
            plat_item = QTableWidgetItem(v.platform)
            plat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if badge.get("color"):
                plat_item.setForeground(QColor(badge["color"]))
            self.vod_table.setItem(i, 1, plat_item)
            live = " [LIVE]" if v.is_live else ""
            title_item = QTableWidgetItem(f"{v.title}{live}")
            if v.is_live:
                title_item.setForeground(QColor(CAT["green"]))
            self.vod_table.setItem(i, 2, title_item)
            date_item = QTableWidgetItem(v.date)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.vod_table.setItem(i, 3, date_item)
            dur_item = QTableWidgetItem(v.duration if v.duration else "Live")
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.vod_table.setItem(i, 4, dur_item)
            views_str = f"{v.viewers:,}" if v.viewers else "—"
            views_item = QTableWidgetItem(views_str)
            views_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.vod_table.setItem(i, 5, views_item)
        self._refresh_vod_summary()
        if hasattr(self, "vod_load_more_btn"):
            self.vod_load_more_btn.setVisible(bool(next_cursor))
            self.vod_load_more_btn.setEnabled(bool(next_cursor))
            self.vod_load_more_btn.setText("Load More VODs")
        total = len(self._vod_list)
        self._log(f"[VOD] Loaded {len(new_vods)} more — {total} total")
        self._set_status(f"{total} VOD(s) loaded. {len(new_vods)} new from this page.", "success")

    def _on_vod_page_error(self, err):
        self._log(f"[VOD] Pagination error: {err}")
        self._set_status(f"Failed to load more VODs: {err}", "error")
        if hasattr(self, "vod_load_more_btn"):
            self.vod_load_more_btn.setEnabled(True)
            self.vod_load_more_btn.setText("Load More VODs")

    def _on_vod_download_all(self):
        checked = [self._vod_list[i] for i, cb in enumerate(self._vod_checks) if cb.isChecked()]
        if not checked:
            self._log("No VODs checked.")
            self._set_status("Select at least one VOD before starting a batch download.", "warning")
            return

        self._cancel_batch_fetch_worker()
        self._batch_vods = checked
        self._batch_idx = 0
        self._batch_total = len(checked)
        self._batch_failed_count = 0
        self._batch_active = True
        self._log(f"\n{'=' * 50}")
        self._log(f"Batch downloading {self._batch_total} VOD(s)")
        self._log(f"{'=' * 50}")
        self.download_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self.vod_dl_all_btn.setEnabled(False)
        self.vod_load_btn.setEnabled(False)
        self.stop_btn.setVisible(True)
        self._set_status(f"Batch download queued for {self._batch_total} VOD(s).", "working")
        self._batch_next()

    def _batch_next(self):
        if not self._batch_active:
            return
        if self._batch_idx >= self._batch_total:
            self._batch_done()
            return
        vod = self._batch_vods[self._batch_idx]
        self._log(f"\n--- VOD {self._batch_idx + 1}/{self._batch_total}: {vod.title} ---")
        self._set_status(
            f"Preparing VOD {self._batch_idx + 1} of {self._batch_total}: {vod.title}",
            "working",
        )

        worker = FetchWorker(
            self.url_input.text().strip(),
            vod_source=vod.source,
            vod_platform=vod.platform,
            vod_title=vod.title,
            vod_channel=vod.channel,
        )
        worker.log.connect(self._log)
        worker.finished.connect(self._batch_on_fetched)
        worker.error.connect(self._batch_on_fetch_error)
        self._batch_fetch_worker = worker
        worker.start()

    def _batch_on_fetched(self, info):
        self._batch_fetch_worker = None
        if not self._batch_active or self._batch_idx >= self._batch_total:
            return
        vod = self._batch_vods[self._batch_idx]

        # Pick quality (prefer 1080p/source)
        playlist_url = None
        fmt_type = "hls"
        audio_url = ""
        ytdlp_source = ""
        ytdlp_format = ""
        selected_q = None
        for q in info.qualities:
            if "1080" in q.name or "source" in q.name.lower():
                selected_q = q
                break
        if not selected_q and info.qualities:
            selected_q = info.qualities[0]
        if selected_q:
            playlist_url = selected_q.url
            fmt_type = selected_q.format_type
            audio_url = selected_q.audio_url
            ytdlp_source = selected_q.ytdlp_source
            ytdlp_format = selected_q.ytdlp_format

        if not playlist_url and not ytdlp_source:
            self._log(f"[ERROR] No playback URL for {vod.title}")
            self._batch_idx += 1
            self._batch_next()
            return

        total_secs = info.total_secs
        seg_secs = self._get_segment_secs()

        # Render folder + filename from templates
        ctx = _build_template_context(info, vod)
        folder_parts = _render_template(
            self._folder_template, ctx
        ) or [_safe_filename(vod.title) or f"{info.platform}_download"]
        file_parts = _render_template(self._file_template, ctx)
        title_safe = file_parts[-1] if file_parts else (
            _safe_filename(info.title) or _safe_filename(vod.title) or f"{info.platform}_download"
        )

        # ytdlp_direct and mp4 formats download monolithically — no segment splitting
        if fmt_type in ("ytdlp_direct", "mp4") or seg_secs == 0 or total_secs <= 0 or total_secs <= seg_secs:
            segments = [(0, title_safe, 0, int(total_secs) if total_secs > 0 else 0)]
        else:
            segments = []
            pos, idx = 0, 0
            while pos < total_secs:
                end = min(pos + seg_secs, total_secs)
                segments.append((idx, f"{title_safe}_part{idx + 1:02d}", pos, int(end - pos)))
                pos = end
                idx += 1

        out_dir = os.path.join(self.output_input.text().strip(), *folder_parts)
        os.makedirs(out_dir, exist_ok=True)

        self._build_segments(total_secs)
        self.stream_info = info

        self._total_segments = len(segments)
        self._completed_segments = 0
        self._download_had_errors = False
        self.overall_progress.setVisible(True)
        self.overall_progress.setValue(0)
        self.overall_progress.setMaximum(len(segments))
        self._refresh_download_summary()
        self._set_status(
            f"Downloading VOD {self._batch_idx + 1} of {self._batch_total}.",
            "working",
        )
        self._set_download_context(
            out_dir=out_dir,
            quality_name=selected_q.name if selected_q else "batch",
            history_url=vod.source or self.url_input.text().strip(),
            info=info,
        )

        worker = DownloadWorker(playlist_url or "", segments, out_dir, format_type=fmt_type)
        worker.audio_url = audio_url
        worker.ytdlp_source = ytdlp_source
        worker.ytdlp_format = ytdlp_format
        worker.cookies_browser = YtDlpExtractor.cookies_browser
        worker.rate_limit = YtDlpExtractor.rate_limit
        worker.proxy = YtDlpExtractor.proxy
        worker.download_subs = YtDlpExtractor.download_subs
        worker.sponsorblock = YtDlpExtractor.sponsorblock
        worker.parallel_connections = self._parallel_connections
        worker.progress.connect(self._on_dl_progress)
        worker.segment_done.connect(self._on_segment_done)
        worker.error.connect(self._on_dl_error)
        worker.log.connect(self._log)
        worker.all_done.connect(self._batch_vod_done)
        self.download_worker = worker
        self._attach_resume_to_worker(worker)
        worker.start()

    def _batch_on_fetch_error(self, err):
        self._batch_fetch_worker = None
        if not self._batch_active or self._batch_idx >= self._batch_total:
            return
        self._log(f"[ERROR] {err}")
        self._set_status(f"Batch fetch error: {err}", "error")
        if hasattr(self, "_batch_failed_count"):
            self._batch_failed_count += 1
        self._batch_idx += 1
        self._batch_next()

    def _batch_vod_done(self):
        if not self._batch_active or self._batch_idx >= self._batch_total:
            return
        vod = self._batch_vods[self._batch_idx]
        if self._download_had_errors:
            self._log(f"[WARN] {vod.title} finished with errors")
            if hasattr(self, "_batch_failed_count"):
                self._batch_failed_count += 1
        else:
            self._log(f"[DONE] {vod.title}")
            self._save_metadata(
                self._active_output_dir,
                self._active_quality_name or "batch",
                history_url=self._active_history_url or vod.source,
                info=self._active_stream_info or self.stream_info,
            )
        self._batch_idx += 1
        self._batch_next()

    def _batch_done(self):
        self._batch_active = False
        self._batch_fetch_worker = None
        failed = getattr(self, "_batch_failed_count", 0)
        done = self._batch_total - failed
        self._log(f"\n{'=' * 50}")
        if failed:
            self._log(
                f"Batch finished with {failed} failed VOD(s). Completed {done} of {self._batch_total}."
            )
        else:
            self._log(f"Batch complete! {self._batch_total} VOD(s) downloaded.")
        self._log(f"{'=' * 50}")
        if failed:
            self._set_status(
                f"Batch finished with {failed} failed VOD(s). Completed {done} of {self._batch_total}.",
                "warning",
            )
        else:
            self._set_status(f"Batch complete. Downloaded {self._batch_total} VOD(s).", "success")
            self._notify("StreamKeep — Batch complete", f"Downloaded {self._batch_total} VOD(s)")
            self._send_webhook("batch complete", f"{self._batch_total} VODs",
                               "Batch download finished")
        self.download_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.vod_dl_all_btn.setEnabled(True)
        self.vod_load_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
        self.open_folder_btn.setVisible(True)
        self._persist_config()

    # ── Segment Management ────────────────────────────────────────────

    def _get_segment_secs(self):
        idx = self.segment_combo.currentIndex()
        return self._segment_options[idx][1]

    @staticmethod
    def _parse_crop_secs(text):
        """Parse a HH:MM:SS, MM:SS, or plain seconds string into total
        seconds. Returns 0 if the text is empty or invalid."""
        text = (text or "").strip()
        if not text:
            return 0
        parts = text.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            return int(float(text))
        except (ValueError, IndexError):
            return 0

    @staticmethod
    def _fmt_crop_time(secs):
        """Format seconds as HH:MM:SS for log output."""
        s = int(secs)
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"

    def _is_audio_only(self):
        """Detect if the current stream is audio-only based on its qualities."""
        if not self.stream_info:
            return False
        if not self.stream_info.qualities:
            return False
        return all(
            (q.resolution or "").lower() == "audio" or "audio" in (q.name or "").lower()
            for q in self.stream_info.qualities
        )

    def _content_label(self, idx, total_segments, seg_secs, total_secs):
        """Generate a content-aware segment label."""
        is_audio = self._is_audio_only()
        kind = "Audio" if is_audio else "Video"
        if total_secs <= 0:
            return "Live Capture" if not is_audio else "Live Audio"

        if total_segments == 1:
            # Single segment — use the content type
            if total_secs < 60:
                return f"{kind} ({int(total_secs)}s)"
            elif total_secs < 3600:
                return f"{kind} ({int(total_secs // 60)}m)"
            else:
                return f"{kind} ({_fmt_duration(total_secs)})"

        # Multi-segment naming based on segment length
        if seg_secs >= 3600:
            return f"Hour {idx + 1}"
        elif seg_secs >= 60:
            mins = seg_secs // 60
            return f"Part {idx + 1} ({mins}m)"
        else:
            return f"Part {idx + 1}"

    def _build_segments(self, total_secs):
        if total_secs <= 0:
            segments = [(0, 0)]
            seg_secs = 0
        else:
            seg_secs = self._get_segment_secs()

            # Auto-collapse: if content is shorter than segment length, use one segment
            if seg_secs == 0 or total_secs <= seg_secs:
                segments = [(0, total_secs)]
            else:
                segments = []
                pos = 0
                while pos < total_secs:
                    end = min(pos + seg_secs, total_secs)
                    segments.append((pos, end))
                    pos = end

        self.table.setRowCount(len(segments))
        self._segment_checks = []
        self._segment_progress = []

        for i, (start, end) in enumerate(segments):
            duration = end - start
            cb = QCheckBox()
            cb.setChecked(True)
            cb.stateChanged.connect(lambda _state, self=self: self._refresh_download_summary())
            cb_w = QWidget()
            cb_l = QHBoxLayout(cb_w)
            cb_l.addWidget(cb)
            cb_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_l.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(i, 0, cb_w)
            self._segment_checks.append(cb)

            label = self._content_label(i, len(segments), seg_secs, total_secs)
            item = QTableWidgetItem(label)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 1, item)

            if total_secs <= 0:
                range_text = "Starts now - runs until stopped"
            else:
                s_str = f"{int(start//3600):02d}:{int((start%3600)//60):02d}:{int(start%60):02d}"
                e_str = f"{int(end//3600):02d}:{int((end%3600)//60):02d}:{int(end%60):02d}"
                range_text = f"{s_str} - {e_str}  ({int(duration//60)}m {int(duration%60)}s)"
            t_item = QTableWidgetItem(range_text)
            t_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 2, t_item)

            pbar = QProgressBar()
            if total_secs <= 0:
                pbar.setMaximum(0)
            else:
                pbar.setValue(0)
            self.table.setCellWidget(i, 3, pbar)
            self._segment_progress.append(pbar)

            # Estimated size: bandwidth (bits/sec) × duration / 8 = bytes
            est = self._estimate_size_bytes(duration)
            sz_text = f"~{_fmt_size(est)}" if est > 0 else "\u2014"
            sz = QTableWidgetItem(sz_text)
            sz.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            sz.setForeground(QColor(CAT["muted"]))
            self.table.setItem(i, 4, sz)
        self._refresh_download_summary()

    def _estimate_size_bytes(self, duration_secs):
        """Return estimated file size in bytes using the selected quality's bandwidth."""
        if duration_secs <= 0:
            return 0
        q = self.quality_combo.currentData() if hasattr(self, "quality_combo") else None
        if not q or not getattr(q, "bandwidth", 0):
            return 0
        # bandwidth is bits/sec; convert to bytes
        return int(q.bandwidth * duration_secs / 8)

    def _on_select_all(self, state):
        checked = state == Qt.CheckState.Checked.value
        for cb in self._segment_checks:
            cb.setChecked(checked)
        self._refresh_download_summary()

    def _on_segment_length_changed(self, idx):
        if self.stream_info and self.stream_info.total_secs > 0:
            self._build_segments(self.stream_info.total_secs)
        else:
            self._refresh_download_summary()

    def _on_quality_changed(self, idx):
        """Rebuild size estimates in the segment table when quality changes."""
        if not self.stream_info or not hasattr(self, "_segment_progress"):
            return
        total_secs = self.stream_info.total_secs
        if total_secs <= 0:
            return
        seg_secs = self._get_segment_secs()
        if seg_secs == 0 or total_secs <= seg_secs:
            durations = [total_secs]
        else:
            durations = []
            pos = 0
            while pos < total_secs:
                end = min(pos + seg_secs, total_secs)
                durations.append(end - pos)
                pos = end
        for i, d in enumerate(durations):
            if i >= self.table.rowCount():
                break
            est = self._estimate_size_bytes(d)
            sz_text = f"~{_fmt_size(est)}" if est > 0 else "\u2014"
            sz = QTableWidgetItem(sz_text)
            sz.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            sz.setForeground(QColor(CAT["muted"]))
            self.table.setItem(i, 4, sz)

    def _on_browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Folder", self.output_input.text())
        if d:
            self.output_input.setText(d)

    # ── Download ──────────────────────────────────────────────────────

    def _on_download(self):
        if not self.stream_info:
            return False
        # Disk-space preflight — catches "no more room on device" before
        # ffmpeg runs for three hours and exits with a muxing error. Only
        # warns when we have a meaningful estimate; lives / unknown-duration
        # streams skip the check.
        if not self._preflight_disk_space():
            return False
        total_secs = self.stream_info.total_secs
        is_live_capture = bool(self.stream_info.is_live or total_secs <= 0)

        q_data = self.quality_combo.currentData()
        audio_url = ""
        ytdlp_source = ""
        ytdlp_format = ""
        if q_data:
            playlist_url = q_data.url
            fmt_type = q_data.format_type
            audio_url = q_data.audio_url
            ytdlp_source = q_data.ytdlp_source
            ytdlp_format = q_data.ytdlp_format
        elif self.stream_info.url:
            playlist_url = self.stream_info.url
            fmt_type = "hls"
        else:
            self._log("[ERROR] No quality selected")
            self._set_status("Pick a quality before starting the download.", "warning")
            return False

        # Per-download overrides (F18)
        from .tabs.download import get_adv_overrides, _reset_adv_overrides
        _dl_overrides = get_adv_overrides(self)

        # Render filename + folder from templates (templates can produce
        # nested paths like "{channel}/{date} - {title}")
        ctx = _build_template_context(self.stream_info)
        _folder_tpl = _dl_overrides.get("folder_template") or self._folder_template
        _file_tpl = _dl_overrides.get("file_template") or self._file_template
        folder_parts = _render_template(_folder_tpl, ctx)
        file_parts = _render_template(_file_tpl, ctx)
        title_safe = file_parts[-1] if file_parts else (
            _safe_filename(self.stream_info.title)
            or f"{self.stream_info.platform}_download"
        )

        # Time-range crop (F21) — parse optional start/end bounds
        crop_start = self._parse_crop_secs(
            self.crop_start_input.text() if hasattr(self, "crop_start_input") else ""
        )
        crop_end = self._parse_crop_secs(
            self.crop_end_input.text() if hasattr(self, "crop_end_input") else ""
        )
        if crop_end and crop_start and crop_end <= crop_start:
            self._set_status("Time range end must be after start.", "warning")
            return False

        seg_secs = self._get_segment_secs()
        single_segment = (is_live_capture or fmt_type in ("mp4", "ytdlp_direct")
                          or seg_secs == 0 or total_secs <= seg_secs)
        segments = []
        for i, cb in enumerate(self._segment_checks):
            if cb.isChecked():
                if single_segment:
                    seg_start = crop_start or 0
                    seg_dur = (crop_end or (0 if is_live_capture else int(total_secs))) - seg_start
                    segments.append((0, title_safe, seg_start, max(0, seg_dur)))
                    break
                else:
                    start = i * seg_secs
                    end = min((i + 1) * seg_secs, total_secs)
                    # Skip segments entirely outside the crop window
                    if crop_end and start >= crop_end:
                        continue
                    if crop_start and end <= crop_start:
                        continue
                    # Clamp segment bounds to the crop window
                    if crop_start and start < crop_start:
                        start = crop_start
                    if crop_end and end > crop_end:
                        end = crop_end
                    label = f"{title_safe}_part{i + 1:02d}"
                    segments.append((i, label, start, int(end - start)))

        if not segments:
            self._log("No segments selected.")
            self._set_status("Select at least one segment before downloading.", "warning")
            return False

        if crop_start or crop_end:
            self._log(f"[CROP] Time range: {self._fmt_crop_time(crop_start)} → {self._fmt_crop_time(crop_end or total_secs)}")

        # For non-channel content, user's output box is the base; folder template
        # adds a subfolder. For channel content the template already has
        # {channel} in it, so joining still works.
        base_out = self.output_input.text().strip()
        if folder_parts:
            out_dir = os.path.join(base_out, *folder_parts)
        else:
            out_dir = base_out
        os.makedirs(out_dir, exist_ok=True)

        self._log(f"\n{'=' * 50}")
        self._log(f"Downloading {len(segments)} segments to {out_dir}")
        self._log(f"Quality: {self.quality_combo.currentText()}")
        self._log(f"{'=' * 50}")

        self._total_segments = len(segments)
        self._completed_segments = 0
        self._download_had_errors = False
        self._init_speed_tracking()
        self.download_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self.stop_btn.setVisible(True)
        self.open_folder_btn.setVisible(False)
        self.overall_progress.setVisible(True)
        self.overall_progress.setValue(0)
        self.overall_progress.setMaximum(len(segments))
        if is_live_capture:
            self._set_status(
                f"Live capture started. Recording to {_path_label(out_dir)} until you stop it.",
                "working",
            )
        else:
            self._set_status(
                f"Downloading 0 of {len(segments)} segment(s) to {_path_label(out_dir)}.",
                "working",
            )

        self._set_download_context(
            out_dir=out_dir,
            quality_name=self.quality_combo.currentText(),
            history_url=self._resolve_history_url(),
            info=self.stream_info,
        )
        self.download_worker = DownloadWorker(playlist_url or "", segments, out_dir, format_type=fmt_type)
        self.download_worker.audio_url = audio_url
        self.download_worker.ytdlp_source = ytdlp_source
        self.download_worker.ytdlp_format = ytdlp_format
        self.download_worker.cookies_browser = YtDlpExtractor.cookies_browser
        self.download_worker.rate_limit = _dl_overrides.get("rate_limit") or YtDlpExtractor.rate_limit
        self.download_worker.proxy = YtDlpExtractor.proxy
        self.download_worker.download_subs = YtDlpExtractor.download_subs
        self.download_worker.sponsorblock = YtDlpExtractor.sponsorblock
        self.download_worker.parallel_connections = _dl_overrides.get("parallel_connections") or self._parallel_connections
        # Pass time-range crop to yt-dlp via --download-sections (F21)
        if fmt_type == "ytdlp_direct" and (crop_start or crop_end):
            cs = self._fmt_crop_time(crop_start) if crop_start else "0:00:00"
            ce = self._fmt_crop_time(crop_end) if crop_end else ""
            self.download_worker.download_sections = f"*{cs}-{ce}" if ce else f"*{cs}-"
        if audio_url:
            self._log("Audio merge: enabled (video-only format detected)")
        if fmt_type == "ytdlp_direct":
            self._log("Download mode: yt-dlp direct (handles URL refresh + format merge)")
        self.download_worker.progress.connect(self._on_dl_progress)
        self.download_worker.segment_done.connect(self._on_segment_done)
        self.download_worker.error.connect(self._on_dl_error)
        self.download_worker.log.connect(self._log)
        self.download_worker.all_done.connect(self._on_all_done)
        self._attach_resume_to_worker(self.download_worker)
        # Store overrides for postprocess snapshot merge (F18)
        self._dl_overrides = _dl_overrides
        if _dl_overrides:
            self._log(f"[OVERRIDE] Per-download overrides active: {', '.join(_dl_overrides.keys())}")
        _reset_adv_overrides(self)
        self.download_worker.start()
        return True

    def _on_dl_progress(self, idx, pct, status):
        if idx < len(self._segment_progress):
            if self.stream_info and (self.stream_info.is_live or self.stream_info.total_secs <= 0):
                self._segment_progress[idx].setMaximum(0)
            else:
                self._segment_progress[idx].setMaximum(100)
                self._segment_progress[idx].setValue(pct)
        if hasattr(self, "_total_segments") and self._total_segments:
            self._set_status(
                f"Downloading {self._completed_segments}/{self._total_segments}. Segment {idx + 1}: {status}",
                "working",
            )
        # Parse speed from the status text (F16 speed dashboard)
        self._update_speed_from_status(status)

    # ── Speed & ETA Tracking (F16) ──────────────────────────────────

    def _init_speed_tracking(self):
        """Reset speed tracking state at the start of a download."""
        self._speed_samples = deque(maxlen=60)  # (timestamp, speed_bytes_per_sec)
        self._dl_start_time = time.monotonic()
        if hasattr(self, "download_speed_value"):
            self.download_speed_value.setText("—")
            self.download_speed_sub.setText("Waiting for data")
        if hasattr(self, "download_eta_value"):
            self.download_eta_value.setText("—")
            self.download_eta_sub.setText("Estimating...")

    def _update_speed_from_status(self, status):
        """Parse speed info from the progress status string and update the
        speed/ETA dashboard cards."""
        if not hasattr(self, "download_speed_value"):
            return
        # Try to extract a speed like "12.4MB/s" or "3.2MiB/s" from the status
        m = re.search(r'([\d.]+)\s*(B|KB|KiB|MB|MiB|GB|GiB)/s', status, re.IGNORECASE)
        if not m:
            return
        val = float(m.group(1))
        unit = m.group(2).upper().replace("I", "")
        multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
        bps = val * multipliers.get(unit, 1)
        now = time.monotonic()
        self._speed_samples.append((now, bps))
        # Compute 5-second smoothed average
        cutoff = now - 5.0
        recent = [(t, s) for t, s in self._speed_samples if t >= cutoff]
        if recent:
            avg_speed = sum(s for _, s in recent) / len(recent)
        else:
            avg_speed = bps
        # Display speed
        self.download_speed_value.setText(_fmt_size(int(avg_speed)) + "/s")
        self.download_speed_sub.setText(f"5-sec avg ({len(recent)} samples)")
        # Calculate ETA from remaining segments
        total = getattr(self, "_total_segments", 0)
        done = getattr(self, "_completed_segments", 0)
        if total > 0 and done < total and avg_speed > 0:
            # Estimate bytes remaining from elapsed speed and segment ratio
            elapsed = now - getattr(self, "_dl_start_time", now)
            if elapsed > 0 and done > 0:
                est_total_time = elapsed * total / done
                remaining = est_total_time - elapsed
                if remaining > 0:
                    self.download_eta_value.setText(_fmt_duration(remaining))
                    self.download_eta_sub.setText(
                        f"{done}/{total} segments done"
                    )
                    return
            self.download_eta_value.setText("Estimating...")
        elif total > 0 and done >= total:
            self.download_eta_value.setText("Done")
            self.download_eta_sub.setText("Finalizing...")

    def _reset_speed_dashboard(self):
        """Clear speed/ETA cards after download completes."""
        if hasattr(self, "download_speed_value"):
            self.download_speed_value.setText("—")
            self.download_speed_sub.setText("Starts during download")
        if hasattr(self, "download_eta_value"):
            self.download_eta_value.setText("—")
            self.download_eta_sub.setText("Estimated time remaining")

    def _on_segment_done(self, idx, size_str):
        if idx < len(self._segment_progress):
            self._segment_progress[idx].setMaximum(100)
            self._segment_progress[idx].setValue(100)
            self._segment_progress[idx].setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {CAT['green']}; border-radius: 6px; }}"
            )
        size_item = QTableWidgetItem(size_str)
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(idx, 4, size_item)
        self._completed_segments += 1
        self.overall_progress.setValue(self._completed_segments)
        self._set_status(
            f"Downloaded {self._completed_segments} of {self._total_segments} segment(s).",
            "working",
        )

    def _on_dl_error(self, idx, err):
        self._download_had_errors = True
        if idx < len(self._segment_progress):
            self._segment_progress[idx].setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {CAT['red']}; border-radius: 6px; }}"
            )
        fail_item = QTableWidgetItem("FAILED")
        fail_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(idx, 4, fail_item)
        self._set_status(f"Segment {idx + 1} failed: {err}", "error")

    def _on_all_done(self):
        self.download_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
        self.open_folder_btn.setVisible(True)
        if hasattr(self, "trim_btn"):
            self.trim_btn.setVisible(True)
        active_info_n = self._active_stream_info or self.stream_info
        title_n = (active_info_n.title if active_info_n and active_info_n.title else "Download")[:80]
        self._notify_center(
            f"Download complete: {title_n}",
            "success" if not self._download_had_errors else "warning",
        )
        active_info = self._active_stream_info or self.stream_info
        out_dir = self._active_output_dir or self.output_input.text().strip()
        q_name = self._active_quality_name or (
            self.quality_combo.currentText() if self.quality_combo.count() else ""
        )
        title = active_info.title if active_info and active_info.title else "Download"

        self._log(f"\n{'=' * 50}")
        if self._download_had_errors:
            self._log("Download finished with one or more failed segments.")
            self._log(f"{'=' * 50}")
            self._set_status(
                "Download finished with one or more failed segments. Review the log before retrying.",
                "warning",
            )
            if self._queue_active_item is not None:
                note = f"{self._completed_segments}/{self._total_segments} segments completed"
                self._release_queue_item("failed", note)
        else:
            self._log("All downloads complete!")
            self._log(f"{'=' * 50}")
            if active_info and (active_info.is_live or active_info.total_secs <= 0):
                self._set_status("Live capture finished and was saved to the selected folder.", "success")
                self._notify("StreamKeep — Capture finished", title[:80])
                self._send_webhook("capture finished", title,
                                   f"Segments: {self._completed_segments}")
            else:
                self._set_status(
                    f"Download complete. Saved {self._completed_segments} segment(s) to the selected folder.",
                    "success",
                )
                self._notify("StreamKeep — Download complete", title[:80])
                self._send_webhook("download complete", title,
                                   f"Segments: {self._completed_segments}")
                self._fire_hook(
                    "download_complete", title=title,
                    path=out_dir,
                    platform=active_info.platform if active_info else "")
            self._save_metadata(
                out_dir,
                q_name,
                history_url=self._active_history_url,
                info=active_info,
            )
            self._media_server_import(out_dir, active_info)
            if self._queue_active_item is not None:
                self._release_queue_item("done")
        self._persist_config()
        self._run_lifecycle_cleanup()
        self._update_tray_badge()
        self._reset_speed_dashboard()
        self._start_next_background_job()

    def _on_stop(self):
        worker = self.download_worker
        resume_background_jobs = bool(
            self._queue_active_item is not None
            or self._autorecord_workers
            or self._autorecord_resolvers
            or self._pending_auto_records
        )
        live_capture = bool(
            worker and any(len(seg) >= 4 and seg[3] <= 0 for seg in getattr(worker, "segments", []))
        )
        # Halt any in-progress batch by marking it done
        if hasattr(self, '_batch_vods') and hasattr(self, '_batch_total'):
            self._batch_active = False
            self._batch_idx = self._batch_total
            self._cancel_batch_fetch_worker()
        if self.download_worker is not None:
            try:
                self.download_worker.cancel()
                if not self.download_worker.wait(5000):
                    self.download_worker.terminate()
                    self.download_worker.wait(1000)
            except Exception:
                pass
            self.download_worker = None
        # Also stop any parallel auto-records. The stop button is a global
        # "halt everything the user is actively watching" — parallel lives
        # included. (Use the Monitor tab's per-row Stop+Remove for selective
        # stops.)
        for ch_id in list(self._autorecord_workers.keys()):
            w = self._autorecord_workers.get(ch_id)
            if w is not None and w.isRunning():
                try:
                    w.cancel()
                    if not w.wait(3000):
                        w.terminate()
                        w.wait(500)
                except Exception:
                    pass
        self._autorecord_workers.clear()
        self._autorecord_contexts.clear()
        for ch_id in list(self._autorecord_resolvers.keys()):
            w = self._autorecord_resolvers.get(ch_id)
            if w is not None and w.isRunning():
                try:
                    w.requestInterruption()
                    w.wait(1500)
                except Exception:
                    pass
        self._autorecord_resolvers.clear()
        # Stop any paired live-chat captures.
        for ch_id in list(self._chat_workers.keys()):
            w = self._chat_workers.get(ch_id)
            if w is not None and w.isRunning():
                try:
                    w.cancel()
                    w.wait(2000)
                except Exception:
                    pass
        self._chat_workers.clear()
        # Clear any green/red chunk overrides left on segment bars so the
        # next download starts from a neutral style instead of inheriting
        # the previous run's success/fail colors.
        for pbar in getattr(self, "_segment_progress", []):
            try:
                pbar.setStyleSheet("")
                pbar.setValue(0)
            except Exception:
                pass
        self.download_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
        self.overall_progress.setVisible(False)
        if hasattr(self, 'vod_dl_all_btn'):
            self.vod_dl_all_btn.setEnabled(True)
            self.vod_load_btn.setEnabled(True)
        for entry in self.monitor.entries:
            entry.is_recording = False
        self._active_auto_record_channel = ""
        self._refresh_monitor_summary()
        self._log("[CANCELLED] Download stopped by user.")
        if self._queue_active_item is not None:
            self._release_queue_item("cancelled", "Stopped by user")
        if live_capture:
            has_media = self._output_contains_media(self._active_output_dir)
            self.open_folder_btn.setVisible(has_media)
            if has_media and self._active_output_dir and self._active_stream_info:
                self._save_metadata(
                    self._active_output_dir,
                    self._active_quality_name,
                    history_url=self._active_history_url,
                    info=self._active_stream_info,
                )
                self._set_status("Recording stopped. Any captured portion was kept on disk.", "warning")
            else:
                self._set_status("Recording stopped before any media was saved.", "warning")
        else:
            self._set_status("Download cancelled. You can adjust the selection and try again.", "warning")
        if resume_background_jobs:
            self._start_next_background_job()

    def _on_open_folder(self):
        out_dir = self._active_output_dir or self.output_input.text().strip()
        if os.path.isdir(out_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))

    # ── Queue context menu: recurrence editor ────────────────────────

    def _on_queue_context_menu(self, pos):
        if not hasattr(self, "queue_table"):
            return
        idx = self.queue_table.indexAt(pos)
        if not idx.isValid():
            return
        row = idx.row()
        if not (0 <= row < len(self._download_queue)):
            return
        item = self._download_queue[row]
        menu = QMenu(self)
        current = (item.get("recurrence") or "").strip().lower() or "(one-shot)"
        header = menu.addAction(f"Recurrence: {current}")
        header.setEnabled(False)
        menu.addSeparator()
        one_shot = menu.addAction("One-shot (no recurrence)")
        daily = menu.addAction("Daily")
        weekly = menu.addAction("Weekly")
        custom = menu.addAction("Weekday mask... (mon,tue,fri)")
        chosen = menu.exec(self.queue_table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        new_rec = ""
        if chosen == one_shot:
            new_rec = ""
        elif chosen == daily:
            new_rec = "daily"
        elif chosen == weekly:
            new_rec = "weekly"
        elif chosen == custom:
            valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}

            def _validate_mask(value):
                tokens = [tok.strip().lower() for tok in (value or "").split(",") if tok.strip()]
                if not tokens:
                    return False, "Enter at least one weekday code."
                invalid = [tok for tok in tokens if tok not in valid_days]
                if invalid:
                    return False, "Use day codes like mon,tue,wed,thu,fri,sat,sun."
                return True, ""

            text, ok = ask_premium_text_input(
                self,
                title="Repeat on specific weekdays",
                body="Use a weekday mask when a queued item should recur only on selected days.",
                eyebrow="QUEUE",
                badge_text="Recurrence",
                tone="info",
                summary_title="Comma-separated short codes are supported.",
                summary_body="Example: mon,wed,fri. Use one-shot or weekly if the item should not use a custom mask.",
                field_label="Weekday mask",
                field_hint="Supported values: mon, tue, wed, thu, fri, sat, sun.",
                text=item.get("recurrence", "") or "mon,wed,fri",
                primary_label="Save recurrence",
                secondary_label="Cancel",
                validator=_validate_mask,
            )
            if not ok:
                return
            tokens = [tok.strip().lower() for tok in text.split(",") if tok.strip()]
            new_rec = ",".join(tokens)
        item["recurrence"] = new_rec
        if new_rec:
            item["note"] = f"recurring ({new_rec})"
        else:
            item["note"] = ""
        self._queue_status_changed()
        self._set_status(
            f"Queue item recurrence set to '{new_rec or 'one-shot'}'.",
            "success",
        )

    # ── Monitor tab: drag-reorder + bulk context menu ────────────────

    def _on_monitor_rows_moved(self, _parent, start, end, _dest, dest_row):
        """Qt-level rowsMoved; sync `self.monitor.entries` to the new
        order so persistence + polling match what the user sees."""
        with self.monitor._entries_lock:
            entries = self.monitor.entries
            if not (0 <= start <= end < len(entries)):
                return
            moved = entries[start:end + 1]
            del entries[start:end + 1]
            # Adjust dest if the removal shifted it left.
            insert_at = dest_row if dest_row <= start else dest_row - len(moved)
            insert_at = max(0, min(insert_at, len(entries)))
            for i, m in enumerate(moved):
                entries.insert(insert_at + i, m)
        self._persist_config()

    def _on_monitor_context_menu(self, pos):
        if not hasattr(self, "monitor_table"):
            return
        sel_rows = sorted({idx.row() for idx in self.monitor_table.selectionModel().selectedRows()})
        if not sel_rows:
            idx = self.monitor_table.indexAt(pos)
            if idx.isValid():
                sel_rows = [idx.row()]
            else:
                return
        menu = QMenu(self)
        header = menu.addAction(f"{len(sel_rows)} channel(s) selected")
        header.setEnabled(False)
        menu.addSeparator()
        act_edit = menu.addAction("Edit profile...") if len(sel_rows) == 1 else None
        act_enable_ar = menu.addAction("Enable auto-record")
        act_disable_ar = menu.addAction("Disable auto-record")
        act_set_window = menu.addAction("Set schedule window for all selected...")
        menu.addSeparator()
        act_remove = menu.addAction("Remove selected")
        chosen = menu.exec(self.monitor_table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        entries = self.monitor.entries
        targets = [entries[r] for r in sel_rows if 0 <= r < len(entries)]
        if chosen == act_edit and sel_rows:
            self._on_monitor_edit(sel_rows[0])
            return
        if chosen == act_enable_ar:
            for e in targets:
                e.auto_record = True
            self._log(f"[MONITOR] Enabled auto-record on {len(targets)} channel(s).")
        elif chosen == act_disable_ar:
            for e in targets:
                e.auto_record = False
            self._log(f"[MONITOR] Disabled auto-record on {len(targets)} channel(s).")
        elif chosen == act_set_window:
            def _validate_window(value):
                text = (value or "").strip()
                if not text:
                    return True, ""
                if not re.fullmatch(r"\d{2}:\d{2}-\d{2}:\d{2}", text):
                    return False, "Use HH:MM-HH:MM, for example 20:00-23:00."
                start, end = text.split("-", 1)
                for label, raw in (("start", start), ("end", end)):
                    try:
                        hour, minute = [int(part) for part in raw.split(":", 1)]
                    except (TypeError, ValueError):
                        return False, f"The {label} time is not valid."
                    if not (0 <= hour <= 23 and 0 <= minute <= 59):
                        return False, f"The {label} time must stay within 00:00-23:59."
                return True, ""

            text, ok = ask_premium_text_input(
                self,
                title="Set a shared schedule window",
                body="Limit the selected channels to a specific recording window in your local time zone.",
                eyebrow="MONITOR",
                badge_text="Schedule",
                tone="info",
                summary_title=f"Updating {len(targets)} selected channel(s).",
                summary_body="Leave the field blank to clear the window for every selected profile.",
                field_label="Schedule window",
                field_hint="Format: HH:MM-HH:MM. Example: 20:00-23:00.",
                text="20:00-23:00",
                primary_label="Apply window",
                secondary_label="Cancel",
                validator=_validate_window,
            )
            if not ok:
                return
            text = text.strip()
            if text and "-" in text:
                try:
                    start, end = text.split("-", 1)
                    for e in targets:
                        e.schedule_start_hhmm = start.strip()
                        e.schedule_end_hhmm = end.strip()
                except Exception:
                    self._set_status("Could not parse window.", "error")
                    return
            else:
                for e in targets:
                    e.schedule_start_hhmm = ""
                    e.schedule_end_hhmm = ""
            self._log(f"[MONITOR] Updated schedule window for {len(targets)} channel(s).")
        elif chosen == act_remove:
            # Remove from the bottom up so indices stay valid.
            for r in reversed(sel_rows):
                if 0 <= r < len(entries):
                    self.monitor.remove_channel(r)
        self._refresh_monitor_table()
        self._persist_config()

    def _on_theme_changed(self, _idx):
        """Apply theme switch instantly (F20)."""
        from ..theme import apply_theme
        from PyQt6.QtWidgets import QApplication
        name = self.theme_combo.currentData() or "dark"
        self._config["theme"] = name
        apply_theme(name, app=QApplication.instance())
        if hasattr(self, "settings_theme_value"):
            theme_display = {"dark": "Dark", "light": "Light", "system": "System"}.get(
                name, "Dark"
            )
            self.settings_theme_value.setText(theme_display)
            self.settings_theme_sub.setText("Catppuccin-based desktop theme")
        if hasattr(self, "_stack"):
            self._switch_tab(self._stack.currentIndex())
        if hasattr(self, "status_label"):
            pill_to_tone = {
                "Standby": "idle",
                "Working": "working",
                "Finalizing": "processing",
                "Ready": "success",
                "Alert": "warning",
                "Error": "error",
            }
            current_tone = pill_to_tone.get(
                self.status_pill.text() if hasattr(self, "status_pill") else "Standby",
                "idle",
            )
            self._set_status(self.status_label.text() or "Theme updated.", current_tone)
        self._refresh_notif_badge()
        self._persist_config()

    def _on_companion_toggled(self, checked):
        """Settings toggle — start or stop the companion server in-place."""
        self._config["companion_server_enabled"] = bool(checked)
        if hasattr(self, "companion_lan_check"):
            self._config["companion_bind_lan"] = bool(self.companion_lan_check.isChecked())
        self._persist_config()
        self._maybe_start_companion_server()
        if checked:
            if self._companion_server is not None:
                self._set_status("Browser companion ready for one-click capture.", "success")
            else:
                self._set_status("Browser companion could not start. Review the Settings panel for details.", "warning")
        else:
            self._set_status("Browser companion disabled.", "idle")

    def _on_companion_scope_toggled(self, checked):
        """Persist LAN scope changes and restart the server if needed."""
        self._config["companion_bind_lan"] = bool(checked)
        self._persist_config()
        if bool(self._config.get("companion_server_enabled", False)):
            self._maybe_start_companion_server(force_restart=self._companion_server is not None)
            if checked:
                self._set_status("Browser companion restarted with LAN access enabled.", "warning")
            else:
                self._set_status("Browser companion returned to local-only access.", "success")
        else:
            self._refresh_companion_ui()
            self._set_status("Browser companion access scope saved.", "success")

    def _copy_text_to_clipboard(self, text, label):
        value = str(text or "").strip()
        if not value:
            self._set_status(f"{label} is not available yet.", "warning")
            return
        try:
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            if clipboard is None:
                raise RuntimeError("Clipboard unavailable")
            clipboard.setText(value)
            self._set_status(f"{label} copied to clipboard.", "success")
        except Exception as e:
            self._log(f"[CLIPBOARD] Could not copy {label.lower()}: {e}")
            self._set_status(f"Could not copy {label.lower()}.", "error")

    def _companion_local_url(self):
        srv = getattr(self, "_companion_server", None)
        port = int(getattr(srv, "port", 0) or 0) if srv is not None else 0
        if port <= 0:
            return ""
        return f"http://127.0.0.1:{port}/"

    def _refresh_companion_ui(self):
        """Update the Browser Companion settings panel from live state."""
        enabled = bool(self._config.get("companion_server_enabled", False))
        bind_lan = bool(self._config.get("companion_bind_lan", False))
        srv = getattr(self, "_companion_server", None)
        running = srv is not None and int(getattr(srv, "port", 0) or 0) > 0
        local_url = self._companion_local_url()
        token = str(getattr(srv, "token", "") or "") if running else ""
        error_text = str(getattr(self, "_companion_last_error", "") or "")

        if hasattr(self, "companion_check"):
            self.companion_check.blockSignals(True)
            self.companion_check.setChecked(enabled)
            self.companion_check.blockSignals(False)
        if hasattr(self, "companion_lan_check"):
            self.companion_lan_check.blockSignals(True)
            self.companion_lan_check.setChecked(bind_lan)
            self.companion_lan_check.blockSignals(False)

        if running and bind_lan:
            banner_title = "LAN access is enabled"
            banner_body = (
                "The companion is live on this PC and other devices on your network can connect if they know the token."
            )
            banner_tone = "warning"
        elif running:
            banner_title = "Ready for one-click capture"
            banner_body = (
                "The browser extension can hand URLs to StreamKeep on this PC, and the local web remote is ready."
            )
            banner_tone = "success"
        elif enabled and error_text:
            banner_title = "Companion could not start"
            banner_body = error_text
            banner_tone = "error"
        elif enabled:
            banner_title = "Starting the local receiver"
            banner_body = "StreamKeep is preparing a token-protected local endpoint for the extension and web remote."
            banner_tone = "info"
        else:
            banner_title = "Companion is off"
            banner_body = "Enable it when you want browser handoff or the lightweight local web remote."
            banner_tone = "info"

        if hasattr(self, "companion_status_banner"):
            update_status_banner(
                self.companion_status_banner,
                self.companion_status_title,
                self.companion_status_body,
                title=banner_title,
                body=banner_body,
                tone=banner_tone,
            )

        if hasattr(self, "companion_scope_value"):
            self.companion_scope_value.setText("LAN enabled" if bind_lan else "Local only")
            self.companion_scope_sub.setText(
                "Other trusted devices can reach the server"
                if bind_lan else
                "Only this PC can reach the companion"
            )
        if hasattr(self, "companion_remote_value"):
            if running:
                self.companion_remote_value.setText("Ready")
                self.companion_remote_sub.setText(local_url)
            elif enabled and error_text:
                self.companion_remote_value.setText("Error")
                self.companion_remote_sub.setText(error_text[:72])
            elif enabled:
                self.companion_remote_value.setText("Starting")
                self.companion_remote_sub.setText("Waiting for the local listener")
            else:
                self.companion_remote_value.setText("Off")
                self.companion_remote_sub.setText("Enable the companion to expose a local URL")
        if hasattr(self, "companion_token_value"):
            if token:
                self.companion_token_value.setText("Ready")
                self.companion_token_sub.setText("Rotates on every app launch")
            elif enabled:
                self.companion_token_value.setText("Pending")
                self.companion_token_sub.setText("Generated after the server starts")
            else:
                self.companion_token_value.setText("Waiting")
                self.companion_token_sub.setText("Generated only while the companion is on")

        if hasattr(self, "companion_url_display"):
            self.companion_url_display.setText(local_url)
        if hasattr(self, "companion_open_url_btn"):
            self.companion_open_url_btn.setEnabled(bool(local_url))
        if hasattr(self, "companion_copy_url_btn"):
            self.companion_copy_url_btn.setEnabled(bool(local_url))
        if hasattr(self, "companion_token_display"):
            self.companion_token_display.setText(token)
        if hasattr(self, "companion_copy_token_btn"):
            self.companion_copy_token_btn.setEnabled(bool(token))

    def _on_copy_companion_url(self):
        self._copy_text_to_clipboard(self._companion_local_url(), "Browser companion URL")

    def _on_copy_companion_token(self):
        text = self.companion_token_display.text() if hasattr(self, "companion_token_display") else ""
        self._copy_text_to_clipboard(text, "Pairing token")

    def _on_open_companion_remote(self):
        url = self._companion_local_url()
        if not url:
            self._set_status("Browser companion web remote is not available yet.", "warning")
            return
        QDesktopServices.openUrl(QUrl(url))
        self._set_status("Opened the browser companion web remote.", "success")

    # ── Notifications Center ─────────────────────────────────────────

    def _notify_center(self, text, level="info"):
        """Push an entry onto the in-app notifications ring buffer and
        refresh the header bell's unread badge. Optionally play a sound
        when the user has enabled audio cues in Settings."""
        self._notifications.push(text, level=level)
        self._refresh_notif_badge()
        if level in ("success", "warning", "error") and bool(self._config.get("notif_sound", False)):
            try:
                from PyQt6.QtWidgets import QApplication
                QApplication.beep()
            except Exception:
                pass

    def _refresh_notif_badge(self):
        if not hasattr(self, "notif_button"):
            return
        unread = self._notifications.unread
        if unread > 0:
            self.notif_button.setText(f"Alerts {unread}")
            self.notif_button.setStyleSheet("font-weight: 700;")
        else:
            self.notif_button.setText("Alerts 0")
            self.notif_button.setStyleSheet("")

    def _on_show_notifications(self):
        """Build a transient QMenu popping down from the bell with the
        most recent events. Marks all read on display."""
        menu = QMenu(self)
        items = self._notifications.items()
        if not items:
            empty = menu.addAction("No notifications yet")
            empty.setEnabled(False)
        else:
            for n in items[:30]:
                prefix = {
                    "success": "\u2714",
                    "warning": "\u26A0",
                    "error": "\u2716",
                    "info": "\u2022",
                }.get(n.level, "\u2022")
                act = menu.addAction(f"{n.ts}  {prefix}  {n.text}")
                act.setEnabled(False)
            menu.addSeparator()
            clear_act = menu.addAction("Clear all")
            clear_act.triggered.connect(self._on_clear_notifications)
        menu.addSeparator()
        log_act = menu.addAction("View full log\u2026")
        log_act.triggered.connect(self._on_show_notification_log)
        self._notifications.mark_all_read()
        self._refresh_notif_badge()
        # Drop down from the button.
        pos = self.notif_button.mapToGlobal(self.notif_button.rect().bottomLeft())
        menu.exec(pos)

    def _on_clear_notifications(self):
        self._notifications.clear()
        self._refresh_notif_badge()

    def _on_show_notification_log(self):
        from .notification_log_dialog import NotificationLogDialog
        dlg = NotificationLogDialog(self, self._notifications)
        dlg.exec()

    def _on_lifecycle_preview(self):
        """Show a preview of what the lifecycle cleanup would remove."""
        from ..lifecycle import evaluate_cleanup, execute_cleanup, removal_real_paths
        policy = self._config.get("lifecycle", {})
        if not policy.get("enabled"):
            policy = dict(policy, enabled=True)  # preview even if disabled
        removals = evaluate_cleanup(self._history, policy)
        if not removals:
            show_premium_message(
                self,
                title="No recordings match the current cleanup rules",
                body="The current lifecycle policy would not recycle anything right now.",
                eyebrow="LIFECYCLE",
                badge_text="Preview",
                tone="info",
                summary_title="Nothing needs attention.",
                summary_body="Try widening the cleanup rules or revisit this preview after more recordings accumulate.",
                primary_label="Close",
                min_width=560,
            )
            return
        # Build preview text
        total_size = 0
        lines = []
        for h, reason in removals:
            title = getattr(h, "title", "") or "Untitled"
            path = getattr(h, "path", "") or ""
            sz = 0
            if path and os.path.isdir(path):
                for f in os.scandir(path):
                    if f.is_file():
                        try:
                            sz += f.stat().st_size
                        except OSError:
                            pass
            total_size += sz
            sz_mb = sz / (1024 * 1024)
            lines.append(f"  {title[:50]}  ({sz_mb:.1f} MB) — {reason}")
        detail_text = "\n".join(lines[:30])
        if len(lines) > 30:
            detail_text += f"\n  … and {len(lines) - 30} more"
        if ask_premium_confirmation(
            self,
            title="Review lifecycle cleanup",
            body="These recordings match the current cleanup policy and would be moved to the Recycle Bin.",
            eyebrow="LIFECYCLE",
            badge_text="Preview",
            tone="warning",
            summary_title=f"{len(removals)} recording(s) matched, using about {total_size / (1024 ** 3):.2f} GB.",
            summary_body="Files stay recoverable through the Recycle Bin if you need to bring something back.",
            details_title="Matched recordings",
            details_body=detail_text,
            primary_label="Recycle matches",
            secondary_label="Keep everything",
            default_action="secondary",
            min_width=720,
            min_height=520,
            details_monospaced=True,
        ):
            removed = execute_cleanup(removals, log_fn=self._log)
            if removed:
                removed_paths = {
                    real_path for real_path in removal_real_paths(removals)
                    if not os.path.isdir(real_path)
                }
                self._remove_history_for_paths(removed_paths)
            self._log(f"[LIFECYCLE] Recycled {removed} recording(s).")
            self._set_status(f"Lifecycle cleanup: {removed} recording(s) recycled.", "success")

    def _remove_history_for_paths(self, real_paths):
        """Remove all history rows that point at any recycled recording path."""
        real_paths = {os.path.realpath(path) for path in (real_paths or set()) if path}
        if not real_paths:
            return

        def _entry_real_path(entry):
            path = getattr(entry, "path", "") or ""
            return os.path.realpath(path) if path else ""

        db_ids = [
            h.db_id for h in self._history
            if getattr(h, "db_id", 0) and _entry_real_path(h) in real_paths
        ]
        self._history = [h for h in self._history if _entry_real_path(h) not in real_paths]
        if db_ids:
            _db.delete_history_entries(db_ids)
        self._refresh_history_table()

    def _run_lifecycle_cleanup(self):
        """Run lifecycle cleanup silently after a download completes."""
        from ..lifecycle import evaluate_cleanup, execute_cleanup, removal_real_paths
        policy = self._config.get("lifecycle", {})
        if not policy or not policy.get("enabled"):
            return
        removals = evaluate_cleanup(self._history, policy)
        if removals:
            removed = execute_cleanup(removals, log_fn=self._log)
            if removed:
                removed_paths = {
                    real_path for real_path in removal_real_paths(removals)
                    if not os.path.isdir(real_path)
                }
                self._remove_history_for_paths(removed_paths)
                self._log(f"[LIFECYCLE] Auto-cleanup recycled {removed} recording(s).")

    def _choose_default_quality_index(self, qualities, platform):
        """Resolve the user's per-platform default to an index into the
        given quality list. Fallbacks:

          pref "1080p" -> first quality whose name/resolution contains "1080"
          pref "720p"  -> first 720
          pref "source"/"highest"/"" -> 1080-or-source heuristic (legacy)
          pref "lowest"  -> last (qualities are typically sorted high→low)
        """
        prefs = self._config.get("quality_defaults") or {}
        pkey = (platform or "").strip().lower() or "other"
        pref = (prefs.get(pkey) or prefs.get("other") or "").strip().lower()
        if not pref or pref in ("highest", "source"):
            # Legacy behaviour: prefer 1080 or "source" if present, else 0.
            for i, q in enumerate(qualities):
                if "1080" in q.name or "source" in q.name.lower():
                    return i
            return 0
        if pref == "lowest":
            return len(qualities) - 1
        for i, q in enumerate(qualities):
            cname = (q.name or "").lower()
            cres = (q.resolution or "").lower()
            if pref in cname or pref in cres:
                return i
        # No match — fall back to the legacy heuristic.
        for i, q in enumerate(qualities):
            if "1080" in q.name or "source" in q.name.lower():
                return i
        return 0

    # ── Browser companion local server ───────────────────────────────

    def _maybe_start_companion_server(self, force_restart=False):
        """Start (or stop) the local companion HTTP server based on the
        current Settings toggle. Called at launch and whenever the user
        changes the setting."""
        enabled = bool(self._config.get("companion_server_enabled", False))
        bind_lan = bool(self._config.get("companion_bind_lan", False))
        desired_bind = "0.0.0.0" if bind_lan else "127.0.0.1"
        running = self._companion_server is not None
        if running and getattr(self._companion_server, "_bind_addr", "") != desired_bind:
            force_restart = True
        if force_restart and running:
            try:
                self._companion_server.stop()
            except Exception:
                pass
            self._companion_server = None
            running = False
        if enabled and not running:
            try:
                srv = LocalCompanionServer(bind_lan=bind_lan)
                srv.state_provider = self._api_state_snapshot
                srv.url_received.connect(self._on_companion_url)
                srv.start()
                self._companion_server = srv
                self._companion_last_error = ""
                self._log(
                    f"[COMPANION] Listening on 127.0.0.1:{srv.port} "
                    f"— token in Settings tab."
                )
            except OSError as e:
                self._companion_last_error = str(e)
                self._log(f"[COMPANION] Could not start server: {e}")
        elif enabled and running:
            self._companion_last_error = ""
        elif not enabled and running:
            try:
                self._companion_server.stop()
            except Exception:
                pass
            self._companion_server = None
            self._companion_last_error = ""
            self._log("[COMPANION] Server stopped.")
        elif not enabled:
            self._companion_last_error = ""
        self._refresh_companion_ui()

    def _api_state_snapshot(self):
        """Return a dict snapshot of app state for the REST API (F37).
        Called from the HTTP server thread — must be thread-safe.
        Take list() copies of shared collections to avoid race conditions."""
        downloads = []
        queue_items = []
        try:
            for q in list(getattr(self, "_download_queue", [])):
                queue_items.append({
                    "url": q.get("url", ""),
                    "title": q.get("title", ""),
                })
        except Exception:
            pass
        history = []
        try:
            for h in list(self._history)[-50:]:
                history.append({
                    "title": h.title or "",
                    "platform": h.platform or "",
                    "date": h.date or "",
                    "quality": h.quality or "",
                    "size": h.size or "",
                })
        except Exception:
            pass
        monitor = []
        try:
            for e in list(self.monitor.entries):
                monitor.append({
                    "channel_id": e.channel_id,
                    "platform": e.platform,
                    "status": e.last_status,
                })
        except Exception:
            pass
        live_channels = [m for m in monitor if m.get("status") == "live"]
        return {
            "downloads": downloads,
            "queue": queue_items,
            "history": history,
            "monitor": monitor,
            "live_channels": live_channels,
        }

    def _on_companion_url(self, url, action):
        """The extension just POSTed a URL. Route it through the Fetch
        path or queue it immediately depending on action."""
        self._log(f"[COMPANION] Received {action.upper()} for {url[:80]}")
        self._present_main_window(0)
        try:
            self.url_input.setText(url)
        except Exception:
            pass
        if action == "queue":
            try:
                added = self._queue_add(url, title="", platform="")
                if added:
                    self._set_status(f"Queued via browser extension: {url[:80]}", "success")
                else:
                    self._set_status("That browser handoff is already in the queue.", "warning")
            except Exception as e:
                self._log(f"[COMPANION] Queue failed: {e}")
        else:
            self._on_fetch()

    # ── Auto-update checker ──────────────────────────────────────────

    def _maybe_check_for_updates(self):
        """Kick off the GitHub release check if the user has opted in.
        Runs once per launch, on a short delay so the UI paints first."""
        if not bool(self._config.get("check_for_updates", False)):
            return
        # Only meaningful in a packaged exe — in a source checkout the
        # updater refuses the self-replace anyway. Skip the network call
        # entirely so source-checkout users don't see a banner.
        if not (getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")):
            return
        if getattr(self, "_update_check_worker", None) is not None:
            return
        worker = UpdateCheckWorker(VERSION)
        worker.result.connect(self._on_update_check_result)
        self._update_check_worker = worker
        worker.start()

    def _on_update_check_result(self, payload):
        worker = getattr(self, "_update_check_worker", None)
        if worker is not None and not worker.isRunning():
            try:
                worker.wait(200)
            except Exception:
                pass
        self._update_check_worker = None
        if not payload or not payload.get("available"):
            return
        tag = payload.get("tag", "")
        if tag == self._config.get("dismissed_update_tag", ""):
            return
        self._latest_update_payload = payload
        if hasattr(self, "update_banner_label"):
            notes = (payload.get("notes") or "").splitlines()
            first_note = next((ln for ln in notes if ln.strip()), "").strip()
            if first_note:
                first_note = first_note[:140] + ("…" if len(first_note) > 140 else "")
            label = f"StreamKeep {tag} is available (you're on v{VERSION})"
            if first_note:
                label = f"{label} — {first_note}"
            self.update_banner_label.setText(label)
            self.update_banner.setVisible(True)
        self._notify_center(f"Update available: StreamKeep {tag}", "info")

    def _on_update_install(self):
        payload = getattr(self, "_latest_update_payload", None) or {}
        asset_url = payload.get("asset_url", "")
        if not asset_url:
            self._set_status("Update available but no Windows asset was attached.", "warning")
            return
        self.update_banner_install_btn.setEnabled(False)
        self.update_banner_install_btn.setText("Downloading...")
        worker = DownloadUpdateWorker(asset_url, payload.get("asset_size", 0))
        worker.progress.connect(self._on_update_download_progress)
        worker.done.connect(self._on_update_download_done)
        self._update_download_worker = worker
        worker.start()

    def _on_update_download_progress(self, pct, status):
        if hasattr(self, "update_banner_install_btn"):
            self.update_banner_install_btn.setText(
                f"Downloading {status}" if status else f"Downloading {pct}%"
            )

    def _on_update_download_done(self, ok, path_or_err):
        worker = getattr(self, "_update_download_worker", None)
        if worker is not None and not worker.isRunning():
            try:
                worker.wait(200)
            except Exception:
                pass
        self._update_download_worker = None
        if not ok:
            self._log(f"[UPDATE] {path_or_err}")
            self._set_status(f"Update failed: {path_or_err}", "error")
            if hasattr(self, "update_banner_install_btn"):
                self.update_banner_install_btn.setEnabled(True)
                self.update_banner_install_btn.setText("Download & install")
            return
        # Download complete — confirm self-replace + relaunch.
        if not ask_premium_confirmation(
            self,
            title="Install the downloaded update?",
            body="StreamKeep will close, swap in the new version, and relaunch itself automatically.",
            eyebrow="UPDATER",
            badge_text="Restart required",
            tone="warning",
            summary_title="Any active download or recording will be interrupted.",
            summary_body="Install now when you are ready for the app to restart itself.",
            details_title="What happens next",
            details_body=(
                "1. StreamKeep closes.\n"
                "2. The downloaded build replaces the current executable.\n"
                "3. StreamKeep relaunches itself."
            ),
            primary_label="Install and relaunch",
            secondary_label="Not now",
            default_action="secondary",
            min_width=620,
        ):
            self._log("[UPDATE] User cancelled the install step.")
            if hasattr(self, "update_banner_install_btn"):
                self.update_banner_install_btn.setEnabled(True)
                self.update_banner_install_btn.setText("Install now")
            return
        if arm_self_replace(path_or_err):
            self._log("[UPDATE] Armed self-replace, quitting now.")
            from PyQt6.QtWidgets import QApplication
            QApplication.quit()
        else:
            self._set_status("Could not arm the update step. See log.", "error")

    def _on_update_dismiss(self):
        payload = getattr(self, "_latest_update_payload", None) or {}
        self._config["dismissed_update_tag"] = payload.get("tag", "")
        self._persist_config()
        self.update_banner.setVisible(False)

    def _preflight_disk_space(self):
        """Show a confirm dialog when the estimated download size is more
        than 80% of free space. Returns True if the user wants to proceed
        (or the check is inapplicable), False to abort.

        Lives and unknown-duration streams pass through silently since we
        can't estimate them meaningfully.
        """
        try:
            out_dir = self.output_input.text().strip() or str(_default_output_dir())
            free = _free_space_bytes(out_dir)
            estimate = _estimate_download_bytes(self.stream_info)
            if not free or not estimate or estimate <= 0:
                return True
            if estimate <= free * 0.8:
                return True
            return ask_premium_confirmation(
                self,
                title="Low free space on the output drive",
                body=(
                    f"This download may need about {_fmt_size(estimate)}, but only "
                    f"{_fmt_size(free)} is currently free in the output location."
                ),
                eyebrow="PREFLIGHT",
                badge_text="Capacity risk",
                tone="warning",
                summary_title="Continuing could leave you with a partial or failed download.",
                summary_body="Free up space first if you want the safest path.",
                details_title="Capacity estimate",
                details_body=(
                    f"Estimated download size: {_fmt_size(estimate)}\n"
                    f"Free space available: {_fmt_size(free)}\n"
                    f"Output folder: {out_dir}"
                ),
                primary_label="Continue anyway",
                secondary_label="Cancel",
                default_action="secondary",
                min_width=620,
            )
        except Exception as e:
            self._log(f"[PREFLIGHT] disk-space check failed: {e}")
            return True

    def _on_trim_last(self):
        """Open the trim dialog for the most-recently-finished download."""
        out_dir = self._active_output_dir or self.output_input.text().strip()
        if not out_dir or not os.path.isdir(out_dir):
            self._set_status("No recent download folder to trim.", "warning")
            return
        self._open_clip_dialog_for_dir(out_dir)

    # ── Monitor Actions ───────────────────────────────────────────────

    # ── Import / Export Monitor Channels (F10) ──────────────────────

    def _on_monitor_export(self):
        """Export monitored channel list to a JSON file."""
        if not self.monitor.entries:
            self._set_status("No channels to export.", "warning")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Monitor Channels", "streamkeep_channels.json",
            "JSON files (*.json)",
        )
        if not path:
            return
        cfg = {}
        self.monitor.save_to_config(cfg)
        data = cfg.get("monitor_channels", [])
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._log(f"[EXPORT] {len(data)} channels exported to {path}")
            self._set_status(f"Exported {len(data)} channels to {os.path.basename(path)}", "success")
        except OSError as e:
            self._set_status(f"Export failed: {e}", "error")

    def _on_monitor_import(self):
        """Import monitored channels from a JSON file, skipping duplicates."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Monitor Channels", "",
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self._set_status(f"Import failed: {e}", "error")
            return
        if not isinstance(data, list):
            self._set_status("Invalid channel list — expected a JSON array.", "error")
            return
        existing_urls = {e.url for e in self.monitor.entries}
        added = 0
        skipped = 0
        for ch in data:
            if not isinstance(ch, dict) or "url" not in ch:
                continue
            if ch["url"] in existing_urls:
                skipped += 1
                continue
            ok = self.monitor.add_channel(
                ch["url"],
                ch.get("interval", 120),
                ch.get("auto_record", False),
                ch.get("subscribe_vods", False),
            )
            if ok:
                # Restore per-channel profile fields
                for e in self.monitor.entries:
                    if e.url == ch["url"]:
                        e.override_output_dir = str(ch.get("override_output_dir", "") or "")
                        e.override_quality_pref = str(ch.get("override_quality_pref", "") or "")
                        e.override_filename_template = str(ch.get("override_filename_template", "") or "")
                        e.schedule_start_hhmm = str(ch.get("schedule_start_hhmm", "") or "")
                        e.schedule_end_hhmm = str(ch.get("schedule_end_hhmm", "") or "")
                        try:
                            e.schedule_days_mask = int(ch.get("schedule_days_mask", 0) or 0)
                        except (TypeError, ValueError):
                            e.schedule_days_mask = 0
                        try:
                            e.retention_keep_last = int(ch.get("retention_keep_last", 0) or 0)
                        except (TypeError, ValueError):
                            e.retention_keep_last = 0
                        e.filter_keywords = str(ch.get("filter_keywords", "") or "")
                        break
                added += 1
                existing_urls.add(ch["url"])
        self._refresh_monitor_table()
        self._persist_config()
        self._log(f"[IMPORT] {added} added, {skipped} skipped (duplicate) from {path}")
        self._set_status(
            f"Imported {added} channels ({skipped} skipped as duplicates).",
            "success" if added else "warning",
        )

    def _on_refresh_schedules(self):
        """Refresh stream schedules in a background thread (F39 audit fix)."""
        import threading
        from PyQt6.QtCore import QTimer

        if hasattr(self, "schedule_calendar"):
            self.schedule_calendar.set_refreshing(True)

        # Thread-safe log shim: marshal _log calls back to the GUI thread.
        def _safe_log(msg, _self=self):
            QTimer.singleShot(0, lambda: _self._log(msg))

        def _bg():
            from ..schedule import refresh_schedules
            cache = dict(self._config.get("schedules", {}))
            error = ""
            try:
                cache = refresh_schedules(
                    list(self.monitor.entries), cache, log_fn=_safe_log,
                )
            except Exception as exc:
                error = str(exc)
                _safe_log(f"[SCHEDULE] Schedule refresh failed: {exc}")
            QTimer.singleShot(0, lambda: self._apply_schedule_cache(cache, error))

        threading.Thread(target=_bg, daemon=True).start()

    def _apply_schedule_cache(self, cache, error=""):
        """Apply refreshed schedule cache on the main thread."""
        self._config["schedules"] = cache
        if hasattr(self, "schedule_calendar"):
            if error:
                self.schedule_calendar.set_refresh_error(error)
            else:
                self.schedule_calendar.set_refreshing(False)
            self.schedule_calendar.set_cache(cache)
        if error:
            self._set_status("Schedule refresh failed. See log for details.", "error")
            return
        self._log("[SCHEDULE] Schedule refresh complete.")
        self._set_status("Schedule cache refreshed.", "success")

    def _on_schedule_block_clicked(self, seg):
        """Handle click on a calendar schedule block (F39)."""
        channel = seg.get("channel", "")
        title = seg.get("title", "")
        cat = seg.get("category", "")
        start_dt = None
        end_dt = None
        start_iso = seg.get("start_iso", "")
        end_iso = seg.get("end_iso", "")
        try:
            if start_iso:
                start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone()
        except (TypeError, ValueError):
            start_dt = None
        try:
            if end_iso:
                end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00")).astimezone()
        except (TypeError, ValueError):
            end_dt = None
        lines = []
        if channel:
            lines.append(f"Channel: {channel}")
        if start_dt:
            start_text = start_dt.strftime("%a, %b %d at %I:%M %p").replace(" 0", " ")
            lines.append(f"Starts: {start_text}")
        if end_dt:
            end_text = end_dt.strftime("%I:%M %p").replace(" 0", " ")
            lines.append(f"Ends: {end_text}")
        if cat:
            lines.append(f"Category: {cat}")
        lines.append("")
        lines.append("Open the channel profile if you want to adjust auto-record rules or retention for this stream.")
        box.setInformativeText("\n".join(lines))

        open_profile_btn = None
        entry_idx = next(
            (
                idx
                for idx, entry in enumerate(self.monitor.entries)
                if (getattr(entry, "channel_id", "") or "").lower() == channel.lower()
            ),
            -1,
        )
        if entry_idx >= 0:
            open_profile = ask_premium_confirmation(
                self,
                title=title or channel or "Scheduled stream",
                body="This stream is in the cached Twitch schedule for one of your monitored channels.",
                eyebrow="SCHEDULE",
                badge_text="Monitored channel",
                tone="info",
                summary_title="Open the channel profile if you want to adjust auto-record rules or retention.",
                summary_body="Schedule blocks are informational until you decide how that channel should behave.",
                details_title="Scheduled stream details",
                details_body="\n".join(lines),
                primary_label="Open Channel Profile",
                secondary_label="Close",
                default_action="secondary",
                min_width=620,
            )
            if open_profile:
                self._on_monitor_edit(entry_idx)
        else:
            show_premium_message(
                self,
                title=title or channel or "Scheduled stream",
                body="This stream is in the cached Twitch schedule, but it is not linked to an editable monitored profile right now.",
                eyebrow="SCHEDULE",
                badge_text="Schedule detail",
                tone="info",
                summary_title="Schedule windows are shown in your local timezone.",
                summary_body="Add the channel to your watch list if you want to configure auto-record behavior from here.",
                details_title="Scheduled stream details",
                details_body="\n".join(lines),
                primary_label="Close",
                min_width=620,
            )

    def _on_monitor_add(self):
        url = self.monitor_url_input.text().strip()
        if not url:
            return
        interval = self.monitor_interval_spin.value()
        auto = self.monitor_auto_cb.isChecked()
        subscribe = self.monitor_subscribe_cb.isChecked()
        if self.monitor.add_channel(url, interval, auto, subscribe):
            ext = Extractor.detect(url)
            channel_id = ext.extract_channel_id(url) if ext else url
            self.monitor_url_input.clear()
            self._log(
                f"[MONITOR] Added: {url} (every {interval}s, "
                f"auto-record: {auto}, subscribe: {subscribe})"
            )
            # Seed the archive with current VODs so we don't download the backlog
            if subscribe and ext and ext.supports_vod_listing():
                self._log(f"[SUBSCRIBE] Seeding archive for {channel_id} in the background...")
                self._start_monitor_seed_worker(url, channel_id)
            self._persist_config()
            if subscribe and ext and ext.supports_vod_listing():
                self._set_status("Channel added. Existing VODs are being seeded in the background.", "success")
            else:
                self._set_status("Channel added to the watch list.", "success")
        else:
            self._log("[MONITOR] Cannot add: unsupported or duplicate")
            self._set_status("Channel could not be added. It may already exist or be unsupported.", "error")

    def _on_monitor_seed_done(self, channel_id, sources):
        self._clear_monitor_seed_worker(channel_id)
        if not any(e.channel_id == channel_id for e in self.monitor.entries):
            return
        self.monitor.seed_archive(channel_id, sources)
        self._persist_config()
        self._log(
            f"[SUBSCRIBE] Seeded archive with {len(sources)} existing VOD(s). "
            f"Only new VODs will be queued from now on."
        )

    def _on_monitor_seed_error(self, channel_id, err):
        self._clear_monitor_seed_worker(channel_id)
        if any(e.channel_id == channel_id for e in self.monitor.entries):
            self._log(f"[SUBSCRIBE] Seed failed for {channel_id}: {err}")

    def _refresh_monitor_table(self):
        entries = self.monitor.entries
        self.monitor_table.setRowCount(len(entries))
        for i, e in enumerate(entries):
            badge = PLATFORM_BADGES.get(e.platform, {})
            plat = QTableWidgetItem(e.platform)
            plat.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if badge.get("color"):
                plat.setForeground(QColor(badge["color"]))
            self.monitor_table.setItem(i, 0, plat)

            ch = QTableWidgetItem(e.channel_id)
            self.monitor_table.setItem(i, 1, ch)

            status = QTableWidgetItem(e.last_status.upper())
            status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if e.last_status == "live":
                status.setForeground(QColor(CAT["green"]))
            elif e.last_status == "error":
                status.setForeground(QColor(CAT["red"]))
            else:
                status.setForeground(QColor(CAT["overlay1"]))
            self.monitor_table.setItem(i, 2, status)

            intv = QTableWidgetItem(f"{e.interval_secs}s")
            intv.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.monitor_table.setItem(i, 3, intv)

            auto = QTableWidgetItem("Yes" if e.auto_record else "No")
            auto.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if e.auto_record:
                auto.setForeground(QColor(CAT["green"]))
            self.monitor_table.setItem(i, 4, auto)

            # Column 5 now carries two buttons: Edit (profile) + Remove.
            cell = QWidget()
            cell_lay = QHBoxLayout(cell)
            cell_lay.setContentsMargins(2, 2, 2, 2)
            cell_lay.setSpacing(4)
            edit_btn = QPushButton("Edit")
            edit_btn.setObjectName("ghost")
            edit_btn.setFixedHeight(28)
            edit_btn.setToolTip("Edit per-channel profile: output folder, quality, schedule, retention.")
            edit_btn.clicked.connect(lambda checked, idx=i: self._on_monitor_edit(idx))
            cell_lay.addWidget(edit_btn)
            rm_btn = QPushButton("Stop" if e.is_recording else "Remove")
            rm_btn.setObjectName("ghost")
            rm_btn.setFixedHeight(28)
            if e.is_recording:
                rm_btn.setToolTip("Stops the active auto-recording first, then removes this channel.")
            rm_btn.clicked.connect(lambda checked, idx=i: self._on_monitor_remove(idx))
            cell_lay.addWidget(rm_btn)
            self.monitor_table.setCellWidget(i, 5, cell)

            # Show a small schedule-window glyph next to the interval column
            # when one is configured so the user can see which channels
            # are time-gated without opening the profile dialog.
            if e.schedule_start_hhmm and e.schedule_end_hhmm:
                sched_item = self.monitor_table.item(i, 3)
                if sched_item is not None:
                    sched_item.setText(
                        f"{e.interval_secs}s  \u23F0 {e.schedule_start_hhmm}-{e.schedule_end_hhmm}"
                    )
        self._refresh_monitor_summary()
        self._update_tray_badge()

    def _refresh_active_recordings_panel(self):
        """Update the Monitor-tab panel that shows every currently-active
        auto-record + resolver. No-op if the panel isn't built yet (early
        calls during __init__)."""
        panel = getattr(self, "active_recordings_panel", None)
        if panel is None:
            return
        rows = []
        for ch_id in sorted(self._autorecord_resolvers.keys()):
            if self._autorecord_resolvers[ch_id].isRunning():
                rows.append((ch_id, "Resolving live URL...", False))
        for ch_id in sorted(self._autorecord_workers.keys()):
            ctx = self._autorecord_contexts.get(ch_id, {})
            status = ctx.get("last_status") or "Starting"
            had_err = bool(ctx.get("had_errors"))
            label_text = f"{ch_id} — {status}"
            if had_err:
                label_text += "  (errors)"
            rows.append((ch_id, label_text, True))
        if not rows:
            panel.setVisible(False)
            return
        panel.setVisible(True)
        # Clear existing dynamic rows (keep the header label at index 0).
        while self.active_recordings_rows_layout.count():
            item = self.active_recordings_rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for _ch_id, text, _live in rows:
            label = QLabel(text)
            label.setObjectName("sectionBody")
            label.setWordWrap(True)
            self.active_recordings_rows_layout.addWidget(label)
        # Header label reflects count.
        self.active_recordings_header.setText(
            f"Active recordings ({len(rows)})"
        )

    def _on_monitor_edit(self, idx):
        """Open the per-channel profile dialog for entries[idx]."""
        if not (0 <= idx < len(self.monitor.entries)):
            return
        entry = self.monitor.entries[idx]
        from .monitor_entry_dialog import MonitorEntryDialog
        globals_preview = {
            "output_dir": self.output_input.text().strip() or str(_default_output_dir()),
            "file_template": self._file_template or "",
        }
        dlg = MonitorEntryDialog(self, entry, globals_preview=globals_preview)
        if dlg.exec():
            self._refresh_monitor_table()
            self._persist_config()
            desc = []
            if entry.override_output_dir:
                desc.append("custom output dir")
            if entry.override_quality_pref:
                desc.append(f"quality={entry.override_quality_pref}")
            if entry.schedule_start_hhmm and entry.schedule_end_hhmm:
                desc.append(f"window {entry.schedule_start_hhmm}-{entry.schedule_end_hhmm}")
            if entry.retention_keep_last:
                desc.append(f"keep last {entry.retention_keep_last}")
            self._set_status(
                f"Updated profile for {entry.channel_id}"
                + (f" — {', '.join(desc)}." if desc else " — cleared overrides."),
                "success",
            )

    # ── Storage tab ──────────────────────────────────────────────────

    def _storage_scan_root(self):
        return self.output_input.text().strip() or str(_default_output_dir())

    def _on_storage_rescan(self):
        """Rescan the output root and repopulate the Storage table."""
        root = self._storage_scan_root()
        self.storage_root_label.setText(f"Scanning: {root}")
        self.storage_rescan_btn.setEnabled(False)
        try:
            scan = scan_storage(root)
        except Exception as e:
            self._log(f"[STORAGE] Scan failed: {e}")
            scan = None
        finally:
            self.storage_rescan_btn.setEnabled(True)
        if scan is None:
            return
        populate_storage_table(self, scan)
        self._set_status(
            f"Storage scan complete — {scan.total_files} file(s), "
            f"{_fmt_size(scan.total_size)}.",
            "success" if scan.total_files else "idle",
        )

    def _on_storage_context_menu(self, pos):
        """Right-click menu on the Storage table — bundle the selected row."""
        if not hasattr(self, "storage_table"):
            return
        idx = self.storage_table.indexAt(pos)
        if not idx.isValid():
            return
        row = idx.row()
        groups = getattr(self, "_storage_groups", None) or []
        if not (0 <= row < len(groups)):
            return
        g = groups[row]
        menu = QMenu(self)
        bundle_act = menu.addAction("Export share bundle (.zip)...")
        trim_act = menu.addAction("Trim / Clip...")
        menu.addSeparator()
        open_act = menu.addAction("Open Folder")
        chosen = menu.exec(self.storage_table.viewport().mapToGlobal(pos))
        if chosen == bundle_act:
            self._start_bundle_export(g.dir_path)
        elif chosen == trim_act:
            self._open_clip_dialog_for_dir(g.dir_path)
        elif chosen == open_act and os.path.isdir(g.dir_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(g.dir_path))

    def _on_storage_selection_changed(self):
        rows = list(self.storage_table.selectionModel().selectedRows())
        count = len(rows)
        self.storage_delete_btn.setEnabled(count > 0)
        self.storage_delete_btn.setText(
            f"Recycle {count} Selected" if count else "Recycle Selected"
        )
        groups = getattr(self, "_storage_groups", None) or []
        total_size = sum(
            groups[idx.row()].total_size
            for idx in rows
            if 0 <= idx.row() < len(groups)
        )
        if count:
            self.storage_delete_btn.setToolTip(
                f"Move {count} folder group(s) totalling {_fmt_size(total_size)} to the Recycle Bin."
            )
        else:
            self.storage_delete_btn.setToolTip(
                "Select one or more folder groups to recycle them safely."
            )

    def _on_storage_delete_selected(self):
        """Move selected recording folders to the system Recycle Bin."""
        rows = sorted(
            {idx.row() for idx in self.storage_table.selectionModel().selectedRows()},
            reverse=True,
        )
        groups_attr = getattr(self, "_storage_groups", None) or []
        targets = [groups_attr[r] for r in rows if 0 <= r < len(groups_attr)]
        if not targets:
            return
        total_size = sum(g.total_size for g in targets)
        sample_paths = [g.dir_path for g in targets]
        if not prompt_confirm_delete(self, len(targets), total_size, sample_paths):
            return
        try:
            from send2trash import send2trash as _send2trash
        except ImportError:
            self._log(
                "[STORAGE] send2trash is not installed. Refusing to delete "
                "permanently. Install with: pip install send2trash"
            )
            self._set_status(
                "send2trash not installed — recycle-bin delete unavailable. "
                "No files were changed.",
                "error",
            )
            return
        recycled = 0
        for g in targets:
            try:
                _send2trash(g.dir_path)
                recycled += 1
            except Exception as e:
                self._log(f"[STORAGE] Could not recycle {g.dir_path}: {e}")
        if recycled:
            self._log(
                f"[STORAGE] Recycled {recycled} folder(s) totalling "
                f"{_fmt_size(total_size)}."
            )
        self._set_status(
            f"Recycled {recycled} of {len(targets)} folder(s).",
            "success" if recycled == len(targets) else "warning",
        )
        self._on_storage_rescan()

    def _apply_retention_for_channel(self, entry, out_dir):
        """If the entry has a retention limit, recycle-bin the oldest
        recordings in `out_dir` beyond the keep-last count. Logs what it
        does; does not prompt — enabling retention on the profile is the
        opt-in."""
        keep = int(getattr(entry, "retention_keep_last", 0) or 0)
        if keep <= 0 or not out_dir or not os.path.isdir(out_dir):
            return
        # Treat each immediate subdir under the channel's output root as
        # one "recording". Group per-channel_id prefix so sibling channels
        # sharing an output dir don't cannibalize each other.
        prefix = f"auto_{entry.channel_id}_" if entry.channel_id else ""
        candidates = []
        try:
            for child in os.scandir(out_dir):
                if not child.is_dir():
                    continue
                if prefix and not child.name.startswith(prefix):
                    continue
                try:
                    mtime = child.stat().st_mtime
                except OSError:
                    continue
                candidates.append((mtime, child.path))
        except OSError:
            return
        if len(candidates) <= keep:
            return
        candidates.sort(reverse=True)  # newest first
        to_remove = candidates[keep:]
        removed = 0
        for _mtime, path in to_remove:
            try:
                from send2trash import send2trash as _send2trash
                _send2trash(path)
            except ImportError:
                # send2trash not available — leave the recording in place
                # rather than permanently deleting it. Retention without
                # recycle-bin fallback is too dangerous.
                self._log(
                    "[RETENTION] send2trash not installed — skipping "
                    "retention cleanup (would otherwise recycle "
                    f"{os.path.basename(path)})."
                )
                break
            except Exception as e:
                self._log(f"[RETENTION] Could not recycle {path}: {e}")
                continue
            removed += 1
        if removed:
            self._log(
                f"[RETENTION] {entry.channel_id}: recycled {removed} old "
                f"recording(s), keeping last {keep}."
            )

    def _on_monitor_remove(self, idx):
        channel_id = None
        is_recording = False
        if 0 <= idx < len(self.monitor.entries):
            channel_id = self.monitor.entries[idx].channel_id
            is_recording = bool(self.monitor.entries[idx].is_recording)
        if channel_id:
            self._pending_auto_records = [cid for cid in self._pending_auto_records if cid != channel_id]
            seed_worker = self._monitor_seed_workers.pop(channel_id, None)
            if seed_worker is not None and seed_worker.isRunning():
                try:
                    seed_worker.requestInterruption()
                    seed_worker.wait(500)
                except Exception:
                    pass
            # Stop just this channel's resolver + auto-record worker if
            # they're active. Other parallel auto-records are unaffected.
            resolve_worker = self._autorecord_resolvers.pop(channel_id, None)
            if resolve_worker is not None and resolve_worker.isRunning():
                try:
                    resolve_worker.requestInterruption()
                    resolve_worker.wait(500)
                except Exception:
                    pass
            ar_worker = self._autorecord_workers.get(channel_id)
            if is_recording and ar_worker is not None and ar_worker.isRunning():
                self._log(f"[AUTO-RECORD] Stopping active recording before removing {channel_id}")
                try:
                    ar_worker.cancel()
                    if not ar_worker.wait(5000):
                        ar_worker.terminate()
                        ar_worker.wait(1000)
                except Exception:
                    pass
                self._autorecord_workers.pop(channel_id, None)
                self._autorecord_contexts.pop(channel_id, None)
                self._refresh_active_recordings_panel()
        self.monitor.remove_channel(idx)
        self._persist_config()
        self._set_status("Channel removed from the watch list.", "success")

    def _queue_auto_record_retry(self, channel_id):
        if channel_id not in self._pending_auto_records:
            self._pending_auto_records.append(channel_id)
        self._refresh_monitor_summary()

    def _drain_pending_auto_records(self):
        resolver = getattr(self, "_auto_record_resolve_worker", None)
        if resolver is not None and resolver.isRunning():
            return True
        worker = getattr(self, "download_worker", None)
        if worker is not None and worker.isRunning():
            return False
        while self._pending_auto_records:
            channel_id = self._pending_auto_records.pop(0)
            if self._try_start_auto_record(channel_id):
                self._refresh_monitor_summary()
                return True
        self._refresh_monitor_summary()
        return False

    def _auto_record_error(self, channel_id, err):
        ctx = self._autorecord_contexts.get(channel_id)
        if ctx is not None:
            ctx["had_errors"] = True
        self._log(f"[AUTO-RECORD] {channel_id}: {err}")

    def _active_autorecord_count(self):
        """Number of channels currently resolving + recording via auto-record."""
        resolvers = sum(
            1 for w in self._autorecord_resolvers.values()
            if w is not None and w.isRunning()
        )
        workers = sum(
            1 for w in self._autorecord_workers.values()
            if w is not None and w.isRunning()
        )
        return resolvers + workers

    def _try_start_auto_record(self, channel_id):
        target = None
        for e in self.monitor.entries:
            if e.channel_id == channel_id and e.auto_record and not e.is_recording:
                target = e
                break
        if target is None:
            return False
        # Already recording / resolving this specific channel — nothing to do.
        if channel_id in self._autorecord_workers or channel_id in self._autorecord_resolvers:
            return False
        # Parallel cap: don't exceed `parallel_autorecords`. Foreground
        # download_worker doesn't count toward this cap — it's a separate
        # track that doesn't interfere.
        cap = max(1, int(self._parallel_autorecords or 1))
        if self._active_autorecord_count() >= cap:
            # Re-queue for the next poll tick; don't fail outright.
            self._queue_auto_record_retry(channel_id)
            return False

        # Respect the per-channel schedule window — if we're outside it,
        # defer auto-record until the next poll tick that lands inside.
        if not entry_in_schedule_window(target):
            self._log(
                f"[AUTO-RECORD] Skipping {channel_id} — outside channel's "
                f"schedule window ({target.schedule_start_hhmm}-{target.schedule_end_hhmm})"
            )
            return False
        target.is_recording = True
        self._refresh_monitor_summary()
        self._log(f"[AUTO-RECORD] Preparing recording for {target.platform}/{channel_id}")
        # Per-channel override_output_dir wins over the global Download-tab
        # output. Empty string = use global.
        base_out = (
            target.override_output_dir.strip()
            if getattr(target, "override_output_dir", "")
            else ""
        ) or self.output_input.text().strip() or str(_default_output_dir())
        worker = AutoRecordResolveWorker(channel_id, target.url, base_out)
        worker.log.connect(self._log)
        worker.resolved.connect(self._on_auto_record_resolved)
        worker.error.connect(self._on_auto_record_resolve_error)
        self._autorecord_resolvers[channel_id] = worker
        worker.start()
        return True

    def _on_auto_record_resolved(self, channel_id, info, q, out_dir):
        resolver = self._autorecord_resolvers.pop(channel_id, None)
        if resolver is not None and not resolver.isRunning():
            try:
                resolver.wait(200)
            except Exception:
                pass

        target = None
        for e in self.monitor.entries:
            if e.channel_id == channel_id and e.auto_record and e.is_recording:
                target = e
                break
        if target is None:
            self._refresh_active_recordings_panel()
            self._start_next_background_job()
            return

        # Keyword filter check (F3) — skip if title doesn't match any keyword
        keywords = (target.filter_keywords or "").strip()
        if keywords and info and info.title:
            kw_list = [k.strip().lower() for k in keywords.split(",") if k.strip()]
            title_lower = info.title.lower()
            if kw_list and not any(kw in title_lower for kw in kw_list):
                self._log(
                    f"[AUTO-RECORD] Skipping {channel_id} — title \"{info.title[:60]}\" "
                    f"does not match keywords: {keywords}"
                )
                target.is_recording = False
                self._refresh_monitor_summary()
                self._refresh_active_recordings_panel()
                self._start_next_background_job()
                return

        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            self._log(f"[AUTO-RECORD] Cannot create output folder: {e}")
            target.is_recording = False
            self._refresh_monitor_summary()
            self._refresh_active_recordings_panel()
            self._start_next_background_job()
            return

        # Honor per-channel quality preference if set. "highest" and "" are
        # both no-ops (we were already handed the top quality). For a named
        # resolution ("720p", etc.) we look for a substring match and fall
        # back to the resolver's choice if nothing matches.
        pref = (target.override_quality_pref or "").strip().lower()
        if pref and pref not in ("", "highest") and getattr(info, "qualities", None):
            chosen = None
            for candidate in info.qualities:
                cname = (candidate.name or "").lower()
                cres = (candidate.resolution or "").lower()
                if pref in cname or pref in cres:
                    chosen = candidate
                    break
            if chosen is not None and chosen is not q:
                self._log(f"[AUTO-RECORD] Using channel profile quality: {chosen.name}")
                q = chosen

        segments = [(0, "live_recording", 0, 0)]
        worker = DownloadWorker(q.url, segments, out_dir, q.format_type)
        worker.audio_url = q.audio_url
        worker.parallel_connections = self._parallel_connections
        # Live auto-split: when enabled, long live captures are chunked.
        if self._chunk_long_captures:
            worker.chunk_length_secs = int(self._chunk_length_secs or 0)
        worker.log.connect(self._log)
        worker.error.connect(lambda _idx, err, ch=channel_id: self._auto_record_error(ch, err))
        worker.progress.connect(
            lambda _idx, pct, status, ch=channel_id:
            self._on_autorecord_progress(ch, pct, status)
        )
        worker.all_done.connect(lambda ch=channel_id: self._auto_record_done(ch))
        self._autorecord_workers[channel_id] = worker
        self._autorecord_contexts[channel_id] = {
            "out_dir": out_dir,
            "q_name": q.name or "Live Capture",
            "info": info,
            "history_url": target.url,
            "title": getattr(info, "title", "") or channel_id,
            "had_errors": False,
            "last_status": "",
        }
        self._attach_resume_to_worker(
            worker,
            context={
                "source_url": target.url,
                "platform": getattr(info, "platform", "") or target.platform,
                "title": getattr(info, "title", "") or "",
                "channel": getattr(info, "channel", "") or channel_id,
                "quality_name": q.name or "Live Capture",
                "info": info,
            },
        )
        worker.start()
        # Kick off live chat capture alongside the recording if the user
        # has opted in. Twitch (IRC) and Kick (Pusher) are supported —
        # other platforms fall through silently.
        platform_key = (getattr(info, "platform", "") or "").lower()
        if (bool(self._config.get("capture_live_chat", False))
                and platform_key in ("twitch", "kick")):
            try:
                chat_channel = getattr(info, "channel", "") or channel_id
                chat = ChatWorker(
                    chat_channel, out_dir,
                    platform=platform_key,
                    render_ass=bool(self._config.get("render_chat_ass", True)),
                )
                chat.log.connect(self._log)
                chat.message.connect(self._on_live_chat_message)
                chat.done.connect(
                    lambda cnt, ch=channel_id: self._on_live_chat_done(ch, cnt)
                )
                self._chat_workers[channel_id] = chat
                chat.start()
            except Exception as e:
                self._log(f"[CHAT] Could not start chat capture: {e}")
        self._refresh_active_recordings_panel()
        self._set_status(
            f"Auto-record started for {channel_id}"
            + (f" ({self._active_autorecord_count()} parallel)."
               if self._active_autorecord_count() > 1 else "."),
            "working",
        )

    def _on_live_chat_message(self, nick, text):
        """Append a line to the Download-tab chat dock. Kept lightweight
        so a fast-moving stream doesn't hitch the UI."""
        if not hasattr(self, "chat_log_view"):
            return
        if hasattr(self, "chat_dock") and not self.chat_dock.isVisible():
            self.chat_dock.setVisible(True)
        safe_nick = (nick or "")[:32]
        safe_text = (text or "")[:500]
        self.chat_log_view.append(f"<b>{safe_nick}</b>: {safe_text}")

    def _on_live_chat_done(self, channel_id, count):
        worker = self._chat_workers.pop(channel_id, None)
        if worker is not None and not worker.isRunning():
            try:
                worker.wait(500)
            except Exception:
                pass
        self._log(f"[CHAT] Capture for {channel_id} ended ({count} line(s))")

    def _on_auto_record_resolve_error(self, channel_id, err):
        resolver = self._autorecord_resolvers.pop(channel_id, None)
        if resolver is not None and not resolver.isRunning():
            try:
                resolver.wait(200)
            except Exception:
                pass
        for e in self.monitor.entries:
            if e.channel_id == channel_id:
                e.is_recording = False
        self._refresh_monitor_summary()
        self._refresh_active_recordings_panel()
        self._log(f"[AUTO-RECORD] Error: {err}")
        self._set_status(f"Auto-record could not start for {channel_id}: {err}", "warning")
        self._start_next_background_job()

    def _on_autorecord_progress(self, channel_id, _pct, status):
        """Update the Active Recordings panel entry for this channel."""
        ctx = self._autorecord_contexts.get(channel_id)
        if ctx is None:
            return
        ctx["last_status"] = status or ""
        self._refresh_active_recordings_panel()

    def _on_channel_live(self, channel_id):
        """Called when a monitored channel goes live."""
        self._set_status(f"{channel_id} went live.", "warning")
        self._notify_center(f"{channel_id} is live", "warning")
        self._fire_hook("channel_live", channel=channel_id)
        if self._try_start_auto_record(channel_id):
            return
        worker = getattr(self, "download_worker", None)
        if worker is not None and worker.isRunning():
            self._queue_auto_record_retry(channel_id)
            self._log(
                f"[AUTO-RECORD] Waiting for the current download to finish before retrying {channel_id}"
            )
            self._set_status(
                f"{channel_id} is live. Auto-record will retry when the current job finishes.",
                "warning",
            )

    def _auto_record_done(self, channel_id):
        ctx = self._autorecord_contexts.pop(channel_id, None) or {}
        worker = self._autorecord_workers.pop(channel_id, None)
        if worker is not None and not worker.isRunning():
            try:
                worker.wait(500)
            except Exception:
                pass
        # Stop the paired chat capture (if any) — it flushes .jsonl and .ass
        # sidecars on clean exit.
        chat = self._chat_workers.pop(channel_id, None)
        if chat is not None and chat.isRunning():
            try:
                chat.cancel()
                chat.wait(2000)
            except Exception:
                pass
        finished_entry = None
        for e in self.monitor.entries:
            if e.channel_id == channel_id:
                e.is_recording = False
                finished_entry = e
        out_dir = ctx.get("out_dir", "")
        had_errors = bool(ctx.get("had_errors", False))
        media_present = self._output_contains_media(out_dir)
        # Retention: if this channel has a keep-last limit, prune old
        # sibling recordings from the channel's output root after a
        # successful run.
        if finished_entry is not None and not had_errors and media_present:
            out_root = (
                finished_entry.override_output_dir.strip()
                if getattr(finished_entry, "override_output_dir", "")
                else ""
            ) or self.output_input.text().strip() or str(_default_output_dir())
            try:
                self._apply_retention_for_channel(finished_entry, out_root)
            except Exception as e:
                self._log(f"[RETENTION] error: {e}")
        self._log(f"[AUTO-RECORD] Recording ended for {channel_id}")
        self._refresh_monitor_summary()
        self._refresh_active_recordings_panel()
        if had_errors:
            self._set_status(
                f"Auto-record for {channel_id} ended with errors. Check the log.",
                "warning",
            )
        elif not media_present:
            self._set_status(
                f"Auto-record for {channel_id} finished without saving media.",
                "warning",
            )
        else:
            self._save_metadata(
                out_dir,
                ctx.get("q_name", "Live Capture") or "Live Capture",
                history_url=ctx.get("history_url", ""),
                info=ctx.get("info"),
            )
            # Clear the resume sidecar — live captures never really "finish"
            # via all_done for the single-segment worker, but a successful
            # stop produced media, so we don't need a future resume.
            try:
                clear_resume_state(out_dir)
            except Exception:
                pass
            self._set_status(f"Auto-record finished for {channel_id}.", "success")
        self._start_next_background_job()

    # ── Download Queue ────────────────────────────────────────────────

    def _normalize_queue_item(self, item):
        if not isinstance(item, dict):
            return None
        url = str(item.get("url", "") or "").strip()
        if not url:
            return None
        title = str(item.get("title", "") or "")
        platform = str(item.get("platform", "") or "?")
        vod_source = str(item.get("vod_source", "") or "").strip()
        vod_platform = str(item.get("vod_platform", "") or "").strip()
        vod_title = str(item.get("vod_title", "") or "").strip()
        vod_channel = str(item.get("vod_channel", "") or "").strip()
        if not vod_source and url.isdigit() and platform.lower() == "twitch":
            # Older queue entries stored Twitch VOD IDs as plain URLs, which
            # breaks auto-start because extractor detection expects an actual URL.
            vod_source = url
        if vod_source and not vod_platform:
            vod_platform = platform
        if not vod_title:
            vod_title = title
        normalized = {
            "url": url,
            "title": title or vod_title or url,
            "platform": platform,
            "status": str(item.get("status", "queued") or "queued"),
            "added": str(item.get("added", "") or ""),
            "note": str(item.get("note", "") or ""),
            "start_at": str(item.get("start_at", "") or ""),
            "vod_source": vod_source,
            "vod_platform": vod_platform,
            "vod_title": vod_title,
            "vod_channel": vod_channel,
        }
        vod_date = str(item.get("vod_date", "") or "")
        if vod_date:
            normalized["vod_date"] = vod_date
        return normalized

    def _queue_add(
        self,
        url,
        title="",
        platform="",
        note="",
        start_at="",
        vod_source="",
        vod_platform="",
        vod_title="",
        vod_channel="",
    ):
        """Append a URL to the persistent download queue.
        If start_at (ISO timestamp) is set, the item will only be picked
        up by _advance_queue after that time."""
        if not url:
            return False
        item_key = str(vod_source or url)
        if any(
            (q.get("vod_source") or q.get("url")) == item_key
            and q.get("status") not in ("failed", "cancelled")
            for q in self._download_queue
        ):
            return False
        self._download_queue.append(self._normalize_queue_item({
            "url": url,
            "title": title or vod_title or url,
            "platform": platform or "?",
            "status": "queued",
            "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "note": note,
            "start_at": start_at,
            "vod_source": vod_source,
            "vod_platform": vod_platform,
            "vod_title": vod_title or title,
            "vod_channel": vod_channel,
        }))
        self._persist_config()
        if hasattr(self, "queue_table"):
            self._refresh_queue_table()
        return True

    def _queue_remove(self, idx):
        if 0 <= idx < len(self._download_queue):
            item = self._download_queue[idx]
            if item is self._queue_active_item or item.get("status") in ("fetching", "downloading"):
                self._set_status("The active queue job cannot be removed while it is running.", "warning")
                return None
            removed = self._download_queue.pop(idx)
            self._persist_config()
            if hasattr(self, "queue_table"):
                self._refresh_queue_table()
            return removed
        return None

    def _active_queue_download_count(self):
        """Return the number of currently active queue downloads + fetches."""
        active = len([w for w in self._queue_workers.values() if w.isRunning()])
        active += len([w for w in self._queue_fetch_workers.values() if w.isRunning()])
        # Count the legacy single-worker path too
        if self._queue_active_item is not None:
            active += 1
        return active

    def _advance_queue(self):
        """Start the next queued item(s) up to the concurrent download limit.
        Scheduled items (start_at in the future) are skipped."""
        # Legacy foreground worker blocks legacy queue path
        worker = getattr(self, "download_worker", None)
        fg_busy = worker is not None and worker.isRunning()
        # Check concurrent capacity
        cap = max(1, int(self._max_concurrent_downloads))
        active = self._active_queue_download_count()
        if active >= cap:
            return
        # Also block if legacy single-worker fetch is running and there's
        # an active queue item using the old path
        if self._queue_active_item is not None and fg_busy:
            return
        now = datetime.now()
        ready = []
        active_ids = set(self._queue_workers.keys()) | set(self._queue_fetch_workers.keys())
        for q in self._download_queue:
            if q.get("status") != "queued":
                continue
            if id(q) in active_ids:
                continue
            start_at = q.get("start_at", "")
            if start_at:
                try:
                    ts = datetime.fromisoformat(start_at)
                    if ts > now:
                        continue
                except Exception:
                    pass
            ready.append(q)
            if active + len(ready) >= cap:
                break
        if not ready:
            return
        for item in ready:
            self._start_queue_item(item)

    def _start_queue_item(self, item):
        """Launch a fetch→download pipeline for a single queue item using
        a dedicated FetchWorker (concurrent, doesn't touch the UI state)."""
        item_id = id(item)
        self._set_queue_item_status(item, "fetching")
        self._log(f"[QUEUE] Starting: {item.get('title', '')[:60]}")
        # Use a dedicated FetchWorker that doesn't share the foreground UI state
        url = item.get("vod_source") or item["url"]
        fetch = FetchWorker(url)
        fetch.finished.connect(
            lambda info, it=item: self._on_queue_fetch_done(it, info)
        )
        fetch.error.connect(
            lambda err, it=item: self._on_queue_fetch_error(it, err)
        )
        self._queue_fetch_workers[item_id] = fetch
        fetch.start()

    def _on_queue_fetch_done(self, item, info):
        """Handle fetch completion for a concurrent queue item."""
        item_id = id(item)
        fw = self._queue_fetch_workers.pop(item_id, None)
        if fw and not fw.isRunning():
            try:
                fw.wait(200)
            except Exception:
                pass
        if info is None:
            self._set_queue_item_status(item, "failed", "Fetch returned no data")
            self._log(f"[QUEUE] Fetch failed: {item.get('title', '')[:60]}")
            self._advance_queue()
            return
        # Pick the best quality
        q_data = None
        if info.qualities:
            q_data = info.qualities[0]  # Highest quality (pre-sorted)
        if q_data is None and not info.url:
            self._set_queue_item_status(item, "failed", "No playable quality")
            self._advance_queue()
            return
        # Build segments and output path
        playlist_url = q_data.url if q_data else info.url
        fmt_type = q_data.format_type if q_data else "hls"
        audio_url = q_data.audio_url if q_data else ""
        ytdlp_source = q_data.ytdlp_source if q_data else ""
        ytdlp_format = q_data.ytdlp_format if q_data else ""
        is_live = info.is_live or info.total_secs <= 0
        title_safe = _safe_filename(info.title or item.get("title") or "download")
        segments = [(0, title_safe, 0, 0 if is_live else int(info.total_secs))]
        ctx = _build_template_context(info)
        folder_parts = _render_template(self._folder_template, ctx)
        base_out = self.output_input.text().strip() or str(_default_output_dir())
        out_dir = os.path.join(base_out, *folder_parts) if folder_parts else base_out
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            self._set_queue_item_status(item, "failed", f"Cannot create dir: {e}")
            self._advance_queue()
            return
        # Create and start the DownloadWorker
        self._set_queue_item_status(item, "downloading")
        self._log(f"[QUEUE] Downloading: {info.title or item.get('title', '')[:60]} → {out_dir}")
        worker = DownloadWorker(playlist_url or "", segments, out_dir, format_type=fmt_type)
        worker.audio_url = audio_url
        worker.ytdlp_source = ytdlp_source
        worker.ytdlp_format = ytdlp_format
        worker.cookies_browser = YtDlpExtractor.cookies_browser
        # Share bandwidth across concurrent workers
        rl = YtDlpExtractor.rate_limit
        active_count = self._active_queue_download_count() + 1
        if rl and active_count > 1:
            try:
                import re as _re
                # Parse yt-dlp rate limit format: number + optional suffix
                m = _re.match(r'^([\d.]+)\s*([KkMmGg])?', str(rl))
                if m:
                    val = float(m.group(1))
                    suffix = (m.group(2) or "").upper()
                    multiplier = {"K": 1_000, "M": 1_000_000, "G": 1_000_000_000}.get(suffix, 1)
                    rl_bytes = int(val * multiplier)
                    shared = max(100_000, rl_bytes // active_count)
                    rl = str(shared)
            except (ValueError, AttributeError):
                pass
        worker.rate_limit = rl
        worker.proxy = YtDlpExtractor.proxy
        worker.download_subs = YtDlpExtractor.download_subs
        worker.sponsorblock = YtDlpExtractor.sponsorblock
        worker.parallel_connections = self._parallel_connections
        worker.log.connect(self._log)
        worker.all_done.connect(lambda it=item, inf=info: self._on_queue_item_done(it, inf, out_dir))
        worker.error.connect(lambda _idx, err, it=item: self._on_queue_item_error(it, err))
        self._queue_workers[item_id] = worker
        self._queue_contexts[item_id] = {
            "out_dir": out_dir, "info": info,
            "q_name": q_data.name if q_data else "",
        }
        worker.start()
        self._update_tray_badge()
        self._refresh_queue_table()
        # Try to fill remaining slots
        self._advance_queue()

    def _on_queue_fetch_error(self, item, err):
        """Handle fetch error for a concurrent queue item."""
        item_id = id(item)
        fw = self._queue_fetch_workers.pop(item_id, None)
        # Join the thread to prevent resource leaks (mirrors _on_queue_fetch_done)
        if fw:
            try:
                fw.wait(500)
            except Exception:
                pass
        self._set_queue_item_status(item, "failed", str(err)[:120])
        self._log(f"[QUEUE] Fetch error for {item.get('title', '')[:60]}: {err}")
        self._advance_queue()

    def _on_queue_item_done(self, item, info, out_dir):
        """Handle download completion for a concurrent queue item."""
        item_id = id(item)
        ctx = self._queue_contexts.pop(item_id, {})
        worker = self._queue_workers.pop(item_id, None)
        if worker and not worker.isRunning():
            try:
                worker.wait(500)
            except Exception:
                pass
        title = info.title if info else item.get("title", "Download")
        self._log(f"[QUEUE] Complete: {title[:60]}")
        self._notify_center(f"Queue download complete: {title[:50]}", "success")
        self._fire_hook("download_complete", title=title)
        # Save metadata + history entry
        q_name = ctx.get("q_name", "")
        self._save_metadata(out_dir, q_name, history_url=item.get("url", ""), info=info)
        self._media_server_import(out_dir, info)
        # Handle recurrence or mark done
        rec = (item.get("recurrence") or "").strip()
        if rec:
            next_fire = self._compute_next_fire(item)
            if next_fire:
                item["status"] = "queued"
                item["start_at"] = next_fire.isoformat()
                item["note"] = f"recurring ({rec}) — next fire {next_fire.strftime('%Y-%m-%d %H:%M')}"
            else:
                item["status"] = "done"
        else:
            item["status"] = "done"
        self._queue_status_changed()
        self._update_tray_badge()
        self._advance_queue()

    def _on_queue_item_error(self, item, err):
        """Handle download error for a concurrent queue item."""
        item_id = id(item)
        self._queue_contexts.pop(item_id, None)
        worker = self._queue_workers.pop(item_id, None)
        if worker and not worker.isRunning():
            try:
                worker.wait(500)
            except Exception:
                pass
        self._set_queue_item_status(item, "failed", str(err)[:120])
        self._log(f"[QUEUE] Error: {item.get('title', '')[:60]} — {err}")
        self._advance_queue()

    def _refresh_queue_table(self):
        if not hasattr(self, "queue_table"):
            return
        self.queue_table.setRowCount(len(self._download_queue))
        now = datetime.now()
        for i, q in enumerate(self._download_queue):
            # Compute effective status: "scheduled" if start_at is in the future
            status = q.get("status", "queued")
            locked = (
                q is self._queue_active_item
                or id(q) in self._queue_workers
                or id(q) in self._queue_fetch_workers
                or status in ("fetching", "downloading")
            )
            start_at = q.get("start_at", "")
            is_scheduled = False
            if start_at and status == "queued":
                try:
                    ts = datetime.fromisoformat(start_at)
                    if ts > now:
                        is_scheduled = True
                except Exception:
                    pass
            display_status = "SCHEDULED" if is_scheduled else status.upper()
            status_item = QTableWidgetItem(display_status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_scheduled:
                status_item.setForeground(QColor(CAT["peach"]))
            elif status in ("fetching", "downloading"):
                status_item.setForeground(QColor(CAT["blue"]))
            elif status == "queued":
                status_item.setForeground(QColor(CAT["yellow"]))
            elif status in ("failed", "cancelled"):
                status_item.setForeground(QColor(CAT["red"]))
            self.queue_table.setItem(i, 0, status_item)
            self.queue_table.setItem(i, 1, QTableWidgetItem(q.get("platform", "?")))
            self.queue_table.setItem(i, 2, QTableWidgetItem(q.get("title", "")[:80]))
            # Added / Scheduled column
            added = q.get("added", "")
            if is_scheduled:
                added = f"@ {start_at[:16].replace('T', ' ')}"
            self.queue_table.setItem(i, 3, QTableWidgetItem(added))
            # Move up/down buttons (single cell with two stacked buttons)
            move_widget = QWidget()
            move_lay = QHBoxLayout(move_widget)
            move_lay.setContentsMargins(2, 2, 2, 2)
            move_lay.setSpacing(2)
            up_btn = QPushButton("↑")
            up_btn.setObjectName("ghost")
            up_btn.setFixedWidth(28)
            up_btn.setToolTip("Move up")
            up_btn.clicked.connect(lambda _c=False, row=i: self._queue_move(row, -1))
            down_btn = QPushButton("↓")
            down_btn.setObjectName("ghost")
            down_btn.setFixedWidth(28)
            down_btn.setToolTip("Move down")
            down_btn.clicked.connect(lambda _c=False, row=i: self._queue_move(row, 1))
            if i == 0 or locked:
                up_btn.setEnabled(False)
            if i == len(self._download_queue) - 1 or locked:
                down_btn.setEnabled(False)
            if locked:
                tip = "Active jobs stay pinned until the current fetch/download finishes."
                up_btn.setToolTip(tip)
                down_btn.setToolTip(tip)
            move_lay.addWidget(up_btn)
            move_lay.addWidget(down_btn)
            self.queue_table.setCellWidget(i, 4, move_widget)
            # Remove button
            rm_btn = QPushButton("Remove")
            rm_btn.setObjectName("secondary")
            rm_btn.clicked.connect(lambda _c=False, row=i: self._queue_remove(row))
            if locked:
                rm_btn.setEnabled(False)
                rm_btn.setToolTip("Stop the current job before removing it from the queue.")
            self.queue_table.setCellWidget(i, 5, rm_btn)
        self._refresh_shell_overview()

    def _queue_move(self, idx, direction):
        """Move a queue item up (-1) or down (+1)."""
        if idx < 0 or idx >= len(self._download_queue):
            return
        target = idx + direction
        if target < 0 or target >= len(self._download_queue):
            return
        item = self._download_queue[idx]
        other = self._download_queue[target]
        locked_statuses = {"fetching", "downloading"}
        if (
            item is self._queue_active_item
            or other is self._queue_active_item
            or item.get("status") in locked_statuses
            or other.get("status") in locked_statuses
        ):
            self._set_status("The active queue job cannot be reordered while it is running.", "warning")
            return
        self._download_queue[idx], self._download_queue[target] = (
            self._download_queue[target], self._download_queue[idx]
        )
        self._persist_config()
        self._refresh_queue_table()

    @staticmethod
    def _quality_rank(quality_str):
        """Parse a quality string like '1080p', 'source', '720p60' into a
        numeric rank for comparison.  Higher is better."""
        if not quality_str:
            return 0
        q = quality_str.lower().strip()
        if q in ("source", "best", "highest"):
            return 9999
        digits = ""
        for c in q:
            if c.isdigit():
                digits += c
            elif digits:
                break
        return int(digits) if digits else 0

    def _check_quality_upgrade(self, channel_id, vod):
        """Return True if *vod* should trigger a quality upgrade for
        an existing recording of the same content."""
        entry = None
        for e in self.monitor.entries:
            if e.channel_id == channel_id:
                entry = e
                break
        if not entry or not entry.auto_upgrade:
            return False
        # Find existing recording in history for this channel
        existing = None
        for h in reversed(self._history):
            if (h.channel or "").lower() == channel_id.lower():
                existing = h
                break
        if not existing or not existing.quality:
            return False
        # Compare quality rank
        existing_rank = self._quality_rank(existing.quality)
        # Use the VOD's resolution if available; otherwise skip
        vod_quality = getattr(vod, "quality", "") or ""
        if not vod_quality:
            return False
        new_rank = self._quality_rank(vod_quality)
        if new_rank <= existing_rank:
            return False
        # Check minimum upgrade threshold
        min_q = entry.min_upgrade_quality or ""
        if min_q:
            min_rank = self._quality_rank(min_q)
            if new_rank < min_rank:
                return False
        self._log(
            f"[UPGRADE] {channel_id}: {existing.quality} → {vod_quality} "
            f"— queuing quality upgrade"
        )
        return True

    def _on_new_vods_found(self, channel_id, vods):
        """New VODs from a subscribed channel — queue their source URLs
        so they get downloaded in the background."""
        added = 0
        for v in vods:
            # Quality auto-upgrade check (F25)
            is_upgrade = self._check_quality_upgrade(channel_id, v)
            # Skip if already in history (prevents re-downloading on seed)
            if not is_upgrade and self._find_duplicate("", v.title, platform=v.platform):
                continue
            if self._queue_add(
                v.source,
                title=v.title,
                platform=v.platform,
                vod_source=v.source,
                vod_platform=v.platform,
                vod_title=v.title,
                vod_channel=v.channel,
            ):
                if self._download_queue:
                    self._download_queue[-1]["vod_date"] = v.date
                    if is_upgrade:
                        self._download_queue[-1]["is_upgrade"] = True
                added += 1
                tag = "[UPGRADE]" if is_upgrade else "[SUBSCRIBE]"
                self._log(f"{tag} Queued: {v.title[:60]}")
        if added and hasattr(self, "queue_table"):
            self._refresh_queue_table()
        # Kick off the queue if nothing is downloading
        if getattr(self.download_worker, "isRunning", lambda: False)() is False:
            self._advance_queue()

    # ── History Actions ───────────────────────────────────────────────

    def _add_history(self, platform, title, quality, size, path, url="", channel=""):
        entry = HistoryEntry(
            date=datetime.now().strftime("%Y-%m-%d %H:%M"),
            platform=platform, title=title[:60],
            channel=self._infer_history_channel(url=url, platform=platform, channel=channel),
            quality=quality, size=size, path=path, url=url,
        )
        # Persist to SQLite immediately (F41)
        entry.db_id = _db.save_history_entry(entry.to_dict())
        self._history.append(entry)
        self._refresh_history_table()
        self._schedule_persist_config()

    def _refresh_history_table(self):
        query = ""
        if hasattr(self, "history_search"):
            query = self.history_search.text().strip().lower()
        ordered = list(reversed(self._history))
        # Transcript FTS search mode (F27)
        transcript_mode = (
            hasattr(self, "transcript_search_check")
            and self.transcript_search_check.isChecked()
        )
        self._transcript_hits = {}  # path -> list of {text, start_sec, end_sec}
        if query and transcript_mode:
            from ..search import search_transcripts
            try:
                hits = search_transcripts(query, limit=200)
            except Exception:
                hits = []
            hit_paths = set()
            for h in hits:
                rp = h["recording_path"]
                hit_paths.add(rp)
                self._transcript_hits.setdefault(rp, []).append(h)
            ordered = [h for h in ordered if h.path in hit_paths]
        elif query:
            ordered = [
                h for h in ordered
                if query in (h.title or "").lower()
                or query in (h.platform or "").lower()
                or query in (self._history_channel_label(h) or "").lower()
                or query in (h.path or "").lower()
                or query in (h.url or "").lower()
            ]
        self._history_view = ordered  # used by double-click handler
        self.history_table.setRowCount(len(ordered))
        _dim_color = QColor(CAT["overlay0"])
        _warn_prefix = "\u26a0 "  # ⚠
        for i, h in enumerate(ordered):
            # Check if the recorded path still exists on disk (F14 orphan detection).
            orphan = bool(h.path) and not os.path.isdir(h.path)
            # Column 0 = thumbnail cell (lazy-loaded).
            thumb_label = QLabel()
            thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb_label.setStyleSheet(
                f"background-color: {CAT['mantle']}; border-radius: 6px; color: {CAT['overlay0']};"
            )
            thumb_label.setText(_warn_prefix if orphan else "…")
            self.history_table.setCellWidget(i, 0, thumb_label)
            # Data columns 1..6
            # Build title with watch/favorite indicators (F38)
            title_display = h.title or ""
            status_prefix = ""
            if getattr(h, "favorite", False):
                status_prefix += "\u2605 "  # ★
            if getattr(h, "watched", False):
                status_prefix += "\u2713 "  # ✓
            elif getattr(h, "watch_position_secs", 0) > 0:
                status_prefix += "\u25b6 "  # ▶
            title_display = status_prefix + title_display
            for col, val in enumerate([h.date, h.platform, title_display, h.quality, h.size, h.path], start=1):
                display = val
                if orphan and col == 6 and val:
                    display = val + "  (missing)"
                item = QTableWidgetItem(display)
                if col in (1, 2, 4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if orphan:
                    item.setForeground(_dim_color)
                elif getattr(h, "watched", False) and col == 3:
                    item.setForeground(QColor(CAT["overlay0"]))
                # Transcript search hit snippet as tooltip (F27)
                if col == 3 and h.path and h.path in self._transcript_hits:
                    snippets = self._transcript_hits[h.path][:3]
                    tip_lines = []
                    for s in snippets:
                        mins = int(s["start_sec"]) // 60
                        secs = int(s["start_sec"]) % 60
                        tip_lines.append(f"[{mins}:{secs:02d}] {s['text']}")
                    item.setToolTip("\n".join(tip_lines))
                self.history_table.setItem(i, col, item)
            # Queue a thumb request (skip orphans — no file to thumbnail).
            if not orphan:
                media = self._first_media_file(h.path) if h.path else ""
                if media:
                    self._history_thumb_loader.request((h.path, h.title), media)
        self._refresh_history_summary()

    def _first_media_file(self, dir_path):
        if not dir_path or not os.path.isdir(dir_path):
            return ""
        try:
            for entry in sorted(os.scandir(dir_path), key=lambda e: e.name):
                if not entry.is_file():
                    continue
                ext = os.path.splitext(entry.name)[1].lower()
                # Pick the biggest video file — matches user intuition for
                # "the recording" vs a tiny preview / chat json.
                if ext in {".mp4", ".mkv", ".webm", ".mov", ".ts"}:
                    return entry.path
        except OSError:
            return ""
        return ""

    def _on_history_thumb_ready(self, row_key, pix):
        """Loader emitted a thumb — find the matching row and paint it."""
        view = getattr(self, "_history_view", None) or []
        for i, h in enumerate(view):
            if (h.path, h.title) == row_key:
                label = self.history_table.cellWidget(i, 0)
                if label is not None:
                    label.setPixmap(pix.scaled(
                        100, 56,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                return

    # ── Hover Preview (F46) ───────────────────────────────────────────

    def _on_history_cell_hover(self, row, col):
        """When the mouse enters a history table row, start the animated
        preview on the thumbnail column (col 0)."""
        view = getattr(self, "_history_view", None) or []
        if row < 0 or row >= len(view):
            self._preview_loader.stop_preview()
            return
        h = view[row]
        if not h.path or not os.path.isdir(h.path):
            self._preview_loader.stop_preview()
            return
        # Find first media file in the recording dir
        media = ""
        for fn in os.listdir(h.path):
            if fn.lower().endswith((".mp4", ".mkv", ".ts", ".webm", ".flv")):
                media = os.path.join(h.path, fn)
                break
        if not media:
            self._preview_loader.stop_preview()
            return
        self._preview_loader.start_preview((row, "history"), media)

    def _on_preview_frame(self, row_key, pix):
        """PreviewLoader emitted a frame — update the thumbnail cell."""
        row, source = row_key
        if source == "history":
            table = self.history_table
        else:
            return
        label = table.cellWidget(row, 0)
        if label is not None:
            label.setPixmap(pix.scaled(
                100, 56,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def _on_storage_thumb_ready(self, row_key, pix):
        """Loader emitted a thumb — find the matching storage row and paint it."""
        groups = getattr(self, "_storage_groups", None) or []
        for i, g in enumerate(groups):
            if g.dir_path == row_key:
                label = self.storage_table.cellWidget(i, 0)
                if label is not None:
                    label.setPixmap(pix.scaled(
                        100, 56,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                return

    def _on_history_search(self, _text):
        self._refresh_history_table()

    def _on_clear_history(self):
        self._history.clear()
        _db.clear_history()
        self._refresh_history_table()
        self._persist_config()
        self._set_status("Download history cleared.", "success")

    def _on_history_context_menu(self, pos):
        """Right-click menu for the history table — offers Trim for files
        that still exist on disk."""
        table = self.history_table
        idx = table.indexAt(pos)
        if not idx.isValid():
            return
        row = idx.row()
        view = getattr(self, "_history_view", list(reversed(self._history)))
        if row >= len(view):
            return
        h = view[row]
        menu = QMenu(self)
        open_act = menu.addAction("Open Folder")
        open_act.setEnabled(bool(h.path and os.path.isdir(h.path)))
        trim_act = menu.addAction("Trim / Clip...")
        trim_act.setEnabled(bool(h.path and os.path.isdir(h.path)))
        bundle_act = menu.addAction("Export share bundle (.zip)...")
        bundle_act.setEnabled(bool(h.path and os.path.isdir(h.path)))
        transcribe_act = menu.addAction("Transcribe (Whisper)...")
        transcribe_act.setEnabled(bool(h.path and os.path.isdir(h.path)))
        silence_act = menu.addAction("Remove silence...")
        silence_act.setEnabled(bool(h.path and os.path.isdir(h.path)))
        # Chat highlights (F8) — only if chat.jsonl exists
        has_chat = bool(
            h.path and os.path.isdir(h.path)
            and os.path.isfile(os.path.join(h.path, "chat.jsonl"))
        )
        chat_highlights_act = menu.addAction("Show chat highlights")
        chat_highlights_act.setEnabled(has_chat)
        chat_render_act = menu.addAction("Render chat overlay...")
        chat_render_act.setEnabled(has_chat)
        chat_preview_act = menu.addAction("Preview chat render (60s)")
        chat_preview_act.setEnabled(has_chat)
        storyboard_act = menu.addAction("Generate storyboard")
        storyboard_act.setEnabled(bool(h.path and os.path.isdir(h.path)))
        highlight_act = menu.addAction("Generate highlights (AI)")
        highlight_act.setEnabled(bool(h.path and os.path.isdir(h.path)))
        menu.addSeparator()
        # Watch status + bookmarks (F38)
        watched_label = "Mark as unwatched" if getattr(h, "watched", False) else "Mark as watched"
        watch_act = menu.addAction(watched_label)
        fav_label = "Remove from favorites" if getattr(h, "favorite", False) else "Add to favorites"
        fav_act = menu.addAction(fav_label)
        bookmark_act = menu.addAction("Add bookmark…")
        # Multi-stream sync (F54) — show when 2+ rows are selected
        selected_rows = sorted({idx.row() for idx in table.selectionModel().selectedRows()})
        sync_entries = [view[r] for r in selected_rows if 0 <= r < len(view)]
        sync_act = menu.addAction(f"Watch together ({len(sync_entries)} streams)")
        sync_act.setEnabled(len(sync_entries) >= 2)
        menu.addSeparator()
        redownload_act = menu.addAction("Re-download")
        redownload_act.setEnabled(bool(h.url))
        rename_act = menu.addAction("Batch Rename…")
        remove_act = menu.addAction("Remove from History")
        # Orphan cleanup (F14) — only show when orphans exist
        orphan_count = sum(
            1 for e in self._history if e.path and not os.path.isdir(e.path)
        )
        remove_missing_act = None
        if orphan_count > 0:
            remove_missing_act = menu.addAction(
                f"Remove missing entries ({orphan_count})"
            )
        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if chosen == sync_act and len(sync_entries) >= 2:
            self._open_sync_viewer(sync_entries)
        elif chosen == open_act and h.path and os.path.isdir(h.path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(h.path))
        elif chosen == trim_act and h.path and os.path.isdir(h.path):
            self._open_clip_dialog_for_dir(h.path)
        elif chosen == bundle_act and h.path and os.path.isdir(h.path):
            self._start_bundle_export(h.path)
        elif chosen == transcribe_act and h.path and os.path.isdir(h.path):
            self._start_transcribe_for_dir(h.path)
        elif chosen == silence_act and h.path and os.path.isdir(h.path):
            self._run_silence_removal_for_dir(h.path)
        elif chosen == chat_highlights_act and has_chat:
            self._show_chat_highlights(h.path)
        elif chosen == chat_render_act and has_chat:
            self._start_chat_render(h.path, preview_secs=0)
        elif chosen == chat_preview_act and has_chat:
            self._start_chat_render(h.path, preview_secs=60)
        elif chosen == storyboard_act and h.path:
            self._generate_storyboard(h.path)
        elif chosen == highlight_act and h.path:
            self._generate_highlights(h.path)
        elif chosen == watch_act:
            h.watched = not getattr(h, "watched", False)
            if h.watched:
                h.watch_position_secs = 0.0
            if getattr(h, "db_id", 0):
                _db.update_history_entry(h.db_id, {
                    "watched": h.watched,
                    "watch_position_secs": h.watch_position_secs,
                })
            self._refresh_history_table()
            self._persist_config()
        elif chosen == fav_act:
            h.favorite = not getattr(h, "favorite", False)
            if getattr(h, "db_id", 0):
                _db.update_history_entry(h.db_id, {"favorite": h.favorite})
            self._refresh_history_table()
            self._persist_config()
        elif chosen == bookmark_act:
            self._add_bookmark_dialog(h)
        elif chosen == rename_act:
            from .rename_dialog import RenameDialog
            entries = [e for e in self._history if e.path and os.path.isdir(e.path)]
            if entries:
                RenameDialog(self, entries).exec()
        elif chosen == redownload_act and h.url:
            self._redownload_from_history(h)
        elif chosen == remove_act:
            try:
                real = self._history.index(h)
                self._history.pop(real)
                if getattr(h, "db_id", 0):
                    _db.delete_history_entries([h.db_id])
                self._refresh_history_table()
                self._persist_config()
            except ValueError:
                pass
        elif remove_missing_act and chosen == remove_missing_act:
            orphans = [e for e in self._history if e.path and not os.path.isdir(e.path)]
            orphan_db_ids = [e.db_id for e in orphans if getattr(e, "db_id", 0)]
            before = len(self._history)
            self._history = [
                e for e in self._history
                if not e.path or os.path.isdir(e.path)
            ]
            removed = before - len(self._history)
            if orphan_db_ids:
                _db.delete_history_entries(orphan_db_ids)
            self._refresh_history_table()
            self._persist_config()
            self._set_status(
                f"Removed {removed} missing history entries.", "success"
            )

    def _add_bookmark_dialog(self, h):
        """Show a dialog to add a named timestamp bookmark to a recording (F38)."""
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Bookmark")
        dlg.setMinimumWidth(340)
        form = QFormLayout(dlg)
        name_input = QLineEdit()
        name_input.setPlaceholderText("e.g. Funny moment")
        form.addRow("Name:", name_input)
        time_input = QLineEdit()
        time_input.setPlaceholderText("HH:MM:SS")
        form.addRow("Timestamp:", time_input)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = name_input.text().strip() or "Bookmark"
        secs = self._parse_crop_secs(time_input.text().strip()) or 0
        if not hasattr(h, "bookmarks") or h.bookmarks is None:
            h.bookmarks = []
        h.bookmarks.append({"name": name, "secs": secs})
        if getattr(h, "db_id", 0):
            _db.update_history_entry(h.db_id, {"bookmarks": h.bookmarks})
        self._persist_config()
        self._log(f"[BOOKMARK] Added '{name}' at {time_input.text().strip()} to {h.title[:40]}")

    def _redownload_from_history(self, h):
        """Pre-fill the Download tab from a HistoryEntry and trigger fetch."""
        self._switch_tab(0)
        self.url_input.setText(h.url)
        # Restore output dir to the parent of the original recording folder
        if h.path:
            parent = os.path.dirname(h.path)
            if parent and os.path.isdir(parent):
                self.output_input.setText(parent)
        self._log(f"[RE-DOWNLOAD] {h.title or h.url[:80]}")
        self._on_fetch()

    def _show_chat_highlights(self, src_dir):
        """Show chat spike timestamps in the log and open Trim dialog."""
        jsonl = os.path.join(src_dir, "chat.jsonl")
        if not os.path.isfile(jsonl):
            return
        try:
            from ..chat.spike_detect import detect_spikes
        except Exception:
            self._log("[CHAT] Could not load spike detector.")
            return
        spikes = detect_spikes(jsonl)
        if not spikes:
            self._log("[CHAT] No chat activity spikes found.")
            self._set_status("No chat spikes detected in this recording.", "info")
            return
        self._log(f"\n[CHAT] Found {len(spikes)} chat spike(s):")
        for sp in spikes:
            t = sp["time"]
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = int(t % 60)
            self._log(
                f"  {h:02d}:{m:02d}:{s:02d}  —  "
                f"{sp['count']} msgs ({sp['score']:.1f}σ)"
            )
        self._set_status(f"{len(spikes)} chat spike(s) found — see log.", "success")
        # Open trim dialog so user sees the spike markers on the filmstrip
        self._open_clip_dialog_for_dir(src_dir)

    def _generate_storyboard(self, src_dir):
        """Run scene detection on the largest video in the folder."""
        vids = []
        try:
            for f in os.listdir(src_dir):
                ext = os.path.splitext(f)[1].lower()
                if ext in (".mp4", ".mkv", ".webm", ".ts"):
                    fp = os.path.join(src_dir, f)
                    if os.path.isfile(fp):
                        vids.append((os.path.getsize(fp), fp))
        except OSError:
            pass
        if not vids:
            self._set_status("No video files found.", "warning")
            return
        vids.sort(reverse=True)
        src = vids[0][1]
        try:
            from ..postprocess.scene_worker import SceneWorker
        except Exception:
            self._log("[SCENE] Could not load scene detector.")
            return
        worker = SceneWorker(src)
        worker.log.connect(self._log)
        worker.scenes_ready.connect(
            lambda scenes: self._on_storyboard_ready(scenes, src_dir))
        worker.progress.connect(lambda _p, s: self._set_status(s, "info"))
        self._storyboard_worker = worker
        worker.start()
        self._set_status("Running scene detection…", "info")

    def _on_storyboard_ready(self, scenes, src_dir):
        if scenes:
            n = len(scenes)
            self._log(f"[SCENE] Storyboard generated — {n} scene(s).")
            self._set_status(
                f"Storyboard ready — {n} scenes. Open Trim dialog to view.",
                "success")
        else:
            self._set_status(
                "No scenes detected or scenedetect not installed.", "warning")

    def _run_silence_removal_for_dir(self, src_dir):
        """Run silence removal on the largest video in the folder."""
        vids = []
        try:
            for f in os.listdir(src_dir):
                ext = os.path.splitext(f)[1].lower()
                if ext in (".mp4", ".mkv", ".webm", ".ts"):
                    fp = os.path.join(src_dir, f)
                    if ".nosilence" not in f and os.path.isfile(fp):
                        vids.append((os.path.getsize(fp), fp))
        except OSError:
            pass
        if not vids:
            self._set_status("No video files found in folder.", "warning")
            return
        vids.sort(reverse=True)
        src = vids[0][1]
        self._log(f"[POST] Running silence removal on: {os.path.basename(src)}")
        self._set_status("Removing silence — this may take a minute…", "working")
        PostProcessor._run_silence_removal(src, self._log)
        self._set_status("Silence removal complete.", "success")

    def _start_transcribe_for_dir(self, src_dir):
        """Pick the biggest video in the folder and launch TranscribeWorker."""
        from ..postprocess import TranscribeWorker, whisper_available
        if not whisper_available():
            self._set_status(
                "No Whisper runtime installed. Install `faster-whisper` "
                "or put whisper.cpp in PATH.",
                "warning",
            )
            self._log("[TRANSCRIBE] No runtime found. See status bar.")
            return
        if getattr(self, "_transcribe_worker", None) is not None and self._transcribe_worker.isRunning():
            self._set_status("A transcription is already running.", "warning")
            return
        # Find the largest mp4/mkv/webm in the folder.
        media = None
        biggest = 0
        try:
            scan_iter = os.scandir(src_dir)
        except OSError as e:
            self._log(f"[TRANSCRIBE] Cannot read directory: {e}")
            return
        for entry in scan_iter:
            if not entry.is_file():
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            if ext in {".mp4", ".mkv", ".webm", ".mov", ".ts"}:
                try:
                    sz = entry.stat().st_size
                except OSError:
                    continue
                if sz > biggest:
                    biggest = sz
                    media = entry.path
        if not media:
            self._set_status("No video file to transcribe in that folder.", "warning")
            return
        model = str(self._config.get("whisper_model", "tiny") or "tiny")
        worker = TranscribeWorker(
            media, model_name=model,
            enable_diarization=bool(self._config.get("enable_diarization")),
            hf_token=str(self._config.get("hf_token", "") or ""),
        )
        worker.progress.connect(self._on_transcribe_progress)
        worker.done.connect(self._on_transcribe_done)
        self._transcribe_worker = worker
        self._set_status(
            f"Transcribing {os.path.basename(media)} with Whisper ({model})...",
            "processing",
        )
        worker.start()

    def _on_transcribe_progress(self, pct, status):
        self._set_status(f"Transcribing: {status} ({pct}%)", "processing")

    def _on_transcribe_done(self, ok, path_or_err):
        w = getattr(self, "_transcribe_worker", None)
        if w is not None and not w.isRunning():
            try:
                w.wait(300)
            except Exception:
                pass
        self._transcribe_worker = None
        if ok:
            self._log(f"[TRANSCRIBE] Wrote .srt / .vtt / .json / .chapters.auto.txt next to {path_or_err}")
            self._set_status(
                "Transcribe complete. SRT, VTT, and auto-chapters saved.",
                "success",
            )
            self._notify_center(f"Transcribe finished: {os.path.basename(path_or_err)}", "success")
        else:
            self._log(f"[TRANSCRIBE] {path_or_err}")
            self._set_status(f"Transcribe failed: {path_or_err}", "error")

    # ── Chat render (F22) ────────────────────────────────────────────

    def _start_chat_render(self, src_dir, preview_secs=0):
        """Launch a ChatRenderWorker for a directory that has chat.jsonl."""
        jsonl_path = os.path.join(src_dir, "chat.jsonl")
        if not os.path.isfile(jsonl_path):
            self._set_status("No chat.jsonl found in that folder.", "warning")
            return
        if getattr(self, "_chat_render_worker", None) is not None and self._chat_render_worker.isRunning():
            self._set_status("A chat render is already running.", "warning")
            return
        from ..postprocess.chat_render_worker import ChatRenderWorker
        cfg = self._config
        suffix = "_preview" if preview_secs else ""
        out_path = os.path.join(src_dir, f"chat_render{suffix}.mp4")
        worker = ChatRenderWorker(
            jsonl_path, out_path,
            width=int(cfg.get("chat_render_width", 400) or 400),
            height=int(cfg.get("chat_render_height", 600) or 600),
            font_size=int(cfg.get("chat_render_font_size", 14) or 14),
            msg_duration=float(cfg.get("chat_render_msg_duration", 8.0) or 8.0),
            bg_opacity=int(cfg.get("chat_render_bg_opacity", 180) or 180),
            preview_secs=preview_secs,
        )
        worker.progress.connect(self._on_chat_render_progress)
        worker.log.connect(self._log)
        worker.done.connect(self._on_chat_render_done)
        self._chat_render_worker = worker
        label = "preview" if preview_secs else "full"
        self._set_status(f"Rendering chat overlay ({label})...", "processing")
        worker.start()

    def _on_chat_render_progress(self, pct, status):
        self._set_status(f"Chat render: {status} ({pct}%)", "processing")

    def _on_chat_render_done(self, ok, path_or_err):
        w = getattr(self, "_chat_render_worker", None)
        if w is not None and not w.isRunning():
            try:
                w.wait(300)
            except Exception:
                pass
        self._chat_render_worker = None
        if ok:
            self._log(f"[CHAT RENDER] Output: {path_or_err}")
            self._set_status("Chat render complete.", "success")
            self._notify_center(f"Chat render done: {os.path.basename(path_or_err)}", "success")
        else:
            self._log(f"[CHAT RENDER] Failed: {path_or_err}")
            self._set_status(f"Chat render failed: {path_or_err}", "error")

    def _start_bundle_export(self, src_dir):
        """Offer a save-file dialog then run a BundleWorker. One worker at
        a time — the button / context action disables until it finishes."""
        if getattr(self, "_bundle_worker", None) is not None and self._bundle_worker.isRunning():
            self._set_status("A bundle is already in progress.", "warning")
            return
        default_name = os.path.basename(src_dir.rstrip(os.sep)) + ".zip"
        parent = os.path.dirname(src_dir.rstrip(os.sep)) or src_dir
        default_path = os.path.join(parent, default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export share bundle", default_path, "Zip archive (*.zip)"
        )
        if not path:
            return
        from ..postprocess import BundleWorker
        worker = BundleWorker(src_dir, path)
        worker.progress.connect(self._on_bundle_progress)
        worker.done.connect(self._on_bundle_done)
        self._bundle_worker = worker
        self._set_status(f"Bundling {os.path.basename(src_dir)}...", "processing")
        worker.start()

    def _on_bundle_progress(self, pct, status):
        self._set_status(f"Bundling: {status} ({pct}%)", "processing")

    def _on_bundle_done(self, ok, path_or_err):
        w = getattr(self, "_bundle_worker", None)
        if w is not None and not w.isRunning():
            try:
                w.wait(300)
            except Exception:
                pass
        self._bundle_worker = None
        if ok:
            self._log(f"[BUNDLE] Wrote {path_or_err}")
            self._set_status(f"Bundle ready: {path_or_err}", "success")
            self._notify_center(f"Bundle exported: {os.path.basename(path_or_err)}", "success")
        else:
            self._log(f"[BUNDLE] {path_or_err}")
            self._set_status(f"Bundle failed: {path_or_err}", "error")

    def _open_clip_dialog_for_dir(self, dir_path):
        """Offer a file picker inside the given directory, then open the
        ClipDialog on the chosen file. Used from History right-click and
        the Download-complete summary."""
        from .clip_dialog import ClipDialog
        from ..postprocess.codecs import VIDEO_EXTS, AUDIO_EXTS
        if not dir_path or not os.path.isdir(dir_path):
            return
        exts = {e.lower() for e in (VIDEO_EXTS | AUDIO_EXTS)}
        candidates = []
        for entry in sorted(os.scandir(dir_path), key=lambda e: e.name):
            if entry.is_file() and Path(entry.name).suffix.lower() in exts:
                candidates.append(entry.path)
        if not candidates:
            self._set_status(
                "No video/audio files found in that folder to trim.",
                "warning",
            )
            return
        if len(candidates) == 1:
            target = candidates[0]
        else:
            target, _ = QFileDialog.getOpenFileName(
                self, "Choose file to trim", dir_path,
                "Media files (*.mp4 *.mkv *.webm *.mov *.ts *.mp3 *.m4a *.aac *.flac *.wav)",
            )
            if not target:
                return
        dlg = ClipDialog(self, target)
        dlg.exec()

    def _on_history_double_click(self, index):
        row = index.row()
        view = getattr(self, "_history_view", list(reversed(self._history)))
        if row >= len(view):
            return
        h = view[row]
        # If the folder exists, try to play with embedded player (F52)
        if h.path and os.path.isdir(h.path):
            media = self._find_media_in_dir(h.path)
            if media:
                self._open_player(h, media)
                return
            # No playable media — fall back to opening the folder
            QDesktopServices.openUrl(QUrl.fromLocalFile(h.path))
            return
        # Otherwise offer to retry the download if we have the URL
        if h.url:
            self._log(f"[HISTORY] Folder missing — re-fetching {h.url}")
            self._set_status(f"Re-fetching {h.title or h.url}...", "working")
            self.url_input.setText(h.url)
            self._switch_tab(0)
            self._on_fetch()
        else:
            self._set_status("Path missing and no saved URL to retry.", "warning")

    def _find_media_in_dir(self, dir_path):
        """Return the first media file path in *dir_path*, or ''."""
        _MEDIA_EXTS = (".mp4", ".mkv", ".ts", ".webm", ".flv", ".mov", ".avi")
        try:
            for fn in sorted(os.listdir(dir_path)):
                if fn.lower().endswith(_MEDIA_EXTS) and not fn.startswith("."):
                    return os.path.join(dir_path, fn)
        except OSError:
            pass
        return ""

    def _open_player(self, history_entry, media_path):
        """Open the embedded media player for a recording (F52)."""
        from streamkeep.player import PlayerPanel, is_mpv_available
        if not is_mpv_available():
            # Fall back to opening the folder
            self._log("[PLAYER] python-mpv not available — opening folder instead.")
            if history_entry.path and os.path.isdir(history_entry.path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(history_entry.path))
            return
        panel = PlayerPanel(self)
        start = float(getattr(history_entry, "watch_position_secs", 0) or 0)
        panel.play_file(
            media_path,
            title=history_entry.title,
            channel=history_entry.channel,
            start_secs=start,
            history_entry=history_entry,
        )

        def _on_close(pos):
            # Persist playback position (F38 watch tracking)
            history_entry.watch_position_secs = pos
            if pos > 0 and not history_entry.watched:
                # Mark as in-progress
                pass
            if getattr(history_entry, "db_id", 0):
                _db.update_history_entry(history_entry.db_id, {
                    "watch_position_secs": pos,
                })
            self._refresh_history_table()

        panel.position_at_close.connect(_on_close)
        panel.exec()

    def _open_sync_viewer(self, history_entries):
        """Open the multi-stream sync viewer for 2-4 recordings (F54)."""
        from streamkeep.player.sync_viewer import SyncViewer
        from streamkeep.player.mpv_widget import is_mpv_available
        if not is_mpv_available():
            self._set_status("python-mpv not available for sync viewer.", "warning")
            return
        viewer = SyncViewer(self)
        for h in history_entries[:4]:
            media = self._find_media_in_dir(h.path) if h.path else ""
            if media:
                viewer.add_stream(media, label=f"{h.channel}: {h.title[:30]}")
        if not viewer._slots:
            self._set_status("No playable media found in selected entries.", "warning")
            viewer.close()
            return
        viewer.start_all()
        viewer.exec()

    def _generate_highlights(self, recording_dir):
        """Run AI highlight detection on a recording (F57)."""
        from streamkeep.intelligence.highlight import HighlightWorker
        self._set_status("Analyzing for highlights...", "processing")
        worker = HighlightWorker(recording_dir, top_n=10)
        worker.log.connect(self._log)

        def _on_done(results):
            if not results:
                self._set_status("No highlights found (needs chat/audio/scene data).", "warning")
                return
            lines = []
            for start, end, score, reason in results:
                h = int(start) // 3600
                m = (int(start) % 3600) // 60
                s = int(start) % 60
                ts = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
                lines.append(f"  {ts} (score {score:.1f}) - {reason}")
            self._log("[HIGHLIGHT] Top highlights:\n" + "\n".join(lines))
            self._set_status(f"Found {len(results)} highlight(s). See log.", "success")
            self._notify_center(f"Highlights: {len(results)} found", "info")

        worker.done.connect(_on_done)
        self._highlight_worker = worker
        worker.start()

    # ── Metadata ──────────────────────────────────────────────────────

    def _save_metadata(self, out_dir, quality_name="", history_url="", info=None):
        info = info or self.stream_info
        url = history_url or self._resolve_history_url()
        info_copy = copy.deepcopy(info) if info else None
        fallback_title = ""
        if out_dir:
            fallback_title = os.path.basename(out_dir.rstrip("\\/"))
        display_title = (
            (info_copy.title if info_copy else "")
            or fallback_title
            or "Download"
        )
        file_base = _safe_filename(info_copy.title) if info_copy and info_copy.title else ""
        task = {
            "out_dir": out_dir,
            "quality_name": quality_name,
            "history_url": url,
            "info": info_copy,
            "file_base": file_base,
            "write_nfo": bool(self._write_nfo and info_copy),
            "download_chat": bool(TwitchExtractor.download_chat_enabled and info_copy),
            "postprocess_snapshot": self._postprocess_snapshot() if info_copy else {},
            "platform": (info_copy.platform if info_copy and info_copy.platform else "?"),
            "channel": self._infer_history_channel(
                url=url,
                platform=(info_copy.platform if info_copy and info_copy.platform else "?"),
                channel=(info_copy.channel if info_copy else ""),
            ),
            "title": display_title,
        }
        self._enqueue_finalize_task(task)
        # Auto-tag recording (F35)
        try:
            from ..tags import _connect, auto_tag_recording
            db = _connect()
            auto_tag_recording(db, out_dir, info=info_copy)
            db.close()
        except Exception:
            pass
        # Index transcripts for this recording (F27)
        try:
            from ..search import index_recording
            index_recording(out_dir)
        except Exception:
            pass

    # ── Global Search (F45) ─────────────────────────────────────────

    def _on_global_search(self):
        """Run a unified search across History, Monitor, Queue, and transcripts."""
        query = self._global_search.text().strip().lower()
        results_widget = self._global_results
        results_widget.clear()

        if not query or len(query) < 2:
            results_widget.setVisible(False)
            return

        from PyQt6.QtWidgets import QListWidgetItem
        items = []
        cap = 15  # max results per source

        # History search
        count = 0
        for h in reversed(self._history):
            if count >= cap:
                break
            if (query in (h.title or "").lower()
                    or query in (h.channel or "").lower()
                    or query in (h.platform or "").lower()):
                item = QListWidgetItem(
                    f"[History] {h.platform}: {h.channel} - {h.title[:50]}"
                )
                item.setData(Qt.ItemDataRole.UserRole, ("history", h))
                items.append(item)
                count += 1

        # Monitor search
        count = 0
        for e in self.monitor.entries:
            if count >= cap:
                break
            if (query in (e.channel_id or "").lower()
                    or query in (e.url or "").lower()
                    or query in (e.platform or "").lower()):
                item = QListWidgetItem(
                    f"[Monitor] {e.platform}: {e.channel_id} ({e.url})"
                )
                item.setData(Qt.ItemDataRole.UserRole, ("monitor", e))
                items.append(item)
                count += 1

        # Queue search
        count = 0
        for q in self._download_queue:
            if count >= cap:
                break
            if (query in (q.get("title", "") or "").lower()
                    or query in (q.get("url", "") or "").lower()):
                item = QListWidgetItem(
                    f"[Queue] {q.get('title', q.get('url', ''))[:60]}"
                )
                item.setData(Qt.ItemDataRole.UserRole, ("queue", q))
                items.append(item)
                count += 1

        # Transcript FTS search (F27)
        try:
            from ..search import search_transcripts
            hits = search_transcripts(query, limit=cap)
            for hit in hits:
                snippet = (hit.get("text", "") or "")[:80]
                item = QListWidgetItem(
                    f"[Transcript] {snippet}... ({hit.get('recording_path', '')[-40:]})"
                )
                item.setData(Qt.ItemDataRole.UserRole, ("transcript", hit))
                items.append(item)
        except Exception:
            pass

        if items:
            for it in items:
                results_widget.addItem(it)
            results_widget.setVisible(True)
        else:
            no_result = QListWidgetItem("No results found.")
            no_result.setData(Qt.ItemDataRole.UserRole, None)
            results_widget.addItem(no_result)
            results_widget.setVisible(True)

    def _on_global_result_click(self, item):
        """Navigate to the source tab when a global search result is clicked."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        source, entry = data
        self._global_results.setVisible(False)

        if source == "history":
            self._switch_tab(2)
            # Try to select the row in history
            if hasattr(self, "history_search"):
                self.history_search.setText(
                    getattr(entry, "title", "")[:30]
                )
        elif source == "monitor":
            self._switch_tab(1)
        elif source == "queue":
            self._switch_tab(0)
        elif source == "transcript":
            self._switch_tab(2)
            if hasattr(self, "history_search") and hasattr(self, "transcript_search_check"):
                self.transcript_search_check.setChecked(True)
                self.history_search.setText(
                    self._global_search.text().strip()[:30]
                )
