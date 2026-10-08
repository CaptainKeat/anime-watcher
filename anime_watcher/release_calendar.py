"""Release calendar presentation. Dates are confirmed airings, never projections."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)


def month_start(day: date) -> date:
    return day.replace(day=1)


def adjacent_month(day: date, offset: int) -> date:
    index = day.year * 12 + day.month - 1 + offset
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def calendar_range(month: date) -> tuple[date, date]:
    start = month_start(month)
    start -= timedelta(days=start.weekday())
    return start, start + timedelta(days=42)


def local_timestamp(day: date) -> int:
    # Each boundary is converted independently, including across DST changes.
    return int(datetime.combine(day, time.min).timestamp())


class CalendarDay(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.day = date.today()
        self.in_month = True
        self.events = []
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(60, 30)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def configure(self, day, month, selected, events):
        self.day, self.in_month, self.events = day, day.month == month.month, events
        self.setChecked(day == selected)
        self.setAccessibleName(f"{day.strftime('%A, %B %d, %Y')}, {len(events)} scheduled episodes")
        details = [f"{datetime.fromtimestamp(e['airing_at']):%I:%M %p} · {e['title']} · Episode {e['episode']}" for e in events]
        self.setToolTip("\n".join([day.strftime('%B %d')] + details))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self.isChecked()
        background = "#251c3c" if selected else ("#1c2433" if self.underMouse() else "#141a24" if self.in_month else "#0e131c")
        painter.setPen(QPen(QColor("#a78bfa" if selected else "#39465d" if self.hasFocus() else "#222b3b"), 1.5 if selected else 1))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 9, 9)
        today = self.day == date.today()
        top = 7 if self.height() >= 40 else 2
        if today:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#8b5cf6"))
            painter.drawEllipse(QRectF(9, top, 25, 25))
        painter.setPen(QColor("#f5f7fb" if self.in_month or today else "#626e81"))
        font = QFont("Segoe UI", 10); font.setBold(True); painter.setFont(font)
        painter.drawText(QRectF(9, top, 25, 25), Qt.AlignmentFlag.AlignCenter, str(self.day.day))
        if self.events:
            font.setPointSize(8); painter.setFont(font)
            painter.setPen(QColor("#bda4ff"))
            painter.drawText(QRectF(self.width() - 32, top + 2, 22, 22), Qt.AlignmentFlag.AlignRight, str(len(self.events)))
            capacity = max(0, min(12, (self.height() - 55) // 25))
            for index, item in enumerate(self.events[:capacity]):
                rect = QRectF(7, 35 + index * 25, self.width() - 14, 22)
                painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor("#203a40"))
                painter.drawRoundedRect(rect, 4, 4)
                painter.setPen(QColor("#8ce0d1"))
                title = painter.fontMetrics().elidedText(item["title"], Qt.TextElideMode.ElideRight, max(0, int(rect.width() - 10)))
                painter.drawText(rect.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignVCenter, title)
            if len(self.events) > capacity and self.height() >= 70:
                painter.setPen(QColor("#9aa4b3")); font.setPointSize(8); painter.setFont(font)
                painter.drawText(QRectF(10, self.height() - 20, self.width() - 20, 16), f"+{len(self.events) - capacity} more")


class ReleaseCalendar(QWidget):
    month_changed = Signal()
    refresh_requested = Signal()
    series_requested = Signal(int)
    library_requested = Signal()
    media_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.month = month_start(date.today())
        self.selected = date.today()
        self.events = []
        self.linked = []
        self.days = defaultdict(list)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(16)
        toolbar = QHBoxLayout()
        self.month_label = QLabel(); self.month_label.setStyleSheet("font-size:24px;font-weight:800;")
        toolbar.addWidget(self.month_label)
        for name, text, step in [("calendarPrevious", "‹", -1), ("calendarNext", "›", 1)]:
            button = QPushButton(text); button.setObjectName(name); button.setFixedWidth(38)
            button.setAccessibleName("Previous period" if step < 0 else "Next period")
            button.clicked.connect(lambda _=False, amount=step: self.change_period(amount)); toolbar.addWidget(button)
        today = QPushButton("Today"); today.setObjectName("calendarToday"); today.clicked.connect(self.go_today)
        toolbar.addWidget(today); toolbar.addStretch(1)
        self.filter = QComboBox(); self.filter.setObjectName("calendarSeriesFilter")
        self.filter.setMinimumWidth(140); self.filter.setMaximumWidth(250)
        self.filter.addItem("All linked shows", None); self.filter.currentIndexChanged.connect(self.render)
        self.refresh = QPushButton("Refresh"); self.refresh.setObjectName("calendarRefresh")
        self.refresh.clicked.connect(self.refresh_requested.emit); toolbar.addWidget(self.refresh)
        outer.addLayout(toolbar)
        filters = QHBoxLayout()
        self.source = QComboBox(); self.source.setObjectName("calendarSource")
        self.source.addItem("Current airings", "current"); self.source.addItem("My library", "library")
        self.source.setAccessibleName("Schedule source")
        filters.addWidget(self.source)
        self.view = QComboBox(); self.view.setObjectName("calendarView")
        self.view.addItem("Week", "week"); self.view.addItem("Month", "month")
        self.view.setCurrentIndex(1)
        self.view.setAccessibleName("Calendar view")
        filters.addWidget(self.view)
        filters.addWidget(self.filter, 1); filters.addStretch(1)
        outer.addLayout(filters)
        self.summary = QLabel(); self.summary.setStyleSheet("color:#bda4ff;font-weight:600;")
        outer.addWidget(self.summary)
        split = QHBoxLayout(); split.setSpacing(18)
        panel = QFrame(); panel.setProperty("class", "panel")
        calendar = QGridLayout(panel); calendar.setContentsMargins(14, 14, 14, 14); calendar.setSpacing(6)
        self.calendar_grid = calendar
        for col, name in enumerate(["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]):
            label = QLabel(name); label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color:#9aa4b3;font-size:10px;font-weight:700;background:transparent;padding-bottom:8px;")
            calendar.addWidget(label, 0, col); calendar.setColumnStretch(col, 1)
        self.cells = []
        for index in range(42):
            cell = CalendarDay(); cell.setObjectName(f"calendarDay{index}")
            cell.clicked.connect(lambda _=False, item=cell: self.select_day(item.day))
            calendar.addWidget(cell, 1 + index // 7, index % 7); self.cells.append(cell)
        for row in range(1, 7): calendar.setRowStretch(row, 1)
        split.addWidget(panel, 1)
        agenda = QFrame(); agenda.setProperty("class", "panel"); agenda.setFixedWidth(270)
        side = QVBoxLayout(agenda); side.setContentsMargins(18, 18, 18, 18); side.setSpacing(12)
        eyebrow = QLabel("EPISODE RELEASES"); eyebrow.setStyleSheet("color:#bda4ff;font-size:10px;font-weight:800;background:transparent;")
        side.addWidget(eyebrow)
        self.day_label = QLabel(); self.day_label.setStyleSheet("font-size:21px;font-weight:800;background:transparent;")
        side.addWidget(self.day_label)
        self.day_summary = QLabel(); self.day_summary.setStyleSheet("color:#9aa4b3;background:transparent;")
        side.addWidget(self.day_summary)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        container = QWidget(); self.agenda = QVBoxLayout(container); self.agenda.setContentsMargins(0, 0, 4, 0); self.agenda.setSpacing(12)
        scroll.setWidget(container); side.addWidget(scroll, 1)
        split.addWidget(agenda)
        outer.addLayout(split, 1)
        self.status = QLabel(); self.status.setObjectName("calendarStatus"); self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#9aa4b3;font-size:12px;"); outer.addWidget(self.status)
        footer = QHBoxLayout()
        note = QLabel("●  Official airings  ·  Local time  ·  Dub dates are not provided by AniList")
        note.setStyleSheet("color:#9aa4b3;font-size:11px;"); note.setWordWrap(True); footer.addWidget(note, 1)
        library = QPushButton("Link shows in Library"); library.clicked.connect(self.library_requested.emit); footer.addWidget(library)
        outer.addLayout(footer)
        self.source.currentIndexChanged.connect(self._source_changed)
        self.view.currentIndexChanged.connect(self._view_changed)
        self.render()

    def timestamp_range(self):
        if self.view.currentData() == "week":
            start = self.selected - timedelta(days=self.selected.weekday())
            return local_timestamp(start), local_timestamp(start + timedelta(days=7))
        return tuple(local_timestamp(day) for day in calendar_range(self.month))

    def _source_changed(self):
        self.events = []
        self.set_events([], self.linked)
        self.month_changed.emit()

    def _view_changed(self):
        self.render(); self.month_changed.emit()

    def set_events(self, events, linked):
        self.events, self.linked = events, linked
        selected = self.filter.currentData()
        self.filter.blockSignals(True); self.filter.clear()
        if self.source.currentData() == "current":
            self.filter.addItem("All airing shows", None)
            shows = {row["media_id"]: row["title"] for row in events}
            for media_id, title in sorted(shows.items(), key=lambda item: item[1].casefold()):
                self.filter.addItem(title, media_id)
        else:
            self.filter.addItem("All linked shows", None)
            for row in linked:
                self.filter.addItem(row["display_title"] or row["title"], int(row["id"]))
        self.filter.setCurrentIndex(max(0, self.filter.findData(selected))); self.filter.blockSignals(False)
        self.render()

    def change_period(self, offset):
        if self.view.currentData() == "week":
            self.selected += timedelta(days=7 * offset); self.month = month_start(self.selected)
            self.render(); self.month_changed.emit()
        else:
            self.change_month(offset)

    def change_month(self, offset):
        self.month = adjacent_month(self.month, offset)
        self.selected = self.month
        self.render(); self.month_changed.emit()

    def go_today(self):
        self.selected = date.today(); self.month = month_start(self.selected)
        self.render(); self.month_changed.emit()

    def select_day(self, day):
        previous_range = self.timestamp_range()
        self.selected = day; self.month = month_start(day)
        self.render()
        if previous_range != self.timestamp_range(): self.month_changed.emit()

    def render(self):
        self.days = defaultdict(list)
        selected_series = self.filter.currentData()
        public = self.source.currentData() == "current"
        weekly = self.view.currentData() == "week"
        start_at, end_at = self.timestamp_range()
        for event in self.events:
            identity = event.get("media_id") if public else event["series_id"]
            if (selected_series is None or identity == selected_series) and start_at <= event["airing_at"] < end_at:
                self.days[datetime.fromtimestamp(event["airing_at"]).date()].append(event)
        for values in self.days.values(): values.sort(key=lambda e: (e["airing_at"], e["title"].casefold()))
        start, _ = calendar_range(self.month)
        if weekly:
            start = self.selected - timedelta(days=self.selected.weekday())
            finish = start + timedelta(days=6)
            self.month_label.setText(f"{start:%b %d} – {finish:%b %d, %Y}")
        else:
            self.month_label.setText(self.month.strftime("%B %Y"))
        count = sum(len(events) for day, events in self.days.items() if weekly or month_start(day) == self.month)
        show_count = len({item.get("media_id") for values in self.days.values() for item in values}) if public else len(self.linked)
        self.summary.setText(f"{count} confirmed episode{'s' if count != 1 else ''} this {'week' if weekly else 'month'}   /   {show_count} {'airing' if public else 'linked'} show{'s' if show_count != 1 else ''}")
        for index, cell in enumerate(self.cells):
            cell.setVisible(not weekly or index < 7)
            day = start + timedelta(days=index)
            cell.configure(day, self.month, self.selected, self.days[day])
            self.calendar_grid.setRowStretch(1 + index // 7, 1 if not weekly or index < 7 else 0)
        self.day_label.setText(self.selected.strftime("%A\n%B %d"))
        episodes = self.days[self.selected]
        self.day_summary.setText(f"{len(episodes)} episode{'s' if len(episodes) != 1 else ''} scheduled")
        while self.agenda.count():
            item = self.agenda.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        for event in episodes:
            card = QFrame(); card.setStyleSheet("QFrame{background:#1b2230;border-radius:10px;} QLabel{background:transparent;}")
            box = QVBoxLayout(card); box.setContentsMargins(12, 12, 12, 12)
            at = datetime.fromtimestamp(event["airing_at"])
            stamp = QLabel(at.strftime("%I:%M %p").lstrip("0")); stamp.setStyleSheet("color:#8ce0d1;font-weight:800;")
            box.addWidget(stamp)
            title = QLabel(event["title"]); title.setTextFormat(Qt.TextFormat.PlainText); title.setWordWrap(True); title.setStyleSheet("font-size:15px;font-weight:700;"); box.addWidget(title)
            episode = QLabel(f"Episode {event['episode']}  ·  Official airing"); episode.setStyleSheet("color:#9aa4b3;font-size:11px;"); box.addWidget(episode)
            if event.get("series_id") is not None:
                open_series = QPushButton("Open series  →")
                open_series.clicked.connect(lambda _=False, sid=event["series_id"]: self.series_requested.emit(sid))
            else:
                open_series = QPushButton("View on AniList  ↗")
                open_series.clicked.connect(lambda _=False, mid=event["media_id"]: self.media_requested.emit(mid))
            box.addWidget(open_series)
            self.agenda.addWidget(card)
        if not episodes:
            empty = QLabel("A quiet day\n\nNo confirmed airings for this date. Try Refresh for the latest schedule." if public or self.linked else "Your schedule starts here\n\nOpen a show in Library and link it to AniList to see its episode dates.")
            empty.setWordWrap(True); empty.setStyleSheet("color:#9aa4b3;line-height:1.5;padding-top:18px;"); self.agenda.addWidget(empty)
        self.agenda.addStretch(1)
