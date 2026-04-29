"""Kick live chat reader over the public Pusher WebSocket.

Kick routes its chat through Pusher. The relevant constants (app key +
cluster) are in the page HTML of any Kick channel — we hard-code the
currently-shipped defaults and fall back to scraping them from the
channel page if the constants rotate.

Flow:
  1. HTTP GET https://kick.com/api/v2/channels/{slug}       -> chatroom.id
  2. WS connect wss://ws-us2.pusher.com/app/<key>?...
  3. Subscribe to channel `chatrooms.<chatroom_id>.v2`
  4. Parse `App\\Events\\ChatMessageEvent` envelopes into the same dict
     shape as TwitchIRCReader.

Requires the `websocket-client` pip package (bootstrap adds it to the
optional list). If unavailable, `is_available()` returns False and the
caller logs a clear "install websocket-client" hint.
"""

import json
import re
import time
import urllib.error
import urllib.request

# Known-good defaults as of late 2025. If Kick rotates these, the page
# scrape path below picks up the new values.
_DEFAULT_APP_KEY = "32cbd69e4b950bf97679"
_DEFAULT_CLUSTER = "us2"


def is_available():
    """Whether the optional WebSocket dep is importable."""
    try:
        import websocket  # availability probe
    except ImportError:
        return False
    return hasattr(websocket, "create_connection")


def _channel_meta(slug):
    """Fetch /api/v2/channels/{slug} — returns (chatroom_id, channel_name).
    Raises OSError on network failure so the caller can log cleanly."""
    url = f"https://kick.com/api/v2/channels/{slug.lstrip('/')}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (StreamKeep)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    chatroom_id = None
    # v2 API shape: {"chatroom": {"id": 12345}, "slug": "...", ...}
    if isinstance(data, dict):
        if isinstance(data.get("chatroom"), dict):
            chatroom_id = data["chatroom"].get("id")
        elif "chatroom_id" in data:
            chatroom_id = data["chatroom_id"]
    if not chatroom_id:
        raise OSError("Could not resolve chatroom id from Kick API response.")
    channel_name = str(data.get("user", {}).get("username") or data.get("slug") or slug)
    return int(chatroom_id), channel_name


def _probe_pusher_constants():
    """If the hard-coded defaults stop working, we can scrape the current
    pusher key + cluster from the main Kick HTML bundle. Best-effort —
    return defaults on any failure so the hot-path always has values."""
    try:
        req = urllib.request.Request(
            "https://kick.com/",
            headers={"User-Agent": "Mozilla/5.0 (StreamKeep)"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return _DEFAULT_APP_KEY, _DEFAULT_CLUSTER
    key_m = re.search(r'PUSHER_APP_KEY\s*[:=]\s*["\']([A-Za-z0-9]+)["\']', html)
    cluster_m = re.search(r'PUSHER_CLUSTER\s*[:=]\s*["\']([A-Za-z0-9]+)["\']', html)
    return (
        key_m.group(1) if key_m else _DEFAULT_APP_KEY,
        cluster_m.group(1) if cluster_m else _DEFAULT_CLUSTER,
    )


class KickChatReader:
    """Blocking Pusher WebSocket consumer. Drive from a QThread so the
    `should_cancel` callback can break out cleanly."""

    def __init__(self, channel_slug, should_cancel=None):
        self.channel_slug = (channel_slug or "").strip().strip("/")
        self.should_cancel = should_cancel or (lambda: False)
        self._ws = None
        self.channel_name = ""
        self.chatroom_id = 0

    def connect(self):
        import websocket   # imported lazily so missing dep doesn't crash import
        self.chatroom_id, self.channel_name = _channel_meta(self.channel_slug)
        app_key, cluster = _probe_pusher_constants()
        url = (
            f"wss://ws-{cluster}.pusher.com/app/{app_key}"
            "?protocol=7&client=js&version=7.6.0&flash=false"
        )
        self._ws = websocket.create_connection(url, timeout=10)
        # Pusher sends pusher:connection_established first; we subscribe
        # to the chatroom channel and then consume indefinitely.
        sub_msg = json.dumps({
            "event": "pusher:subscribe",
            "data": {"auth": "", "channel": f"chatrooms.{self.chatroom_id}.v2"},
        })
        self._ws.send(sub_msg)

    def close(self):
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def iter_messages(self):
        """Yield dicts matching the TwitchIRCReader shape."""
        if self._ws is None:
            self.connect()
        # Short recv timeout so should_cancel is checked regularly.
        self._ws.settimeout(1.0)
        while not self.should_cancel():
            try:
                raw = self._ws.recv()
            except Exception:
                # Includes websocket._exceptions.WebSocketTimeoutException and
                # a hard-close during shutdown. Both end the iteration.
                # Distinguish timeout from close by peeking at state.
                try:
                    is_open = bool(self._ws and self._ws.connected)
                except Exception:
                    is_open = False
                if not is_open:
                    return
                continue
            if not raw:
                continue
            try:
                envelope = json.loads(raw)
            except ValueError:
                continue
            event = envelope.get("event", "")
            if event == "pusher:ping":
                try:
                    self._ws.send(json.dumps({"event": "pusher:pong"}))
                except Exception:
                    return
                continue
            if not event.endswith("ChatMessageEvent"):
                continue
            # Pusher nests the payload as a JSON-encoded string inside data.
            try:
                payload = json.loads(envelope.get("data") or "{}")
            except ValueError:
                continue
            sender = payload.get("sender") or {}
            username = sender.get("username") or sender.get("slug") or ""
            content = payload.get("content") or ""
            if not username or not content:
                continue
            yield {
                "ts": time.time(),
                "nick": str(username),
                "message": str(content),
                "color": str((sender.get("identity") or {}).get("color", "") or ""),
                "badges": "",
                "mod": False,
                "sub": False,
            }
