"""Channel monitor — round-robin live detection + VOD subscriptions.

The poll tick dispatches each check to a background QRunnable so the
Qt event loop is never blocked by a network call. Each entry can also
only have one outstanding check at a time (guarded by `_in_flight`)
so a slow response on one timer fire can't stack up duplicate requests
on the next tick.
"""

import threading
import time
from datetime import datetime

from PyQt6.QtCore import (
    QObject, QRunnable, QThreadPool, QTimer, pyqtSignal, pyqtSlot,
)

from .extractors import Extractor
from .http import http_interruptible
from .models import MonitorEntry


def entry_in_schedule_window(entry, now=None):
    """Return True if an entry's schedule window includes the given time.

    An entry with no start/end is always in-window. Days_mask 0 means
    "every day"; otherwise bit i (Mon=0 ... Sun=6) must be set. Windows
    may wrap midnight (e.g. 22:00 -> 04:00 = overnight)."""
    start = getattr(entry, "schedule_start_hhmm", "") or ""
    end = getattr(entry, "schedule_end_hhmm", "") or ""
    if not start or not end:
        return True
    if now is None:
        now = datetime.now()
    mask = int(getattr(entry, "schedule_days_mask", 0) or 0)
    if mask and not (mask & (1 << now.weekday())):
        return False
    try:
        sh, sm = (int(x) for x in start.split(":", 1))
        eh, em = (int(x) for x in end.split(":", 1))
    except (ValueError, AttributeError):
        return True
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    cur_min = now.hour * 60 + now.minute
    if start_min == end_min:
        return True
    if start_min < end_min:
        return start_min <= cur_min < end_min
    # Wrap around midnight.
    return cur_min >= start_min or cur_min < end_min


class _PollSignals(QObject):
    """Signals emitted by a poll QRunnable back to the Qt thread."""

    went_live = pyqtSignal(str)              # channel_id
    new_vods = pyqtSignal(str, list)         # channel_id, list[VODInfo]
    log = pyqtSignal(str)
    finished = pyqtSignal(str, str)          # channel_id, status


class _PollTask(QRunnable):
    """Runs one channel check on a worker thread."""

    def __init__(self, entry, signals, check_vods):
        super().__init__()
        self.entry = entry
        self.signals = signals
        self.check_vods = check_vods

    def run(self):
        entry = self.entry
        status = entry.last_status
        try:
            with http_interruptible(lambda: getattr(entry, "_cancel_requested", False)):
                ext = Extractor.detect(entry.url)
                if not ext:
                    self.signals.finished.emit(entry.channel_id, "error")
                    return
                if ext.supports_live_check():
                    try:
                        is_live = ext.check_live(entry.url)
                    except Exception as ex:
                        self.signals.log.emit(
                            f"[MONITOR ERROR] {entry.channel_id}: {ex}"
                        )
                        self.signals.finished.emit(entry.channel_id, "error")
                        return
                    prev = entry.last_status
                    status = "live" if is_live else "offline"
                    if is_live and prev != "live" and not getattr(entry, "_cancel_requested", False):
                        self.signals.went_live.emit(entry.channel_id)
                        self.signals.log.emit(
                            f"[LIVE] {entry.platform}/{entry.channel_id} went live!"
                        )
                if self.check_vods and ext.supports_vod_listing() and not getattr(entry, "_cancel_requested", False):
                    try:
                        vods, _cursor = ext.list_vods(
                            entry.url, log_fn=self.signals.log.emit
                        )
                        new_vods = [
                            v for v in vods
                            if v.source and v.source not in entry.archive_ids
                        ]
                        if new_vods and not getattr(entry, "_cancel_requested", False):
                            self.signals.log.emit(
                                f"[SUBSCRIBE] {entry.channel_id}: "
                                f"{len(new_vods)} new VOD(s) found"
                            )
                            self.signals.new_vods.emit(entry.channel_id, new_vods)
                    except Exception as sub_ex:
                        self.signals.log.emit(
                            f"[SUBSCRIBE ERROR] {entry.channel_id}: {sub_ex}"
                        )
        except Exception as ex:
            self.signals.log.emit(
                f"[MONITOR ERROR] {entry.channel_id}: {ex}"
            )
            status = "error"
        finally:
            self.signals.finished.emit(entry.channel_id, status)


