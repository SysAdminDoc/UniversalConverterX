"""Caption presets — bundled styles for 9:16 burn-in.

Each preset is a self-contained description of how captions should
look on the exported video. Sizes and margins are *resolution-relative*
(expressed as fractions of video height) so the same preset lands
correctly on 1080 × 1920, 720 × 1280, or anything else.

2026 creator-tool consensus baked into defaults:

    font size    : height / 22                   (~87 pt at 1080 p)
    bottom margin: 0.20 × height                 (safe-area above UI chrome)
    max lines    : 2
    max chars per line : ~18 at 1080 p
    chunk words  : 3–4 words, ≤ 1.2 s per chunk

Presets compile to ASS `Style:` + `force_style=` strings inside
`core.encode._subtitles_filter()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Animation = Literal["none", "karaoke", "pop"]


@dataclass(frozen=True)
class CaptionPreset:
    """A resolution-relative caption style."""

    id: str
    label: str
    description: str

    # Typography
    font_name: str = "Inter"
    font_fallback: tuple[str, ...] = ("Segoe UI", "Arial", "sans-serif")
    # Font size as a fraction of video height (height / scale). 22 ≈ 87pt at 1080p.
    font_scale: float = 22.0
    bold: bool = True
    italic: bool = False

    # Colours (hex strings, alpha 00 = opaque for ASS)
    primary: str = "#FFFFFF"      # fill
    secondary: str = "#FFD166"    # karaoke highlight
    outline: str = "#11111B"
    back: str = "#11111B"

    # Stroke / shadow
    outline_px: float = 3.0       # at 1080p reference; scaled per clip
    shadow_px: float = 0.0
    border_style: int = 1         # 1 = outline+shadow; 3 = opaque box

    # Animation
    animation: Animation = "none"

    # Layout
    alignment: int = 2            # ASS: 2 = bottom-center, 8 = top-center
    margin_v_fraction: float = 0.20  # vertical margin as fraction of height
    margin_h_fraction: float = 0.06

    # Word chunking (for karaoke/pop modes using word-level timings)
    max_chars_per_line: int = 18
    max_lines: int = 2
    max_words_per_chunk: int = 4
    max_seconds_per_chunk: float = 1.2


# ---------------------------------------------------------------- presets

PRESETS: dict[str, CaptionPreset] = {
    "clean": CaptionPreset(
        id="clean",
        label="Clean",
        description="Minimal white text with a subtle outline. Reads anywhere.",
        font_name="Inter",
        primary="#FFFFFF",
        outline="#11111B",
        outline_px=3.0,
        shadow_px=0.0,
        border_style=1,
    ),
    "pop": CaptionPreset(
        id="pop",
        label="Pop",
        description="White text with a heavier outline and subtle drop shadow.",
        font_name="Inter",
        font_scale=20.0,
        primary="#FFFFFF",
        outline="#11111B",
        outline_px=4.5,
        shadow_px=1.2,
        border_style=1,
        animation="pop",
    ),
    "karaoke": CaptionPreset(
        id="karaoke",
        label="Karaoke",
        description="Per-word fill sweep in accent colour. Requires word-level timings.",
        font_name="Inter",
        font_scale=20.0,
        primary="#FFFFFF",
        secondary="#CBA6F7",
        outline="#11111B",
        outline_px=3.5,
        border_style=1,
        animation="karaoke",
    ),
    "bold_yellow": CaptionPreset(
        id="bold_yellow",
        label="Bold Yellow",
        description="Creator-favourite yellow on heavy black outline.",
        font_name="Inter",
        font_scale=19.0,
        primary="#FFD166",
        outline="#11111B",
        outline_px=5.0,
        shadow_px=1.0,
        border_style=1,
        animation="pop",
    ),
    "neon_outline": CaptionPreset(
        id="neon_outline",
        label="Neon Outline",
        description="White fill, magenta outline, subtle glow-style stroke.",
        font_name="Inter",
        font_scale=21.0,
        primary="#FFFFFF",
        outline="#F5C2E7",
        outline_px=4.0,
        shadow_px=1.5,
        border_style=1,
    ),
    "classic": CaptionPreset(
        id="classic",
        label="Classic",
        description="Broadcast-style opaque box, lower-third positioning.",
        font_name="Inter",
        font_scale=24.0,
        bold=False,
        primary="#FFFFFF",
        outline="#000000",
        back="#000000",
        border_style=3,
        margin_v_fraction=0.12,
    ),
}


def default_preset() -> CaptionPreset:
    return PRESETS["pop"]


def resolve(preset_id: str | None) -> CaptionPreset:
    if preset_id and preset_id in PRESETS:
        return PRESETS[preset_id]
    return default_preset()


# ---------------------------------------------------------------- ASS helpers

def _hex_to_ass_color(hex_str: str, alpha: int = 0) -> str:
    """#RRGGBB → ASS &HAABBGGRR (alpha 0 = fully opaque)."""
    s = hex_str.lstrip("#").upper()
    if len(s) != 6:
        s = "FFFFFF"
    r, g, b = s[0:2], s[2:4], s[4:6]
    return f"&H{alpha:02X}{b}{g}{r}"


def style_for_height(preset: CaptionPreset, height_px: int) -> dict:
    """Translate a resolution-relative preset into concrete ASS values.

    Returns a dict that can be serialized into ASS `force_style=...`.
    """
    h = max(240, int(height_px))
    font_size = max(14, int(round(h / preset.font_scale)))
    margin_v = max(24, int(round(h * preset.margin_v_fraction)))
    margin_lr = max(16, int(round(h * preset.margin_h_fraction)))

    # Stroke/shadow scale relative to 1080p reference
    px_scale = h / 1080.0
    outline = max(1.0, preset.outline_px * px_scale)
    shadow = max(0.0, preset.shadow_px * px_scale)

    return {
        "FontName": preset.font_name,
        "FontSize": font_size,
        "Bold": -1 if preset.bold else 0,
        "Italic": -1 if preset.italic else 0,
        "PrimaryColour": _hex_to_ass_color(preset.primary),
        "SecondaryColour": _hex_to_ass_color(preset.secondary),
        "OutlineColour": _hex_to_ass_color(preset.outline),
        "BackColour": _hex_to_ass_color(preset.back, alpha=0 if preset.border_style == 3 else 0x60),
        "BorderStyle": preset.border_style,
        "Outline": f"{outline:.2f}",
        "Shadow": f"{shadow:.2f}",
        "Alignment": preset.alignment,
        "MarginV": margin_v,
        "MarginL": margin_lr,
        "MarginR": margin_lr,
    }


def force_style_string(preset: CaptionPreset, height_px: int) -> str:
    """Serialise a style dict into the FFmpeg `force_style=` form."""
    pairs = [f"{k}={v}" for k, v in style_for_height(preset, height_px).items()]
    return ",".join(pairs)
