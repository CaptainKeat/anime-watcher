from __future__ import annotations

import os
import shutil
import sys
import time
import webbrowser
from collections import defaultdict
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRunnable, QSizeF, QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCloseEvent, QCursor, QGuiApplication, QIcon, QImage, QKeyEvent, QKeySequence, QMouseEvent, QPainter, QPixmap, QShortcut
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QKeySequenceEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QSystemTrayIcon,
)

from .ass_renderer import LibassRenderer
from .anilist import release_schedule, save_list_entry, search_anime, viewer
from .database import LibraryDatabase
from .downloader import CatalogResult, EpisodeResult, download_authorized_file, load_catalog_episodes, search_catalog
from .library_actions import LANGUAGES, rename_episode_file, rename_series_files, rollback_series_files, send_to_recycle_bin
from .keybindings import KEYBINDING_ACTIONS, duplicate_keybindings, merged_keybindings
from .media_chapters import MediaChapter, probe_chapter_ranges
from .media_quality import probe_quality_sources
from .metadata import fetch_metadata
from .organizer import VIDEO_EXTENSIONS, organize_files, scan_video_files
from .preview import cached_video_preview, generate_video_preview, nearest_cached_video_preview, preview_bucket
from .profiles import ProfileManager
from .qt_player import QtMediaPlayer
from .subtitles import (
    SubtitleCue,
    attach_subtitle_file,
    default_whisper_model_path,
    download_whisper_model,
    find_sidecar_subtitles,
    find_whisper_cli,
    generate_english_subtitles,
    load_subtitle_file,
    subtitle_texts_at,
)
from .secure_store import protect_secret, unprotect_secret
from .ui_common import (
    choose_episode_variant,
    episode_language_options,
    format_time,
    language_switch_required,
    library_root_from_setting,
    resource_path,
)


BG = "#090b10"
PANEL = "#11151d"
PANEL_2 = "#181e29"
TEXT = "#f5f7fb"
MUTED = "#9aa4b3"
ACCENT = "#8b5cf6"
PINK = "#ec4899"