class ChannelMonitor(QObject):
    """Polls channels for live status via round-robin."""

    status_changed = pyqtSignal()
    channel_went_live = pyqtSignal(str)      # channel_id
    new_vods_found = pyqtSignal(str, list)   # channel_id, list[VODInfo]
    log = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.entries = []
        self._poll_idx = 0
        # Dedicated thread pool so we don't share with Qt's default one.
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(2)
        self._in_flight = set()
        self._entries_lock = threading.RLock()
        self._signals = _PollSignals()
        self._signals.went_live.connect(self._on_went_live)
        self._signals.new_vods.connect(self._on_new_vods)
        self._signals.log.connect(self.log.emit)
        self._signals.finished.connect(self._on_poll_finished)
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll_tick)
        self._timer.start(15_000)  # check one channel every 15s

    def add_channel(self, url, interval=120, auto_record=False, subscribe_vods=False):
        ext = Extractor.detect(url)
        if not ext:
            return False
        # Allow subscribe-only even if extractor doesn't support live check
        if not ext.supports_live_check() and not (
            subscribe_vods and ext.supports_vod_listing()
        ):
            return False
        ch_id = ext.extract_channel_id(url) or url
        with self._entries_lock:
            for e in self.entries:
                if e.channel_id == ch_id:
                    return False
            self.entries.append(MonitorEntry(
                url=url, platform=ext.NAME, channel_id=ch_id,
                interval_secs=interval, auto_record=auto_record,
                subscribe_vods=subscribe_vods,
            ))
        self.status_changed.emit()
        return True

    def remove_channel(self, idx):
        with self._entries_lock:
            if 0 <= idx < len(self.entries):
                removed = self.entries.pop(idx)
                removed._cancel_requested = True
                self._in_flight.discard(removed.channel_id)
        self.status_changed.emit()

    def _poll_tick(self):
        # Snapshot entries so remove_channel during poll doesn't break indexing
        with self._entries_lock:
            entries_snapshot = list(self.entries)
        if not entries_snapshot:
            return
        entry = entries_snapshot[self._poll_idx % len(entries_snapshot)]
        self._poll_idx += 1
        # Skip if entry was removed between snapshot and dispatch, or if a
        # previous slow poll for the same channel is still running, or if
        # the entry's schedule window doesn't include right now.
        if not entry_in_schedule_window(entry):
            return
        with self._entries_lock:
            if entry not in self.entries:
                return
            if entry.channel_id in self._in_flight:
                return
            entry._cancel_requested = False
            now = time.time()
            if now - entry.last_check < entry.interval_secs:
                return
            entry.last_check = now
            self._in_flight.add(entry.channel_id)
        check_vods = entry.subscribe_vods
        task = _PollTask(entry, self._signals, check_vods)
        self._pool.start(task)

    @pyqtSlot(str, str)
    def _on_poll_finished(self, channel_id, status):
        with self._entries_lock:
            for e in self.entries:
                if e.channel_id == channel_id:
                    e.last_status = status
                    e._cancel_requested = False
                    break
            self._in_flight.discard(channel_id)
        self.status_changed.emit()

    @pyqtSlot(str)
    def _on_went_live(self, channel_id):
        self.channel_went_live.emit(channel_id)

    @pyqtSlot(str, list)
    def _on_new_vods(self, channel_id, new_vods):
        emit = False
        with self._entries_lock:
            for e in self.entries:
                if e.channel_id == channel_id and not e._cancel_requested:
                    for v in new_vods:
                        if v.source and v.source not in e.archive_ids:
                            e.archive_ids.append(v.source)
                    if len(e.archive_ids) > 500:
                        e.archive_ids = e.archive_ids[-500:]
                    emit = True
                    break
        if emit:
            self.new_vods_found.emit(channel_id, new_vods)

    def seed_archive(self, channel_id, vod_sources):
        """Populate the archive list for a channel (e.g. on first subscribe
        so we don't download the entire backlog)."""
        with self._entries_lock:
            for e in self.entries:
                if e.channel_id == channel_id:
                    for vs in vod_sources:
                        if vs and vs not in e.archive_ids:
                            e.archive_ids.append(vs)
                    break

    def _entry_to_dict(self, e):
        return {
            "url": e.url, "interval_secs": e.interval_secs,
            "platform": e.platform, "channel_id": e.channel_id,
            "auto_record": e.auto_record,
            "subscribe_vods": e.subscribe_vods,
            "archive_ids": list(e.archive_ids),
            "override_output_dir": e.override_output_dir or "",
            "override_quality_pref": e.override_quality_pref or "",
            "override_filename_template": e.override_filename_template or "",
            "schedule_start_hhmm": e.schedule_start_hhmm or "",
            "schedule_end_hhmm": e.schedule_end_hhmm or "",
            "schedule_days_mask": int(e.schedule_days_mask or 0),
            "retention_keep_last": int(e.retention_keep_last or 0),
            "filter_keywords": e.filter_keywords or "",
            "override_pp_preset": e.override_pp_preset or "",
            "auto_upgrade": bool(e.auto_upgrade),
            "min_upgrade_quality": e.min_upgrade_quality or "",
        }

    def save_to_config(self, cfg):
        # Legacy format for export and backward compat; also persists to DB.
        cfg["monitor_channels"] = [
            {
                "url": e.url, "interval": e.interval_secs,
                "auto_record": e.auto_record,
                "subscribe_vods": e.subscribe_vods,
                "archive_ids": list(e.archive_ids),
                "override_output_dir": e.override_output_dir or "",
                "override_quality_pref": e.override_quality_pref or "",
                "override_filename_template": e.override_filename_template or "",
                "schedule_start_hhmm": e.schedule_start_hhmm or "",
                "schedule_end_hhmm": e.schedule_end_hhmm or "",
                "schedule_days_mask": int(e.schedule_days_mask or 0),
                "retention_keep_last": int(e.retention_keep_last or 0),
                "filter_keywords": e.filter_keywords or "",
                "override_pp_preset": e.override_pp_preset or "",
                "auto_upgrade": bool(e.auto_upgrade),
                "min_upgrade_quality": e.min_upgrade_quality or "",
            }
            for e in self.entries
        ]

    def save_to_db(self):
        """Persist all monitor entries to SQLite (F41)."""
        from . import db
        db.save_all_monitor_channels([self._entry_to_dict(e) for e in self.entries])

    def load_from_db(self):
        """Load monitor entries from SQLite (F41)."""
        from . import db
        for ch in db.load_monitor_channels():
            self._load_channel_dict(ch)

    def load_from_config(self, cfg):
        for ch in cfg.get("monitor_channels", []):
            self._load_channel_dict(ch)

    def _load_channel_dict(self, ch):
        ok = self.add_channel(
            ch.get("url", ""),
            ch.get("interval_secs", ch.get("interval", 120)),
            ch.get("auto_record", False),
            ch.get("subscribe_vods", False),
        )
        if ok:
            archive_ids = ch.get("archive_ids", [])
            for e in self.entries:
                if e.url == ch.get("url", ""):
                    if isinstance(archive_ids, list):
                        e.archive_ids = [str(x) for x in archive_ids if x]
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
                    e.override_pp_preset = str(ch.get("override_pp_preset", "") or "")
                    e.auto_upgrade = bool(ch.get("auto_upgrade", False))
                    e.min_upgrade_quality = str(ch.get("min_upgrade_quality", "") or "")
                    break
