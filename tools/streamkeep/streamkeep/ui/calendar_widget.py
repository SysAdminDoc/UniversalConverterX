"""Premium week-view schedule calendar for monitored channels."""

from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QToolTip, QVBoxLayout, QWidget,
)

from ..theme import CAT
from .widgets import make_empty_state, make_status_banner, update_status_banner

_BLOCK_COLOR_KEYS = ["blue", "green", "peach", "mauve", "teal", "pink", "yellow", "lavender"]
_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Display window: 6 AM to midnight (18 hours)
_START_HOUR = 6
_END_HOUR = 24
_HOUR_SPAN = _END_HOUR - _START_HOUR


def _block_colors():
    """Return current block colors from the live CAT dict (theme-safe)."""
    return [CAT[k] for k in _BLOCK_COLOR_KEYS]


def _segment_bounds_local(seg):
    """Return (start_dt, end_dt) in local time or (None, None)."""
    start_iso = seg.get("start_iso", "")
    if not start_iso:
        return None, None
    try:
        start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone()
    except (ValueError, TypeError):
        return None, None

    end_dt = None
    end_iso = seg.get("end_iso", "")
    if end_iso:
        try:
            end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00")).astimezone()
        except (ValueError, TypeError):
            end_dt = None
    return start_dt, end_dt


def _segment_duration_hours(seg):
    """Return scheduled duration in hours, clamped to a visible minimum."""
    start_dt, end_dt = _segment_bounds_local(seg)
    if start_dt and end_dt:
        return max(0.25, (end_dt - start_dt).total_seconds() / 3600.0)
    return 1.0


def _format_dt(dt):
    """Format a local datetime in a compact human way."""
    if not dt:
        return "Unknown"
    text = dt.strftime("%a, %b %d at %I:%M %p")
    return text.replace(" 0", " ")


def _format_time_range(seg):
    """Return a compact local time range string for a schedule segment."""
    start_dt, end_dt = _segment_bounds_local(seg)
    if not start_dt:
        return "Time unavailable"
    if not end_dt:
        return start_dt.strftime("%I:%M %p").replace(" 0", " ")
    start_text = start_dt.strftime("%I:%M %p").replace(" 0", " ")
    end_text = end_dt.strftime("%I:%M %p").replace(" 0", " ")
    return f"{start_text} - {end_text}"


