"""Background finalization for completed downloads."""

import os
import re

from PyQt6.QtCore import QThread, pyqtSignal

from ..extractors import TwitchExtractor
from ..metadata import MetadataSaver
from ..postprocess import PostProcessor
from ..postprocess.processor import PP_LOCK as _PP_LOCK
from ..utils import fmt_size


class FinalizeWorker(QThread):
    """Runs metadata/chat/post-processing off the UI thread."""

    log = pyqtSignal(str)
    progress = pyqtSignal(str, int, int)
    done = pyqtSignal(dict)

    def __init__(self, task):
        super().__init__()
        self.task = dict(task or {})
        self._cancel = False

    def cancel(self):
        self._cancel = True
        self.requestInterruption()

    def _interrupted(self):
        return self._cancel or self.isInterruptionRequested()

    def _has_postprocess_work(self, snapshot):
        if not snapshot:
            return False
        flags = (
            "extract_audio",
            "normalize_loudness",
            "reencode_h265",
            "contact_sheet",
            "split_by_chapter",
            "convert_video",
            "convert_audio",
        )
        return any(bool(snapshot.get(name)) for name in flags)

    def _chat_vod_id(self, info):
        if getattr(info, "platform", "") != "Twitch":
            return ""
        url = getattr(info, "url", "") or ""
        match = re.search(r"/vod/(\d+)\.m3u8", url)
        return match.group(1) if match else ""

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
        return fmt_size(total) if total > 0 else ""

    def _planned_steps(self, task, info, snapshot):
        steps = [("Saving metadata", "metadata")]
        if task.get("write_nfo"):
            steps.append(("Writing NFO", "nfo"))
        if getattr(info, "chapters", None):
            steps.append(("Exporting chapters", "chapters"))
        if task.get("download_chat") and self._chat_vod_id(info):
            steps.append(("Downloading chat", "chat"))
        if self._has_postprocess_work(snapshot):
            steps.append(("Running post-processing", "postprocess"))
        return steps

    def _emit_progress(self, label, index, total):
        self.progress.emit(label, index, total)

    def run(self):
        task = dict(self.task)
        info = task.get("info")
        out_dir = task.get("out_dir", "")
        file_base = task.get("file_base", "")
        snapshot = dict(task.get("postprocess_snapshot") or {})
        chat_vod_id = self._chat_vod_id(info) if info else ""
        result = {
            "platform": task.get("platform", "?"),
            "title": task.get("title", "?"),
            "channel": task.get("channel", ""),
            "quality_name": task.get("quality_name", ""),
            "out_dir": out_dir,
            "history_url": task.get("history_url", ""),
            "cancelled": False,
        }
        if self._interrupted():
            result["cancelled"] = True
            self.done.emit(result)
            return

        # Only snapshot keys that actually exist on PostProcessor — a stale
        # config key must not AttributeError-crash the entire finalize pass
        # before metadata is even saved.
        # Guard PostProcessor class-level state with a lock so concurrent
        # FinalizeWorker threads don't clobber each other.
        _PP_LOCK.acquire()
        orig = {k: getattr(PostProcessor, k) for k in snapshot if hasattr(PostProcessor, k)}
        try:
            if info and out_dir:
                steps = self._planned_steps(task, info, snapshot)
                total_steps = len(steps)
                step_no = 0

                step_no += 1
                self._emit_progress("Saving metadata", step_no, total_steps)
                MetadataSaver.save(out_dir, info)
                if self._interrupted():
                    result["cancelled"] = True
                    self.done.emit(result)
                    return
                if task.get("write_nfo"):
                    step_no += 1
                    self._emit_progress("Writing NFO", step_no, total_steps)
                    MetadataSaver.write_nfo(out_dir, info, file_base=file_base)
                    self.log.emit(f"[NFO] Wrote {file_base or 'movie'}.nfo for media library")
                if getattr(info, "chapters", None):
                    step_no += 1
                    self._emit_progress("Exporting chapters", step_no, total_steps)
                    if MetadataSaver.write_chapters(out_dir, info, file_base=file_base):
                        count = len(getattr(info, "chapters", None) or [])
                        self.log.emit(f"[CHAPTERS] Exported {count} chapter(s) to {file_base}.chapters.txt/.json")
                if task.get("download_chat") and chat_vod_id and not self._interrupted():
                    step_no += 1
                    self._emit_progress("Downloading chat", step_no, total_steps)
                    vod_id = chat_vod_id
                    if vod_id:
                        chat_base = os.path.join(out_dir, file_base or "chat")
                        self.log.emit(f"[CHAT] Fetching chat replay for VOD {vod_id}...")
                        count, err = TwitchExtractor().download_chat(
                            vod_id, chat_base, log_fn=self.log.emit
                        )
                        if err:
                            self.log.emit(f"[CHAT] Failed: {err}")
                        else:
                            self.log.emit(f"[CHAT] Saved {count} comments to {file_base or 'chat'}.chat.json/.txt")
                if self._has_postprocess_work(snapshot) and not self._interrupted():
                    step_no += 1
                    self._emit_progress("Running post-processing", step_no, total_steps)
                if snapshot and not self._interrupted():
                    for k, v in snapshot.items():
                        if hasattr(PostProcessor, k):
                            setattr(PostProcessor, k, v)
                    if PostProcessor.has_any_preset():
                        PostProcessor.process_directory(
                            out_dir,
                            log_fn=self.log.emit,
                            chapters=getattr(info, "chapters", None) or None,
                        )
        except Exception as e:
            self.log.emit(f"[FINALIZE] Background finalization error: {e}")
        finally:
            for k, v in orig.items():
                setattr(PostProcessor, k, v)
            _PP_LOCK.release()

        result["cancelled"] = self._interrupted()
        result["size_label"] = self._output_size_label(out_dir) if not result["cancelled"] else ""
        self.done.emit(result)
