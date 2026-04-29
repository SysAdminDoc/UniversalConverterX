"""Minimal anonymous Twitch IRC reader.

Connects to `irc.chat.twitch.tv:6667` as an anonymous (justinfanNNNNN)
user, requests the tags+commands capabilities, joins one channel, and
yields parsed messages to the caller. No external deps — just stdlib
`socket`.

This is scoped to public chat read-only. Authenticated (member-only)
chat would need an OAuth flow we don't ship yet.
"""

import random
import re
import socket
import ssl
import time

SERVER = "irc.chat.twitch.tv"
PORT = 6697


# IRCv3 tag-bearing line pattern:
#   @tag1=val;tag2=val :nick!user@host PRIVMSG #chan :message text
_MSG_RE = re.compile(
    r"^(?:@(?P<tags>[^ ]+)\s)?"
    r":(?P<nick>[^!]+)!(?:[^ ]+)\s"
    r"PRIVMSG\s#(?P<channel>\S+)\s"
    r":(?P<message>.+)$"
)


def _parse_tags(tag_str):
    if not tag_str:
        return {}
    out = {}
    for pair in tag_str.split(";"):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        out[k] = v
    return out


class TwitchIRCReader:
    """Open a blocking-but-interruptible Twitch IRC connection and
    iterate chat messages. Intended to be driven by a QThread so the
    `should_cancel` callback can stop the read loop."""

    def __init__(self, channel, should_cancel=None, timeout=15):
        # Twitch IRC expects lower-case channels without the # prefix.
        self.channel = (channel or "").lstrip("#").lower()
        self.should_cancel = should_cancel or (lambda: False)
        self.timeout = timeout
        self._sock = None

    def connect(self):
        nick = f"justinfan{random.randint(10000, 99999)}"
        raw = socket.create_connection((SERVER, PORT), timeout=self.timeout)
        ctx = ssl.create_default_context()
        sock = ctx.wrap_socket(raw, server_hostname=SERVER)
        sock.settimeout(1.0)   # short timeout so we can poll should_cancel
        sock.sendall(b"CAP REQ :twitch.tv/tags twitch.tv/commands\r\n")
        sock.sendall(b"PASS SCHMOOPIIE\r\n")   # anonymous password
        sock.sendall(f"NICK {nick}\r\n".encode())
        sock.sendall(f"JOIN #{self.channel}\r\n".encode())
        self._sock = sock

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def iter_messages(self):
        """Yield dicts {ts, nick, message, color, badges, mod, sub} as
        they arrive. Returns when the cancel hook fires or the socket
        dies — safe for a QThread run-loop."""
        if self._sock is None:
            self.connect()
        buf = ""
        while not self.should_cancel():
            try:
                data = self._sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            try:
                buf += data.decode("utf-8", errors="replace")
            except Exception:
                continue
            while "\r\n" in buf:
                line, buf = buf.split("\r\n", 1)
                if not line:
                    continue
                if line.startswith("PING"):
                    try:
                        self._sock.sendall(b"PONG :tmi.twitch.tv\r\n")
                    except OSError:
                        return
                    continue
                m = _MSG_RE.match(line)
                if not m:
                    continue
                tags = _parse_tags(m.group("tags") or "")
                yield {
                    "ts": time.time(),
                    "nick": tags.get("display-name") or m.group("nick"),
                    "message": m.group("message"),
                    "color": tags.get("color", "") or "",
                    "badges": tags.get("badges", "") or "",
                    "mod": tags.get("mod", "0") == "1",
                    "sub": tags.get("subscriber", "0") == "1",
                }
