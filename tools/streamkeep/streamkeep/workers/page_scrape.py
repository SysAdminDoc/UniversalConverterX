"""Page scrape worker — headless + regex media link extraction."""

from PyQt6.QtCore import QThread, pyqtSignal

from ..http import http_interruptible
from ..scrape import scrape_media_links, scrape_media_links_headless


class PageScrapeWorker(QThread):
    """Fetch a webpage and extract media/video links from its HTML.
    Runs the headless-browser scraper first (catches lazy-loaded players)
    and merges with the regex scraper's results."""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, url, use_headless=True):
        super().__init__()
        self.url = url
        self.use_headless = use_headless

    def _interrupted(self):
        return self.isInterruptionRequested()

    def run(self):
        try:
            with http_interruptible(self._interrupted):
                if self._interrupted():
                    return
                all_links = []
                seen = set()

                def merge(pairs):
                    for url, hint in pairs:
                        if url in seen:
                            continue
                        seen.add(url)
                        all_links.append((url, hint))

                # Headless-browser pass: captures lazy-loaded players, JS-injected
                # <video> elements, and blob-fed HLS streams.
                if self.use_headless:
                    merge(scrape_media_links_headless(
                        self.url,
                        log_fn=self.log.emit,
                        should_cancel=self._interrupted,
                    ))
                    if self._interrupted():
                        return

                # Static-HTML pass: cheap regex scan for anything the headless
                # pass might have missed (e.g. pages with many linked videos).
                merge(scrape_media_links(self.url, log_fn=self.log.emit))
                if self._interrupted():
                    return

                self.finished.emit(all_links)
        except Exception as e:
            if not self._interrupted():
                self.error.emit(str(e))
