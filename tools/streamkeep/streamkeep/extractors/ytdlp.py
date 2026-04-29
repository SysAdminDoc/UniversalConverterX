"""yt-dlp catch-all fallback extractor.

Handles anything the native extractors don't. Includes:
- Auto-scan of installed browsers for cookies on auth errors
- Volume Shadow Copy bypass for locked Chromium cookie DBs
- --flat-playlist probe for channel/playlist expansion
- Video+audio pairing via ytdlp_direct format spec
"""

import json
import os
import re
import time
import urllib.parse
from pathlib import Path

from ..http import http_interrupted, run_capture_interruptible
from ..models import QualityInfo, StreamInfo
from ..utils import fmt_duration, scan_browser_cookies
from .base import Extractor


class YtDlpExtractor(Extractor):
    NAME = "yt-dlp"
    ICON = "Y"
    COLOR = "overlay1"
    URL_PATTERNS = [
        re.compile(r'https?://.+'),  # Catch-all — must register last
    ]
    # Set by Settings tab
    cookies_browser = ""
    cookies_file = ""
    rate_limit = ""
    proxy = ""
    download_subs = False
    sponsorblock = False

    def _has_ytdlp(self):
        result = run_capture_interruptible(["yt-dlp", "--version"], timeout=5)
        return result.returncode == 0

    def extract_channel_id(self, url):
        try:
            parsed = urllib.parse.urlparse(url.strip())
            parts = parsed.path.strip("/").split("/")
            if parts and parts[-1]:
                return f"{parsed.netloc}_{parts[-1]}"
            return parsed.netloc
        except Exception:
            return "download"

    def _build_cmd(self, url):
        cmd = ["yt-dlp", "--dump-json", "--no-download"]
        if self.cookies_file and os.path.isfile(self.cookies_file):
            cmd.extend(["--cookies", self.cookies_file])
        elif self.cookies_browser:
            cmd.extend(["--cookies-from-browser", self.cookies_browser])
        if self.proxy:
            cmd.extend(["--proxy", self.proxy])
        cmd.extend(["--", url])
        return cmd

    _AUTH_ERRORS = [
        "Sign in", "age", "confirm your age", "login", "cookies",
        "authentication", "members-only", "private video",
        "This video is available to this channel",
    ]

    def _is_auth_error(self, stderr):
        lower = stderr.lower()
        return any(phrase.lower() in lower for phrase in self._AUTH_ERRORS)

    def _try_with_browser(self, url, browser_name, log_fn=None):
        """Attempt yt-dlp extraction with a specific browser's cookies.
        Returns (data_dict, None) or (None, error_str)."""
        cmd = ["yt-dlp", "--dump-json", "--no-download",
               "--cookies-from-browser", browser_name, "--", url]
        try:
            result = run_capture_interruptible(cmd, timeout=60)
            if result.interrupted:
                return None, "Interrupted"
            if result.timed_out:
                return None, "Timed out"
            if result.returncode == 0:
                return json.loads(result.stdout), None
            err = result.stderr.strip().split("\n")[-1] if result.stderr else "Unknown error"
            return None, err
        except json.JSONDecodeError:
            return None, "Bad JSON"
        except Exception as e:
            return None, str(e)

    def _copy_locked_cookie_db(self, cookie_db_path, log_fn=None):
        """Copy a locked Chromium cookie DB using Volume Shadow Copy (VSS).
        Requires a UAC admin elevation prompt. Returns the temp profile
        path, or None."""
        import tempfile
        import shutil
        try:
            parts = Path(cookie_db_path).parts
            user_data_idx = None
            for i, p in enumerate(parts):
                if p == "User Data":
                    user_data_idx = i
                    break
            if user_data_idx is None:
                return None

            user_data_dir = str(Path(*parts[:user_data_idx + 1]))
            local_state_path = os.path.join(user_data_dir, "Local State")
            if not os.path.exists(local_state_path):
                return None

            tmp_base = os.path.join(tempfile.gettempdir(), "streamkeep_cookies")
            try:
                if os.path.exists(tmp_base):
                    shutil.rmtree(tmp_base, ignore_errors=True)
                tmp_profile = os.path.join(tmp_base, "Default")
                tmp_network = os.path.join(tmp_profile, "Network")
                os.makedirs(tmp_network, exist_ok=True)
            except OSError as e:
                self._log(log_fn, f"  Cannot create temp profile dir: {e}")
                return None

            try:
                shutil.copy2(local_state_path, os.path.join(tmp_base, "Local State"))
            except OSError as e:
                self._log(log_fn, f"  Cannot copy Local State: {e}")
                return None

            if "Network" in cookie_db_path:
                dst_cookies = os.path.join(tmp_network, "Cookies")
            else:
                dst_cookies = os.path.join(tmp_profile, "Cookies")

            try:
                shutil.copy2(cookie_db_path, dst_cookies)
                self._log(log_fn, "  Copied cookie DB directly")
                return tmp_profile
            except (PermissionError, OSError):
                pass

            self._log(
                log_fn,
                "  Cookie DB locked — using Volume Shadow Copy (admin required)...",
            )

            drive = cookie_db_path[:3]  # e.g. "C:\"
            rel_path = cookie_db_path[3:]
            done_flag = os.path.join(tempfile.gettempdir(), "sk_copy_done")
            err_log = os.path.join(tempfile.gettempdir(), "sk_copy_err.txt")
            for f in [done_flag, err_log]:
                if os.path.exists(f):
                    os.remove(f)

            ps_file = os.path.join(tempfile.gettempdir(), "sk_vss.ps1")
            with open(ps_file, "w", encoding="utf-8") as f:
                lines = [
                    "try {",
                    f"  $s = (Get-WmiObject -List Win32_ShadowCopy).Create('{drive}','ClientAccessible')",
                    "  $sc = Get-WmiObject Win32_ShadowCopy | Sort-Object InstallDate -Descending | Select-Object -First 1",
                    "  $dev = $sc.DeviceObject",
                    '  $src = "$dev\\' + rel_path + '"',
                    '  Copy-Item -LiteralPath $src -Destination "' + dst_cookies + '" -Force',
                    "  $sc.Delete()",
                    '  "done" | Out-File "' + done_flag + '"',
                    "} catch {",
                    '  $_.Exception.Message | Out-File "' + err_log + '"',
                    '  "error" | Out-File "' + done_flag + '"',
                    "}",
                ]
                f.write("\n".join(lines))

            import ctypes
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "powershell.exe",
                f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{ps_file}"',
                None, 0,
            )
            if ret <= 32:
                self._log(log_fn, "  UAC elevation denied")
                return None

            for _ in range(40):
                if http_interrupted():
                    return None
                time.sleep(0.5)
                if os.path.exists(done_flag):
                    break
            else:
                self._log(log_fn, "  VSS copy timed out")
                return None

            if os.path.exists(err_log):
                with open(err_log, encoding="utf-8") as f:
                    self._log(log_fn, f"  VSS error: {f.read().strip()}")
                return None

            if os.path.exists(dst_cookies) and os.path.getsize(dst_cookies) > 0:
                self._log(log_fn, "  Copied cookie DB via VSS shadow copy")
                return tmp_profile

            self._log(log_fn, "  VSS copy produced no output")
            return None

        except Exception as e:
            self._log(log_fn, f"  Cookie DB copy failed: {e}")
            return None

    def _find_cookie_db_path(self, ytdlp_name):
        """Find the actual Cookies file path for a browser."""
        local = os.environ.get("LOCALAPPDATA", "")
        roaming = os.environ.get("APPDATA", "")
        candidates = {
            "chrome": [
                os.path.join(local, "Google", "Chrome", "User Data", "Default", "Network", "Cookies"),
                os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cookies"),
            ],
            "chromium": [
                os.path.join(local, "Chromium", "User Data", "Default", "Network", "Cookies"),
                os.path.join(local, "Chromium", "User Data", "Default", "Cookies"),
            ],
            "edge": [
                os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Network", "Cookies"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Cookies"),
            ],
            "brave": [
                os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Network", "Cookies"),
                os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data", "Default", "Cookies"),
            ],
            "opera": [
                os.path.join(roaming, "Opera Software", "Opera Stable", "Network", "Cookies"),
                os.path.join(roaming, "Opera Software", "Opera Stable", "Cookies"),
            ],
            "vivaldi": [
                os.path.join(local, "Vivaldi", "User Data", "Default", "Network", "Cookies"),
                os.path.join(local, "Vivaldi", "User Data", "Default", "Cookies"),
            ],
        }
        for p in candidates.get(ytdlp_name, []):
            if os.path.exists(p):
                return p
        return None

    def _auto_retry_with_browsers(self, url, original_stderr, log_fn=None):
        """Scan for installed browsers and try each one's cookies until one works."""
        err_line = original_stderr.strip().split("\n")[-1] if original_stderr else ""
        self._log(log_fn, f"Auth required: {err_line}")
        self._log(log_fn, "Auto-scanning for browser cookies...")

        browsers = scan_browser_cookies()
        if not browsers:
            self._log(log_fn, "No browsers found on this system.")
            return None

        self._log(
            log_fn,
            f"Found {len(browsers)} browser(s) to try: "
            f"{', '.join(d for d, _, _ in browsers)}",
        )

        for display, ytdlp_name, path in browsers:
            if http_interrupted():
                return None
            self._log(log_fn, f"Trying cookies from {display} ({ytdlp_name})...")
            data, err = self._try_with_browser(url, ytdlp_name, log_fn)
            if http_interrupted():
                return None
            if data:
                self._log(log_fn, f"Success with {display}! Saving as default.")
                YtDlpExtractor.cookies_browser = ytdlp_name
                return data

            if err and "could not copy" in err.lower():
                self._log(log_fn, "  DB locked — copying with sqlite3 backup...")
                db_path = self._find_cookie_db_path(ytdlp_name)
                if db_path:
                    tmp_profile = self._copy_locked_cookie_db(db_path, log_fn)
                    if tmp_profile:
                        browser_arg = f"{ytdlp_name}:{tmp_profile}"
                        self._log(log_fn, "  Retrying with copied profile...")
                        data2, err2 = self._try_with_browser(url, browser_arg, log_fn)
                        if data2:
                            self._log(
                                log_fn,
                                f"Success with {display} (copied profile)! "
                                "Saving as default.",
                            )
                            YtDlpExtractor.cookies_browser = browser_arg
                            return data2
                        else:
                            self._log(log_fn, f"  {display} (copied) failed: {err2}")
            else:
                self._log(log_fn, f"  {display} failed: {err}")

        self._log(log_fn, "All browsers tried — none had valid cookies for this URL.")
        return None

    def list_playlist_entries(self, url, log_fn=None, limit=200):
        """Probe URL for a playlist/channel. If it's a list container,
        return a list of entries (empty list for single videos)."""
        has_ytdlp = self._has_ytdlp()
        if http_interrupted():
            return []
        if not has_ytdlp:
            return []
        self._log(log_fn, f"Probing for playlist/channel: {url}")
        cmd = [
            "yt-dlp", "--flat-playlist", "--dump-single-json",
            "--playlist-end", str(limit), "--no-warnings",
        ]
        if self.cookies_browser:
            cmd.extend(["--cookies-from-browser", self.cookies_browser])
        if self.proxy:
            cmd.extend(["--proxy", self.proxy])
        cmd.extend(["--", url])
        try:
            result = run_capture_interruptible(cmd, timeout=60)
            if result.interrupted or result.returncode != 0:
                return []
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, dict):
            return []
        if data.get("_type") not in ("playlist", "multi_video"):
            return []
        entries = data.get("entries") or []
        results = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            entry_url = e.get("url") or e.get("webpage_url") or ""
            if not entry_url:
                continue
            if entry_url and not entry_url.startswith("http"):
                entry_url = f"https://www.youtube.com/watch?v={entry_url}"
            results.append({
                "title": (e.get("title") or "Untitled")[:120],
                "url": entry_url,
                "duration": e.get("duration"),
            })
        return results

    def resolve(self, url, log_fn=None):
        has_ytdlp = self._has_ytdlp()
        if http_interrupted():
            return None
        if not has_ytdlp:
            self._log(log_fn, "yt-dlp not found. Install with: pip install yt-dlp")
            return None

        self._log(log_fn, f"Running yt-dlp extraction for: {url}")

        if self.cookies_browser:
            self._log(log_fn, f"Using cookies from: {self.cookies_browser}")
        try:
            result = run_capture_interruptible(self._build_cmd(url), timeout=60)
            if result.interrupted:
                return None
            if result.timed_out:
                self._log(log_fn, "yt-dlp timed out")
                return None
            if result.returncode == 0:
                data = json.loads(result.stdout)
            elif self._is_auth_error(result.stderr):
                data = self._auto_retry_with_browsers(url, result.stderr, log_fn)
                if data is None:
                    return None
            else:
                err = result.stderr.strip().split("\n")[-1] if result.stderr else "Unknown error"
                self._log(log_fn, f"yt-dlp error: {err}")
                return None
        except json.JSONDecodeError:
            self._log(log_fn, "Failed to parse yt-dlp output")
            return None
        except Exception:
            if http_interrupted():
                return None
            self._log(log_fn, "yt-dlp timed out")
            return None

        info = StreamInfo(
            platform="yt-dlp",
            url=url,
            title=data.get("title", ""),
            channel=(
                data.get("channel")
                or data.get("uploader_id")
                or data.get("uploader")
                or data.get("channel_id")
                or ""
            ),
            is_live=data.get("is_live", False),
        )

        raw_chapters = data.get("chapters") or []
        if isinstance(raw_chapters, list):
            for ch in raw_chapters:
                if not isinstance(ch, dict):
                    continue
                try:
                    info.chapters.append({
                        "title": str(ch.get("title") or "Chapter"),
                        "start": float(ch.get("start_time") or 0),
                        "end": float(ch.get("end_time") or 0),
                    })
                except (TypeError, ValueError):
                    continue

        # First pass — identify best audio-only format ID for pairing
        best_audio_id = ""
        best_audio_abr = 0
        audio_only_fmts = []
        for fmt in data.get("formats", []):
            if fmt.get("vcodec") != "none":
                continue
            if fmt.get("acodec") == "none":
                continue
            abr = fmt.get("abr") or 0
            fid = fmt.get("format_id", "")
            if fid and abr > best_audio_abr:
                best_audio_abr = abr
                best_audio_id = fid
            if fid:
                audio_only_fmts.append(fmt)

        # Second pass — video QualityInfo entries with ytdlp_direct spec
        for fmt in data.get("formats", []):
            if fmt.get("vcodec") == "none":
                continue
            ext = fmt.get("ext", "?")
            w = fmt.get("width") or 0
            h = fmt.get("height") or 0
            note = fmt.get("format_note", fmt.get("format_id", "?"))
            fid = fmt.get("format_id", "")
            if not fid:
                continue

            if fmt.get("acodec") == "none" and best_audio_id:
                format_spec = f"{fid}+{best_audio_id}"
                note = f"{note} +audio"
            else:
                format_spec = fid

            info.qualities.append(QualityInfo(
                name=f"{note} ({ext})",
                url=fmt.get("url", ""),
                resolution=f"{w}x{h}" if w and h else "?",
                bandwidth=int((fmt.get("tbr", 0) or 0) * 1000),
                format_type="ytdlp_direct",
                ytdlp_source=url,
                ytdlp_format=format_spec,
            ))

        dur = data.get("duration", 0)
        if dur:
            info.total_secs = float(dur)
            info.duration_str = fmt_duration(info.total_secs)

        info.qualities = [q for q in info.qualities if q.resolution != "0x0"]
        info.qualities.sort(key=lambda q: q.bandwidth, reverse=True)

        seen = set()
        unique = []
        for q in info.qualities:
            key = q.resolution
            if key not in seen:
                seen.add(key)
                unique.append(q)
        info.qualities = unique

        # Third pass — audio-only entries at the end of the list
        audio_only_fmts.sort(key=lambda f: f.get("abr") or 0, reverse=True)
        seen_audio = set()
        for fmt in audio_only_fmts:
            fid = fmt.get("format_id", "")
            abr = fmt.get("abr") or 0
            acodec = fmt.get("acodec", "?")
            key = f"{acodec}:{int(abr // 16) * 16}"
            if key in seen_audio:
                continue
            seen_audio.add(key)
            codec_short = acodec.split(".")[0] if "." in acodec else acodec
            if "mp4a" in acodec:
                codec_short = "aac"
            elif "opus" in acodec:
                codec_short = "opus"
            info.qualities.append(QualityInfo(
                name=f"Audio only ({codec_short}, {abr:.0f}k)",
                url=fmt.get("url", ""),
                resolution="audio",
                bandwidth=int(abr * 1000),
                format_type="ytdlp_direct",
                ytdlp_source=url,
                ytdlp_format=fid,
            ))

        self._log(
            log_fn,
            f"yt-dlp: {info.title}, {len(info.qualities)} formats, "
            f"{info.duration_str}",
        )
        if best_audio_id:
            self._log(
                log_fn,
                f"  Audio merge enabled (best audio id={best_audio_id}, "
                f"{best_audio_abr:.0f} kbps)",
            )
        audio_count = sum(1 for q in info.qualities if q.resolution == "audio")
        if audio_count:
            self._log(log_fn, f"  {audio_count} audio-only format(s) available")
        return info