APP_STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: 'Segoe UI'; font-size: 13px; }}
QWidget#playerOverlay {{ background: transparent; }}
QFrame#sidebar, QFrame[class="card"], QFrame[class="panel"] {{ background: {PANEL}; border: 0; border-radius: 14px; }}
QFrame#playerTop, QFrame#playerControls {{ background: rgba(8, 11, 16, 220); border: 0; }}
QFrame#playerSettings {{ background: rgba(17, 21, 29, 245); border: 1px solid #303849; border-radius: 12px; }}
QFrame#playerTop QLabel, QFrame#playerControls QLabel, QFrame#playerSettings QLabel, QFrame#playerSettings QCheckBox {{ background: transparent; }}
QPushButton {{ background: {PANEL_2}; border: 0; border-radius: 8px; padding: 9px 13px; font-weight: 600; }}
QPushButton:hover {{ background: #283142; }}
QPushButton#playerIcon {{ background: transparent; border-radius: 20px; font-size: 18px; padding: 7px 10px; }}
QPushButton#playerIcon:hover {{ background: rgba(255, 255, 255, 28); }}
QPushButton#playerIcon:checked {{ background: rgba(139, 92, 246, 70); }}
QPushButton#skipIntro {{ background: #f5f7fb; color: #090b10; border-radius: 6px; padding: 11px 16px; font-weight: 800; }}
QLabel#playerSubtitle {{ background: rgba(0, 0, 0, 185); color: white; border-radius: 7px; padding: 8px 12px; font-size: 22px; font-weight: 700; }}
QPushButton#accent {{ background: {ACCENT}; }}
QPushButton#accent:hover {{ background: #7c3aed; }}
QPushButton#danger {{ background: transparent; border: 1px solid #ef4444; color: #fca5a5; }}
QPushButton#nav {{ background: transparent; color: {MUTED}; text-align: left; padding: 12px 16px; }}
QPushButton#nav:hover, QPushButton#nav:checked {{ background: {PANEL_2}; color: {TEXT}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QKeySequenceEdit {{ background: {PANEL_2}; border: 1px solid #303849; border-radius: 8px; padding: 9px; }}
QScrollArea {{ border: 0; }}
QSlider::groove:horizontal {{ height: 5px; background: #3a404b; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {PINK}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 15px; margin: -5px 0; background: {PINK}; border-radius: 7px; }}
QProgressBar {{ background: #343b49; border: 0; border-radius: 3px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {PINK}; border-radius: 3px; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid #333a48; }}
"""


class WorkerSignals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)


class Worker(QRunnable):
    def __init__(self, function: Callable, *args, with_progress: bool = False):
        super().__init__()
        self.function = function
        self.args = args
        self.with_progress = with_progress
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            if self.with_progress:
                result = self.function(*self.args, lambda *values: self.signals.progress.emit(values))
            else:
                result = self.function(*self.args)
            self.signals.done.emit(result)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class ClickableFrame(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class CompositedVideoSurface(QGraphicsView):
    """Video surface that stays inside Qt's widget compositor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.video_scene = QGraphicsScene(self)
        self.video_item = QGraphicsVideoItem()
        self.video_item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video_scene.addItem(self.video_item)
        self.subtitle_item = QGraphicsPixmapItem()
        self.subtitle_item.setZValue(10)
        self.subtitle_item.hide()
        self.video_scene.addItem(self.subtitle_item)
        self.setScene(self.video_scene)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setStyleSheet("background:black;border:0;")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        size = self.viewport().size()
        self.video_scene.setSceneRect(0, 0, size.width(), size.height())
        self.video_item.setSize(QSizeF(size.width(), size.height()))

    def video_content_rect(self) -> tuple[int, int, int, int]:
        viewport = self.viewport().size()
        width, height = max(1, viewport.width()), max(1, viewport.height())
        native = self.video_item.nativeSize()
        if native.width() <= 0 or native.height() <= 0:
            return 0, 0, width, height
        scale = min(width / native.width(), height / native.height())
        content_width = max(1, round(native.width() * scale))
        content_height = max(1, round(native.height() * scale))
        return (
            (width - content_width) // 2,
            (height - content_height) // 2,
            content_width,
            content_height,
        )

    def native_video_size(self) -> tuple[int, int]:
        native = self.video_item.nativeSize()
        if native.width() <= 0 or native.height() <= 0:
            viewport = self.viewport().size()
            return max(1, viewport.width()), max(1, viewport.height())
        return max(1, round(native.width())), max(1, round(native.height()))

    def show_subtitle_bitmap(self, pixmap: QPixmap, x: int, y: int) -> None:
        self.subtitle_item.setPixmap(pixmap)
        self.subtitle_item.setPos(int(x), int(y))
        self.subtitle_item.show()

    def clear_subtitle_bitmap(self) -> None:
        self.subtitle_item.setPixmap(QPixmap())
        self.subtitle_item.hide()


class PlayerOverlay(QWidget):
    activity = Signal()
    center_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.top_height = 0
        self.bottom_height = 0
        self.setObjectName("playerOverlay")
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.activity.emit()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        y = event.position().y()
        if event.button() == Qt.MouseButton.LeftButton and self.top_height <= y < self.height() - self.bottom_height:
            self.center_clicked.emit()
        self.activity.emit()
        super().mousePressEvent(event)


class PreviewSlider(QSlider):
    preview = Signal(int, QPoint)
    preview_left = Signal()

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setMouseTracking(True)
        self.chapter_markers: list[MediaChapter] = []
        self.chapter_duration_ms = 0

    def set_chapters(self, chapters: list[MediaChapter], duration_ms: int) -> None:
        self.chapter_markers = list(chapters)
        self.chapter_duration_ms = max(0, int(duration_ms))
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.chapter_markers or self.chapter_duration_ms <= 0:
            return
        colors = {"intro": "#f59e0b", "outro": "#ec4899", "recap": "#38bdf8", "filler": "#a78bfa"}
        painter = QPainter(self)
        for chapter in self.chapter_markers:
            x1 = round(chapter.start_ms / self.chapter_duration_ms * self.width())
            x2 = round(chapter.end_ms / self.chapter_duration_ms * self.width())
            painter.fillRect(x1, max(0, self.height() - 4), max(2, x2 - x1), 3, QColor(colors.get(chapter.kind, "#ffffff")))
        painter.end()

    def _value_from_event(self, event: QMouseEvent) -> int:
        ratio = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
        return round(self.minimum() + ratio * (self.maximum() - self.minimum()))

    def _emit_preview(self, event: QMouseEvent) -> int:
        value = self._value_from_event(event)
        self.preview.emit(value, event.position().toPoint())
        return value

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        value = self._emit_preview(event)
        if self.isSliderDown() and event.buttons() & Qt.MouseButton.LeftButton:
            self.setSliderPosition(value)
            self.sliderMoved.emit(value)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            value = self._emit_preview(event)
            self.setSliderDown(True)
            self.setSliderPosition(value)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            value = self._emit_preview(event)
            self.setSliderPosition(value)
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self.preview_left.emit()
        super().leaveEvent(event)


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


class AnimeWatcherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Anime Watcher")
        self.resize(1420, 900)
        self.setMinimumSize(1080, 680)
        icon = resource_path("assets", "anime_watcher.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.setStyleSheet(APP_STYLE)

        data_root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "AnimeWatcher"
        data_root.mkdir(parents=True, exist_ok=True)
        self.data_root = data_root
        self.profile_manager = ProfileManager(data_root)
        self.db = LibraryDatabase(self.profile_manager.database_path())
        self.library_root = library_root_from_setting(self.db.setting("library_root", ""))
        self.player = QtMediaPlayer(self)
        self.player.on_tracks_changed(self._load_tracks)
        self.player.on_error(self._playback_error)
        self.pool = QThreadPool.globalInstance()
        self.active_workers: set[Worker] = set()
        self.current_episode_id: int | None = None
        self.current_video_path: str | None = None
        self.known_duration_ms = 0
        self.last_saved = 0
        self.autoplay_enabled = True
        self.controls_visible = True
        self.preview_token = 0
        self.preview_bucket_requested: int | None = None
        self.preview_target_ms = 0
        self.intro_probe_token = 0
        self.media_chapters: list[MediaChapter] = []
        self.active_skip_chapter: MediaChapter | None = None
        self.quality_probe_token = 0
        self.quality_map: dict[str, int] = {}
        self.external_subtitle_cues: list[SubtitleCue] = []
        self.external_subtitle_path: Path | None = None
        self.ass_renderer: LibassRenderer | None = None
        self.subtitle_delay_ms = 0
        self.player_shortcuts: list[QShortcut] = []
        self.pip_active = False
        self.pip_restore_geometry = None
        self.pip_restore_maximized = False
        self.variant_map: dict[str, int] = {}
        self.visible_series_id: int | None = None
        self.metadata_attempted: set[int] = set()
        self.was_maximized = False
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("Anime Watcher")
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

        root = QWidget()
        self.setCentralWidget(root)
        self.root_layout = QHBoxLayout(root)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)
        self.sidebar = self._build_sidebar()
        self.stack = QStackedWidget()
        self.root_layout.addWidget(self.sidebar)
        self.root_layout.addWidget(self.stack, 1)

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self._player_tick)
        self.tick_timer.start(250)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._hide_controls)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._request_preview_generation)
        self.ass_timer = QTimer(self)
        self.ass_timer.setInterval(33)
        self.ass_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.ass_timer.timeout.connect(lambda: self._update_ass_subtitle(self.player.time()))
        self.show_home()
        QTimer.singleShot(900, self._auto_metadata)
        QTimer.singleShot(1800, self._refresh_release_schedule)

    def _start_worker(self, worker: Worker) -> None:
        # QThreadPool owns the C++ QRunnable while it runs, but keeping the
        # Python wrapper alive is essential because its signals call Python.
        worker.setAutoDelete(False)
        self.active_workers.add(worker)
        cleanup = lambda item=worker: QTimer.singleShot(
            0, lambda held=item: self.active_workers.discard(held)
        )
        worker.signals.done.connect(lambda _result: cleanup())
        worker.signals.failed.connect(lambda _error: cleanup())
        self.pool.start(worker)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(205)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 24, 18, 20)
        brand = QLabel("桜  ANIME")
        brand.setStyleSheet("font-size: 23px; font-weight: 800;")
        layout.addWidget(brand)
        sub = QLabel("WATCHER")
        sub.setStyleSheet(f"color:{PINK}; font-size:10px; font-weight:700; margin-left:32px;")
        layout.addWidget(sub)
        layout.addSpacing(30)
        self.nav_buttons: list[QPushButton] = []
        for text, callback in [
            ("⌂   Home", self.show_home), ("▥   Library", self.show_library),
            ("▶   Continue", self.show_continue), ("＋   Import", self.show_import),
            ("↓   Downloads", self.show_downloads), ("≡   Files", self.show_file_manager),
            ("●   Updates", self.show_notifications), ("⚙   Settings", self.show_settings),
        ]:
            button = QPushButton(text)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(callback)
            layout.addWidget(button)
            self.nav_buttons.append(button)
        layout.addStretch(1)
        self.profile_status = QLabel(f"Profile: {self.profile_manager.active.name}")
        self.profile_status.setStyleSheet(f"color:{TEXT};font-weight:700;font-size:11px;")
        layout.addWidget(self.profile_status)
        self.sidebar_status = QLabel(str(self.library_root) if self.library_root else "No library selected")
        self.sidebar_status.setWordWrap(True)
        self.sidebar_status.setStyleSheet(f"color:{MUTED}; font-size:10px;")
        layout.addWidget(self.sidebar_status)
        return sidebar

    def _select_nav(self, index: int | None) -> None:
        for item, button in enumerate(self.nav_buttons):
            button.setChecked(index == item)

    def _set_page(self, page: QWidget, nav_index: int | None = None, player: bool = False) -> None:
        if self.current_episode_id and not player:
            self._save_progress(stop=True)
        old = self.stack.currentWidget()
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()
        self.sidebar.setVisible(not player)
        self._select_nav(nav_index)
        if nav_index is not None or player:
            self.visible_series_id = None

    def _page(self, title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(34, 30, 34, 28)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:30px; font-weight:800;")
        outer.addWidget(heading)
        if subtitle:
            label = QLabel(subtitle)
            label.setStyleSheet(f"color:{MUTED};")
            outer.addWidget(label)
        outer.addSpacing(14)
        return page, outer

    def _scroll(self) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 10, 20)
        layout.setSpacing(14)
        scroll.setWidget(body)
        return scroll, body, layout

    def _poster(self, path: str | None, width: int = 180, height: int = 255) -> QPixmap:
        if path and Path(path).exists():
            pixmap = QPixmap(str(path))
        else:
            image = QImage(width, height, QImage.Format.Format_RGB32)
            image.fill(QColor(PANEL_2))
            pixmap = QPixmap.fromImage(image)
        return pixmap.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)

    def _series_card(self, series) -> ClickableFrame:
        card = ClickableFrame()
        card.setProperty("class", "card")
        card.setFixedWidth(196)
        card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 12)
        poster = QLabel()
        poster.setPixmap(self._poster(series["poster_path"]))
        poster.setFixedSize(180, 255)
        poster.setScaledContents(True)
        layout.addWidget(poster)
        title = QLabel(series["display_title"] or series["title"])
        title.setWordWrap(True)
        title.setStyleSheet("font-weight:700;")
        layout.addWidget(title)
        count = QLabel(f"{series['episode_count']} episodes")
        count.setStyleSheet(f"color:{MUTED};")
        layout.addWidget(count)
        card.clicked.connect(lambda sid=int(series["id"]): self.show_series(sid))
        return card

    def show_home(self) -> None:
        page, outer = self._page("Welcome back")
        series = self.db.series()
        continues = self.db.continue_watching(8)
        outer.addWidget(QLabel(f"{len(series)} series • {sum(row['episode_count'] for row in series)} episodes ready"))
        scroll, _, body = self._scroll()
        if continues:
            label = QLabel("Continue watching")
            label.setStyleSheet("font-size:20px;font-weight:700;")
            body.addWidget(label)
            row = QHBoxLayout()
            for episode in continues[:4]:
                button = QPushButton(f"{episode['series_title']}\nS{episode['season']:02d} • Episode {episode['episode']} • {episode['language']}\n{format_time(episode['progress_ms'])} / {format_time(episode['duration_ms'])}")
                button.setMinimumSize(230, 105)
                button.clicked.connect(lambda _=False, eid=int(episode["id"]): self.play_episode(eid))
                row.addWidget(button)
            row.addStretch(1)
            body.addLayout(row)
        label = QLabel("Your collection")
        label.setStyleSheet("font-size:20px;font-weight:700;")
        body.addWidget(label)
        grid = QGridLayout()
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        for index, item in enumerate(series[:12]):
            grid.addWidget(self._series_card(item), index // 5, index % 5)
        body.addLayout(grid)
        body.addStretch(1)
        outer.addWidget(scroll, 1)
        self._set_page(page, 0)

    def show_library(self) -> None:
        page, outer = self._page("Library", "Every series, season, and episode in one place")
        search = QLineEdit()
        search.setPlaceholderText("Search your library…")
        outer.addWidget(search)
        scroll, _, body = self._scroll()
        grid = QGridLayout()
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        body.addLayout(grid)
        body.addStretch(1)

        def render(text: str) -> None:
            clear_layout(grid)
            rows = self.db.series(text)
            for index, item in enumerate(rows):
                grid.addWidget(self._series_card(item), index // 5, index % 5)
            if not rows:
                grid.addWidget(QLabel("No matching anime found."), 0, 0)

        search.textChanged.connect(render)
        render("")
        outer.addWidget(scroll, 1)
        self._set_page(page, 1)

    def show_series(self, series_id: int) -> None:
        series = self.db.get_series(series_id)
        if not series:
            return self.show_library()
        self.visible_series_id = series_id
        page, outer = self._page(series["display_title"] or series["title"], "Choose an episode or continue where you left off")
        top = QHBoxLayout()
        poster = QLabel()
        poster.setPixmap(self._poster(series["poster_path"], 220, 310))
        poster.setFixedSize(220, 310)
        poster.setScaledContents(True)
        top.addWidget(poster)
        details = QVBoxLayout()
        synopsis = QLabel(series["synopsis"] or "No details yet. Fetch a poster and synopsis when you are online.")
        synopsis.setWordWrap(True)
        synopsis.setAlignment(Qt.AlignmentFlag.AlignTop)
        details.addWidget(synopsis)
        actions = QHBoxLayout()
        rename = QPushButton("Rename anime")
        rename.clicked.connect(lambda: self._rename_series(series_id))
        metadata = QPushButton("Fetch poster & details")
        metadata.clicked.connect(lambda: self._refresh_metadata(series_id))
        anilist = QPushButton("Relink AniList" if series["anilist_id"] else "Link AniList")
        anilist.clicked.connect(lambda: self._link_anilist(series_id))
        actions.addWidget(rename)
        actions.addWidget(metadata)
        actions.addWidget(anilist)
        if series["anilist_id"]:
            list_settings = QPushButton("AniList list settings")
            list_settings.clicked.connect(lambda: self._edit_anilist_entry(series_id))
            actions.addWidget(list_settings)
        actions.addStretch(1)
        details.addLayout(actions)
        if series["anilist_id"]:
            schedule = "AniList linked"
            if series["next_airing_episode"] and series["next_airing_at"]:
                schedule += f" • Episode {series['next_airing_episode']} airs {time.strftime('%b %d, %Y %I:%M %p', time.localtime(series['next_airing_at']))}"
            schedule_label = QLabel(schedule)
            schedule_label.setStyleSheet(f"color:{MUTED};")
            details.addWidget(schedule_label)
        details.addStretch(1)
        top.addLayout(details, 1)
        outer.addLayout(top)

        scroll, _, body = self._scroll()
        grouped: dict[tuple[int, int], list] = defaultdict(list)
        for episode in self.db.episodes(series_id):
            grouped[(int(episode["season"]), int(episode["episode"]))].append(episode)
        current_season = None
        preference = self.db.series_language_preference(series_id)
        for (season, number), variants in grouped.items():
            if season != current_season:
                current_season = season
                season_label = QLabel(f"Season {season:02d}")
                season_label.setStyleSheet("font-size:21px;font-weight:800;margin-top:12px;")
                body.addWidget(season_label)
            selected = choose_episode_variant(variants, preference)
            row = QFrame()
            row.setProperty("class", "card")
            row_layout = QHBoxLayout(row)
            play = QPushButton(f"▶   Episode {number:02d}")
            play.setStyleSheet("text-align:left;font-size:15px;")
            play.clicked.connect(lambda _=False, eid=int(selected["id"]): self.play_episode(eid))
            row_layout.addWidget(play, 1)
            versions = " / ".join(str(v["language"] or "Unknown") for v in variants)
            row_layout.addWidget(QLabel(versions))
            manage = QPushButton("Manage versions")
            manage.clicked.connect(lambda _=False, ids=[int(v["id"]) for v in variants]: self._manage_versions(ids))
            row_layout.addWidget(manage)
            body.addWidget(row)
        body.addStretch(1)
        outer.addWidget(scroll, 1)
        self._set_page(page)

    def show_continue(self) -> None:
        page, outer = self._page("Continue watching", "Resume exactly where you stopped")
        scroll, _, body = self._scroll()
        for episode in self.db.continue_watching(50):
            row = QPushButton(
                f"{episode['series_title']}   •   S{episode['season']:02d}E{episode['episode']:02d}   •   "
                f"{episode['language']}   •   {format_time(episode['progress_ms'])} / {format_time(episode['duration_ms'])}"
            )
            row.setMinimumHeight(56)
            row.setStyleSheet("text-align:left;")
            row.clicked.connect(lambda _=False, eid=int(episode["id"]): self.play_episode(eid))
            body.addWidget(row)
        body.addStretch(1)
        outer.addWidget(scroll, 1)
        self._set_page(page, 2)

    def _require_library(self) -> Path | None:
        if self.library_root:
            return self.library_root
        QMessageBox.information(self, "Choose a library", "Open Settings and choose your anime library folder first.")
        self.show_settings()
        return None

    def show_import(self) -> None:
        page, outer = self._page("Import", "Bring downloaded episodes into your organized library")
        panel = QFrame()
        panel.setProperty("class", "panel")
        layout = QVBoxLayout(panel)
        label = QLabel("Anime Watcher reads filenames, detects season and episode numbers, and moves files into the correct anime folder. Existing files are never overwritten.")
        label.setWordWrap(True)
        layout.addWidget(label)
        files = QPushButton("Choose episode files")
        folder = QPushButton("Choose a folder")
        files.clicked.connect(self._import_files)
        folder.clicked.connect(self._import_folder)
        layout.addWidget(files)
        layout.addWidget(folder)
        outer.addWidget(panel)
        outer.addStretch(1)
        self._set_page(page, 3)

    def _import_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose anime episodes", "", "Video files (*.mkv *.mp4 *.webm *.avi *.mov *.m4v);;All files (*)")
        if paths:
            self._organize(paths)

    def _import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder containing anime episodes")
        if folder:
            self._organize(scan_video_files(folder))

    def _organize(self, paths) -> None:
        root = self._require_library()
        if root is None:
            return
        results = organize_files(paths, root)
        moved = sum(item.status == "moved" for item in results)
        duplicate = sum(item.status == "duplicate" for item in results)
        self._scan(False)
        QMessageBox.information(self, "Import complete", f"Moved {moved} episode(s).\nSkipped {duplicate} identical duplicate(s).")
        self.show_library()

    def show_downloads(self) -> None:
        page, outer = self._page("Find & download", "Search public catalog pages and organize authorized direct media files")
        scroll, _, body = self._scroll()
        search_panel = QFrame()
        search_panel.setProperty("class", "panel")
        form = QVBoxLayout(search_panel)
        title = QLabel("Search a source website")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        form.addWidget(title)
        self.search_source = QLineEdit(str(self.db.setting("catalog_source_url", self.db.setting("provider_url", "")) or ""))
        self.search_source.setPlaceholderText("https://example.com/catalog or https://example.com/search?q={query}")
        self.catalog_query = QLineEdit()
        self.catalog_query.setPlaceholderText("Anime title or part of it…")
        search_button = QPushButton("Search source")
        search_button.setObjectName("accent")
        search_button.clicked.connect(self._catalog_search)
        self.catalog_query.returnPressed.connect(self._catalog_search)
        form.addWidget(self.search_source)
        query_row = QHBoxLayout()
        query_row.addWidget(self.catalog_query, 1)
        query_row.addWidget(search_button)
        form.addLayout(query_row)
        self.catalog_status = QLabel("")
        self.catalog_status.setStyleSheet(f"color:{MUTED};")
        form.addWidget(self.catalog_status)
        self.catalog_results = QVBoxLayout()
        form.addLayout(self.catalog_results)
        body.addWidget(search_panel)

        direct = QFrame()
        direct.setProperty("class", "panel")
        direct_form = QVBoxLayout(direct)
        direct_title = QLabel("Download a direct media file")
        direct_title.setStyleSheet("font-size:20px;font-weight:700;")
        direct_form.addWidget(direct_title)
        self.download_url = QLineEdit()
        self.download_url.setPlaceholderText("https://example.com/Show.S01E01.mkv")
        self.rights_check = QCheckBox("I own this file or have permission to download it")
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 1000)
        self.download_label = QLabel("")
        download_button = QPushButton("Download & organize")
        download_button.setObjectName("accent")
        download_button.clicked.connect(self._start_download)
        for widget in (self.download_url, self.rights_check, self.download_progress, self.download_label, download_button):
            direct_form.addWidget(widget)
        body.addWidget(direct)
        body.addStretch(1)
        outer.addWidget(scroll, 1)
        self._set_page(page, 4)

    def _catalog_search(self) -> None:
        source = self.search_source.text().strip()
        query = self.catalog_query.text().strip()
        if not source or not query:
            return QMessageBox.warning(self, "Search needs two things", "Enter a source URL and an anime title.")
        self.db.set_setting("catalog_source_url", source)
        self.catalog_status.setText("Reading public catalog pages…")
        clear_layout(self.catalog_results)
        worker = Worker(search_catalog, source, query)
        worker.signals.done.connect(self._catalog_results_ready)
        worker.signals.failed.connect(lambda error: self.catalog_status.setText(error))
        self._start_worker(worker)

    def _catalog_results_ready(self, results: list[CatalogResult]) -> None:
        self.catalog_status.setText(f"{len(results)} matching result(s)" if results else "No matching links found.")
        for result in results:
            row = QFrame()
            row.setProperty("class", "card")
            layout = QVBoxLayout(row)
            header = QHBoxLayout()
            text = QLabel(f"<b>{result.title}</b><br><span style='color:{MUTED}'>{result.url}</span>")
            text.setWordWrap(True)
            header.addWidget(text, 1)
            if result.direct_media:
                use = QPushButton("Use download URL")
                use.clicked.connect(lambda _=False, url=result.url: self._use_download_url(url))
                header.addWidget(use)
            else:
                episodes = QPushButton("View episodes")
                header.addWidget(episodes)
            open_page = QPushButton("Open page")
            open_page.clicked.connect(lambda _=False, url=result.url: webbrowser.open(url))
            header.addWidget(open_page)
            layout.addLayout(header)
            episode_box = QVBoxLayout()
            layout.addLayout(episode_box)
            if not result.direct_media:
                episodes.clicked.connect(lambda _=False, item=result, box=episode_box: self._load_catalog_episodes(item, box))
            self.catalog_results.addWidget(row)

    def _load_catalog_episodes(self, result: CatalogResult, box: QVBoxLayout) -> None:
        clear_layout(box)
        box.addWidget(QLabel("Reading public episode links…"))
        worker = Worker(load_catalog_episodes, result.url)
        worker.signals.done.connect(lambda episodes: self._catalog_episodes_ready(result, box, episodes))
        worker.signals.failed.connect(lambda error: self._layout_message(box, error))
        self._start_worker(worker)

    def _layout_message(self, layout, text: str) -> None:
        clear_layout(layout)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)

    def _catalog_episodes_ready(self, result: CatalogResult, box: QVBoxLayout, episodes: list[EpisodeResult]) -> None:
        clear_layout(box)
        if not episodes:
            return box.addWidget(QLabel("No public episode links were found."))
        grid = QGridLayout()
        for index, episode in enumerate(episodes):
            target = episode.url if episode.direct_open else result.url
            button = QPushButton(episode.title)
            button.clicked.connect(lambda _=False, url=target: webbrowser.open(url))
            grid.addWidget(button, index // 6, index % 6)
        box.addLayout(grid)

    def _use_download_url(self, url: str) -> None:
        self.download_url.setText(url)
        self.download_label.setText("Direct media URL selected. Confirm permission, then download.")

    def _start_download(self) -> None:
        root = self._require_library()
        if root is None:
            return
        if not self.rights_check.isChecked():
            return QMessageBox.warning(self, "Permission required", "Confirm that you are authorized to download this file.")
        url = self.download_url.text().strip()
        if not url:
            return
        self.download_label.setText("Connecting…")
        worker = Worker(download_authorized_file, url, self.data_root / "downloads", root, with_progress=True)
        worker.signals.progress.connect(self._download_progress_update)
        worker.signals.done.connect(self._download_finished)
        worker.signals.failed.connect(lambda error: QMessageBox.critical(self, "Download failed", error))
        self._start_worker(worker)

    def _download_progress_update(self, values) -> None:
        received, total = values
        self.download_progress.setValue(round(received / total * 1000) if total else 0)
        self.download_label.setText(f"{received / 1048576:.1f} MB" + (f" / {total / 1048576:.1f} MB" if total else ""))

    def _download_finished(self, result) -> None:
        self._scan(False)
        self.download_progress.setValue(1000)
        self.download_label.setText(f"Added: {result.destination}")

    def show_file_manager(self) -> None:
        page, outer = self._page("File manager", "Correct anime, season, episode, and Sub/Dub identification")
        search = QLineEdit()
        search.setPlaceholderText("Search anime name or file path…")
        outer.addWidget(search)
        scroll, _, body = self._scroll()

        def render(text: str = "") -> None:
            clear_layout(body)
            rows = self.db.all_episodes(text)
            for episode in rows:
                card = QFrame(); card.setProperty("class", "card")
                card_layout = QHBoxLayout(card)
                description = QLabel(
                    f"{episode['series_title']}  •  S{episode['season']:02d}E{episode['episode']:02d}  •  {episode['language']}\n{episode['path']}"
                )
                description.setWordWrap(True)
                card_layout.addWidget(description, 1)
                fix = QPushButton("Fix details")
                fix.clicked.connect(lambda _=False, eid=int(episode["id"]): self._rename_episode(eid))
                delete = QPushButton("Delete"); delete.setObjectName("danger")
                delete.clicked.connect(lambda _=False, eid=int(episode["id"]): self._delete_episode(eid))
                card_layout.addWidget(fix); card_layout.addWidget(delete)
                body.addWidget(card)
            if not rows:
                body.addWidget(QLabel("No matching files."))
            body.addStretch(1)

        search.textChanged.connect(render)
        render()
        outer.addWidget(scroll, 1)
        self._set_page(page, 5)

    def show_notifications(self) -> None:
        page, outer = self._page("Release updates", "AniList official airing updates for linked anime")
        row = QHBoxLayout()
        refresh = QPushButton("Check schedules now")
        refresh.clicked.connect(self._refresh_release_schedule)
        row.addWidget(refresh); row.addStretch(1)
        outer.addLayout(row)
        scroll, _, body = self._scroll()
        notifications = self.db.notifications()
        for item in notifications:
            card = QFrame(); card.setProperty("class", "card")
            layout = QVBoxLayout(card)
            title = QLabel(item["title"]); title.setStyleSheet("font-size:16px;font-weight:800;")
            body_text = QLabel(item["body"]); body_text.setWordWrap(True)
            timestamp = QLabel(item["created_at"]); timestamp.setStyleSheet(f"color:{MUTED};font-size:11px;")
            layout.addWidget(title); layout.addWidget(body_text); layout.addWidget(timestamp)
            body.addWidget(card)
        if not notifications:
            body.addWidget(QLabel("No release updates yet. Link anime to AniList, then check schedules."))
        body.addStretch(1)
        outer.addWidget(scroll, 1)
        self.db.mark_notifications_read()
        self._set_page(page, 6)

    def _refresh_release_schedule(self) -> None:
        linked = self.db.linked_series()
        ids = [int(row["anilist_id"]) for row in linked]
        if not ids:
            return
        worker = Worker(release_schedule, ids)
        worker.signals.done.connect(self._release_schedule_ready)
        worker.signals.failed.connect(lambda _error: None)
        self._start_worker(worker)

    def _release_schedule_ready(self, media_rows: list[dict]) -> None:
        for media in media_rows:
            series, changed = self.db.update_release_schedule(media)
            next_airing = media.get("nextAiringEpisode") or {}
            if not series or not changed or not next_airing:
                continue
            episode = int(next_airing.get("episode") or 0)
            airing_at = int(next_airing.get("airingAt") or 0)
            title = series["display_title"] or series["title"]
            when = time.strftime("%b %d, %Y at %I:%M %p", time.localtime(airing_at)) if airing_at else "soon"
            body = f"Episode {episode} is scheduled to air {when}. This is the official airing schedule; AniList does not provide dub dates."
            created = self.db.add_notification("airing", f"{title} • Episode {episode}", body, int(series["id"]), f"airing|{media['id']}|{episode}|{airing_at}")
            if created and self.tray.isVisible():
                self.tray.showMessage(f"{title} release update", body, QSystemTrayIcon.MessageIcon.Information, 8000)

    def _link_anilist(self, series_id: int) -> None:
        series = self.db.get_series(series_id)
        if not series:
            return
        dialog = QDialog(self); dialog.setWindowTitle("Link anime to AniList"); dialog.resize(720, 560)
        layout = QVBoxLayout(dialog)
        search = QLineEdit(series["display_title"] or series["title"])
        button = QPushButton("Search AniList"); button.setObjectName("accent")
        results = QVBoxLayout()
        layout.addWidget(QLabel("Choose the exact anime so progress and release schedules match correctly."))
        layout.addWidget(search); layout.addWidget(button); layout.addLayout(results); layout.addStretch(1)

        def show_results(items: list[dict]) -> None:
            clear_layout(results)
            if not items:
                results.addWidget(QLabel("No matching AniList anime found.")); return
            for media in items:
                titles = media.get("title") or {}
                name = titles.get("english") or titles.get("romaji") or titles.get("native") or "Untitled"
                detail = " • ".join(str(value) for value in (media.get("seasonYear"), media.get("format"), media.get("status")) if value)
                choose = QPushButton(f"{name}\n{detail}")
                choose.setStyleSheet("text-align:left;")
                choose.clicked.connect(lambda _=False, selected=media: (self.db.link_anilist(series_id, selected), dialog.accept()))
                results.addWidget(choose)

        def start_search() -> None:
            clear_layout(results); results.addWidget(QLabel("Searching AniList…"))
            worker = Worker(search_anime, search.text().strip())
            worker.signals.done.connect(show_results)
            worker.signals.failed.connect(lambda error: self._layout_message(results, error))
            self._start_worker(worker)

        button.clicked.connect(start_search); search.returnPressed.connect(start_search)
        start_search()
        if dialog.exec():
            self.show_series(series_id)

    def _anilist_token_value(self) -> str:
        protected = str(self.db.setting("anilist_token_protected", "") or "")
        if not protected:
            return ""
        try:
            return unprotect_secret(protected)
        except Exception:
            return ""

    def _edit_anilist_entry(self, series_id: int) -> None:
        series = self.db.get_series(series_id)
        token = self._anilist_token_value()
        if not series or not series["anilist_id"]:
            return
        if not token:
            return QMessageBox.information(self, "Connect AniList", "Connect your AniList account in Settings first.")
        saved = self.db.setting("anilist_list_settings", {})
        current = saved.get(str(series_id), {}) if isinstance(saved, dict) else {}
        dialog = QDialog(self); dialog.setWindowTitle("AniList list settings")
        form = QFormLayout(dialog)
        status = QComboBox(); status.addItems(["CURRENT", "COMPLETED", "PAUSED", "DROPPED", "PLANNING", "REPEATING"])
        status.setCurrentText(str(current.get("status", "CURRENT")))
        score = QDoubleSpinBox(); score.setRange(0, 100); score.setDecimals(1); score.setValue(float(current.get("score", 0)))
        progress = QSpinBox(); progress.setRange(0, 9999); progress.setValue(int(current.get("progress", 0)))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow("Status", status); form.addRow("Score (0–100)", score); form.addRow("Episodes watched", progress); form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        payload = {"status": status.currentText(), "score": score.value(), "progress": progress.value()}
        if not isinstance(saved, dict):
            saved = {}
        saved[str(series_id)] = payload
        self.db.set_setting("anilist_list_settings", saved)
        worker = Worker(save_list_entry, token, int(series["anilist_id"]), progress.value(), status.currentText(), score.value() or None)
        worker.signals.done.connect(lambda _result: QMessageBox.information(self, "AniList updated", "Your list entry was updated."))
        worker.signals.failed.connect(lambda error: QMessageBox.warning(self, "AniList update failed", error))
        self._start_worker(worker)

    def show_settings(self) -> None:
        page, outer = self._page("Settings", "Profiles, library, playback, AniList, and provider bookmarks")
        scroll, _, settings_body = self._scroll()
        panel = QFrame()
        panel.setProperty("class", "panel")
        layout = QVBoxLayout(panel)
        heading = QLabel("Profile")
        heading.setStyleSheet("font-size:18px;font-weight:800;")
        layout.addWidget(heading)
        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        for profile in self.profile_manager.profiles():
            self.profile_combo.addItem(profile.name, profile.id)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(self.profile_manager.active.id)))
        switch = QPushButton("Switch")
        switch.clicked.connect(self._switch_profile)
        create = QPushButton("New profile")
        create.clicked.connect(self._create_profile)
        rename_profile = QPushButton("Rename")
        rename_profile.clicked.connect(self._rename_profile)
        profile_row.addWidget(self.profile_combo, 1); profile_row.addWidget(switch); profile_row.addWidget(create); profile_row.addWidget(rename_profile)
        layout.addLayout(profile_row)
        layout.addSpacing(18)
        layout.addWidget(QLabel("Library folder"))
        row = QHBoxLayout()
        self.library_entry = QLineEdit(str(self.library_root or ""))
        browse = QPushButton("Browse")
        browse.clicked.connect(self._choose_library)
        row.addWidget(self.library_entry, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        save = QPushButton("Save & rescan")
        save.setObjectName("accent")
        save.clicked.connect(self._save_settings)
        layout.addWidget(save)
        layout.addSpacing(20)
        shortcut_title = QLabel("Keyboard shortcuts")
        shortcut_title.setStyleSheet("font-size:18px;font-weight:800;")
        layout.addWidget(shortcut_title)
        shortcuts = merged_keybindings(self.db.setting("keybindings", {}))
        self.keybinding_edits: dict[str, QKeySequenceEdit] = {}
        shortcut_form = QFormLayout()
        for action, (label, _default) in KEYBINDING_ACTIONS.items():
            editor = QKeySequenceEdit(QKeySequence(shortcuts[action]))
            self.keybinding_edits[action] = editor
            shortcut_form.addRow(label, editor)
        layout.addLayout(shortcut_form)
        save_shortcuts = QPushButton("Save shortcuts")
        save_shortcuts.clicked.connect(self._save_keybindings)
        layout.addWidget(save_shortcuts)
        layout.addSpacing(20)
        anilist_title = QLabel("AniList account")
        anilist_title.setStyleSheet("font-size:18px;font-weight:800;")
        layout.addWidget(anilist_title)
        note = QLabel("Optional. Used only when you explicitly connect. Your token is encrypted to this Windows account and never stored as plain text.")
        note.setWordWrap(True); note.setStyleSheet(f"color:{MUTED};")
        layout.addWidget(note)
        self.anilist_client_id = QLineEdit(str(self.db.setting("anilist_client_id", "") or ""))
        self.anilist_client_id.setPlaceholderText("AniList application client ID")
        self.anilist_token = QLineEdit(); self.anilist_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.anilist_token.setPlaceholderText("Paste AniList access token")
        layout.addWidget(self.anilist_client_id); layout.addWidget(self.anilist_token)
        anilist_buttons = QHBoxLayout()
        authorize = QPushButton("Open authorization")
        authorize.clicked.connect(self._open_anilist_authorization)
        connect = QPushButton("Save & verify")
        connect.clicked.connect(self._connect_anilist)
        disconnect = QPushButton("Disconnect")
        disconnect.clicked.connect(self._disconnect_anilist)
        anilist_buttons.addWidget(authorize); anilist_buttons.addWidget(connect); anilist_buttons.addWidget(disconnect); anilist_buttons.addStretch(1)
        layout.addLayout(anilist_buttons)
        self.anilist_status = QLabel(str(self.db.setting("anilist_viewer_name", "Not connected") or "Not connected"))
        self.anilist_status.setStyleSheet(f"color:{MUTED};")
        layout.addWidget(self.anilist_status)
        layout.addSpacing(20)
        layout.addWidget(QLabel("Provider bookmarks"))
        bookmarks = QHBoxLayout()
        for name, url in [("Crunchyroll", "https://www.crunchyroll.com/"), ("HIDIVE", "https://www.hidive.com/"), ("Netflix", "https://www.netflix.com/browse/genre/7424")]:
            button = QPushButton(f"Open {name}")
            button.clicked.connect(lambda _=False, target=url: webbrowser.open(target))
            bookmarks.addWidget(button)
        bookmarks.addStretch(1)
        layout.addLayout(bookmarks)
        self.provider_entry = QLineEdit(str(self.db.setting("provider_url", "") or ""))
        self.provider_entry.setPlaceholderText("Optional custom provider website")
        open_custom = QPushButton("Open custom provider")
        open_custom.clicked.connect(self._open_custom_provider)
        layout.addWidget(self.provider_entry)
        layout.addWidget(open_custom)
        settings_body.addWidget(panel)
        settings_body.addStretch(1)
        outer.addWidget(scroll, 1)
        self._set_page(page, 7)

    def _choose_library(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose your anime library folder", str(self.library_root or ""))
        if folder:
            self.library_entry.setText(folder)

    def _profile_name_dialog(self, title: str, initial: str = "") -> str | None:
        dialog = QDialog(self); dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        entry = QLineEdit(initial); entry.selectAll()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        layout.addWidget(QLabel("Profile name")); layout.addWidget(entry); layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return entry.text().strip()

    def _create_profile(self) -> None:
        name = self._profile_name_dialog("New profile")
        if name is None:
            return
        try:
            profile = self.profile_manager.create(name)
        except ValueError as exc:
            return QMessageBox.warning(self, "Could not create profile", str(exc))
        self.profile_combo.addItem(profile.name, profile.id)
        self.profile_combo.setCurrentIndex(self.profile_combo.findData(profile.id))
        self._switch_profile()

    def _rename_profile(self) -> None:
        profile_id = self.profile_combo.currentData()
        if not profile_id:
            return
        name = self._profile_name_dialog("Rename profile", self.profile_combo.currentText())
        if name is None:
            return
        try:
            profile = self.profile_manager.rename(str(profile_id), name)
        except ValueError as exc:
            return QMessageBox.warning(self, "Could not rename profile", str(exc))
        self.profile_combo.setItemText(self.profile_combo.currentIndex(), profile.name)
        if profile.id == self.profile_manager.active.id:
            self.profile_status.setText(f"Profile: {profile.name}")

    def _switch_profile(self) -> None:
        profile_id = str(self.profile_combo.currentData() or "")
        if not profile_id or profile_id == self.profile_manager.active.id:
            return
        self._save_progress(stop=True)
        self.db.close()
        profile = self.profile_manager.set_active(profile_id)
        self.db = LibraryDatabase(self.profile_manager.database_path(profile_id))
        self.library_root = library_root_from_setting(self.db.setting("library_root", ""))
        self.profile_status.setText(f"Profile: {profile.name}")
        self.sidebar_status.setText(str(self.library_root) if self.library_root else "No library selected")
        self.show_home()
        self._refresh_release_schedule()

    def _save_keybindings(self) -> None:
        bindings = {action: editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText) for action, editor in self.keybinding_edits.items()}
        empty = [KEYBINDING_ACTIONS[action][0] for action, value in bindings.items() if not value]
        duplicates = duplicate_keybindings(bindings)
        if empty:
            return QMessageBox.warning(self, "Shortcut required", f"Choose a shortcut for {empty[0]}.")
        if duplicates:
            return QMessageBox.warning(self, "Duplicate shortcut", "Each player action needs a unique shortcut.")
        self.db.set_setting("keybindings", bindings)
        QMessageBox.information(self, "Shortcuts saved", "Your player shortcuts will be used the next time the player opens.")

    def _open_anilist_authorization(self) -> None:
        client_id = self.anilist_client_id.text().strip()
        if not client_id.isdigit():
            return QMessageBox.warning(self, "Client ID required", "Enter the numeric client ID from your AniList developer application first.")
        self.db.set_setting("anilist_client_id", client_id)
        webbrowser.open(f"https://anilist.co/api/v2/oauth/authorize?client_id={client_id}&response_type=token")
        self.anilist_status.setText("Authorize in the browser, then paste the returned token here.")

    def _connect_anilist(self) -> None:
        client_id = self.anilist_client_id.text().strip()
        token = self.anilist_token.text().strip()
        if not client_id.isdigit() or not token:
            return QMessageBox.warning(self, "AniList details required", "Enter your client ID and access token.")
        self.anilist_status.setText("Verifying AniList account…")
        worker = Worker(viewer, token)
        worker.signals.done.connect(lambda account, secret=token, cid=client_id: self._anilist_connected(account, secret, cid))
        worker.signals.failed.connect(lambda error: self.anilist_status.setText(error))
        self._start_worker(worker)

    def _anilist_connected(self, account: dict, token: str, client_id: str) -> None:
        try:
            protected = protect_secret(token)
        except Exception as exc:
            return self.anilist_status.setText(f"Could not protect the token: {exc}")
        self.db.set_setting("anilist_token_protected", protected)
        self.db.set_setting("anilist_client_id", client_id)
        self.db.set_setting("anilist_viewer_name", account.get("name", "Connected"))
        self.anilist_token.clear()
        self.anilist_status.setText(f"Connected as {account.get('name', 'AniList user')}")

    def _disconnect_anilist(self) -> None:
        self.db.set_setting("anilist_token_protected", "")
        self.db.set_setting("anilist_viewer_name", "")
        self.anilist_token.clear()
        self.anilist_status.setText("Not connected")

    def _save_settings(self) -> None:
        selected = self.library_entry.text().strip()
        if not selected:
            return QMessageBox.warning(self, "Library folder required", "Choose a folder before saving.")
        candidate = Path(selected)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return QMessageBox.critical(self, "Invalid folder", str(exc))
        self.library_root = candidate
        self.db.set_setting("library_root", str(candidate))
        self.sidebar_status.setText(str(candidate))
        self._scan()

    def _open_custom_provider(self) -> None:
        url = self.provider_entry.text().strip()
        if not url.startswith(("http://", "https://")):
            return QMessageBox.warning(self, "Invalid website", "Enter a complete HTTP(S) address.")
        self.db.set_setting("provider_url", url)
        webbrowser.open(url)

    def _scan(self, show_status: bool = True) -> None:
        if not self.library_root:
            return
        before = {str(row["path"]).casefold() for row in self.db.all_episodes()}
        stats = self.db.scan_library(self.library_root)
        initialized = bool(self.db.setting("release_notifications_initialized", False))
        if initialized:
            for episode in self.db.all_episodes():
                if str(episode["path"]).casefold() in before:
                    continue
                language = str(episode["language"] or "Unknown")
                title = f"{episode['series_title']} • {language} episode added"
                body = f"Season {episode['season']}, Episode {episode['episode']} is now in your local library."
                created = self.db.add_notification(
                    f"local-{language.casefold()}", title, body, int(episode["series_id"]),
                    f"local|{str(episode['path']).casefold()}",
                )
                if created and self.tray.isVisible():
                    self.tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 7000)
        else:
            self.db.set_setting("release_notifications_initialized", True)
        if show_status:
            QMessageBox.information(self, "Library refreshed", f"Found {stats['files']} episodes.")

    def _manage_versions(self, episode_ids: list[int]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Manage episode versions")
        dialog.resize(640, 180 + 62 * len(episode_ids))
        layout = QVBoxLayout(dialog)
        title = QLabel("Episode versions")
        title.setStyleSheet("font-size:22px;font-weight:800;")
        layout.addWidget(title)
        for episode_id in episode_ids:
            episode = self.db.episode(episode_id)
            if not episode:
                continue
            row = QHBoxLayout()
            row.addWidget(QLabel(f"Episode {episode['episode']:02d}   •   {episode['language']}"), 1)
            rename = QPushButton("Rename")
            delete = QPushButton("Delete")
            delete.setObjectName("danger")
            rename.clicked.connect(lambda _=False, eid=episode_id, dlg=dialog: (dlg.accept(), self._rename_episode(eid)))
            delete.clicked.connect(lambda _=False, eid=episode_id, dlg=dialog: (dlg.accept(), self._delete_episode(eid)))
            row.addWidget(rename)
            row.addWidget(delete)
            layout.addLayout(row)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def _rename_series(self, series_id: int) -> None:
        series = self.db.get_series(series_id)
        root = self._require_library()
        if not series or root is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Rename anime")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Rename the anime and all episode files. Watch progress stays attached."))
        entry = QLineEdit(series["title"])
        layout.addWidget(entry)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted or not entry.text().strip():
            return
        plans = None
        try:
            plans = rename_series_files(self.db.episodes(series_id), root, entry.text().strip())
            clean_title = next(iter(plans.values()))[1].relative_to(root).parts[0]
            self.db.rename_series(series_id, clean_title, {eid: dst for eid, (_, dst) in plans.items()})
            self.db.scan_library(root)
        except Exception as exc:
            if plans:
                try:
                    rollback_series_files(plans)
                except OSError:
                    pass
            return QMessageBox.critical(self, "Anime rename failed", str(exc))
        self.show_series(series_id)
        QMessageBox.information(self, "Anime renamed", f"Renamed to {clean_title}. Poster and details are refreshing.")
        self._refresh_metadata(series_id, clean_title)

    def _rename_episode(self, episode_id: int) -> None:
        root = self._require_library()
        episode = self.db.episode(episode_id)
        if root is None or not episode:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Rename episode")
        form = QFormLayout(dialog)
        source = Path(episode["path"])
        try:
            folder_title = source.relative_to(root).parts[0]
        except (ValueError, IndexError):
            folder_title = episode["series_title"]
        title = QLineEdit(folder_title)
        season = QSpinBox(); season.setRange(0, 999); season.setValue(int(episode["season"]))
        number = QSpinBox(); number.setRange(0, 9999); number.setValue(int(episode["episode"]))
        language = QComboBox(); language.addItems(sorted(LANGUAGES)); language.setCurrentText(str(episode["language"]))
        form.addRow("Anime title", title)
        form.addRow("Season", season)
        form.addRow("Episode", number)
        form.addRow("Version", language)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        destination = None
        try:
            destination = rename_episode_file(source, root, title.text().strip(), season.value(), number.value(), language.currentText())
            clean_title = destination.relative_to(root).parts[0]
            target_series = self.db.relocate_episode(episode_id, destination, clean_title, season.value(), number.value(), language.currentText())
            self.db.scan_library(root)
        except Exception as exc:
            if destination is not None and destination != source and destination.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(source))
            return QMessageBox.critical(self, "Rename failed", str(exc))
        self.show_series(target_series)

    def _delete_episode(self, episode_id: int) -> None:
        root = self._require_library()
        episode = self.db.episode(episode_id)
        if root is None or not episode:
            return
        path = Path(episode["path"])
        answer = QMessageBox.question(self, "Move episode to Recycle Bin?", f"Move this video to the Recycle Bin?\n\n{path.name}")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            send_to_recycle_bin(path, root)
            self.db.scan_library(root)
        except Exception as exc:
            return QMessageBox.critical(self, "Delete failed", str(exc))
        series_id = int(episode["series_id"])
        self.show_series(series_id) if self.db.get_series(series_id) else self.show_library()

    def _refresh_metadata(self, series_id: int, title: str | None = None) -> None:
        series = self.db.get_series(series_id)
        if not series:
            return
        lookup_title = title or series["title"]
        worker = Worker(fetch_metadata, lookup_title, self.data_root / "posters")
        worker.signals.done.connect(lambda data: self._metadata_ready(series_id, data))
        worker.signals.failed.connect(lambda error: QMessageBox.warning(self, "Metadata lookup failed", error))
        self._start_worker(worker)

    def _metadata_ready(self, series_id: int, data: dict) -> None:
        if not self.db.get_series(series_id):
            return
        self.db.update_metadata(series_id, data["title"], data["synopsis"], data["poster_path"], data["id"])
        if self.visible_series_id == series_id:
            self.show_series(series_id)

    def _auto_metadata(self) -> None:
        missing = [
            row for row in self.db.series()
            if not row["metadata_updated"] and int(row["id"]) not in self.metadata_attempted
        ]
        if not missing:
            return
        series = missing[0]
        self.metadata_attempted.add(int(series["id"]))
        worker = Worker(fetch_metadata, series["title"], self.data_root / "posters")
        worker.signals.done.connect(lambda data, sid=int(series["id"]): self._metadata_ready(sid, data))
        worker.signals.done.connect(lambda _data: QTimer.singleShot(600, self._auto_metadata))
        worker.signals.failed.connect(lambda _error: QTimer.singleShot(600, self._auto_metadata))
        self._start_worker(worker)

    def _install_player_shortcuts(self, page: QWidget) -> None:
        bindings = merged_keybindings(self.db.setting("keybindings", {}))
        actions = {
            "play_pause": self._toggle_play,
            "seek_back": lambda: self._seek_relative(-10000),
            "seek_forward": lambda: self._seek_relative(10000),
            "fullscreen": self._toggle_fullscreen,
            "next_episode": lambda: self._change_episode(1),
            "previous_episode": lambda: self._change_episode(-1),
            "cycle_subtitles": self._cycle_subtitles,
            "subtitle_delay_down": lambda: self._adjust_subtitle_delay(-100),
            "subtitle_delay_up": lambda: self._adjust_subtitle_delay(100),
            "picture_in_picture": self._toggle_picture_in_picture,
        }
        self.player_shortcuts = []
        for action, callback in actions.items():
            shortcut = QShortcut(QKeySequence(bindings[action]), page)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self.player_shortcuts.append(shortcut)

    def _build_player_page(self) -> QWidget:
        page = QWidget()
        page.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._install_player_shortcuts(page)
        stack = QStackedLayout(page)
        self.player_stack = stack
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stack.setContentsMargins(0, 0, 0, 0)
        self.video_frame = CompositedVideoSurface()
        self.video_frame.setMouseTracking(True)
        self.video_frame.installEventFilter(self)
        self.video_frame.viewport().setMouseTracking(True)
        self.video_frame.viewport().installEventFilter(self)
        stack.addWidget(self.video_frame)

        self.player_overlay = PlayerOverlay()
        overlay_layout = QVBoxLayout(self.player_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(0)
        self.player_top = QFrame()
        self.player_top.setObjectName("playerTop")
        top_layout = QHBoxLayout(self.player_top)
        back = QPushButton("‹  BACK")
        back.clicked.connect(self.show_library)
        self.player_title = QLabel("")
        self.player_title.setStyleSheet("font-size:18px;font-weight:800;")
        self.player_meta = QLabel("")
        title_box = QVBoxLayout(); title_box.addWidget(self.player_title); title_box.addWidget(self.player_meta)
        top_layout.addWidget(back)
        top_layout.addLayout(title_box, 1)
        top_layout.addWidget(QLabel("ANIME WATCHER"))
        overlay_layout.addWidget(self.player_top)
        overlay_layout.addStretch(1)

        self.player_controls = QFrame()
        self.player_controls.setObjectName("playerControls")
        controls = QVBoxLayout(self.player_controls)
        controls.setContentsMargins(18, 10, 18, 14)
        controls.setSpacing(7)
        self.timeline = PreviewSlider()
        self.timeline.setRange(0, 1000)
        self.timeline.sliderPressed.connect(lambda: self.hide_timer.stop())
        self.timeline.sliderReleased.connect(self._timeline_released)
        self.timeline.preview.connect(self._timeline_preview)
        self.timeline.preview_left.connect(self._hide_preview)
        controls.addWidget(self.timeline)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        rewind = QPushButton("↶ 10")
        rewind.setObjectName("playerIcon")
        rewind.setToolTip("Back 10 seconds  (Left arrow)")
        rewind.clicked.connect(lambda: self._seek_relative(-10000))
        buttons.addWidget(rewind)
        self.play_button = QPushButton("❚❚")
        self.play_button.setObjectName("playerIcon")
        self.play_button.setToolTip("Play / Pause  (Space)")
        self.play_button.clicked.connect(self._toggle_play)
        buttons.addWidget(self.play_button)
        forward = QPushButton("10 ↷")
        forward.setObjectName("playerIcon")
        forward.setToolTip("Forward 10 seconds  (Right arrow)")
        forward.clicked.connect(lambda: self._seek_relative(10000))
        buttons.addWidget(forward)
        volume_label = QLabel("VOL")
        volume_label.setStyleSheet("font-size:10px;font-weight:800;color:#b8c0cc;")
        volume_label.setToolTip("Volume")
        buttons.addWidget(volume_label)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(85)
        self.volume.setFixedWidth(105)
        self.volume.valueChanged.connect(self.player.set_volume)
        buttons.addWidget(self.volume)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setStyleSheet("font-size:15px;font-weight:700;")
        buttons.addWidget(self.time_label)
        buttons.addStretch(1)
        self.now_title = QLabel("Episode 00")
        self.now_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.now_title.setStyleSheet("font-size:15px;font-weight:700;color:#d8dde6;")
        buttons.addWidget(self.now_title, 1)
        buttons.addStretch(1)
        next_episode = QPushButton("›│")
        next_episode.setObjectName("playerIcon")
        next_episode.setToolTip("Next episode")
        next_episode.clicked.connect(lambda: self._change_episode(1))
        buttons.addWidget(next_episode)
        pip = QPushButton("▣")
        pip.setObjectName("playerIcon")
        pip.setToolTip("Picture in picture")
        pip.clicked.connect(self._toggle_picture_in_picture)
        buttons.addWidget(pip)
        self.settings_button = QPushButton("⚙")
        self.settings_button.setObjectName("playerIcon")
        self.settings_button.setToolTip("Playback settings")
        self.settings_button.setCheckable(True)
        self.settings_button.clicked.connect(self._toggle_player_settings)
        buttons.addWidget(self.settings_button)
        fullscreen = QPushButton("⛶")
        fullscreen.setObjectName("playerIcon")
        fullscreen.setToolTip("Fullscreen  (F)")
        fullscreen.clicked.connect(self._toggle_fullscreen)
        buttons.addWidget(fullscreen)
        controls.addLayout(buttons)
        overlay_layout.addWidget(self.player_controls)
        stack.addWidget(self.player_overlay)
        stack.setCurrentWidget(self.player_overlay)
        self.player_overlay.raise_()
        self.player_overlay.activity.connect(self._show_controls)
        self.player_overlay.center_clicked.connect(self._toggle_play)

        self.player_settings = QFrame(page)
        self.player_settings.setObjectName("playerSettings")
        self.player_settings.setFixedWidth(330)
        settings_layout = QFormLayout(self.player_settings)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(10)
        self.variant_combo = QComboBox()
        self.variant_combo.currentTextChanged.connect(self._variant_changed)
        self.variant_label = QLabel("Version")
        settings_layout.addRow(self.variant_label, self.variant_combo)
        self.audio_combo = QComboBox()
        self.audio_combo.currentIndexChanged.connect(self._audio_changed)
        settings_layout.addRow("Audio", self.audio_combo)
        self.subtitle_combo = QComboBox()
        self.subtitle_combo.currentIndexChanged.connect(self._subtitle_changed)
        settings_layout.addRow("Subtitles", self.subtitle_combo)
        self.subtitle_delay = QDoubleSpinBox()
        self.subtitle_delay.setRange(-10.0, 10.0)
        self.subtitle_delay.setDecimals(1)
        self.subtitle_delay.setSingleStep(0.1)
        self.subtitle_delay.setSuffix(" s")
        self.subtitle_delay.valueChanged.connect(self._subtitle_delay_changed)
        settings_layout.addRow("Subtitle delay", self.subtitle_delay)
        subtitle_actions = QWidget()
        subtitle_actions.setStyleSheet("background:transparent;")
        subtitle_actions_layout = QHBoxLayout(subtitle_actions)
        subtitle_actions_layout.setContentsMargins(0, 0, 0, 0)
        subtitle_actions_layout.setSpacing(7)
        self.import_subtitles_button = QPushButton("Import file…")
        self.import_subtitles_button.setToolTip("Attach an SRT, VTT, ASS, or SSA subtitle file to this episode")
        self.import_subtitles_button.clicked.connect(self._import_subtitles)
        subtitle_actions_layout.addWidget(self.import_subtitles_button)
        self.generate_subtitles_button = QPushButton("Generate English")
        self.generate_subtitles_button.setToolTip("Create English subtitles locally with Whisper")
        self.generate_subtitles_button.clicked.connect(self._generate_subtitles)
        subtitle_actions_layout.addWidget(self.generate_subtitles_button)
        settings_layout.addRow("", subtitle_actions)
        self.subtitle_status = QLabel("")
        self.subtitle_status.setWordWrap(True)
        self.subtitle_status.setStyleSheet(f"color:{MUTED};font-size:11px;")
        settings_layout.addRow("", self.subtitle_status)
        self.quality_combo = QComboBox()
        self.quality_combo.currentTextChanged.connect(self._quality_changed)
        settings_layout.addRow("Quality", self.quality_combo)
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.75×", "1.0×", "1.25×", "1.5×", "2.0×"])
        self.speed_combo.setCurrentText("1.0×")
        self.speed_combo.currentTextChanged.connect(lambda text: self.player.set_rate(float(text.rstrip("×"))))
        settings_layout.addRow("Playback speed", self.speed_combo)
        self.autoplay_check = QCheckBox("Play next episode automatically")
        self.autoplay_check.setChecked(True)
        self.autoplay_check.toggled.connect(self._set_autoplay)
        settings_layout.addRow("", self.autoplay_check)
        self.player_settings.hide()

        self.skip_intro_button = QPushButton("SKIP INTRO  ››", page)
        self.skip_intro_button.setObjectName("skipIntro")
        self.skip_intro_button.clicked.connect(self._skip_intro)
        self.skip_intro_button.hide()

        self.preview_box = QFrame(page)
        self.preview_box.setProperty("class", "card")
        self.preview_box.setFixedSize(248, 170)
        preview_layout = QVBoxLayout(self.preview_box)
        preview_layout.setContentsMargins(4, 4, 4, 4)
        self.preview_image = QLabel("Loading preview…")
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.setFixedSize(240, 136)
        self.preview_time = QLabel("0:00")
        self.preview_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.preview_image)
        preview_layout.addWidget(self.preview_time)
        self.preview_box.hide()

        self.external_subtitle_label = QLabel("", page)
        self.external_subtitle_label.setObjectName("playerSubtitle")
        self.external_subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.external_subtitle_label.setWordWrap(True)
        self.external_subtitle_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.external_subtitle_label.hide()
        self.external_subtitle_top_label = QLabel("", page)
        self.external_subtitle_top_label.setObjectName("playerSubtitle")
        self.external_subtitle_top_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.external_subtitle_top_label.setWordWrap(True)
        self.external_subtitle_top_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.external_subtitle_top_label.hide()
        return page

    def play_episode(self, episode_id: int, start_ms: int | None = None) -> None:
        episode = self.db.episode(episode_id)
        if not episode or not Path(episode["path"]).exists():
            return QMessageBox.critical(self, "Episode missing", "The episode file is no longer available. Rescan the library.")
        position = int(episode["progress_ms"] if start_ms is None else max(0, start_ms))
        if self.current_episode_id and hasattr(self, "video_frame"):
            self._save_progress(stop=False)
            self._load_episode(episode, position)
            return
        page = self._build_player_page()
        self._set_page(page, player=True)
        QApplication.processEvents()
        page.setFocus(Qt.FocusReason.OtherFocusReason)
        self.player.attach(self.video_frame.video_item)
        self.player.set_volume(85)
        self._load_episode(episode, position)

    def _load_episode(self, episode, position: int) -> None:
        self.current_episode_id = int(episode["id"])
        self.current_video_path = str(episode["path"])
        self.known_duration_ms = int(episode["duration_ms"] or 0)
        self.last_saved = position
        language = str(episode["language"] or "Unknown")
        self.db.set_series_language_preference(int(episode["series_id"]), language)
        self.player_title.setText(str(episode["series_title"]))
        self.player_meta.setText(f"SEASON {int(episode['season']):02d}  •  EPISODE {int(episode['episode']):02d}  •  {language.upper()}")
        self.now_title.setText(f"Episode {int(episode['episode']):02d}")
        variants = self.db.episode_variants(self.current_episode_id)
        self.variant_map = episode_language_options(variants, self.current_episode_id)
        self.variant_combo.blockSignals(True)
        self.variant_combo.clear()
        self.variant_combo.addItems(list(self.variant_map))
        selected = next((name for name, eid in self.variant_map.items() if eid == self.current_episode_id), "")
        self.variant_combo.setCurrentText(selected)
        has_variants = len(self.variant_map) > 1
        self.variant_combo.setVisible(has_variants)
        self.variant_label.setVisible(has_variants)
        self.variant_combo.blockSignals(False)
        self.quality_probe_token += 1
        quality_token = self.quality_probe_token
        self.quality_map = {}
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        self.quality_combo.addItem("Detecting source…")
        self.quality_combo.setEnabled(False)
        self.quality_combo.blockSignals(False)
        quality_sources = [
            (int(row["id"]), str(row["path"]))
            for row in variants
            if str(row["language"] or "Unknown") == language
        ]
        self.player_settings.hide()
        self.settings_button.setChecked(False)
        self.media_chapters = []
        self.active_skip_chapter = None
        self.timeline.set_chapters([], self.known_duration_ms)
        self.intro_probe_token += 1
        intro_token = self.intro_probe_token
        self.skip_intro_button.hide()
        self.preview_token += 1
        self.preview_bucket_requested = None
        self.preview_box.hide()
        self._clear_external_subtitles()
        delays = self.db.setting("subtitle_delays", {})
        self.subtitle_delay_ms = int(delays.get(str(episode["series_id"]), 0)) if isinstance(delays, dict) else 0
        self.subtitle_delay.blockSignals(True)
        self.subtitle_delay.setValue(self.subtitle_delay_ms / 1000)
        self.subtitle_delay.blockSignals(False)
        self.subtitle_status.clear()
        self.player.play(self.current_video_path)
        self._resume_when_ready(position, 0)
        QTimer.singleShot(1400, self._load_tracks)
        intro_worker = Worker(probe_chapter_ranges, self.current_video_path)
        intro_worker.signals.done.connect(lambda result, token=intro_token: self._intro_ready(token, result))
        self._start_worker(intro_worker)
        quality_worker = Worker(probe_quality_sources, quality_sources)
        quality_worker.signals.done.connect(
            lambda result, token=quality_token, episode_id=self.current_episode_id:
                self._quality_ready(token, episode_id, result)
        )
        self._start_worker(quality_worker)
        self._show_controls()

    def _playback_error(self, message: str) -> None:
        if not self.current_episode_id or not message:
            return
        self.player_meta.setText(f"PLAYBACK ERROR  •  {message}")
        self._show_controls()

    def _resume_when_ready(self, position: int, attempt: int) -> None:
        if not self.current_episode_id:
            return
        duration = self.player.duration()
        if duration > 0 or attempt >= 40:
            if duration > 0:
                self.known_duration_ms = duration
            if position:
                self.player.seek(position)
            return
        QTimer.singleShot(50, lambda: self._resume_when_ready(position, attempt + 1))

    def _variant_changed(self, label: str) -> None:
        episode_id = self.variant_map.get(label)
        if not episode_id or episode_id == self.current_episode_id:
            return
        self.play_episode(episode_id, self.player.time())

    def _load_tracks(self) -> None:
        if not self.current_episode_id:
            return
        episode = self.db.episode(self.current_episode_id)
        if not episode:
            return
        self.audio_combo.blockSignals(True)
        self.audio_combo.clear()
        for track_id, name in self.player.audio_tracks():
            self.audio_combo.addItem(name, track_id)
        self.audio_combo.blockSignals(False)
        self.subtitle_combo.blockSignals(True)
        self.subtitle_combo.clear()
        for track_id, name in self.player.subtitle_tracks():
            self.subtitle_combo.addItem(name, track_id)
        sidecars = find_sidecar_subtitles(self.current_video_path or "")
        for path in sidecars:
            label = path.name
            if path.name.casefold().endswith(".generated.en.srt"):
                label = "English (Generated)"
            elif ".en." in path.name.casefold() or ".eng." in path.name.casefold():
                label = "English (Imported)"
            self.subtitle_combo.addItem(label, f"external::{path}")
        preferences = self.db.setting("subtitle_preferences", {})
        preferred = str(preferences.get(str(episode["series_id"]), "")) if isinstance(preferences, dict) else ""
        chosen = self.external_subtitle_path if self.external_subtitle_path in sidecars else None
        preferred_index = -1
        if preferred.startswith("external::"):
            wanted_name = preferred.removeprefix("external::")
            chosen = next((path for path in sidecars if path.name == wanted_name), chosen)
        elif preferred.startswith("embedded::"):
            try:
                wanted_track = int(preferred.removeprefix("embedded::"))
                preferred_index = next((i for i in range(self.subtitle_combo.count()) if self.subtitle_combo.itemData(i) == wanted_track), -1)
            except ValueError:
                preferred_index = -1
        elif preferred == "off":
            preferred_index = 0
        if chosen is None and preferred_index < 0 and sidecars:
            chosen = sidecars[0]
        if chosen:
            data = f"external::{chosen}"
            index = next(
                (item for item in range(self.subtitle_combo.count()) if self.subtitle_combo.itemData(item) == data),
                -1,
            )
            if index >= 0:
                self.subtitle_combo.setCurrentIndex(index)
        elif preferred_index >= 0:
            self.subtitle_combo.setCurrentIndex(preferred_index)
        self.subtitle_combo.blockSignals(False)
        if chosen:
            self.player.set_subtitle_track(-1)
            self._select_external_subtitle(chosen)
        else:
            self._clear_external_subtitles()
            track = self.subtitle_combo.currentData()
            self.player.set_subtitle_track(int(track) if track is not None else -1)

    def _audio_changed(self, index: int) -> None:
        track = self.audio_combo.itemData(index)
        if track is not None:
            self.player.set_audio_track(int(track))

    def _subtitle_changed(self, index: int) -> None:
        track = self.subtitle_combo.itemData(index)
        episode = self.db.episode(self.current_episode_id) if self.current_episode_id else None
        preference = "off"
        if isinstance(track, str) and track.startswith("external::"):
            self.player.set_subtitle_track(-1)
            path = Path(track.removeprefix("external::"))
            self._select_external_subtitle(path)
            preference = f"external::{path.name}"
        else:
            self._clear_external_subtitles()
            if track is not None:
                self.player.set_subtitle_track(int(track))
                if int(track) >= 0:
                    preference = f"embedded::{int(track)}"
        if episode:
            preferences = self.db.setting("subtitle_preferences", {})
            if not isinstance(preferences, dict):
                preferences = {}
            preferences[str(episode["series_id"])] = preference
            self.db.set_setting("subtitle_preferences", preferences)

    def _cycle_subtitles(self) -> None:
        if not hasattr(self, "subtitle_combo") or self.subtitle_combo.count() < 2:
            return
        self.subtitle_combo.setCurrentIndex((self.subtitle_combo.currentIndex() + 1) % self.subtitle_combo.count())
        self._show_controls()

    def _subtitle_delay_changed(self, seconds: float) -> None:
        self.subtitle_delay_ms = round(float(seconds) * 1000)
        episode = self.db.episode(self.current_episode_id) if self.current_episode_id else None
        if episode:
            delays = self.db.setting("subtitle_delays", {})
            if not isinstance(delays, dict):
                delays = {}
            delays[str(episode["series_id"])] = self.subtitle_delay_ms
            self.db.set_setting("subtitle_delays", delays)
        self._update_external_subtitle(self.player.time())

    def _adjust_subtitle_delay(self, milliseconds: int) -> None:
        if hasattr(self, "subtitle_delay"):
            self.subtitle_delay.setValue(max(-10.0, min(10.0, (self.subtitle_delay_ms + milliseconds) / 1000)))
            self.subtitle_status.setText(f"Subtitle delay: {self.subtitle_delay_ms / 1000:+.1f}s")
            self._show_controls()

    def _select_external_subtitle(self, path: Path) -> None:
        self._clear_external_subtitles()
        if path.suffix.casefold() in {".ass", ".ssa"}:
            try:
                renderer = LibassRenderer(path)
            except Exception as exc:
                self.subtitle_status.setText(f"Full ASS rendering unavailable; using basic text: {exc}")
            else:
                self.external_subtitle_path = path
                self.ass_renderer = renderer
                self.ass_timer.start()
                self.subtitle_status.setText(f"Using {path.name} • full ASS styling")
                self._update_ass_subtitle(self.player.time())
                return
        try:
            cues = load_subtitle_file(path)
            if not cues:
                raise ValueError("No readable timed captions were found")
        except Exception as exc:
            self._clear_external_subtitles()
            self.subtitle_status.setText(f"Could not load subtitles: {exc}")
            return
        self.external_subtitle_path = path
        self.external_subtitle_cues = cues
        self.subtitle_status.setText(f"Using {path.name}")
        self._update_external_subtitle(self.player.time())

    def _clear_external_subtitles(self) -> None:
        self.ass_timer.stop()
        if self.ass_renderer is not None:
            self.ass_renderer.close()
            self.ass_renderer = None
        self.external_subtitle_path = None
        self.external_subtitle_cues = []
        if hasattr(self, "video_frame"):
            self.video_frame.clear_subtitle_bitmap()
        if hasattr(self, "external_subtitle_label"):
            self.external_subtitle_label.clear()
            self.external_subtitle_label.hide()
        if hasattr(self, "external_subtitle_top_label"):
            self.external_subtitle_top_label.clear()
            self.external_subtitle_top_label.hide()

    def _update_external_subtitle(self, position: int) -> None:
        if self.ass_renderer is not None:
            self._update_ass_subtitle(position)
            return
        if not hasattr(self, "external_subtitle_label"):
            return
        active = subtitle_texts_at(self.external_subtitle_cues, position - self.subtitle_delay_ms)
        bottom = "\n".join(text for alignment, text in active if alignment in {"bottom", "center"})
        top = "\n".join(text for alignment, text in active if alignment == "top")
        if not bottom and not top:
            self.external_subtitle_label.clear()
            self.external_subtitle_label.hide()
            self.external_subtitle_top_label.clear()
            self.external_subtitle_top_label.hide()
            return
        self.external_subtitle_label.setText(bottom)
        self.external_subtitle_label.setVisible(bool(bottom))
        self.external_subtitle_top_label.setText(top)
        self.external_subtitle_top_label.setVisible(bool(top))
        self._position_player_popups()
        if bottom:
            self.external_subtitle_label.raise_()
        if top:
            self.external_subtitle_top_label.raise_()

    def _update_ass_subtitle(self, position: int) -> None:
        if self.ass_renderer is None or not hasattr(self, "video_frame"):
            return
        content_x, content_y, content_width, content_height = self.video_frame.video_content_rect()
        storage_width, storage_height = self.video_frame.native_video_size()
        try:
            result = self.ass_renderer.render(
                position - self.subtitle_delay_ms,
                content_width,
                content_height,
                storage_width,
                storage_height,
            )
        except Exception as exc:
            self.ass_timer.stop()
            self.video_frame.clear_subtitle_bitmap()
            self.subtitle_status.setText(f"ASS subtitle rendering stopped: {exc}")
            return
        if not result.changed:
            return
        if result.bitmap is None:
            self.video_frame.clear_subtitle_bitmap()
            return
        bitmap = result.bitmap
        image = QImage(
            bitmap.rgba,
            bitmap.width,
            bitmap.height,
            bitmap.width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        self.video_frame.show_subtitle_bitmap(
            QPixmap.fromImage(image),
            content_x + bitmap.x,
            content_y + bitmap.y,
        )

    def _import_subtitles(self) -> None:
        if not self.current_video_path:
            return
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose subtitles for this episode",
            "",
            "Subtitle files (*.srt *.vtt *.ass *.ssa);;All files (*)",
        )
        if not selected:
            return
        try:
            attached = attach_subtitle_file(self.current_video_path, selected)
        except Exception as exc:
            QMessageBox.warning(self, "Could not import subtitles", str(exc))
            return
        self.external_subtitle_path = attached
        self._load_tracks()
        self.subtitle_status.setText(f"Imported {attached.name}")

    def _generate_subtitles(self) -> None:
        if not self.current_episode_id or not self.current_video_path:
            return
        cli = find_whisper_cli(self.db.setting("whisper_cli_path", ""))
        if not cli:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Locate whisper-cli.exe",
                "",
                "Whisper CLI (whisper-cli.exe whisper-cli);;All files (*)",
            )
            if not selected:
                self.subtitle_status.setText("Local Whisper was not found. Install whisper.cpp or choose whisper-cli.exe.")
                return
            cli = Path(selected)
            self.db.set_setting("whisper_cli_path", str(cli))
        model = Path(self.db.setting("whisper_model_path", str(default_whisper_model_path())))
        if model.is_file():
            self._begin_subtitle_generation(self.current_episode_id, Path(self.current_video_path), cli, model)
            return
        answer = QMessageBox.question(
            self,
            "Download local subtitle model?",
            "Generating subtitles needs the official Whisper small model (about 488 MB). "
            "It downloads once, runs locally afterward, and does not upload your video. Download it now?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._set_subtitle_busy(True, "Downloading local Whisper model…")
        worker = Worker(download_whisper_model, model, with_progress=True)
        worker.signals.progress.connect(self._subtitle_progress)
        worker.signals.done.connect(
            lambda downloaded, episode_id=self.current_episode_id, video=Path(self.current_video_path), executable=cli:
                self._subtitle_model_ready(episode_id, video, executable, Path(downloaded))
        )
        worker.signals.failed.connect(self._subtitle_generation_failed)
        self._start_worker(worker)

    def _subtitle_model_ready(self, episode_id: int, video: Path, cli: Path, model: Path) -> None:
        self.db.set_setting("whisper_model_path", str(model))
        self._begin_subtitle_generation(episode_id, video, cli, model)

    def _begin_subtitle_generation(self, episode_id: int, video: Path, cli: Path, model: Path) -> None:
        self._set_subtitle_busy(True, "Preparing audio for local subtitle generation…")
        if self.player.is_playing():
            self.player.toggle()
        output = video.with_name(f"{video.stem}.generated.en.srt")
        worker = Worker(generate_english_subtitles, video, output, cli, model, with_progress=True)
        worker.signals.progress.connect(self._subtitle_progress)
        worker.signals.done.connect(lambda path, expected=episode_id: self._generated_subtitle_ready(expected, Path(path)))
        worker.signals.failed.connect(self._subtitle_generation_failed)
        self._start_worker(worker)

    def _subtitle_progress(self, values) -> None:
        percent, message = values if len(values) >= 2 else (0, str(values[0]) if values else "Working")
        try:
            self.subtitle_status.setText(f"{message}… {percent}%" if percent else f"{message}…")
        except RuntimeError:
            pass

    def _set_subtitle_busy(self, busy: bool, status: str = "") -> None:
        try:
            self.import_subtitles_button.setEnabled(not busy)
            self.generate_subtitles_button.setEnabled(not busy)
            if status:
                self.subtitle_status.setText(status)
        except RuntimeError:
            # The player page can be closed while a local model job finishes.
            pass

    def _generated_subtitle_ready(self, episode_id: int, path: Path) -> None:
        self._set_subtitle_busy(False)
        if episode_id == self.current_episode_id:
            self.external_subtitle_path = path
            self._load_tracks()
            self.subtitle_status.setText(f"English subtitles ready: {path.name}")
        QMessageBox.information(self, "Subtitles ready", f"English subtitles were saved beside the episode:\n{path.name}")

    def _subtitle_generation_failed(self, error: str) -> None:
        if hasattr(self, "import_subtitles_button"):
            self._set_subtitle_busy(False, f"Subtitle generation failed: {error}")
        QMessageBox.warning(self, "Subtitle generation failed", error)

    def _quality_ready(self, token: int, episode_id: int, options: list[dict]) -> None:
        if token != self.quality_probe_token or episode_id != self.current_episode_id:
            return
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        self.quality_map = {}
        if not options:
            self.quality_combo.addItem("Auto (source)")
            self.quality_combo.setEnabled(False)
            self.quality_combo.blockSignals(False)
            return

        best = options[0]
        auto_label = f"Auto ({best['label']})"
        self.quality_map[auto_label] = int(best["episode_id"])
        self.quality_combo.addItem(auto_label)
        if len(options) == 1:
            self.quality_combo.setEnabled(False)
            self.quality_combo.blockSignals(False)
            return
        label_counts: dict[str, int] = defaultdict(int)
        for option in options:
            label_counts[str(option["label"])] += 1
        label_indexes: dict[str, int] = defaultdict(int)
        selected_label = auto_label
        for option in options:
            base_label = str(option["label"])
            label_indexes[base_label] += 1
            label = base_label
            if label_counts[base_label] > 1:
                label = f"{base_label} ({label_indexes[base_label]})"
            self.quality_map[label] = int(option["episode_id"])
            self.quality_combo.addItem(label)
            if int(option["episode_id"]) == self.current_episode_id:
                selected_label = label
        self.quality_combo.setCurrentText(selected_label)
        self.quality_combo.setEnabled(len(options) > 1)
        self.quality_combo.blockSignals(False)

    def _quality_changed(self, label: str) -> None:
        episode_id = self.quality_map.get(label)
        if not episode_id or episode_id == self.current_episode_id:
            return
        self.play_episode(episode_id, self.player.time())

    def _toggle_play(self) -> None:
        if not self.current_episode_id:
            return
        self.player.toggle()
        self.play_button.setText("❚❚" if self.player.is_playing() else "▶")
        self._show_controls()

    def _seek_relative(self, milliseconds: int) -> None:
        if not self.current_episode_id:
            return
        self.player.seek_relative(milliseconds)
        self._show_controls()

    def _set_autoplay(self, enabled: bool) -> None:
        self.autoplay_enabled = bool(enabled)

    def _toggle_player_settings(self, checked: bool) -> None:
        if checked:
            self.player_settings.adjustSize()
            self.player_settings.show()
            self._position_player_popups()
            self.player_settings.raise_()
            if self.skip_intro_button.isVisible():
                self.skip_intro_button.raise_()
            self.hide_timer.stop()
        else:
            self.player_settings.hide()
            self._show_controls()

    def _intro_ready(self, token: int, chapters) -> None:
        if token != self.intro_probe_token:
            return
        self.media_chapters = list(chapters or [])
        self.timeline.set_chapters(self.media_chapters, self.known_duration_ms or self.player.duration())
        self._update_skip_intro(self.player.time())

    def _skip_intro(self) -> None:
        if not self.current_episode_id or not self.active_skip_chapter:
            return
        self.player.seek(self.active_skip_chapter.end_ms)
        self.skip_intro_button.hide()
        self._show_controls()

    def _update_skip_intro(self, position: int) -> None:
        self.active_skip_chapter = next(
            (chapter for chapter in self.media_chapters if chapter.start_ms <= position < chapter.end_ms), None
        )
        if self.current_episode_id and self.active_skip_chapter:
            self.skip_intro_button.setText(f"SKIP {self.active_skip_chapter.kind.upper()}  ››")
            self.skip_intro_button.adjustSize()
            self._position_player_popups()
            self.skip_intro_button.show()
            self.skip_intro_button.raise_()
        else:
            self.skip_intro_button.hide()

    def _position_player_popups(self) -> None:
        if not hasattr(self, "player_controls") or not self.stack.currentWidget():
            return
        page = self.stack.currentWidget()
        controls_top = self.player_controls.y() if self.player_controls.isVisible() else page.height()
        if hasattr(self, "player_settings"):
            self.player_settings.adjustSize()
            anchor = page.mapFromGlobal(self.settings_button.mapToGlobal(QPoint(0, 0)))
            settings_x = max(12, min(anchor.x() + self.settings_button.width() - self.player_settings.width(), page.width() - self.player_settings.width() - 12))
            settings_y = max(12, controls_top - self.player_settings.height() - 12)
            self.player_settings.move(settings_x, settings_y)
        if hasattr(self, "skip_intro_button"):
            if self.player_settings.isVisible():
                skip_x = max(12, self.player_settings.x() - self.skip_intro_button.width() - 18)
            else:
                skip_x = max(12, page.width() - self.skip_intro_button.width() - 24)
            skip_y = max(12, controls_top - self.skip_intro_button.height() - 18)
            self.skip_intro_button.move(skip_x, skip_y)
        if hasattr(self, "external_subtitle_label") and self.external_subtitle_label.isVisible():
            subtitle_width = max(320, min(1000, page.width() - 120))
            subtitle_height = max(
                48,
                self.external_subtitle_label.heightForWidth(subtitle_width),
            )
            self.external_subtitle_label.resize(subtitle_width, subtitle_height)
            subtitle_x = max(12, (page.width() - subtitle_width) // 2)
            subtitle_y = max(12, controls_top - subtitle_height - 22)
            self.external_subtitle_label.move(subtitle_x, subtitle_y)
        if hasattr(self, "external_subtitle_top_label") and self.external_subtitle_top_label.isVisible():
            subtitle_width = max(320, min(1000, page.width() - 120))
            subtitle_height = max(48, self.external_subtitle_top_label.heightForWidth(subtitle_width))
            self.external_subtitle_top_label.resize(subtitle_width, subtitle_height)
            self.external_subtitle_top_label.move(max(12, (page.width() - subtitle_width) // 2), self.player_top.height() + 22)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        video_frame = getattr(self, "video_frame", None)
        if video_frame is not None and watched in (video_frame, video_frame.viewport()):
            if event.type() in (QEvent.Type.Enter, QEvent.Type.MouseMove):
                self._show_controls()
            elif event.type() == QEvent.Type.MouseButtonPress:
                mouse_event = event
                if mouse_event.button() == Qt.MouseButton.LeftButton:
                    self._toggle_play()
                    return True
        return super().eventFilter(watched, event)

    def _show_controls(self) -> None:
        if not hasattr(self, "player_top"):
            return
        self.controls_visible = True
        self.player_top.setVisible(not self.pip_active)
        self.player_controls.show()
        self.player_stack.setCurrentWidget(self.player_overlay)
        self.player_overlay.raise_()
        if self.preview_box.isVisible():
            self.preview_box.raise_()
        if self.player_settings.isVisible():
            self.player_settings.raise_()
        if self.skip_intro_button.isVisible():
            self.skip_intro_button.raise_()
        if hasattr(self, "external_subtitle_label") and self.external_subtitle_label.isVisible():
            self.external_subtitle_label.raise_()
        if hasattr(self, "external_subtitle_top_label") and self.external_subtitle_top_label.isVisible():
            self.external_subtitle_top_label.raise_()
        self.player_overlay.top_height = self.player_top.sizeHint().height()
        self.player_overlay.bottom_height = self.player_controls.sizeHint().height()
        self._position_player_popups()
        if self.player_settings.isVisible():
            self.hide_timer.stop()
        else:
            self.hide_timer.start(3000)

    def _hide_controls(self) -> None:
        if (
            not self.current_episode_id
            or not self.player.is_playing()
            or self.timeline.isSliderDown()
            or self.preview_box.isVisible()
            or self.player_settings.isVisible()
        ):
            return
        self.controls_visible = False
        self.player_top.hide()
        self.player_controls.hide()
        self.player_overlay.top_height = 0
        self.player_overlay.bottom_height = 0
        self.preview_box.hide()

    def _timeline_released(self) -> None:
        duration = self.known_duration_ms or self.player.duration()
        if duration > 0:
            self.player.seek(round(self.timeline.value() / 1000 * duration))
        self._show_controls()

    def _timeline_preview(self, slider_value: int, point: QPoint) -> None:
        if not self.current_video_path:
            return
        self.hide_timer.stop()
        duration = self.known_duration_ms or self.player.duration()
        if duration <= 0:
            return
        target_ms = round(slider_value / 1000 * duration)
        self.preview_time.setText(format_time(target_ms))
        slider_global = self.timeline.mapToGlobal(point)
        local = self.stack.currentWidget().mapFromGlobal(slider_global)
        x = max(0, min(local.x() - self.preview_box.width() // 2, self.stack.currentWidget().width() - self.preview_box.width()))
        y = max(0, self.player_controls.y() - self.preview_box.height() - 8)
        self.preview_box.move(x, y)
        self.preview_box.raise_()
        self.preview_box.show()
        bucket = preview_bucket(target_ms)
        cache = self.data_root / "previews"
        ready = cached_video_preview(self.current_video_path, bucket, cache) or nearest_cached_video_preview(self.current_video_path, bucket, cache)
        if ready:
            self._show_preview_image(ready)
        else:
            self.preview_image.setPixmap(QPixmap())
            self.preview_image.setText("Loading preview…")
        if bucket == self.preview_bucket_requested:
            return
        self.preview_bucket_requested = bucket
        self.preview_target_ms = target_ms
        # Wait until the pointer pauses briefly. This avoids starting a swarm of
        # FFmpeg jobs while the user moves quickly across the timeline.
        self.preview_timer.start(120)

    def _request_preview_generation(self) -> None:
        if not self.current_video_path or not self.preview_box.isVisible():
            return
        self.preview_token += 1
        token = self.preview_token
        worker = Worker(
            lambda path, timestamp, directory: generate_video_preview(
                path, timestamp, directory, width=240, height=136
            ),
            self.current_video_path,
            self.preview_target_ms,
            self.data_root / "previews",
        )
        worker.signals.done.connect(lambda path, expected=token: self._preview_ready(expected, path))
        self._start_worker(worker)

    def _preview_ready(self, token: int, path) -> None:
        if token == self.preview_token and self.preview_box.isVisible():
            self._show_preview_image(Path(path))

    def _show_preview_image(self, path: Path) -> None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return
        self.preview_image.setText("")
        self.preview_image.setPixmap(pixmap.scaled(240, 136, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _hide_preview(self) -> None:
        self.preview_timer.stop()
        self.preview_token += 1
        self.preview_bucket_requested = None
        if hasattr(self, "preview_box"):
            self.preview_box.hide()
        if self.current_episode_id and self.player.is_playing():
            self.hide_timer.start(3000)

    def _change_episode(self, direction: int) -> None:
        if not self.current_episode_id:
            return
        next_episode = self.db.next_episode(self.current_episode_id, direction)
        if not next_episode:
            return
        current = self.db.episode(self.current_episode_id)
        if current and language_switch_required(str(current["language"]), str(next_episode["language"])):
            answer = QMessageBox.question(
                self,
                "Switch language version?",
                f"The next episode is {next_episode['language']}, but you are watching {current['language']}. Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.autoplay_enabled = False
                self.autoplay_check.setChecked(False)
                return
        self.play_episode(int(next_episode["id"]), 0)

    def _player_tick(self) -> None:
        if not self.current_episode_id:
            return
        position = self.player.time()
        duration = self.player.duration() or self.known_duration_ms
        if duration > 0:
            self.known_duration_ms = duration
            if self.timeline.chapter_duration_ms != duration and self.media_chapters:
                self.timeline.set_chapters(self.media_chapters, duration)
            if not self.timeline.isSliderDown():
                self.timeline.setValue(round(position / duration * 1000))
            self.time_label.setText(f"{format_time(position)} / {format_time(duration)}")
        self.play_button.setText("❚❚" if self.player.is_playing() else "▶")
        self._update_skip_intro(position)
        self._update_external_subtitle(position)
        if position - self.last_saved >= 10000:
            self.db.save_progress(self.current_episode_id, position, duration)
            self.last_saved = position
            if duration > 0 and (position / duration >= 0.90 or duration - position < 120000):
                self._sync_anilist_progress(self.current_episode_id)
        if self.autoplay_enabled and duration > 0 and position >= duration - 1500:
            self._change_episode(1)

    def _sync_anilist_progress(self, episode_id: int) -> None:
        episode = self.db.episode(episode_id)
        if not episode:
            return
        series = self.db.get_series(int(episode["series_id"]))
        token = self._anilist_token_value()
        if not series or not series["anilist_id"] or not token:
            return
        synced = self.db.setting("anilist_synced_progress", {})
        if not isinstance(synced, dict):
            synced = {}
        key = str(series["id"])
        progress = int(episode["episode"])
        if int(synced.get(key, 0)) >= progress:
            return
        synced[key] = progress
        self.db.set_setting("anilist_synced_progress", synced)
        list_settings = self.db.setting("anilist_list_settings", {})
        saved = list_settings.get(key, {}) if isinstance(list_settings, dict) else {}
        status = "COMPLETED" if series["release_status"] == "FINISHED" and progress >= max(1, len({int(row['episode']) for row in self.db.episodes(int(series['id']))})) else "CURRENT"
        score = float(saved.get("score", 0)) or None
        worker = Worker(save_list_entry, token, int(series["anilist_id"]), progress, status, score)
        worker.signals.failed.connect(lambda error, sid=int(series["id"]), value=progress: self._anilist_sync_failed(sid, value, error))
        self._start_worker(worker)

    def _anilist_sync_failed(self, series_id: int, progress: int, error: str) -> None:
        synced = self.db.setting("anilist_synced_progress", {})
        if isinstance(synced, dict) and int(synced.get(str(series_id), 0)) == progress:
            synced.pop(str(series_id), None)
            self.db.set_setting("anilist_synced_progress", synced)
        self.db.add_notification("anilist-error", "AniList sync needs attention", error, series_id, f"anilist-error|{series_id}|{progress}|{error}")

    def _save_progress(self, stop: bool) -> None:
        if self.current_episode_id:
            self.db.save_progress(self.current_episode_id, self.player.time(), self.known_duration_ms or self.player.duration())
            if stop:
                self._clear_external_subtitles()
                self.player.stop()
                self.current_episode_id = None
                self.current_video_path = None

    def _toggle_picture_in_picture(self) -> None:
        if not self.current_episode_id:
            return
        if self.pip_active:
            self.pip_active = False
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            self.setMinimumSize(1080, 680)
            self.show()
            if self.pip_restore_geometry is not None:
                self.setGeometry(self.pip_restore_geometry)
            if self.pip_restore_maximized:
                self.showMaximized()
            self.player_top.show()
            self._show_controls()
            return
        self.pip_restore_geometry = self.geometry()
        self.pip_restore_maximized = self.isMaximized()
        if self.isFullScreen():
            self.showNormal()
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or self.screen()
        available = screen.availableGeometry()
        width = min(640, max(480, available.width() // 3))
        height = round(width * 9 / 16)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumSize(480, 270)
        self.setGeometry(available.right() - width - 24, available.bottom() - height - 24, width, height)
        self.show()
        self.pip_active = True
        self.player_top.hide()
        self._show_controls()

    def _toggle_fullscreen(self) -> None:
        if self.pip_active:
            self._toggle_picture_in_picture()
        if self.isFullScreen():
            self.showMaximized() if self.was_maximized else self.showNormal()
        else:
            self.was_maximized = self.isMaximized()
            self.showFullScreen()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "player_controls"):
            QTimer.singleShot(0, self._position_player_popups)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self._toggle_fullscreen()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_progress(stop=True)
        self._clear_external_subtitles()
        self.tray.hide()
        self.player.release()
        self.db.close()
        event.accept()


def run() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Anime Watcher")
    app.setOrganizationName("AnimeWatcher")
    app.setStyle("Fusion")
    window = AnimeWatcherWindow()
    window.show()
    return app.exec()
