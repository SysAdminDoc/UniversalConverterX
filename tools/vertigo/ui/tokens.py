"""Design tokens — the single source of truth for Vertigo's visual system.

Every pixel value, font size, radius, duration, and motion curve that
appears more than once should be anchored here. Stylesheets and widgets
reference these constants instead of hard-coding numbers so the whole
product can be re-tuned by editing one file.

Scales follow a coherent ratio:

    spacing : 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48     (4 px rhythm)
    radius  : 6 / 10 / 14 / 18                              (chip → panel → hero)
    text    : 11 / 12 / 13 / 15 / 20 / 28                   (caption → display)
    weight  : 400 / 500 / 600 / 700                         (regular → bold)

Use `S.md` / `R.panel` / `T.body` at call sites so the intent is legible.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------- spacing

@dataclass(frozen=True)
class _Spacing:
    xxs: int = 2
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 20
    xxl: int = 24
    huge: int = 32
    gargantuan: int = 48


S = _Spacing()


# ---------------------------------------------------------------- radius

@dataclass(frozen=True)
class _Radius:
    pill: int = 999       # fully-rounded chips
    chip: int = 6         # small inputs, badges, status dots
    control: int = 10     # buttons, inputs, dropdowns
    panel: int = 14       # cards, sidebars
    hero: int = 18        # hero/feature surfaces
    modal: int = 14


R = _Radius()


# ---------------------------------------------------------------- type

@dataclass(frozen=True)
class _Text:
    # sizes (px)
    caption: int = 11      # meta, helper, muted info
    body_s: int = 12       # default small body / secondary UI
    body: int = 13         # default body, buttons, cards
    title: int = 15        # panel headings, emphasized row titles
    subtitle: int = 14     # subsection labels
    display: int = 20      # hero titles, big counts
    hero: int = 28         # rarely-used, for empty state art


T = _Text()


@dataclass(frozen=True)
class _Weight:
    regular: int = 400
    medium: int = 500
    semibold: int = 600
    bold: int = 700


W = _Weight()


# ---------------------------------------------------------------- motion

@dataclass(frozen=True)
class _Motion:
    fast: int = 120        # ms — hover, tiny state changes
    base: int = 180        # ms — standard transitions
    slow: int = 280        # ms — panel transitions, modals
    page: int = 360        # ms — big reveals


M = _Motion()


# ---------------------------------------------------------------- elevation
# Qt Widgets don't have true shadow DOM; we simulate elevation with
# background color layering (crust → mantle → surface0 → ...). These
# aliases label intent so code can reference `E.resting`, not `mantle`.

class E:
    """Semantic layer names for surface backgrounds.

    resting   : the page itself (`palette.base`)
    elevated  : a card / panel sitting on the page (`palette.mantle`)
    raised    : an item on an elevated surface (`palette.surface0`)
    pressed   : hover / selected surfaces (`palette.surface1`)
    """
    resting: str = "base"
    elevated: str = "mantle"
    raised: str = "surface0"
    pressed: str = "surface1"
