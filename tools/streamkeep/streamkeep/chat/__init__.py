"""Live chat capture — Twitch IRC + .ass sidecar renderer.

Kick support is deferred; Kick chat rides on Pusher (proprietary WS on top
of encrypted channels) and is its own moderate feature.
"""

from .twitch_irc import TwitchIRCReader
from .kick_ws import KickChatReader, is_available as kick_chat_available
from .chat_worker import ChatWorker

__all__ = [
    "TwitchIRCReader", "KickChatReader",
    "kick_chat_available", "ChatWorker",
]
