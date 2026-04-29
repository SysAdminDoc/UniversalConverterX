"""ChatWorker — QThread that drives a TwitchIRCReader during a live
capture, writes a JSONL sidecar, and (optionally) renders a .ass
subtitle sidecar so the chat replays in-sync with the video.

One worker per active auto-record. The caller passes the output
directory and a start-timestamp (roughly when ffmpeg began capturing)
so .ass event times can be referenced to video time zero.
"""

import json
import os
import time

from PyQt6.QtCore import QThread, pyqtSignal

from .twitch_irc import TwitchIRCReader
from .kick_ws import KickChatReader, is_available as kick_chat_available


def _ass_time(secs):
    """Format seconds as H:MM:SS.cs required by the .ass spec."""
    secs = max(0.0, float(secs))
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = secs - h * 3600 - m * 60
    return f"{h}:{m:02d}:{s:05.2f}"


_ASS_HEADER = """\
[Script Info]
Title: StreamKeep live chat
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Chat,Consolas,22,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,1,0,7,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


class ChatWorker(QThread):
    """One worker per live capture. Streams IRC chat to a .jsonl file
    and optionally writes a .ass subtitle sidecar on shutdown.

    Signals:
        message(str nick, str text)     every new chat line
        log(str)                        diagnostic output
        done(int count)                 on exit, lines written
    """

    message = pyqtSignal(str, str)
    log = pyqtSignal(str)
    done = pyqtSignal(int)

    def __init__(self, channel, out_dir, *, platform="twitch", render_ass=True, start_ts=None):
        super().__init__()
        self.channel = channel
        self.out_dir = out_dir
        self.platform = (platform or "twitch").lower()
        self.render_ass = bool(render_ass)
        self.start_ts = float(start_ts or time.time())
        self._cancel = False
        self._count = 0

    def cancel(self):
        self._cancel = True

    def _should_cancel(self):
        return self._cancel

    def run(self):
        try:
            os.makedirs(self.out_dir, exist_ok=True)
        except OSError:
            self.done.emit(0)
            return
        jsonl_path = os.path.join(self.out_dir, "chat.jsonl")
        ass_path = os.path.join(self.out_dir, "chat.ass") if self.render_ass else None
        if self.platform == "kick":
            if not kick_chat_available():
                self.log.emit(
                    "[CHAT] Kick chat needs the `websocket-client` pip "
                    "package — install with `pip install websocket-client` "
                    "or re-run the bundled exe to bootstrap it."
                )
                self.done.emit(0)
                return
            reader = KickChatReader(self.channel, should_cancel=self._should_cancel)
            platform_label = "kick"
        else:
            reader = TwitchIRCReader(self.channel, should_cancel=self._should_cancel)
            platform_label = "twitch"
        try:
            reader.connect()
        except OSError as e:
            self.log.emit(f"[CHAT] Could not connect to {platform_label}: {e}")
            self.done.emit(0)
            return
        except Exception as e:
            self.log.emit(f"[CHAT] {platform_label} reader failed: {e}")
            self.done.emit(0)
            return
        ch_label = getattr(reader, "channel", None) or getattr(reader, "channel_name", "") or self.channel
        self.log.emit(f"[CHAT] Capturing {platform_label} chat for {ch_label}")
        try:
            with open(jsonl_path, "a", encoding="utf-8") as jsonl_f:
                ass_events = []
                for msg in reader.iter_messages():
                    if self._cancel:
                        break
                    jsonl_f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                    jsonl_f.flush()
                    self._count += 1
                    self.message.emit(msg["nick"], msg["message"])
                    if self.render_ass:
                        rel = max(0.0, msg["ts"] - self.start_ts)
                        # Each chat line stays on screen for 8 seconds.
                        text = self._ass_escape(f"{msg['nick']}: {msg['message']}")
                        ass_events.append((rel, rel + 8.0, text))
        except Exception as e:
            self.log.emit(f"[CHAT] Reader error: {e}")
        finally:
            reader.close()
        # Write .ass sidecar at the end so partial captures still produce
        # a usable file.
        if self.render_ass and ass_path:
            try:
                with open(ass_path, "w", encoding="utf-8") as f:
                    f.write(_ASS_HEADER)
                    for start, end, text in ass_events:
                        f.write(
                            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},"
                            f"Chat,,0,0,0,,{text}\n"
                        )
                self.log.emit(f"[CHAT] Wrote {self._count} line(s) + .ass sidecar")
            except OSError as e:
                self.log.emit(f"[CHAT] Could not write .ass: {e}")
        self.done.emit(self._count)

    @staticmethod
    def _ass_escape(s):
        # ASS comment/format characters must be escaped or the line is
        # silently dropped by the renderer.
        return (
            s.replace("\\", "\\\\")
             .replace("{", "(").replace("}", ")")
             .replace("\r", "").replace("\n", " ")
        )