class _GridCanvas(QWidget):
    """Custom-painted week grid with schedule blocks."""

    block_clicked = pyqtSignal(dict)  # emits the segment dict

    _label_w = 52
    _header_h = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(400)
        self.setMouseTracking(True)
        self._segments = []   # list of (day_idx, hour_frac, seg_dict, color)
        self._channel_colors = {}
        self._hovered_idx = -1
        self._selected_idx = -1
        self._week_start = None

    def set_segments(self, week_segments, week_start):
        """Set visible week segments and redraw."""
        colors = _block_colors()
        self._week_start = week_start
        self._segments = []
        self._hovered_idx = -1
        if self._selected_idx >= len(week_segments):
            self._selected_idx = -1
        for day_idx, hour_frac, seg in week_segments:
            channel = seg.get("channel", "")
            if channel not in self._channel_colors:
                idx = len(self._channel_colors) % len(colors)
                self._channel_colors[channel] = colors[idx]
            color = self._channel_colors[channel]
            self._segments.append((day_idx, hour_frac, seg, color))
        self.update()

    def _grid_metrics(self):
        width = max(1, self.width())
        height = max(1, self.height())
        grid_w = max(1.0, width - self._label_w)
        grid_h = max(1.0, height - self._header_h)
        return grid_w / 7.0, grid_h / float(_HOUR_SPAN)

    def _segment_rect(self, day_idx, hour_frac, seg):
        """Return the on-canvas QRectF for a segment or None if off-screen."""
        col_w, row_h = self._grid_metrics()
        duration = _segment_duration_hours(seg)
        y_start = hour_frac - _START_HOUR
        if y_start + duration < 0 or y_start > _HOUR_SPAN:
            return None
        y_start = max(0.0, y_start)
        x = self._label_w + day_idx * col_w + 4
        y = self._header_h + y_start * row_h + 2
        width = max(14.0, col_w - 8)
        height = max(10.0, duration * row_h - 4)
        return QRectF(x, y, width, height)

    def _segment_index_at(self, pos):
        """Return the segment index under the given point, or -1."""
        for idx, (day_idx, hour_frac, seg, _color) in enumerate(self._segments):
            rect = self._segment_rect(day_idx, hour_frac, seg)
            if rect and rect.contains(pos):
                return idx
        return -1

    def _tooltip_for_segment(self, seg):
        """Build a richer tooltip string for the current segment."""
        start_dt, end_dt = _segment_bounds_local(seg)
        lines = [
            seg.get("channel", "") or "Scheduled stream",
            seg.get("title", "") or "Untitled stream",
            _format_time_range(seg),
        ]
        if seg.get("category"):
            lines.append(seg["category"])
        if start_dt:
            lines.append(start_dt.tzname() or "Local time")
        if end_dt:
            duration_minutes = max(1, int((end_dt - start_dt).total_seconds() / 60.0))
            lines.append(f"Approx. {duration_minutes} min")
        return "\n".join(line for line in lines if line)

    def _update_hover(self, pos, global_pos=None):
        """Update the hovered block, tooltip, and cursor."""
        idx = self._segment_index_at(pos)
        if idx != self._hovered_idx:
            self._hovered_idx = idx
            self.update()
        if idx >= 0:
            _, _, seg, _ = self._segments[idx]
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            if global_pos is not None:
                QToolTip.showText(global_pos, self._tooltip_for_segment(seg), self)
        else:
            self.unsetCursor()
            QToolTip.hideText()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        height = self.height()
        col_w, row_h = self._grid_metrics()

        painter.fillRect(0, 0, width, height, QColor(CAT["base"]))

        # Subtle alternating hour bands keep long schedules easier to scan.
        band_color = QColor(CAT["panelSoft"])
        band_color.setAlpha(120)
        for hr in range(_HOUR_SPAN):
            if hr % 2 == 0:
                y = self._header_h + hr * row_h
                painter.fillRect(
                    QRectF(self._label_w, y, width - self._label_w, row_h),
                    band_color,
                )

        # Highlight the current local day when the visible week includes it.
        today = datetime.now(timezone.utc).astimezone().date()
        if self._week_start and self._week_start <= today < self._week_start + timedelta(days=7):
            today_idx = (today - self._week_start).days
            today_rect = QRectF(
                self._label_w + today_idx * col_w + 2,
                0,
                col_w - 4,
                height,
            )
            today_fill = QColor(CAT["accent"])
            today_fill.setAlpha(24)
            painter.fillRect(today_rect, today_fill)

        # Day headers
        for day_idx in range(7):
            day_rect = QRectF(self._label_w + day_idx * col_w + 2, 2, col_w - 4, self._header_h - 6)
            header_fill = QColor(CAT["mantle"])
            header_fill.setAlpha(230)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(header_fill)
            painter.drawRoundedRect(day_rect, 10, 10)

            day_text = _DAY_NAMES[day_idx]
            if self._week_start:
                day_date = self._week_start + timedelta(days=day_idx)
                day_text = f"{day_text} {day_date.day}"
                if day_date == today:
                    header_fill = QColor(CAT["accent"])
                    header_fill.setAlpha(55)
                    painter.setBrush(header_fill)
                    painter.drawRoundedRect(day_rect, 10, 10)
            painter.setPen(QColor(CAT["text"]))
            painter.drawText(day_rect, Qt.AlignmentFlag.AlignCenter, day_text)

        # Hour grid lines + labels
        line_color = QColor(CAT["surface0"])
        line_color.setAlpha(180)
        painter.setPen(QPen(line_color, 1))
        for hr in range(_HOUR_SPAN + 1):
            y = self._header_h + hr * row_h
            painter.drawLine(int(self._label_w), int(y), width, int(y))
            if hr < _HOUR_SPAN:
                actual_hr = _START_HOUR + hr
                lbl = f"{actual_hr:02d}"
                painter.setPen(QColor(CAT["subtext0"]))
                painter.drawText(
                    QRectF(0, y - 1, self._label_w - 8, row_h),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                    lbl,
                )
                painter.setPen(QPen(line_color, 1))

        # Day separators
        for day_idx in range(8):
            x = self._label_w + day_idx * col_w
            painter.drawLine(int(x), self._header_h, int(x), height)

        # Current-time line on today's column for the current week.
        now = datetime.now(timezone.utc).astimezone()
        if (
            self._week_start
            and self._week_start <= now.date() < self._week_start + timedelta(days=7)
            and _START_HOUR <= now.hour < _END_HOUR
        ):
            day_idx = (now.date() - self._week_start).days
            y = self._header_h + (now.hour + now.minute / 60.0 - _START_HOUR) * row_h
            now_color = QColor(CAT["red"])
            painter.setPen(QPen(now_color, 2))
            painter.drawLine(
                int(self._label_w + day_idx * col_w + 3),
                int(y),
                int(self._label_w + (day_idx + 1) * col_w - 3),
                int(y),
            )

        metrics = painter.fontMetrics()

        # Schedule blocks
        for idx, (day_idx, hour_frac, seg, color_value) in enumerate(self._segments):
            rect = self._segment_rect(day_idx, hour_frac, seg)
            if rect is None:
                continue

            base_color = QColor(color_value)
            if idx == self._selected_idx:
                fill = base_color.lighter(120)
            elif idx == self._hovered_idx:
                fill = base_color.lighter(112)
            else:
                fill = QColor(base_color)
            fill.setAlpha(220)

            glow = QColor(fill)
            glow.setAlpha(52 if idx == self._hovered_idx else 28)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 14, 14)

            border = QColor(fill.lighter(122 if idx in (self._hovered_idx, self._selected_idx) else 108))
            painter.setBrush(fill)
            painter.setPen(QPen(border, 1.4))
            painter.drawRoundedRect(rect, 12, 12)

            text_rect = rect.adjusted(8, 6, -8, -6)
            painter.setPen(QColor(CAT["crust"]))
            title = seg.get("title", "") or seg.get("channel", "") or "Scheduled stream"
            title = metrics.elidedText(title, Qt.TextElideMode.ElideRight, int(max(40.0, text_rect.width())))
            painter.drawText(
                QRectF(text_rect.left(), text_rect.top(), text_rect.width(), 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                title,
            )

            if text_rect.height() >= 30:
                painter.setPen(QColor(CAT["mantle"]))
                subtitle = seg.get("channel", "") or _format_time_range(seg)
                if seg.get("channel") and text_rect.height() >= 44:
                    subtitle = _format_time_range(seg)
                subtitle = metrics.elidedText(
                    subtitle,
                    Qt.TextElideMode.ElideRight,
                    int(max(40.0, text_rect.width())),
                )
                painter.drawText(
                    QRectF(text_rect.left(), text_rect.top() + 18, text_rect.width(), 16),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                    subtitle,
                )

            if text_rect.height() >= 46 and seg.get("category"):
                painter.setPen(QColor(CAT["surface0"]))
                category = metrics.elidedText(
                    seg["category"],
                    Qt.TextElideMode.ElideRight,
                    int(max(40.0, text_rect.width())),
                )
                painter.drawText(
                    QRectF(text_rect.left(), text_rect.top() + 34, text_rect.width(), 16),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                    category,
                )

        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        idx = self._segment_index_at(event.position())
        if idx >= 0:
            self._selected_idx = idx
            self.update()
            self.block_clicked.emit(self._segments[idx][2])
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self._update_hover(event.position(), event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        del event
        if self._hovered_idx != -1:
            self._hovered_idx = -1
            self.update()
        self.unsetCursor()
        QToolTip.hideText()


class ScheduleCalendar(QWidget):
    """Week-view calendar with premium navigation, feedback, and empty states."""

    block_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = {}
        self._segments = []
        self._is_refreshing = False
        self._last_error = ""

        today = datetime.now(timezone.utc).astimezone().date()
        self._current_week_start = today - timedelta(days=today.weekday())
        self._week_start = self._current_week_start

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self.summary_banner, self.summary_title, self.summary_body = make_status_banner()
        root.addWidget(self.summary_banner)

        nav_card = QFrame()
        nav_card.setObjectName("toolbar")
        nav = QHBoxLayout(nav_card)
        nav.setContentsMargins(14, 12, 14, 12)
        nav.setSpacing(8)

        self.prev_btn = QPushButton("Previous week")
        self.prev_btn.setObjectName("ghost")
        self.prev_btn.setFixedWidth(112)
        self.prev_btn.clicked.connect(self._prev_week)
        nav.addWidget(self.prev_btn)

        center_copy = QVBoxLayout()
        center_copy.setSpacing(2)
        self.week_label = QLabel("")
        self.week_label.setObjectName("sectionTitle")
        center_copy.addWidget(self.week_label)
        self.week_meta = QLabel("")
        self.week_meta.setObjectName("sectionBody")
        self.week_meta.setWordWrap(True)
        center_copy.addWidget(self.week_meta)
        nav.addLayout(center_copy, 1)

        self.this_week_btn = QPushButton("This week")
        self.this_week_btn.setObjectName("secondary")
        self.this_week_btn.setFixedWidth(92)
        self.this_week_btn.clicked.connect(self._jump_to_current_week)
        nav.addWidget(self.this_week_btn)

        self.next_btn = QPushButton("Next week")
        self.next_btn.setObjectName("ghost")
        self.next_btn.setFixedWidth(96)
        self.next_btn.clicked.connect(self._next_week)
        nav.addWidget(self.next_btn)

        self.refresh_btn = QPushButton("Refresh schedules")
        self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.setFixedWidth(128)
        nav.addWidget(self.refresh_btn)

        root.addWidget(nav_card)

        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(2, 0, 2, 0)
        stats_row.setSpacing(8)
        self.segment_badge = QLabel("")
        self.segment_badge.setObjectName("pillBadge")
        stats_row.addWidget(self.segment_badge)
        self.channel_badge = QLabel("")
        self.channel_badge.setObjectName("pillBadge")
        stats_row.addWidget(self.channel_badge)
        self.timezone_badge = QLabel("")
        self.timezone_badge.setObjectName("pillBadge")
        stats_row.addWidget(self.timezone_badge)
        stats_row.addStretch(1)
        root.addLayout(stats_row)

        self.empty_card, self.empty_title, self.empty_body = make_empty_state(
            "No schedule in view",
            "Refresh Twitch schedules or move to another week to look ahead.",
        )
        root.addWidget(self.empty_card)

        canvas_card = QFrame()
        canvas_card.setObjectName("dialogSection")
        canvas_lay = QVBoxLayout(canvas_card)
        canvas_lay.setContentsMargins(12, 12, 12, 12)
        canvas_lay.setSpacing(0)
        self._canvas = _GridCanvas()
        self._canvas.block_clicked.connect(self.block_clicked.emit)
        canvas_lay.addWidget(self._canvas, 1)
        root.addWidget(canvas_card, 1)
        self._canvas_card = canvas_card

        self._update_label()
        self._refresh_grid()

    def set_cache(self, cache):
        """Update the cached schedule data shown by the widget."""
        self._cache = cache or {}
        self._last_error = ""
        self._refresh_grid()

    def set_refreshing(self, refreshing):
        """Toggle refresh-button state and loading copy."""
        self._is_refreshing = bool(refreshing)
        self.refresh_btn.setEnabled(not refreshing)
        self.refresh_btn.setText("Refreshing..." if refreshing else "Refresh schedules")
        self._update_summary_state()

    def set_refresh_error(self, message):
        """Surface a recoverable refresh error to the user."""
        self._last_error = str(message or "")
        self._is_refreshing = False
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("Refresh schedules")
        self._update_summary_state()

    def _refresh_grid(self):
        from ..schedule import get_week_segments

        self._segments = get_week_segments(self._cache, self._week_start)
        self._canvas.set_segments(self._segments, self._week_start)
        self._update_summary_state()

    def _update_summary_state(self):
        """Update contextual copy, badges, and empty-state visibility."""
        channels = {
            seg.get("channel", "")
            for _, _, seg in self._segments
            if seg.get("channel")
        }
        timezone_name = datetime.now(timezone.utc).astimezone().tzname() or "Local time"
        self.segment_badge.setText(
            f"{len(self._segments)} scheduled item(s)"
        )
        self.channel_badge.setText(
            f"{len(channels)} channel(s) in view"
        )
        self.timezone_badge.setText(f"{timezone_name} shown")

        has_segments = bool(self._segments)
        self._canvas_card.setVisible(has_segments)
        self.empty_card.setVisible(not has_segments)

        if self._last_error:
            update_status_banner(
                self.summary_banner,
                self.summary_title,
                self.summary_body,
                title="Schedule refresh ran into a problem",
                body=self._last_error,
                tone="error",
            )
            self.empty_title.setText("Schedule data could not be refreshed")
            self.empty_body.setText("Try again in a moment. Cached results will appear here when available.")
            return

        if self._is_refreshing:
            update_status_banner(
                self.summary_banner,
                self.summary_title,
                self.summary_body,
                title="Refreshing schedule cache",
                body="StreamKeep is checking the latest Twitch schedule windows for channels in your watch list.",
                tone="info",
            )
            self.empty_title.setText("Refreshing schedule data")
            self.empty_body.setText("Schedule blocks will appear here as soon as the refresh completes.")
            return

        if not self._cache:
            update_status_banner(
                self.summary_banner,
                self.summary_title,
                self.summary_body,
                title="No schedule cache yet",
                body="Refresh schedules after adding Twitch channels to fill this calendar with upcoming stream windows.",
                tone="warning",
            )
            self.empty_title.setText("No schedule data yet")
            self.empty_body.setText("Calendar view is most useful after a schedule refresh has cached Twitch programming windows.")
            return

        if not has_segments:
            update_status_banner(
                self.summary_banner,
                self.summary_title,
                self.summary_body,
                title="Nothing scheduled for this week",
                body="Try the next or previous week, or refresh schedules if you expect upcoming streams to appear.",
                tone="warning",
            )
            self.empty_title.setText("No scheduled streams in view")
            self.empty_body.setText("This week is quiet for the currently cached channels, so there is nothing to plot on the calendar.")
            return

        day_count = len({
            day_idx for day_idx, _, _seg in self._segments
        })
        update_status_banner(
            self.summary_banner,
            self.summary_title,
            self.summary_body,
            title="Schedule overview",
            body=(
                f"{len(self._segments)} scheduled stream(s) across {len(channels)} channel(s), "
                f"spread over {day_count} day(s). Click any block to inspect it or jump into that channel's profile."
            ),
            tone="success",
        )

    def _update_label(self):
        """Refresh week copy and current-week affordances."""
        end = self._week_start + timedelta(days=6)
        self.week_label.setText(
            f"{self._week_start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"
        )
        if self._week_start == self._current_week_start:
            self.week_meta.setText(
                "Current week in your local timezone. Use the calendar to spot upcoming schedule windows quickly."
            )
        else:
            self.week_meta.setText(
                "Browsing a different week. Click a block to review timing and open that channel's recording profile."
            )
        self.this_week_btn.setEnabled(self._week_start != self._current_week_start)

    def _jump_to_current_week(self):
        self._week_start = self._current_week_start
        self._update_label()
        self._refresh_grid()

    def _prev_week(self):
        self._week_start -= timedelta(days=7)
        self._update_label()
        self._refresh_grid()

    def _next_week(self):
        self._week_start += timedelta(days=7)
        self._update_label()
        self._refresh_grid()
