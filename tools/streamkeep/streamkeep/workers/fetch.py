"""Fetch worker — resolves URLs via the extractor system."""

from PyQt6.QtCore import QThread, pyqtSignal

from ..extractors import Extractor
from ..extractors.kick import KickExtractor
from ..extractors.twitch import TwitchExtractor
from ..http import http_interruptible
from ..scrape import detect_direct_media


class FetchWorker(QThread):
    """Resolves URLs using the extractor system."""

    finished = pyqtSignal(object)        # StreamInfo
    vods_found = pyqtSignal(list, str, object)  # list[VODInfo], platform_name, next_cursor
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, url, vod_source=None, vod_platform=None, vod_title=None, vod_channel=None):
        super().__init__()
        self.url = url.strip()
        self.vod_source = vod_source
        self.vod_platform = vod_platform
        self.vod_title = str(vod_title or "")
        self.vod_channel = str(vod_channel or "")

    def _interrupted(self):
        return self.isInterruptionRequested()

    def run(self):
        try:
            with http_interruptible(self._interrupted):
                if self._interrupted():
                    return
                if self.vod_source:
                    info = self._resolve_direct(self.vod_source)
                    if self._interrupted():
                        return
                    if info:
                        self.finished.emit(info)
                    else:
                        self.error.emit("Failed to resolve VOD source")
                    return

                ext = Extractor.detect(self.url)
                if self._interrupted():
                    return
                if not ext:
                    # Try direct media URL detection before giving up
                    direct = detect_direct_media(self.url, log_fn=self.log.emit)
                    if self._interrupted():
                        return
                    if direct:
                        self.finished.emit(direct)
                        return
                    self.error.emit("No extractor found for this URL")
                    return

                # If yt-dlp fallback matched, try direct media detection first
                if ext.NAME == "yt-dlp":
                    direct = detect_direct_media(self.url, log_fn=self.log.emit)
                    if self._interrupted():
                        return
                    if direct:
                        self.finished.emit(direct)
                        return

                self.log.emit(f"Detected platform: {ext.NAME}")

                if ext.supports_live_check():
                    is_live = False
                    try:
                        is_live = bool(ext.check_live(self.url))
                    except Exception as live_err:
                        self.log.emit(f"[LIVE CHECK] {live_err}")
                    if self._interrupted():
                        return
                    if is_live:
                        info = ext.resolve(self.url, log_fn=self.log.emit)
                        if self._interrupted():
                            return
                        if info:
                            self.finished.emit(info)
                            return
                        self.log.emit("[LIVE CHECK] Live source detected but resolve failed; falling back to VOD lookup.")

                if ext.supports_vod_listing():
                    vods, next_cursor = ext.list_vods(self.url, log_fn=self.log.emit)
                    if self._interrupted():
                        return
                    if len(vods) > 1:
                        self.vods_found.emit(vods, ext.NAME, next_cursor)
                        return
                    elif len(vods) == 1:
                        self.log.emit(f"Auto-selecting only VOD: {vods[0].title}")
                        info = self._resolve_source(vods[0], ext)
                        if self._interrupted():
                            return
                        if info:
                            self.finished.emit(info)
                            return

                info = ext.resolve(self.url, log_fn=self.log.emit)
                if self._interrupted():
                    return
                if info:
                    self.finished.emit(info)
                else:
                    # Maybe there were VODs but none to auto-select
                    if ext.supports_vod_listing():
                        vods, next_cursor = ext.list_vods(self.url, log_fn=self.log.emit)
                        if self._interrupted():
                            return
                        if vods:
                            self.vods_found.emit(vods, ext.NAME, next_cursor)
                            return
                    self.error.emit("Failed to resolve stream URL")

        except Exception as e:
            if not self._interrupted():
                self.error.emit(str(e))

    def _apply_vod_metadata(self, info, platform="", title="", channel=""):
        if info is None:
            return None
        if platform and not getattr(info, "platform", ""):
            info.platform = platform
        if title and not getattr(info, "title", ""):
            info.title = title
        if channel and not getattr(info, "channel", ""):
            info.channel = channel
        return info

    def _resolve_direct(self, source):
        """Resolve a direct source URL (m3u8 or VOD ID)."""
        # Twitch VOD IDs are numeric strings
        if source.isdigit():
            info = TwitchExtractor()._resolve_vod(source, log_fn=self.log.emit)
            return self._apply_vod_metadata(
                info,
                platform=self.vod_platform or "Twitch",
                title=self.vod_title,
                channel=self.vod_channel,
            )
        # Try as m3u8 URL — use Kick extractor's generic m3u8 resolver
        info = KickExtractor()._resolve_m3u8(source, log_fn=self.log.emit)
        return self._apply_vod_metadata(
            info,
            platform=self.vod_platform,
            title=self.vod_title,
            channel=self.vod_channel,
        )

    def _resolve_source(self, vod, ext):
        """Resolve a VODInfo to StreamInfo."""
        if vod.platform == "Twitch" and vod.source.isdigit():
            info = TwitchExtractor()._resolve_vod(vod.source, log_fn=self.log.emit)
        elif ".m3u8" in vod.source or "stream.kick.com" in vod.source:
            info = KickExtractor()._resolve_m3u8(vod.source, log_fn=self.log.emit)
        else:
            info = ext.resolve(vod.source, log_fn=self.log.emit)
        return self._apply_vod_metadata(
            info,
            platform=getattr(vod, "platform", ""),
            title=getattr(vod, "title", ""),
            channel=getattr(vod, "channel", ""),
        )


class VodPageWorker(QThread):
    """Fetches the next page of VODs for a channel (pagination)."""

    page_ready = pyqtSignal(list, object)  # list[VODInfo], next_cursor
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, url, cursor):
        super().__init__()
        self.url = url.strip()
        self.cursor = cursor

    def _interrupted(self):
        return self.isInterruptionRequested()

    def run(self):
        try:
            from ..http import http_interruptible
            with http_interruptible(self._interrupted):
                ext = Extractor.detect(self.url)
                if not ext or not ext.supports_vod_listing():
                    self.error.emit("Extractor does not support VOD listing")
                    return
                vods, next_cursor = ext.list_vods(
                    self.url, log_fn=self.log.emit, cursor=self.cursor,
                )
                if self._interrupted():
                    return
                self.page_ready.emit(vods, next_cursor)
        except Exception as e:
            if not self._interrupted():
                self.error.emit(str(e))
