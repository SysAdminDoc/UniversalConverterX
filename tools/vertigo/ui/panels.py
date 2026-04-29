"""Panel-assembly helpers that don't depend on MainWindow state.

Most of Vertigo's ``_build_*`` methods live on ``MainWindow`` because
they mutate window-local widget attributes (``self._preset_buttons``,
``self._mode_cards``, ``self._export_btn``, etc.) and connect signals
to window-local methods. Moving those helpers out would force every
builder to take the window as a parameter and drag the entire
widget/model/signal import set along with it — strictly more
cross-imports, not fewer.

The two helpers here are the exceptions: they build reusable container
layouts without touching window state at all, so they can live in a
module on their own.

  * ``build_tool_section(title, body, widget)`` — the labelled
    "Look / Track" / "Captions / Text" side-by-side tool wrappers used
    inside GlassPanel groupings.
  * ``add_overview_metric(lay, row, col, label)`` — the
    label-over-value metric tile used across the SESSION OVERVIEW
    panel.

If the rest of the build helpers ever lose their window coupling
(e.g. after a broader move to a props-style widget model), they can
migrate here. Until then, adding them would be churn.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def build_tool_section(title: str, body: str, widget: QWidget) -> QWidget:
    """Label + tooltip wrapper around a sub-panel widget.

    Used inside LOOK & TRACK / CAPTIONS & TEXT groupings so each half
    carries a small caption and a descriptive tooltip for the hover.
    """
    host = QWidget()
    host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    host.setToolTip(body)

    title_lbl = QLabel(title)
    title_lbl.setObjectName("formLabel")
    lay.addWidget(title_lbl)

    lay.addWidget(widget, 1)
    return host


def add_overview_metric(lay: QGridLayout, row: int, col: int, label: str) -> QLabel:
    """Attach a "label-over-value" metric tile to a grid layout.

    Returns the value QLabel so the caller can keep a reference and
    update it later as the session state changes.
    """
    host = QWidget()
    host_lay = QVBoxLayout(host)
    host_lay.setContentsMargins(0, 0, 0, 0)
    host_lay.setSpacing(2)
    title = QLabel(label)
    title.setObjectName("formLabel")
    value = QLabel("")
    value.setObjectName("valueBright")
    value.setWordWrap(True)
    host_lay.addWidget(title)
    host_lay.addWidget(value)
    lay.addWidget(host, row, col)
    return value
