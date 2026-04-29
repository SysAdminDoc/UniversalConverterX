"""Embedded media player — mpv backend (F52)."""

from .mpv_widget import MpvWidget, is_mpv_available
from .player_controls import PlayerControls
from .player_panel import PlayerPanel

__all__ = ["MpvWidget", "PlayerControls", "PlayerPanel", "is_mpv_available"]
