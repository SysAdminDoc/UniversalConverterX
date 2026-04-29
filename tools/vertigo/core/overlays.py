"""Text overlays — title cards, burned-in lower-thirds, on-screen labels.

Each overlay compiles to a single FFmpeg `drawtext=` filter gated by
`enable='between(t,start,end)'`. They chain together comma-separated
and sit at the end of the video-filter pipeline.

Four placement presets:

    TITLE       - centered hero title, large
    TOP         - top-centered strap
    LOWER_THIRD - left-anchored lower-third headline
    CAPTION     - bottom-centered short label
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum


class OverlayPosition(str, Enum):
    TITLE = "title"
    TOP = "top"
    LOWER_THIRD = "lower_third"
    CAPTION = "caption"


_POSITIONS: dict[OverlayPosition, tuple[str, str]] = {
    # (x_expr, y_expr)
    OverlayPosition.TITLE:       ("(w-text_w)/2", "(h-text_h)/2"),
    OverlayPosition.TOP:         ("(w-text_w)/2", "h*0.08"),
    OverlayPosition.LOWER_THIRD: ("w*0.08",       "h*0.72"),
    OverlayPosition.CAPTION:     ("(w-text_w)/2", "h-text_h-h*0.06"),
}


@dataclass
class TextOverlay:
    text: str
    start: float = 0.0
    end: float = 3.0
    position: OverlayPosition = OverlayPosition.TITLE
    size: int = 72                   # font px
    color: str = "#ffffff"
    background: bool = True          # pill behind text
    background_color: str = "#11111b"
    background_alpha: float = 0.55
    stroke: bool = True
    stroke_color: str = "#11111b"
    stroke_width: int = 3
    id: int = 0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def build_filter_chain(overlays: list[TextOverlay]) -> str:
    """Return a comma-joined drawtext chain for all non-empty overlays."""
    parts = [_overlay_filter(o) for o in overlays if _is_usable(o)]
    return ",".join(p for p in parts if p)


def _is_usable(o: TextOverlay) -> bool:
    if not o.text.strip():
        return False
    if not (math.isfinite(o.start) and math.isfinite(o.end)):
        return False
    if o.duration <= 0.05:
        return False
    return True


def _overlay_filter(o: TextOverlay) -> str:
    text = _escape_text(o.text)
    x, y = _POSITIONS[o.position]

    # Clamp user-tunable numbers into sane ranges so FFmpeg never receives
    # negative font sizes, exploding border widths, or NaN time windows.
    font_size = max(8, min(512, int(o.size)))
    stroke_width = max(0, min(32, int(o.stroke_width)))
    start = max(0.0, float(o.start))
    end = max(start, float(o.end))

    args: list[str] = [
        f"drawtext=text='{text}'",
        f"x={x}",
        f"y={y}",
        f"fontsize={font_size}",
        f"fontcolor={_ffmpeg_color(o.color)}",
        f"enable='between(t,{start:.3f},{end:.3f})'",
        # line spacing feels right for mobile at this weight
        "line_spacing=6",
    ]

    if o.stroke and stroke_width > 0:
        args.append(f"bordercolor={_ffmpeg_color(o.stroke_color)}")
        args.append(f"borderw={stroke_width}")

    if o.background:
        alpha = max(0.0, min(1.0, float(o.background_alpha)))
        args.append("box=1")
        args.append(f"boxcolor={_ffmpeg_color(o.background_color)}@{alpha:.2f}")
        args.append("boxborderw=18")

    return ":".join(args)


_HEX_PATTERN = re.compile(r"^[0-9a-fA-F]{6}$")


def _ffmpeg_color(hex_str: str) -> str:
    """FFmpeg accepts both `0xRRGGBB` and `#RRGGBB`; normalize to 0x form.

    Unknown / malformed input falls back to opaque white so a broken
    colour field never corrupts the whole filter graph.
    """
    s = (hex_str or "").strip()
    if s.startswith("#"):
        s = s[1:]
    elif s.lower().startswith("0x"):
        s = s[2:]
    if not _HEX_PATTERN.fullmatch(s):
        return "0xFFFFFF"
    return "0x" + s.upper()


def _escape_text(text: str) -> str:
    """Escape FFmpeg drawtext metacharacters and keep newlines as literal \\n."""
    out = (
        text.replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "\\\u2019")   # curly apostrophe avoids needing expr escape
            .replace("\n", "\\n")
    )
    # percent is filter metachar
    out = out.replace("%", "\\%")
    return out
