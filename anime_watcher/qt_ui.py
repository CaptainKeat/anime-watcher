from __future__ import annotations

import faulthandler
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
import webbrowser
from collections import defaultdict
from functools import partial
from pathlib import Path
from typing import Callable
from shiboken6 import isValid

from . import __version__
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QRect, QRunnable, QSignalBlocker, QSize, QSizeF, QThreadPool, QTimer, Qt, QVariantAnimation, Signal
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
    QGraphicsOpacityEffect,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QKeySequenceEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QSystemTrayIcon,
)

from .ass_renderer import LibassRenderer, capped_ass_frame_size
from .anilist import calendar_schedule, current_airing_schedule, release_schedule, save_list_entry, search_anime, viewer
from .release_calendar import ReleaseCalendar
from .database import LibraryDatabase
from .downloader import CatalogResult, EpisodeResult, download_authorized_file, is_wco_url, load_catalog_episodes, search_catalog
from .download_queue import DownloadJob, DownloadQueue, FINISHED
from .wco import batch_episodes, library_status, library_title
from .library_actions import LANGUAGES, move_episode_bundle, move_library_episode, move_library_episodes, plan_library_episode_moves, plan_episode_version_update, update_episode_version, rename_episode_file, rename_series_files, rollback_series_files, send_to_recycle_bin
from .keybindings import KEYBINDING_ACTIONS, duplicate_keybindings, merged_keybindings
from .media_chapters import MediaChapter, probe_chapter_ranges
from .media_quality import probe_quality_sources, probe_video_size, quality_label
from .feature_widgets import FileDropPanel, DownloadJobFrame, ImportReviewDialog, PlaylistReviewDialog
from .import_review import ImportEntry, import_reviewed, suggested_imports
from .library_tools import up_next, remember_catalog, season_completeness, backup_library, backup_directory, inspect_backup, restore_library
from .metadata import fetch_metadata
from .organizer import VIDEO_EXTENSIONS, scan_video_files
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
    episode_watch_progress,
    choose_episode_variant,
    episode_language_options,
    format_time,
    language_switch_required,
    library_root_from_setting,
    resource_path,
)
from .youtube import download_youtube_video, fetch_youtube_thumbnail, youtube_video_url, youtube_playlist_url, preview_youtube_playlist
from .youtube_library import read_youtube_metadata, series_snapshot, suggested_slot, video_title
from .updater import (
    GITHUB_RELEASES_URL,
    application_install_dir,
    fetch_latest_release,
    is_newer_version,
    launch_staged_update,
    mark_update_receipt_reported,
    read_update_receipt,
    stage_update,
)


BG = "#090b10"
PANEL = "#11151d"
PANEL_2 = "#181e29"
TEXT = "#f5f7fb"
MUTED = "#9aa4b3"
ACCENT = "#8b5cf6"
PINK = "#ec4899"
CHECK_MARK = resource_path("assets", "checkbox-check.svg").as_posix()


APP_STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: 'Segoe UI'; font-size: 13px; }}
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
QTabWidget#wcoEpisodeTabs::pane {{ border: 1px solid #3a3158; border-radius: 8px; }}
QTabBar#wcoVersionTabs::tab, QTabBar#libraryCategoryTabs::tab {{ background: {PANEL_2}; color: {MUTED}; border: 1px solid #303849; border-bottom: 3px solid transparent; border-top-left-radius: 8px; border-top-right-radius: 8px; padding: 11px 22px; margin-right: 6px; min-width: 90px; font-weight: 800; }}
QTabBar#wcoVersionTabs::tab:hover:!selected, QTabBar#libraryCategoryTabs::tab:hover:!selected {{ background: #283142; color: {TEXT}; }}
QTabBar#wcoVersionTabs::tab:selected, QTabBar#libraryCategoryTabs::tab:selected {{ background: #6d28d9; color: white; border-color: #a78bfa; border-bottom: 3px solid {PINK}; }}
QCheckBox#wcoEpisodeSelect::indicator, QCheckBox#wcoSkipExisting::indicator {{ width: 16px; height: 16px; border: 1px solid {MUTED}; border-radius: 3px; background: {PANEL_2}; }}
QCheckBox#wcoEpisodeSelect::indicator:checked, QCheckBox#wcoSkipExisting::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("{CHECK_MARK}"); }}
QCheckBox#wcoEpisodeSelect::indicator:disabled {{ border-color: #3a404b; background: {BG}; }}
QSlider::groove:horizontal {{ height: 5px; background: #3a404b; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {PINK}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 15px; margin: -5px 0; background: {PINK}; border-radius: 7px; }}
QProgressBar {{ background: #343b49; border: 0; border-radius: 3px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {PINK}; border-radius: 3px; }}
QProgressBar#episodeWatchProgress {{ background: #2b3241; border: 0; border-radius: 3px; }}
QProgressBar#episodeWatchProgress::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QProgressBar#episodeWatchProgress[watchState="Completed"]::chunk {{ background: #35c779; }}
QFrame#downloadJob QLabel {{ background: transparent; }}
QFrame#downloadJob[downloadStatus="Completed"] {{ background: #142d24; border: 1px solid #275e46; }}
QFrame#downloadJob[downloadStatus="Failed"], QFrame#downloadJob[downloadStatus="Needs attention"] {{ background: #361c26; border: 1px solid #94414f; }}
QProgressBar#downloadProgress[downloadStatus="Completed"]::chunk {{ background: #35c779; }}
QProgressBar#downloadProgress[downloadStatus="Failed"] {{ background: #632e3c; }}
QProgressBar#downloadProgress[downloadStatus="Failed"]::chunk {{ background: #ef596b; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid #333a48; }}
"""


class WorkerSignals(QObject):
    metadata = Signal(object)
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


class SeriesCardLayout(QLayout):
    """Wrap existing cards against the available width, including inside scroll areas."""

    def __init__(self):
        super().__init__()
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(14)

    def addItem(self, item):
        self._items.append(item)
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            self.invalidate()
            return item
        return None

    def expandingDirections(self):
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self):
        return True

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def sizeHint(self):
        return self.minimumSize()

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def _arrange(self, rect, *, apply):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        if not self._items:
            return margins.top() + margins.bottom()
        width = max(item.sizeHint().width() for item in self._items)
        height = max(max(item.sizeHint().height(), item.heightForWidth(width)) for item in self._items)
        spacing = self.spacing()
        columns = max(1, (area.width() + spacing) // (width + spacing))
        if apply:
            for index, item in enumerate(self._items):
                row, column = divmod(index, columns)
                item.setGeometry(QRect(area.x() + column * (width + spacing), area.y() + row * (height + spacing), width, height))
        rows = (len(self._items) + columns - 1) // columns
        return rows * height + (rows - 1) * spacing + margins.top() + margins.bottom()


class DownloadFlyout(QLabel):
    """Brief, click-through feedback inside the current Downloads page."""

    def __init__(self, start: QPoint, destination: QPoint, parent: QWidget):
        super().__init__("↓", parent)
        self.setObjectName("downloadFlyout")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(32, 32)
        self.setStyleSheet("background:#6d28d9;color:white;border:1px solid #c4b5fd;border-radius:16px;font-size:23px;font-weight:800;")
        self.opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self.start_point, self.destination = start, destination
        self.control = QPoint((start.x() + destination.x()) // 2,
                              max(16, min(start.y(), destination.y()) - 48))
        self.easing = QEasingCurve(QEasingCurve.Type.OutCubic)
        self.timeline = QVariantAnimation(self)
        self.timeline.setDuration(720)
        self.timeline.setStartValue(0.0)
        self.timeline.setEndValue(1.0)
        self.timeline.valueChanged.connect(self._frame)
        self.timeline.finished.connect(self.deleteLater)
        self._frame(0.0)
        self.show()
        self.raise_()
        self.timeline.start()

    def _frame(self, value):
        progress = self.easing.valueForProgress(min(float(value) / 0.78, 1.0))
        remaining = 1.0 - progress
        x = remaining ** 2 * self.start_point.x() + 2 * remaining * progress * self.control.x() + progress ** 2 * self.destination.x()
        y = remaining ** 2 * self.start_point.y() + 2 * remaining * progress * self.control.y() + progress ** 2 * self.destination.y()
        self.move(round(x) - 16, round(y) - 16)
        self.opacity.setOpacity(min(1.0, max(0.0, (1.0 - float(value)) / 0.22)))


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
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        self.setStyleSheet("background:black;border:0;")
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(33)
        self._resize_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._resize_timer.timeout.connect(self._apply_viewport_size)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_timer.start()

    def _apply_viewport_size(self) -> None:
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
        self.youtube_jobs = {}
        self.youtube_message = "Add videos here. Follow progress and cancel individual videos in the Downloads tab."
        self.youtube_last_url = ""
        self.youtube_last_quality = "best"
        self.youtube_last_target = None
        self.youtube_last_season = 0
        self.youtube_last_episode = 0
        self._youtube_page = None
        self._closing = False
        self.import_job = None
        self.import_message = ''
        self.playlist_request = None
        self.backup_message = ''
        self.setAcceptDrops(True)
        self.download_queue = DownloadQueue(self)
        saved_limit = self.db.setting("download_parallel", 3)
        if isinstance(saved_limit, int) and 1 <= saved_limit <= 6:
            self.download_queue.limit = saved_limit
        self.download_queue.changed.connect(self._download_queue_changed)
        self._download_rows = {}
        self._download_artwork_rows = {}
        self.download_metadata = {}
        self.download_metadata_attempted = set()
        self.download_metadata_pending = {}
        self.catalog_artwork_rows = {}
        self.catalog_artwork_pending = {}
        self.catalog_artwork_cache = {}
        self.library_refresh_job = None
        self.library_refresh_messages = {}
        self.metadata_lookup_in_progress = False
        self._download_page = None
        self.wco_downloads = {}
        self._restore_download_history()
        self.wco_download_timer = QTimer(self)
        self.wco_download_timer.setInterval(300)
        self.wco_download_timer.timeout.connect(self._poll_wco_downloads)
        self.wco_download_timer.start()
        self.download_snapshot_timer = QTimer(self)
        self.download_snapshot_timer.setInterval(3000)
        self.download_snapshot_timer.timeout.connect(self._save_download_snapshot)
        self.download_snapshot_timer.start()
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
        self.catalog_quality_cache = {}
        self.catalog_quality_groups = {}
        self.catalog_quality_probe = None
        self.catalog_quality_timer = QTimer(self)
        self.catalog_quality_timer.setInterval(1000)
        self.catalog_quality_timer.timeout.connect(self._catalog_quality_tick)
        self.catalog_quality_timer.start()
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
        self.metadata_attempted: set[tuple[Path, int]] = set()
        self.available_app_update = None
        self.staged_app_update = None
        self.app_update_check_in_progress = False
        self.app_update_download_in_progress = False
        self.app_update_percent = 0
        self.app_update_phase = ""
        self.app_update_message = ""
        self._app_update_checked_this_session = False
        self._app_update_retry_at = 0.0
        self.calendar_requests = set()
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
        self.player_layout_timer = QTimer(self)
        self.player_layout_timer.setSingleShot(True)
        self.player_layout_timer.setInterval(33)
        self.player_layout_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self.player_layout_timer.timeout.connect(self._position_player_popups)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._request_preview_generation)
        self.ass_timer = QTimer(self)
        self.ass_timer.setInterval(50)
        self.ass_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self.ass_timer.timeout.connect(lambda: self._update_ass_subtitle(self.player.time()))
        self.show_home()
        self._download_queue_changed("")
        QTimer.singleShot(900, self._auto_metadata)
        QTimer.singleShot(1800, self._refresh_release_schedule)
        QTimer.singleShot(2500, self._report_pending_app_update)
        QTimer.singleShot(5000, self._auto_check_for_app_update)
        self.backup_timer = QTimer(self)
        self.backup_timer.timeout.connect(self._automatic_library_backup)
        self.backup_timer.start(30 * 60 * 1000)
        QTimer.singleShot(10000, self._automatic_library_backup)
        self.app_update_timer = QTimer(self)
        self.app_update_timer.setInterval(15 * 60 * 1000)
        self.app_update_timer.timeout.connect(self._auto_check_for_app_update)
        self.app_update_timer.start()

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
        warning = QPixmap(32, 32)
        warning.fill(Qt.GlobalColor.transparent)
        painter = QPainter(warning)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ef4444"))
        painter.drawEllipse(1, 1, 30, 30)
        painter.setPen(QColor("white"))
        font = painter.font(); font.setPixelSize(24); font.setBold(True)
        painter.setFont(font)
        painter.drawText(warning.rect(), Qt.AlignmentFlag.AlignCenter, "!")
        painter.end()
        self.download_failure_icon = QIcon(warning)
        for text, callback in [
            ("⌂   Home", self.show_home), ("▥   Library", self.show_library),
            ("▶   Continue", self.show_continue), ("＋   Import", self.show_import),
            ("↓   Downloads", self.show_downloads), ("≡   Files", self.show_file_manager),
            ("▦   Schedule", self.show_schedule), ("⚙   Settings", self.show_settings),
        ]:
            button = QPushButton(text)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(callback)
            layout.addWidget(button)
            self.nav_buttons.append(button)
        layout.addStretch(1)
        self.sidebar_update_button = QPushButton("↓  Update available")
        self.sidebar_update_button.setObjectName("appUpdateNotice")
        self.sidebar_update_button.setStyleSheet(
            "QPushButton{background:#3b82f6;color:white;border:1px solid #60a5fa;"
            "border-radius:12px;padding:11px 8px;font-weight:800;}"
            "QPushButton:hover{background:#2563eb;}"
            "QPushButton:disabled{background:#244c86;color:#dbeafe;border-color:#3b66a2;}"
        )
        self.sidebar_update_button.clicked.connect(lambda: self._start_app_update_download())
        self.sidebar_update_button.hide()
        layout.addWidget(self.sidebar_update_button)
        self.sidebar_update_progress = QProgressBar()
        self.sidebar_update_progress.setFixedHeight(8)
        self.sidebar_update_progress.setTextVisible(False)
        self.sidebar_update_progress.setStyleSheet("QProgressBar::chunk{background:#60a5fa;}")
        self.sidebar_update_progress.hide()
        layout.addWidget(self.sidebar_update_progress)
        self.sidebar_update_status = QLabel()
        self.sidebar_update_status.setWordWrap(True)
        self.sidebar_update_status.setMaximumHeight(48)
        self.sidebar_update_status.setStyleSheet(f"color:{MUTED};font-size:10px;")
        self.sidebar_update_status.hide()
        layout.addWidget(self.sidebar_update_status)
        layout.addSpacing(8)
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
        if getattr(self, "catalog_quality_groups", None):
            self.catalog_quality_groups.clear()
            self._cancel_catalog_quality_probe()
        if self.current_episode_id and not player:
            self._save_progress(stop=True)
        if player:
            self.player_page = page
            page.installEventFilter(self)
        else:
            self.player_page = None
        old = self.stack.currentWidget()
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()
        self.sidebar.setVisible(not player)
        if player:
            self.player_layout_timer.start()
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
        scaled = pixmap.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        return scaled.copy(max(0, (scaled.width() - width) // 2), max(0, (scaled.height() - height) // 2), width, height)

    def _series_card(self, series) -> ClickableFrame:
        card = ClickableFrame()
        card.setProperty("class", "card")
        youtube = series["library_type"] == "YouTube"
        width, height = (288, 162) if youtube else (180, 255)
        card.setFixedWidth(width + 16)
        card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 12)
        poster = QLabel()
        poster.setObjectName("seriesThumbnail")
        poster.setPixmap(self._poster(series["poster_path"], width, height))
        poster.setFixedSize(width, height)
        poster.setScaledContents(True)
        layout.addWidget(poster)
        title = QLabel(series["display_title"] or series["title"])
        title.setWordWrap(True)
        title.setStyleSheet("font-weight:700;")
        layout.addWidget(title)
        unit = "video" if youtube else "episode"
        count = QLabel(f"{series['episode_count']} {unit}{'' if series['episode_count'] == 1 else 's'}")
        count.setStyleSheet(f"color:{MUTED};")
        layout.addWidget(count)
        card.clicked.connect(lambda sid=int(series["id"]): self.show_series(sid))
        return card

    def show_home(self) -> None:
        if self.current_episode_id:
            self._save_progress(stop=True)
        page, outer = self._page("Welcome back")
        series = self.db.series()
        continues = self.db.continue_watching(8)
        outer.addWidget(QLabel(f"{len(series)} series • {sum(row['episode_count'] for row in series)} episodes ready"))
        scroll, _, body = self._scroll()
        if continues:
            label = QLabel("Continue watching")
            label.setStyleSheet("font-size:20px;font-weight:700;")
            body.addWidget(label)
            row = SeriesCardLayout()
            for episode in continues[:4]:
                button = QPushButton(f"{episode['series_title']}\nS{episode['season']:02d} • Episode {episode['episode']} • {episode['language']}\n{format_time(episode['progress_ms'])} / {format_time(episode['duration_ms'])}")
                button.setMinimumSize(230, 105)
                button.setFixedWidth(230)
                button.clicked.connect(lambda _=False, eid=int(episode["id"]): self.play_episode(eid))
                row.addWidget(button)
            body.addLayout(row)
        upcoming = up_next(self.db)[:12]
        if upcoming:
            label = QLabel('Up next'); label.setStyleSheet('font-size:20px;font-weight:700;')
            body.addWidget(label)
            next_row = SeriesCardLayout()
            series_by_id = {int(item['id']): item for item in series}
            for episode in upcoming:
                item = series_by_id[int(episode['series_id'])]
                youtube = item['library_type'] == 'YouTube'
                width, height = (230, 129) if youtube else (180, 255)
                card = ClickableFrame()
                card.setObjectName('upNextCard')
                card.setProperty('class', 'card')
                card.setFixedWidth(246)
                card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                layout = QVBoxLayout(card)
                layout.setContentsMargins(8, 8, 8, 12)
                thumbnail = QLabel()
                thumbnail.setObjectName('upNextThumbnail')
                thumbnail.setPixmap(self._poster(item['poster_path'], width, height))
                thumbnail.setFixedSize(230, 255)
                thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(thumbnail)
                title = QLabel(item['display_title'] or episode['series_title'])
                title.setWordWrap(True)
                title.setStyleSheet('font-weight:700;')
                title.setMinimumHeight(36)
                layout.addWidget(title)
                details = QLabel(f"Season {episode['season']} · Episode {episode['episode']} · {episode['language']}")
                details.setWordWrap(True)
                details.setStyleSheet(f'color:{MUTED};')
                layout.addWidget(details)
                button = QPushButton('▶  Play')
                button.setObjectName('upNextEpisode'); button.setProperty('episodeId', int(episode['id']))
                button.clicked.connect(lambda _=False, eid=int(episode['id']): self.play_episode(eid))
                card.clicked.connect(lambda eid=int(episode['id']): self.play_episode(eid))
                layout.addWidget(button)
                next_row.addWidget(card)
            body.addLayout(next_row)
        body.addStretch(1)
        outer.addWidget(scroll, 1)
        self._set_page(page, 0)

    def show_library(self) -> None:
        page, outer = self._page("Library", "Every series, season, and episode in one place")
        self._library_page = page
        search = QLineEdit()
        search.setObjectName("librarySearch")
        search.setPlaceholderText("Search your library…")
        self._library_search = search
        controls = QHBoxLayout(); controls.addWidget(search, 1)
        refresh = QPushButton("Refresh library"); refresh.setObjectName("refreshLibrary")
        refresh.setToolTip("Rescan the library folder after adding, moving, or removing files outside the app.")
        refresh.clicked.connect(self._refresh_library)
        self._library_refresh_button = refresh
        controls.addWidget(refresh); outer.addLayout(controls)
        self._library_refresh_label = QLabel(); self._library_refresh_label.setObjectName("libraryRefreshStatus")
        self._library_refresh_label.setWordWrap(True); self._library_refresh_label.setStyleSheet(f"color:{MUTED};")
        outer.addWidget(self._library_refresh_label)
        tabs = QTabWidget(); tabs.setObjectName("libraryTabs")
        tabs.tabBar().setObjectName("libraryCategoryTabs")
        self._library_tabs = tabs
        grids = {}
        for category in ("Anime", "YouTube"):
            scroll, _, body = self._scroll()
            grid = SeriesCardLayout(); grids[category] = grid
            body.addLayout(grid); body.addStretch(1)
            tabs.addTab(scroll, category)
        tabs.setCurrentIndex(1 if self.db.setting("library_tab", "Anime") == "YouTube" else 0)
        tabs.currentChanged.connect(lambda index: self.db.set_setting("library_tab", "YouTube" if index == 1 else "Anime"))

        def render(text: str) -> None:
            for category, grid in grids.items():
                clear_layout(grid)
                rows = self.db.series(text, library_type=category)
                for item in rows:
                    grid.addWidget(self._series_card(item))
                if not rows:
                    message = "No matching anime found." if category == "Anime" else "No YouTube series found. Import with the YouTube checkbox, or open an existing series and choose Move to YouTube."
                    empty = QLabel(message); empty.setWordWrap(True); grid.addWidget(empty)

        search.textChanged.connect(render)
        self._library_render = render
        render("")
        outer.addWidget(tabs, 1)
        self._set_page(page, 1)
        self._refresh_library_controls()

    def _refresh_library_controls(self):
        if self._closing or self.stack.currentWidget() is not getattr(self, "_library_page", None):
            return
        key = (self.db.path, self.library_root)
        busy = self.library_refresh_job == key
        self._library_refresh_button.setText("Refreshing…" if busy else "Refresh library")
        self._library_refresh_button.setEnabled(self.library_root is not None and self.library_refresh_job is None)
        self._library_refresh_label.setText("Scanning your library folder…" if busy else self.library_refresh_messages.get(key, "") if self.library_root else "Choose a library folder in Settings first.")

    @staticmethod
    def _prepare_library_refresh(database, root):
        owner = LibraryDatabase(database)
        try:
            if library_root_from_setting(owner.setting("library_root", "")) != root:
                raise ValueError("The library folder changed. Refresh the new folder instead.")
            return owner.prepare_library_scan(root, strict=True)
        finally:
            owner.close()

    def _refresh_library(self):
        if self._closing or self.import_job is not None or self.library_refresh_job is not None or self.library_root is None:
            return
        key = (self.db.path, self.library_root)
        self.library_refresh_job = key
        self._refresh_library_controls()
        worker = Worker(self._prepare_library_refresh, *key)
        worker.signals.done.connect(lambda prepared: self._library_refresh_ready(key, prepared))
        worker.signals.failed.connect(lambda error: self._library_refresh_finished(key, f"Refresh failed: {error}"))
        self._start_worker(worker)

    def _library_refresh_ready(self, key, prepared):
        if self._closing:
            return
        database, root = key
        owner = None
        try:
            owner = self.db if database == self.db.path else LibraryDatabase(database) if database.is_file() else None
            if owner is None or library_root_from_setting(owner.setting("library_root", "")) != root:
                return self._library_refresh_finished(key, "Library folder changed; refresh skipped.")
            if not root.is_dir():
                raise FileNotFoundError("The library folder is unavailable. Reconnect the drive and try again.")
            with owner.connection:
                stats = owner.scan_library(root, prepared=prepared)
            message = f"Library refreshed — {stats['files']} episodes found. Removed {stats['removed']} missing {'entry' if stats['removed'] == 1 else 'entries'}."
        except (OSError, sqlite3.Error, ValueError) as exc:
            message = f"Refresh failed: {exc}"
        finally:
            if owner is not None and owner is not self.db:
                owner.close()
        self._library_refresh_finished(key, message)
        if key == (self.db.path, self.library_root):
            if self.stack.currentWidget() is getattr(self, "_library_page", None):
                self._library_render(self._library_search.text())
            QTimer.singleShot(0, self._auto_metadata)

    def _library_refresh_finished(self, key, message):
        if self._closing:
            return
        self.library_refresh_job = None
        self.library_refresh_messages[key] = message
        self._refresh_library_controls()

    def show_series(self, series_id: int) -> None:
        series = self.db.get_series(series_id)
        if not series:
            return self.show_library()
        # Save the final position before rendering when returning from playback.
        if self.current_episode_id:
            self._save_progress(stop=True)
        self.visible_series_id = series_id
        page, outer = self._page(series["display_title"] or series["title"], "Choose an episode or continue where you left off")
        self._series_page = page
        youtube = series["library_type"] == "YouTube"
        top = QHBoxLayout()
        poster = QLabel()
        poster.setObjectName("seriesDetailThumbnail")
        width, height = (320, 180) if youtube else (220, 310)
        poster.setPixmap(self._poster(series["poster_path"], width, height))
        poster.setFixedSize(width, height)
        poster.setScaledContents(True)
        cover = QVBoxLayout()
        cover.addWidget(poster)
        year = QLabel(str(series["release_year"]) if series["release_year"] else "Year unavailable")
        year.setObjectName("seriesReleaseYear")
        year.setAlignment(Qt.AlignmentFlag.AlignCenter)
        year.setStyleSheet(f"color:{MUTED};font-weight:700;")
        cover.addWidget(year)
        cover.addStretch(1)
        top.addLayout(cover)
        details = QVBoxLayout()
        synopsis = QLabel(series["synopsis"] or ("YouTube thumbnails and descriptions are saved with downloads." if youtube else "No details yet. Grab details and thumbnail when you are online."))
        synopsis.setWordWrap(True)
        synopsis.setAlignment(Qt.AlignmentFlag.AlignTop)
        details.addWidget(synopsis)
        actions = QHBoxLayout()
        rename = QPushButton("Rename series" if youtube else "Rename anime")
        rename.clicked.connect(lambda: self._rename_series(series_id))
        metadata = QPushButton("Grab details and thumbnail")
        metadata.clicked.connect(lambda: self._refresh_metadata(series_id))
        anilist = QPushButton("Relink AniList" if series["anilist_id"] else "Link AniList")
        anilist.clicked.connect(lambda: self._link_anilist(series_id))
        actions.addWidget(rename)
        if not youtube:
            actions.addWidget(metadata)
            actions.addWidget(anilist)
        else:
            metadata.deleteLater(); anilist.deleteLater()
            thumbnail = QPushButton("Grab YouTube thumbnail")
            thumbnail.setObjectName("grabYouTubeThumbnail")
            thumbnail.setEnabled(bool(self._youtube_series_info(series_id)))
            thumbnail.setToolTip("Use the YouTube source information saved with this series's downloads.")
            thumbnail.clicked.connect(lambda: self._refresh_youtube_series_thumbnail(series_id))
            actions.addWidget(thumbnail)
        category = QPushButton("Move to Anime" if youtube else "Move to YouTube")
        category.setObjectName("moveLibraryTab")
        category.setToolTip("Move this entire series to the other library tab. Files and watch progress stay in place.")
        category.clicked.connect(lambda: self._move_series_library_tab(series_id, "Anime" if youtube else "YouTube"))
        actions.addWidget(category)
        if series["anilist_id"] and not youtube:
            list_settings = QPushButton("AniList list settings")
            list_settings.clicked.connect(lambda: self._edit_anilist_entry(series_id))
            actions.addWidget(list_settings)
        actions.addStretch(1)
        details.addLayout(actions)
        if series["anilist_id"] and not youtube:
            schedule = "AniList linked"
            if series["next_airing_episode"] and series["next_airing_at"]:
                schedule += f" • Episode {series['next_airing_episode']} airs {time.strftime('%b %d, %Y %I:%M %p', time.localtime(series['next_airing_at']))}"
            schedule_label = QLabel(schedule)
            schedule_label.setStyleSheet(f"color:{MUTED};")
            details.addWidget(schedule_label)
        details.addStretch(1)
        top.addLayout(details, 1)
        outer.addLayout(top)

        bulk_controls = QHBoxLayout()
        bulk_move = QPushButton("Move episodes…"); bulk_move.setObjectName("bulkMoveSeries")
        bulk_move.clicked.connect(lambda: self._bulk_move_episodes([int(row["id"]) for row in self.db.episodes(series_id)]))
        bulk_controls.addWidget(bulk_move)
        if not youtube:
            completeness = QPushButton('Season completeness'); completeness.setObjectName('seasonCompleteness')
            completeness.clicked.connect(lambda: self._show_season_completeness(series_id))
            bulk_controls.addWidget(completeness)
        bulk_controls.addWidget(QLabel("Move a whole season or selected episodes to another series."))
        bulk_controls.addStretch(1); outer.addLayout(bulk_controls)
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
            progress = episode_watch_progress(variants)
            play_box = QVBoxLayout(); play_box.setSpacing(6)
            play_box.addWidget(play)
            bar = QProgressBar(); bar.setObjectName("episodeWatchProgress")
            bar.setRange(0, 1000); bar.setValue(progress["value"])
            bar.setTextVisible(False); bar.setFixedHeight(7)
            bar.setProperty("watchState", "Completed" if progress["completed"] else "In progress")
            bar.setProperty("season", season); bar.setProperty("episode", number)
            bar.setProperty("sourceEpisodeId", progress["episode_id"])
            bar.setAccessibleName(f"Episode {number} watched progress")
            bar.setToolTip(progress["tooltip"])
            play_box.addWidget(bar)
            watch_status = QLabel(progress["label"]); watch_status.setObjectName("episodeWatchStatus")
            watch_status.setWordWrap(True)
            watch_status.setStyleSheet(f"background:transparent;color:{'#35c779' if progress['completed'] else MUTED};font-size:11px;")
            play_box.addWidget(watch_status)
            row_layout.addLayout(play_box, 1)
            versions = " / ".join(str(v["language"] or "Unknown") for v in variants)
            row_layout.addWidget(QLabel(versions))
            manage = QPushButton("Manage versions")
            manage.clicked.connect(lambda _=False, ids=[int(v["id"]) for v in variants]: self._manage_versions(ids))
            row_layout.addWidget(manage)
            move = QPushButton("Move to series")
            move.clicked.connect(lambda _=False, eid=int(selected["id"]): self._move_episode(eid))
            row_layout.addWidget(move)
            body.addWidget(row)
        body.addStretch(1)
        outer.addWidget(scroll, 1)
        self._set_page(page)

    def _show_season_completeness(self, series_id):
        series = self.db.get_series(series_id)
        if not series:
            return
        dialog = QDialog(self); dialog.setWindowTitle('Season completeness'); dialog.resize(780, 500)
        layout = QVBoxLayout(dialog)
        note = QLabel('Sub and Dub are counted separately. Totals refer to the source episode list last viewed in Find videos; new releases may have appeared since then. Without a source list, only gaps before your highest episode are known.')
        note.setWordWrap(True); layout.addWidget(note)
        scroll, _, body = self._scroll()
        for item in season_completeness(self.db, series_id):
            row = QFrame(); row.setProperty('class', 'panel'); box = QVBoxLayout(row)
            total = str(item['total']) if item['total'] is not None else 'total unknown'
            checked = time.strftime('%b %d, %Y %H:%M', time.localtime(item['checked_at'])) if item['checked_at'] else ''
            missing = ', '.join(str(number) for number in item['missing']) or ('None in the viewed source list' if item['total'] else 'No known gaps')
            label = QLabel(f"Season {item['season']} · {item['language']} · {item['have']} local / {total}\nMissing: {missing}" + (f'\nSource checked {checked}' if checked else ''))
            label.setObjectName('seasonCompletenessStatus'); label.setWordWrap(True); box.addWidget(label)
            download = QPushButton(f"Download missing ({len(item['links'])})")
            download.setObjectName('downloadMissingEpisodes'); download.setEnabled(bool(item['links']))
            download.clicked.connect(lambda _=False, rows=item['links'], dlg=dialog: (dlg.accept(), self._download_missing(series['title'], rows)))
            box.addWidget(download); body.addWidget(row)
        body.addStretch(1); layout.addWidget(scroll, 1)
        find = QPushButton('Find / refresh source episode list')
        find.clicked.connect(lambda: (dialog.accept(), self._find_series_episodes(series['title'])))
        layout.addWidget(find)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(dialog.reject); layout.addWidget(close)
        dialog.exec()

    def _find_series_episodes(self, title):
        self.show_downloads(); self.catalog_query.setText(title)
        if self.search_source.text().strip():
            self._catalog_search()

    def _download_missing(self, title, rows):
        if not self._downloads_allowed():
            return QMessageBox.warning(self, 'Permission required', 'Enable the download-permission checkbox in Downloads first.')
        episodes = [EpisodeResult(row['title'], row['url'], True, int(row['season']), str(row['number']), row['language']) for row in rows]
        self._queue_wco_batch(title, episodes, skip_existing=True)

    def _move_series_library_tab(self, series_id: int, library_type: str) -> None:
        self.db.set_series_library_type(series_id, library_type)
        self.db.set_setting("library_tab", library_type)
        self.show_series(series_id)
        if library_type == "YouTube":
            self._refresh_youtube_series_thumbnail(series_id)

    def _youtube_series_info(self, series_id: int) -> dict:
        episodes = self.db.episodes(series_id)
        for episode in episodes:
            info = read_youtube_metadata(episode["path"])
            if info.get("thumbnail"):
                return info
        paths = {str(episode["path"]).casefold() for episode in episodes}
        for job in self.download_queue.jobs.values():
            if job.database == self.db.path and job.destination and str(job.destination).casefold() in paths:
                info = job.artwork.get("youtube", {})
                if info.get("thumbnail"):
                    return info
        return {}

    def _refresh_youtube_series_thumbnail(self, series_id: int) -> None:
        info = self._youtube_series_info(series_id)
        series = self.db.get_series(series_id)
        if not info or not series or series["library_type"] != "YouTube":
            return
        worker = Worker(fetch_youtube_thumbnail, info["thumbnail"], self.data_root / "youtube-thumbnails")
        worker.signals.done.connect(lambda path, database=self.db.path, expected=series["title"]: self._youtube_series_thumbnail_ready(database, series_id, expected, info, path))
        self._start_worker(worker)

    def _youtube_series_thumbnail_ready(self, database, series_id, expected_title, info, path):
        if self._closing or QPixmap(str(path)).isNull():
            return
        owner = self.db if self.db.path == database else LibraryDatabase(database) if Path(database).is_file() else None
        try:
            series = owner.get_series(series_id) if owner else None
            if not series or series["title"] != expected_title or series["library_type"] != "YouTube":
                return
            date = str(info.get("upload_date") or "")
            year = int(date[:4]) if re.fullmatch(r"\d{8}", date) else series["release_year"]
            owner.update_metadata(series_id, series["display_title"] or series["title"], info.get("description") or series["synopsis"], str(path), None, year)
        except (OSError, sqlite3.Error):
            return
        finally:
            if owner is not None and owner is not self.db:
                owner.close()
        if owner is self.db:
            if self.visible_series_id == series_id and self.stack.currentWidget() is getattr(self, "_series_page", None):
                self.show_series(series_id)
            elif self.stack.currentWidget() is getattr(self, "_library_page", None):
                self._library_render(self._library_search.text())

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
        panel = FileDropPanel(); panel.files_dropped.connect(self._dropped_import)
        panel.setProperty("class", "panel")
        layout = QVBoxLayout(panel)
        label = QLabel('Drop videos or folders here, or choose files below. Review series, season, episode, and Sub/Dub before importing. Choose Replace matching version to upgrade an existing episode and preserve watch progress.')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.import_youtube = QCheckBox("These are YouTube videos — put them in the YouTube library tab")
        self.import_youtube.setObjectName("importYouTube")
        layout.addWidget(self.import_youtube)
        files = QPushButton("Choose episode files")
        folder = QPushButton("Choose a folder")
        files.clicked.connect(self._import_files)
        folder.clicked.connect(self._import_folder)
        layout.addWidget(files)
        layout.addWidget(folder)
        outer.addWidget(panel)
        self.import_status = QLabel(self.import_message or ('Importing and verifying files…' if self.import_job else ''))
        self.import_status.setObjectName('importStatus'); self.import_status.setWordWrap(True)
        outer.addWidget(self.import_status)
        self.import_progress = QProgressBar(); self.import_progress.setTextVisible(False)
        self.import_progress.setRange(0, 0); self.import_progress.setVisible(self.import_job is not None)
        outer.addWidget(self.import_progress)
        self._import_page = page
        outer.addStretch(1)
        self._set_page(page, 3)

    def _import_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose videos", "", "Video files (*.mkv *.mp4 *.webm *.avi *.mov *.m4v);;All files (*)")
        if paths:
            self._organize(paths)

    def _import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder containing videos")
        if folder:
            self._organize(scan_video_files(folder))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.show_import(); self._dropped_import(paths); event.acceptProposedAction()

    def _dropped_import(self, paths):
        files = []
        for path in paths:
            files.extend(scan_video_files(path) if Path(path).is_dir() else [path])
        self._organize(files)

    def _organize(self, paths, replacement_id=None) -> None:
        root = self._require_library()
        if root is None:
            return
        if self.import_job or self.library_refresh_job:
            return QMessageBox.information(self, 'Import busy', 'Wait for the current import or library refresh to finish.')
        entries = suggested_imports(paths)
        if not entries:
            return QMessageBox.information(self, 'No videos', 'No supported video files were selected.')
        youtube = hasattr(self, 'import_youtube') and isValid(self.import_youtube) and self.import_youtube.isChecked()
        if replacement_id is not None:
            old = self.db.episode(replacement_id)
            if not old:
                return
            entries = [ImportEntry(entry.source, old['series_title'], old['season'], old['episode'], old['language'], True, replacement_id) for entry in entries]
            youtube = self.db.get_series(old['series_id'])['library_type'] == 'YouTube'
        dialog = ImportReviewDialog(entries, self.db.series(), youtube=youtube, replacement_id=replacement_id, parent=self)
        dialog.quality_token = 0
        def refresh_qualities():
            dialog.quality_token += 1
            token = dialog.quality_token
            selected = list(enumerate(dialog.reviewed_entries(include_unchecked=True)))
            existing = [dict(row) for row in self.db.connection.execute('SELECT e.*,s.title series_title FROM episodes e JOIN series s ON s.id=e.series_id')]
            worker = Worker(self._review_import_qualities, selected, existing, replacement_id)
            worker.signals.done.connect(lambda result: dialog.show_qualities(result) if isValid(dialog) and dialog.isVisible() and dialog.quality_token == token else None)
            self._start_worker(worker)
        dialog.review_changed.connect(refresh_qualities)
        refresh_qualities()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.review_timer.stop()
            dialog.deleteLater()
            return
        dialog.review_timer.stop()
        reviewed = dialog.reviewed_entries()
        if not reviewed:
            dialog.deleteLater()
            return
        category, recycle = 'YouTube' if dialog.youtube.isChecked() else 'Anime', dialog.recycle.isChecked()
        dialog.deleteLater()
        self._begin_reviewed_import(reviewed, category, recycle)

    @staticmethod
    def _review_import_qualities(entries, existing, replacement_id=None):
        result = {}
        for index, entry in entries:
            width, height = probe_video_size(entry.source)
            old = [row for row in existing if row['series_title'].casefold() == entry.title.casefold()
                   and (row['season'], row['episode'], row['language']) == (entry.season, entry.episode, entry.language)
                   and (replacement_id is None or row['id'] == replacement_id)]
            result[index] = dict(new=quality_label(width, height) if height else 'Unavailable',
                                 old=[quality_label(*probe_video_size(row['path'])) for row in old])
        return result

    @staticmethod
    def _import_owner(database, root, entries, library_type, recycle, progress=None):
        owner = LibraryDatabase(database)
        try:
            if library_root_from_setting(owner.setting('library_root', '')) != root:
                raise ValueError('The original library folder changed. Review the import again.')
            return import_reviewed(owner, root, entries, library_type=library_type, recycle=recycle, progress=progress)
        finally:
            owner.close()

    def _begin_reviewed_import(self, entries, library_type, recycle):
        if self.import_job or self.library_refresh_job or self.library_root is None:
            return
        if self.current_episode_id:
            self._save_progress(stop=True)
        key = (self.db.path, self.library_root)
        self.import_job = key; self.import_message = 'Importing and verifying files…'
        self._render_import_status()
        worker = Worker(self._import_owner, *key, entries, library_type, recycle, with_progress=True)
        worker.signals.progress.connect(lambda values: self._import_progress_changed(key, values))
        worker.signals.done.connect(lambda result: self._import_finished(key, library_type, result))
        worker.signals.failed.connect(lambda error: self._import_finished(key, library_type, None, error))
        try:
            self._start_worker(worker)
        except Exception as exc:
            self._import_finished(key, library_type, None, str(exc))

    def _import_progress_changed(self, key, values):
        if self.import_job == key:
            self.import_message = values[2]; self._render_import_status()

    def _render_import_status(self):
        if not self._closing and self.stack.currentWidget() is getattr(self, '_import_page', None):
            self.import_status.setText(self.import_message)
            self.import_progress.setVisible(self.import_job is not None)

    def _import_finished(self, key, library_type, result, error=''):
        if self._closing or self.import_job != key:
            return
        self.import_job = None
        if error:
            self.import_message = f'Import failed: {error}. Original files were retained.'
        else:
            self.import_message = f"Imported {result['imported']} video(s); upgraded {result['replaced']} version(s)."
            if result['recovery']:
                self.import_message += f" Old copies are recoverable in {result['recovery']}"
            if result['warnings']:
                self.import_message += '\n' + '\n'.join(result['warnings'])
            if key == (self.db.path, self.library_root):
                self.db.set_setting('library_tab', library_type)
                self._automatic_library_backup()
                self._auto_metadata()
                if library_type == 'YouTube':
                    for series in self.db.series(library_type='YouTube'):
                        if not series['poster_path']:
                            self._refresh_youtube_series_thumbnail(series['id'])
        self._render_import_status()

    def _replace_episode(self, episode_id):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Choose higher quality replacement', '', 'Video files (*.mkv *.mp4 *.webm *.avi *.mov *.m4v)')
        if paths:
            self._organize(paths, replacement_id=episode_id)

    def show_downloads(self) -> None:
        self.catalog_token = getattr(self, "catalog_token", 0) + 1
        self.catalog_artwork_rows.clear()
        self.catalog_artwork_pending.clear()
        page, outer = self._page("Downloads", "Find videos and follow your downloads")
        self.download_permission = QCheckBox("I have permission to download the videos I choose — remember for this profile")
        self.download_permission.setChecked(self._downloads_allowed())
        self.download_permission.toggled.connect(lambda checked: self.db.set_setting("download_permission_confirmed", checked))
        outer.addWidget(self.download_permission)
        permission_note = QLabel("Applies to YouTube, WCO, and direct-file downloads. Uncheck to require confirmation again.")
        permission_note.setWordWrap(True)
        permission_note.setStyleSheet(f"color:{MUTED};")
        outer.addWidget(permission_note)
        transfer_settings = QHBoxLayout()
        transfer_settings.addWidget(QLabel("Simultaneous downloads"))
        self.download_parallel = QSpinBox()
        self.download_parallel.setObjectName("downloadParallel")
        self.download_parallel.setRange(1, 6)
        self.download_parallel.setValue(self.download_queue.limit)
        self.download_parallel.setToolTip("Use 1 to give one episode the available bandwidth. More downloads may finish a season sooner. Lowering this lets active downloads finish before starting more.")
        self.download_parallel.valueChanged.connect(self._set_download_limit)
        transfer_settings.addWidget(self.download_parallel)
        transfer_settings.addStretch(1)
        outer.addLayout(transfer_settings)
        self.download_tabs = QTabWidget()
        self.download_tabs.setObjectName("downloadTabs")
        self.download_tabs.currentChanged.connect(lambda _: self._catalog_quality_tick())
        outer.addWidget(self.download_tabs, 1)
        scroll, _, body = self._scroll()
        self.download_tabs.addTab(scroll, "Find videos")
        queue_scroll, _, self.download_queue_layout = self._scroll()
        self.download_tabs.addTab(queue_scroll, "Downloads")
        self._download_rows = {}
        self._download_page = page
        youtube = QFrame()
        youtube.setProperty("class", "panel")
        youtube_form = QVBoxLayout(youtube)
        youtube_title = QLabel("Download a YouTube video")
        youtube_title.setStyleSheet("font-size:20px;font-weight:700;")
        youtube_form.addWidget(youtube_title)
        self.youtube_url = QLineEdit(self.youtube_last_url)
        self.youtube_url.setPlaceholderText("Paste a YouTube video or Shorts link…")
        youtube_form.addWidget(self.youtube_url)
        quality_row = QHBoxLayout()
        quality_row.addWidget(QLabel("Quality"))
        self.youtube_quality = QComboBox()
        for label, value in (("Best available", "best"), ("Up to 1080p", "1080p"), ("Up to 720p", "720p"), ("Up to 480p", "480p")):
            self.youtube_quality.addItem(label, value)
        self.youtube_quality.setCurrentIndex(self.youtube_quality.findData(self.youtube_last_quality))
        quality_row.addWidget(self.youtube_quality, 1)
        youtube_form.addLayout(quality_row)
        target_row = QFormLayout()
        self.youtube_series = QComboBox()
        self.youtube_series.setEditable(True)
        self.youtube_series.addItem("Automatic (match title or channel)", None)
        for series in self.db.series():
            self.youtube_series.addItem(series["display_title"] or series["title"], series["title"])
        if self.youtube_last_target:
            index = self.youtube_series.findData(self.youtube_last_target)
            self.youtube_series.setCurrentIndex(index if index >= 0 else -1)
            if index < 0:
                self.youtube_series.setEditText(self.youtube_last_target)
        self.youtube_series.setToolTip("Choose an existing series, or type a name to create one.")
        target_row.addRow("Add to series", self.youtube_series)
        slot_row = QHBoxLayout()
        self.youtube_season = QSpinBox(); self.youtube_season.setRange(0, 999); self.youtube_season.setSpecialValueText("Auto"); self.youtube_season.setValue(self.youtube_last_season)
        self.youtube_episode = QSpinBox(); self.youtube_episode.setRange(0, 9999); self.youtube_episode.setSpecialValueText("Auto (title or next)"); self.youtube_episode.setValue(self.youtube_last_episode)
        slot_row.addWidget(QLabel("Season")); slot_row.addWidget(self.youtube_season)
        slot_row.addWidget(QLabel("Episode")); slot_row.addWidget(self.youtube_episode)
        target_row.addRow(slot_row)
        youtube_form.addLayout(target_row)
        self.youtube_rights = self.download_permission
        self.youtube_label = QLabel("")
        self.youtube_label.setTextFormat(Qt.TextFormat.PlainText)
        self.youtube_label.setWordWrap(True)
        youtube_form.addWidget(self.youtube_label)
        buttons = QHBoxLayout()
        self.youtube_download_button = QPushButton("Add YouTube video to Downloads")
        self.youtube_download_button.setObjectName("accent")
        self.youtube_download_button.clicked.connect(self._start_youtube_download)
        buttons.addWidget(self.youtube_download_button, 1)
        youtube_form.addLayout(buttons)
        playlist_row = QHBoxLayout()
        self.youtube_playlist = QLineEdit(); self.youtube_playlist.setObjectName('youtubePlaylistUrl')
        self.youtube_playlist.setPlaceholderText('YouTube playlist URL…')
        self.playlist_button = QPushButton('Preview playlist'); self.playlist_button.setObjectName('previewYouTubePlaylist')
        self.playlist_button.clicked.connect(self._preview_playlist)
        playlist_row.addWidget(self.youtube_playlist, 1); playlist_row.addWidget(self.playlist_button)
        youtube_form.addLayout(playlist_row)
        body.addWidget(youtube)
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
        source_row = QHBoxLayout()
        source_row.addWidget(self.search_source, 1)
        wco_preset = QPushButton("Use WCO")
        wco_preset.clicked.connect(lambda: self.search_source.setText("https://www.wco.tv/"))
        source_row.addWidget(wco_preset)
        form.addLayout(source_row)
        query_row = QHBoxLayout()
        query_row.addWidget(self.catalog_query, 1)
        query_row.addWidget(search_button)
        form.addLayout(query_row)
        self.catalog_status = QLabel("")
        self.catalog_status.setStyleSheet(f"color:{MUTED};")
        form.addWidget(self.catalog_status)
        wco_connection = QPushButton("Open WCO browser connection")
        wco_connection.clicked.connect(lambda: self._wco_session().open_connection(self))
        form.addWidget(wco_connection)
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
        self.rights_check = self.download_permission
        self.download_label = QLabel("Follow progress and cancel downloads in the Downloads tab.")
        self.download_label.setWordWrap(True)
        download_button = QPushButton("Download & organize")
        download_button.setObjectName("accent")
        download_button.clicked.connect(self._start_download)
        for widget in (self.download_url, self.download_label, download_button):
            direct_form.addWidget(widget)
        body.addWidget(direct)
        body.addStretch(1)
        self._youtube_page = page
        self._set_page(page, 4)
        self._render_youtube_download()
        self._download_queue_changed("")

    def _downloads_allowed(self):
        return bool(self.db.setting("download_permission_confirmed", False))

    def _set_download_limit(self, limit):
        self.db.set_setting("download_parallel", limit)
        self.download_queue.set_limit(limit)

    def _save_download_snapshot(self):
        rows = []
        for job in self.download_queue.jobs.values():
            row = {"id":job.id,"title":job.title,"source":job.source,"profile":job.profile,
                   "page_url":job.url if job.source in {"WCO", "YouTube"} else None,"status":job.status,"detail":job.detail,
                   "received":job.received,"total":job.total,
                   "owner_database":str(job.database),"library_root":str(job.root),
                   "destination":str(job.destination) if job.destination else None,
                   "retry_data":job.retry_data,"attempt_history":job.attempt_history,"artwork":job.artwork}
            row.update(bytes_per_second=round(job.bytes_per_second), eta_seconds=job.eta_seconds)
            row.update(job.diagnostics)
            runtime = self.wco_downloads.get(job.id)
            if runtime:
                dialog = runtime["dialog"]
                state = getattr(dialog, "media_state", {})
                job.diagnostics = dict(attempt=getattr(dialog,"attempt",1),offered_quality=state.get("choices",[]),
                                       selected_quality=state.get("selected"),requested_quality=getattr(dialog,"requested_quality",None))
                row.update(job.diagnostics)
            rows.append(row)
        try:
            temporary = self.data_root / "download-queue.json.tmp"
            temporary.write_text(json.dumps({"updated_at":time.time(),"paused":self.download_queue.paused,"jobs":rows},indent=2),encoding="utf-8")
            temporary.replace(self.data_root / "download-queue.json")
        except OSError:
            pass  # Diagnostics must not interrupt a download.

    def _restore_download_history(self):
        try:
            payload = json.loads((self.data_root / "download-queue.json").read_text(encoding="utf-8"))
            rows = payload.get("jobs", [])
            self.download_queue.paused = payload.get('paused') is True
            if not isinstance(rows, list):
                return
        except (OSError, ValueError, AttributeError):
            return
        owners = {self.profile_manager.database_path(item.id) for item in self.profile_manager.profiles()}
        roots = {self.db.path: self.library_root}
        for row in rows:
            if not isinstance(row, dict) or row.get("status") not in FINISHED:
                continue
            try:
                profile = next((item for item in self.profile_manager.profiles() if item.name == row.get("profile")), None)
                database = Path(row.get("owner_database") or (self.profile_manager.database_path(profile.id) if profile else self.data_root / "unknown-profile.db"))
                if database not in owners:
                    database = self.data_root / "unknown-profile.db"
                root = row.get("library_root")
                if not root and database in roots:
                    root = roots[database]
                elif not root and database.is_file():
                    owner = LibraryDatabase(database)
                    try:
                        root = owner.setting("library_root", "")
                    finally:
                        owner.close()
                    roots[database] = root
                job = DownloadJob(str(row["title"]), str(row["source"]), str(row.get("page_url") or ""), database,
                                  Path(root or ""), str(row.get("profile", "Unknown")), lambda: None, lambda: None,
                                  id=str(row["id"]), status=row["status"], detail=str(row.get("detail", "")),
                                  received=max(0,int(row.get("received",0))), total=max(0,int(row.get("total",0))))
                job.destination = Path(row["destination"]) if row.get("destination") else None
                job.artwork = row.get("artwork", {}) if isinstance(row.get("artwork"), dict) else {}
                job.attempt_history = row.get("attempt_history", []) if isinstance(row.get("attempt_history", []), list) else []
                job.diagnostics = {key:row[key] for key in ("attempt","offered_quality","selected_quality","requested_quality") if key in row}
                data = row.get("retry_data", {})
                job.retry_data = data if isinstance(data, dict) else {}
                match = re.fullmatch(r"(.*) · S(\d+) · Episode (\d+) · (Dub|Sub|Unknown)", job.title)
                if not data and match:
                    title, season, number, language = match.groups()
                    data = dict(title=title,season=int(season),number=number,language=language,
                                episode_title=f"S{season} · Episode {number} · {language}")
                if job.source == "WCO" and is_wco_url(job.url) and isinstance(data, dict) and all(name in data for name in ("title", "episode_title", "season", "number", "language")):
                    episode = EpisodeResult(str(data["episode_title"]),job.url,True,int(data["season"]),str(data["number"]),str(data["language"]))
                    title = str(data["title"])
                    job.retry_data = data
                    job.start = lambda item=job, ep=episode, name=title: self._start_wco_job(item,ep,name,None,None)
                    job.cancel_action = lambda item=job: self._cancel_wco_job(item.id)
                    job.prepare_action = lambda item=job, ep=episode, name=title: self._prepare_wco_job(item,ep,name,None,None)
                    job.retry_action = lambda item=job: self._retry_wco_job(item)
                elif job.source == "YouTube" and youtube_video_url(job.url) == job.url and job.retry_data.get("quality") in {"best", "1080p", "720p", "480p"}:
                    self._wire_youtube_job(job)
                self.download_queue.jobs[job.id] = job
            except (KeyError, TypeError, ValueError, OSError, sqlite3.Error):
                continue

    def _download_metadata_key(self, job):
        title = str(job.retry_data.get("title") or "").strip()
        return (job.database, job.root, title.casefold()) if title else None

    def _prepare_download_artwork(self, job):
        if job.source == "YouTube":
            return  # Video artwork comes from YouTube, rather than a title search.
        key = self._download_metadata_key(job)
        if key is None and job.destination:
            try:
                relative = job.destination.resolve().relative_to(job.root.resolve())
                if len(relative.parts) >= 3:
                    job.retry_data["title"] = relative.parts[0]
                    key = self._download_metadata_key(job)
            except ValueError:
                pass
        if key is None:
            return
        title = str(job.retry_data["title"])
        if key not in self.download_metadata:
            data = dict(job.artwork)
            owner = self.db if self.db.path == job.database else LibraryDatabase(job.database) if job.database.is_file() else None
            try:
                if owner is None or library_root_from_setting(owner.setting("library_root", "")) != job.root:
                    return
                series = owner.series_for_title(title)
                if series:
                    data.update(poster_path=series["poster_path"], year=series["release_year"])
                    if series["metadata_year_checked"] and series["poster_path"] and Path(series["poster_path"]).is_file():
                        self.download_metadata_attempted.add(key)
            finally:
                if owner is not None and owner is not self.db:
                    owner.close()
            self.download_metadata[key] = data
        job.artwork = {name: self.download_metadata[key].get(name) for name in ("poster_path", "year")}
        if key not in self.download_metadata_attempted:
            self.download_metadata_attempted.add(key)
            if getattr(self, "download_metadata_inflight", None) != key:
                self.download_metadata_pending[key] = title
            QTimer.singleShot(0, self._auto_metadata)

    def _download_metadata_ready(self, key, title, data):
        if self._closing:
            return
        database, root, _ = key
        owner = None
        series = None
        try:
            owner = self.db if self.db.path == database else LibraryDatabase(database) if database.is_file() else None
            if owner is not None and library_root_from_setting(owner.setting("library_root", "")) == root:
                series = owner.series_for_title(title)
                if series and series["library_type"] == "Anime":
                    owner.update_metadata(series["id"], data["title"], data["synopsis"], data["poster_path"], data["id"], data.get("year"))
        except (OSError, sqlite3.Error):
            pass  # Optional artwork must not change a video's download result.
        finally:
            if owner is not None and owner is not self.db:
                owner.close()
        self.download_metadata[key] = data
        self.download_metadata_attempted.add(key)
        self.catalog_artwork_pending.pop(key, None)
        self._render_catalog_artwork(key, data)
        for job in list(self.download_queue.jobs.values()):
            if self._download_metadata_key(job) == key:
                self._download_queue_changed(job.id)
        if owner is self.db and series and self.visible_series_id == series["id"] and self.stack.currentWidget() is getattr(self, "_series_page", None):
            self.show_series(series["id"])

    def _apply_download_metadata(self, database, episode, job):
        if job.source == "YouTube":
            self._apply_youtube_artwork(database, episode, job)
            return
        series = database.get_series(episode["series_id"])
        if series["library_type"] == "YouTube":
            return
        job.retry_data["title"] = series["title"]
        key = self._download_metadata_key(job)
        data = self.download_metadata.get(self._download_metadata_key(job), {})
        if "id" in data and "synopsis" in data:
            try:
                database.update_metadata(episode["series_id"], data["title"], data["synopsis"], data["poster_path"], data["id"], data.get("year"))
            except (OSError, sqlite3.Error):
                pass
        elif not series["metadata_updated"]:
            marker = (database.path, int(series["id"]))
            if marker not in self.metadata_attempted:
                self.metadata_attempted.add(marker)
                if getattr(self, "download_metadata_inflight", None) != key:
                    self.download_metadata_pending[key] = series["title"]
                QTimer.singleShot(0, self._auto_metadata)

    def _apply_youtube_artwork(self, database, episode, job):
        try:
            series = database.get_series(episode["series_id"])
            job.retry_data["title"] = series["title"]
            self.metadata_attempted.add((database.path, int(series["id"])))
            path = job.artwork.get("poster_path")
            if not path or not Path(path).is_file() or series["poster_path"]:
                return
            info = job.artwork.get("youtube", {})
            database.update_metadata(series["id"], series["display_title"] or series["title"],
                                     series["synopsis"] or info.get("description", ""), path,
                                     series["metadata_id"], series["release_year"] or job.artwork.get("year"))
            if database is self.db and self.visible_series_id == series["id"] and self.stack.currentWidget() is getattr(self, "_series_page", None):
                self.show_series(series["id"])
        except (OSError, sqlite3.Error):
            pass

    def _youtube_metadata_update(self, job, info):
        if self._closing:
            return
        job.artwork.setdefault("youtube", {}).update(info)
        date = str(info.get("upload_date") or "")
        if re.fullmatch(r"\d{8}", date):
            job.artwork["year"] = int(date[:4])
        if info.get("title"):
            self.download_queue.update(job.id, title=info["title"])
        url = info.get("thumbnail")
        if url and url != job.artwork.get("thumbnail_requested"):
            job.artwork["thumbnail_requested"] = url
            worker = Worker(fetch_youtube_thumbnail, url, self.data_root / "youtube-thumbnails")
            worker.signals.done.connect(lambda path: self._youtube_thumbnail_ready(job, url, path))
            self._start_worker(worker)

    def _youtube_thumbnail_ready(self, job, url, path):
        if self._closing or job.artwork.get("thumbnail_requested") != url or QPixmap(str(path)).isNull():
            return
        job.artwork["poster_path"] = str(path)
        if job.destination and job.destination.is_file():
            try:
                self._index_download_owner(job, job.destination)
            except (OSError, sqlite3.Error):
                pass
        self._download_queue_changed(job.id)
        self._save_download_snapshot()

    def _download_queue_changed(self, job_id):
        if self._closing:
            return
        count = self.download_queue.remaining_count
        failed_count = self.download_queue.failed_count
        label = "Downloads" + (f" ({count})" if count else "")
        tooltip = f"{self.download_queue.active_count} active · {self.download_queue.queued_count} queued · {failed_count} failed"
        if self.download_queue.verifying_count:
            tooltip += f" · {self.download_queue.verifying_count} of the active downloads importing"
        icon = self.download_failure_icon if failed_count else QIcon()
        button = self.nav_buttons[4]
        button.setText(label if failed_count else "↓   " + label)
        button.setIcon(icon)
        button.setIconSize(QSize(16, 16))
        button.setToolTip(tooltip)
        button.setAccessibleName(f"Downloads. {tooltip}")
        for job in ([self.download_queue.jobs[job_id]] if job_id in self.download_queue.jobs else self.download_queue.jobs.values()):
            try:
                self._prepare_download_artwork(job)
            except (OSError, sqlite3.Error):
                pass
        if self.stack.currentWidget() is not self._download_page:
            return
        self.download_tabs.setTabText(1, label)
        self.download_tabs.setTabIcon(1, icon)
        self.download_tabs.setTabToolTip(1, tooltip)
        ordered_jobs = self.download_queue.display_jobs()
        order = tuple(job.id for job in ordered_jobs)
        if not job_id or job_id not in self._download_rows:
            clear_layout(self.download_queue_layout)
            self._download_rows = {}
            self._download_artwork_rows = {}
            summary = QLabel()
            self.download_queue_layout.addWidget(summary)
            self.download_queue_summary = summary
            toolbar = QWidget(); controls = QHBoxLayout(toolbar); controls.setContentsMargins(0, 0, 0, 0)
            pause = QPushButton('Resume queue' if self.download_queue.paused else 'Pause queue'); pause.setObjectName('pauseDownloadQueue')
            pause.setToolTip('Active transfers finish. Pausing prevents queued downloads from starting.')
            pause.clicked.connect(lambda: self.download_queue.set_paused(not self.download_queue.paused)); controls.addWidget(pause)
            retry_all = QPushButton('Retry all failed'); retry_all.setObjectName('retryAllFailed')
            retry_all.clicked.connect(self._retry_all_failed); controls.addWidget(retry_all)
            clear = QPushButton("Clear finished entries")
            clear.clicked.connect(self.download_queue.clear_finished)
            controls.addWidget(clear); controls.addWidget(QLabel('Drag queued cards to change their order.')); controls.addStretch(1)
            self.download_queue_layout.addWidget(toolbar)
            if not self.download_queue.jobs:
                self.download_queue_layout.addWidget(QLabel("No downloads yet. Find a video to start downloading."))
            for job in ordered_jobs:
                row = DownloadJobFrame(job); row.reordered.connect(self.download_queue.reorder)
                row.setProperty("class", "panel"); row.setObjectName("downloadJob")
                columns = QHBoxLayout(row)
                cover = QVBoxLayout()
                thumbnail = QLabel(); thumbnail.setObjectName("downloadThumbnail")
                thumbnail.setFixedSize(140, 79) if job.source == "YouTube" else thumbnail.setFixedSize(84, 118)
                thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter); thumbnail.setWordWrap(True)
                cover.addWidget(thumbnail)
                year = QLabel(); year.setObjectName("downloadReleaseYear"); year.setAlignment(Qt.AlignmentFlag.AlignCenter)
                year.setStyleSheet(f"color:{MUTED};font-size:11px;")
                cover.addWidget(year); cover.addStretch(1)
                columns.addLayout(cover)
                layout = QVBoxLayout(); columns.addLayout(layout, 1)
                self._download_artwork_rows[job.id] = (thumbnail, year)
                title = QLabel(); title.setTextFormat(Qt.TextFormat.PlainText); title.setWordWrap(True)
                title.setStyleSheet("font-size:16px;font-weight:700;")
                layout.addWidget(title)
                profile = QLabel(f"{job.source} · Profile: {job.profile}")
                profile.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(profile)
                status = QLabel(); status.setTextFormat(Qt.TextFormat.PlainText); status.setWordWrap(True)
                layout.addWidget(status)
                progress = QProgressBar(); progress.setObjectName("downloadProgress"); layout.addWidget(progress)
                buttons = QHBoxLayout()
                cancel = QPushButton("Cancel")
                cancel.clicked.connect(lambda _=False, item=job: self._retry_download(item) if item.status in {"Failed", "Cancelled"} and item.retry_action else self.download_queue.cancel(item.id))
                buttons.addWidget(cancel)
                player = QPushButton("Open player")
                player.clicked.connect(lambda _=False, item=job: item.open_player() if item.open_player else None)
                buttons.addWidget(player)
                buttons.addStretch(1); layout.addLayout(buttons)
                self.download_queue_layout.addWidget(row)
                self._download_rows[job.id] = (title, status, progress, cancel, player)
            self.download_queue_layout.addStretch(1)
            self._download_row_order = order
            job_id = ""
        if order != self._download_row_order:
            for position, job in enumerate(ordered_jobs, start=2):
                row = self._download_rows[job.id][0].parentWidget()
                self.download_queue_layout.insertWidget(position, row)
            self._download_row_order = order
        self.download_queue_summary.setText(('Queue paused · ' if self.download_queue.paused else '') + f"{self.download_queue.transfer_count} active · {self.download_queue.verifying_count} importing · {self.download_queue.queued_count} queued · {failed_count} failed")
        for key in ([job_id] if job_id else list(self._download_rows)):
            widgets = self._download_rows.get(key)
            job = self.download_queue.jobs.get(key)
            if widgets is None or job is None:
                continue
            title, status, progress, cancel, player = widgets
            thumbnail, year = self._download_artwork_rows[key]
            path = str(job.artwork.get("poster_path") or "")
            if thumbnail.property("posterPath") != path:
                thumbnail.setProperty("posterPath", path)
                pixmap = QPixmap(path) if path and Path(path).is_file() else QPixmap()
                if pixmap.isNull():
                    thumbnail.clear(); thumbnail.setText("Thumbnail\nunavailable")
                else:
                    thumbnail.setPixmap(pixmap.scaled(thumbnail.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            year.setText(("Uploaded " if job.source == "YouTube" else "") + str(job.artwork["year"]) if job.artwork.get("year") else "Year unavailable")
            if progress.property("downloadStatus") != job.status:
                row = progress.parentWidget()
                row.setProperty("downloadStatus", job.status)
                progress.setProperty("downloadStatus", job.status)
                for widget in (row, progress):
                    widget.style().unpolish(widget); widget.style().polish(widget); widget.update()
                status.setStyleSheet("color: #86efac;" if job.status == "Completed" else "color: #fda4af;" if job.status in {"Failed", "Needs attention"} else "")
            title.setText(job.title)
            detail = job.detail
            if job.source == "WCO" and job.status == "Downloading":
                runtime = self.wco_downloads.get(key)
                height = getattr(runtime["dialog"], "selected_height", 0) if runtime else 0
                if height:
                    detail = f"{height}p video"
            if job.total:
                detail += f" · {job.received / 1048576:.1f} / {job.total / 1048576:.1f} MB"
            elif job.received:
                detail += f" · {job.received / 1048576:.1f} MB"
            if job.status == "Downloading":
                speed = job.bytes_per_second
                eta = job.eta_seconds
                detail += f" · {speed / 1048576:.2f} MB/s" if speed > 0 else " · Measuring speed…"
                if eta is not None:
                    detail += f" · {format_time(eta * 1000)} remaining"
            if job.destination:
                detail += f"\n{job.destination}"
            status.setText(f"{job.status} · {detail}")
            if job.active and not job.total:
                progress.setRange(0, 0)
            else:
                progress.setRange(0, 1000)
                progress.setValue(1000 if job.status == "Completed" else min(1000, round(job.received / job.total * 1000)) if job.total else 0)
            retryable = job.status in {"Failed", "Cancelled"} and job.retry_action is not None
            cancel.setText("Retry" if retryable else "Cancel")
            cancel.setEnabled(retryable or job.status not in FINISHED | {"Cancelling", "Verifying"})
            player.setVisible(job.open_player is not None and job.status not in FINISHED)

    def _index_download_owner(self, job, destination=None):
        if self._closing:
            return
        if self.db.path == job.database and self.library_root == job.root:
            if destination is not None:
                episode, added = self.db.index_download(destination, job.root, library_type="YouTube" if job.source == "YouTube" else "Anime")
                self._apply_download_metadata(self.db, episode, job)
                if added:
                    self._notify_download_added(self.db, episode)
            else:
                self._scan(False)
        elif job.database.is_file():
            owner = LibraryDatabase(job.database)
            try:
                if library_root_from_setting(owner.setting("library_root", "")) == job.root:
                    if destination is not None:
                        episode, added = owner.index_download(destination, job.root, library_type="YouTube" if job.source == "YouTube" else "Anime")
                        self._apply_download_metadata(owner, episode, job)
                        if added:
                            self._notify_download_added(owner, episode)
                    else:
                        owner.scan_library(job.root)
            finally:
                owner.close()

    def _notify_download_added(self, database, episode):
        if not database.setting("release_notifications_initialized", False):
            database.set_setting("release_notifications_initialized", True)
            return
        language = str(episode["language"] or "Unknown")
        title = f"{episode['series_title']} • {language} episode added"
        body = f"Season {episode['season']}, Episode {episode['episode']} is now in your local library."
        created = database.add_notification(f"local-{language.casefold()}", title, body, int(episode["series_id"]), f"local|{str(episode['path']).casefold()}")
        if created and database is self.db and self.tray.isVisible():
            self.tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 7000)

    def _retry_download(self, job):
        if self._closing or job.status not in {"Failed", "Cancelled"} or job.retry_action is None:
            return
        if self.db.path != job.database or self.library_root != job.root:
            return QMessageBox.warning(self, "Switch profile", f"Switch to the {job.profile} profile and its original library to retry this download.")
        job.retry_action()

    def _retry_all_failed(self):
        if not self._downloads_allowed():
            return QMessageBox.warning(self, 'Permission required', 'Enable the download-permission checkbox first.')
        paused = self.download_queue.paused
        self.download_queue.set_paused(True)
        try:
            for job in list(self.download_queue.jobs.values()):
                if job.status == 'Failed' and job.retry_action and job.database == self.db.path and job.root == self.library_root:
                    self._retry_download(job)
        finally:
            self.download_queue.set_paused(paused)

    def _retry_wco_job(self, job):
        if not self._downloads_allowed():
            return QMessageBox.warning(self, "Permission required", "Check the saved download-permission checkbox at the top of Downloads.")
        runtime = self.wco_downloads.get(job.id)
        if runtime and runtime["dialog"].worker and runtime["dialog"].worker.isRunning():
            runtime["dialog"].worker.finished.connect(lambda: self._retry_download(job))
            return
        self._dispose_wco_job(job)
        if not self.download_queue.retry(job.id):
            QMessageBox.information(self, "Already queued", "Another download of this episode is already queued or active.")

    def _render_youtube_download(self) -> None:
        if self._closing or self.stack.currentWidget() is not self._youtube_page:
            return
        self.youtube_label.setText(self.youtube_message)

    def _start_youtube_download(self) -> None:
        if self._closing:
            return
        if not self._downloads_allowed():
            return QMessageBox.warning(self, "Permission required", "Check the saved download-permission checkbox at the top of Downloads.")
        try:
            url = youtube_video_url(self.youtube_url.text())
        except ValueError as exc:
            return QMessageBox.warning(self, "YouTube link required", str(exc))
        root = self._require_library()
        if root is None:
            return
        existing = self.download_queue.existing("YouTube", url, self.db.path, root)
        if existing:
            self.youtube_message = "This video is already in Downloads. Paste another link to add a different video."
            self._render_youtube_download()
            self._animate_download_to_tab(self.youtube_download_button)
            return existing
        self.youtube_last_quality = self.youtube_quality.currentData()
        if self.youtube_series.currentIndex() == 0 and self.youtube_series.currentText() == self.youtube_series.itemText(0):
            self.youtube_last_target = None
        else:
            self.youtube_last_target = self.youtube_series.currentData() if self.youtube_series.currentText() == self.youtube_series.itemText(self.youtube_series.currentIndex()) else None
            self.youtube_last_target = self.youtube_last_target or self.youtube_series.currentText().strip()
            if not self.youtube_last_target:
                return QMessageBox.warning(self, "Series required", "Choose Automatic, an existing series, or type a new series name.")
        self.youtube_last_season = self.youtube_season.value()
        self.youtube_last_episode = self.youtube_episode.value()
        job = DownloadJob(self.youtube_last_target or "YouTube video", "YouTube", url, self.db.path, root,
                          self.profile_manager.active.name, lambda: None, lambda: None)
        job.retry_data = dict(title=self.youtube_last_target, quality=self.youtube_last_quality,
                              season=self.youtube_last_season or None, episode=self.youtube_last_episode or None)
        self._wire_youtube_job(job)
        self._cancel_catalog_quality_probe()
        self.download_queue.add(job)
        self.youtube_last_url = ""
        self.youtube_url.clear()
        self.youtube_message = "Added to Downloads. Paste another link to add the next video."
        self._render_youtube_download()
        self._animate_download_to_tab(self.youtube_download_button)
        return job

    def _wire_youtube_job(self, job):
        job.start = lambda: self._start_youtube_job(job)
        job.cancel_action = lambda: self._cancel_youtube_job(job)
        job.retry_action = lambda: self._retry_youtube_job(job)

    def _preview_playlist(self):
        if self.playlist_request is not None:
            return
        try:
            url = youtube_playlist_url(self.youtube_playlist.text())
        except ValueError as exc:
            return QMessageBox.warning(self, 'Playlist link required', str(exc))
        key = (self.db.path, self.library_root, self._youtube_page)
        self.playlist_request = key; self.playlist_button.setEnabled(False)
        self.youtube_message = 'Reading playlist titles… No videos are being downloaded yet.'; self._render_youtube_download()
        worker = Worker(preview_youtube_playlist, url)
        worker.signals.done.connect(lambda result: self._playlist_ready(key, result))
        worker.signals.failed.connect(lambda error: self._playlist_ready(key, None, error))
        self._start_worker(worker)

    def _playlist_ready(self, key, result, error=''):
        if self._closing or self.playlist_request != key:
            return
        self.playlist_request = None
        if key != (self.db.path, self.library_root, self.stack.currentWidget()):
            return
        self.playlist_button.setEnabled(True)
        if error:
            self.youtube_message = f'Playlist preview failed: {error}'; self._render_youtube_download(); return
        dialog = PlaylistReviewDialog(result, self.db.series(library_type='YouTube'), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self._queue_youtube_playlist(dialog.selected_videos(), dialog.series.currentText().strip(),
                                             dialog.season.value(), dialog.first.value(), dialog.quality.currentData())
            except ValueError as exc:
                return QMessageBox.warning(self, 'Playlist not queued', str(exc))

    def _queue_youtube_playlist(self, videos, title, season, first=0, quality='best'):
        from .organizer import safe_component
        if not self._downloads_allowed():
            raise ValueError('Enable the saved download-permission checkbox before queuing videos.')
        root = self._require_library()
        if root is None or not videos:
            return []
        if not title or not 1 <= season <= 999 or not 0 <= first <= 9999 or quality not in {'best', '1080p', '720p', '480p'}:
            raise ValueError('Choose a series, valid season, and video quality.')
        title = safe_component(title)
        series = self.db.series_for_title(title)
        occupied = {row['episode'] for row in self.db.episodes(series['id']) if row['season'] == season} if series else set()
        for job in self.download_queue.jobs.values():
            data = job.retry_data
            if job.database == self.db.path and job.root == root and str(data.get('title') or '').casefold() == title.casefold() and data.get('season') == season:
                number = data.get('episode', data.get('number'))
                if number is not None and job.status not in {'Cancelled'}:
                    occupied.add(int(number))
        number = first or max(occupied, default=0) + 1
        planned, seen = [], set()
        for video in videos:
            url = youtube_video_url(video['url'])
            if url in seen or self.download_queue.existing('YouTube', url, self.db.path, root):
                continue
            seen.add(url)
            if number > 9999 or number in occupied:
                raise ValueError('A selected video number already exists. Choose Next available or another first number.')
            job = DownloadJob(str(video['title']), 'YouTube', url, self.db.path, root, self.profile_manager.active.name, lambda: None, lambda: None)
            job.retry_data = dict(title=title, quality=quality, season=season, episode=number, number=number)
            self._wire_youtube_job(job); planned.append(job); number += 1
        self._cancel_catalog_quality_probe()
        accepted = self.download_queue.add_many(planned)
        self.youtube_message = f'Added {len(planned)} playlist videos in order to Downloads.'
        self._render_youtube_download()
        if self.stack.currentWidget() is self._youtube_page:
            self._animate_download_to_tab(self.playlist_button)
        return accepted

    def _start_youtube_job(self, job):
        if self._closing:
            return
        if not job.database.is_file():
            raise ValueError("The original profile's library database is unavailable.")
        owner = self.db if job.database == self.db.path else LibraryDatabase(job.database)
        try:
            if library_root_from_setting(owner.setting("library_root", "")) != job.root:
                raise ValueError("The original library folder changed. Select it again before retrying this video.")
            snapshot = series_snapshot(owner.series(), owner.all_episodes())
        finally:
            if owner is not self.db:
                owner.close()
        runtime = {"cancel": threading.Event()}
        self.youtube_jobs[job.id] = runtime
        data = job.retry_data
        download = partial(download_youtube_video,
                           library_series=snapshot,
                           target_title=data.get("title"), season=data.get("season"), episode=data.get("episode"),
                           metadata_callback=lambda info: worker.signals.metadata.emit(info))
        worker = Worker(download, job.url, self.data_root / "downloads", job.root,
                        data["quality"], runtime["cancel"], with_progress=True)
        worker.signals.progress.connect(lambda values: self._youtube_progress_update(job, runtime, values))
        worker.signals.done.connect(lambda result: self._youtube_download_finished(job, runtime, result))
        worker.signals.failed.connect(lambda error: self._youtube_download_failed(job, runtime, error))
        worker.signals.metadata.connect(lambda info: self._youtube_metadata_update(job, info) if self.youtube_jobs.get(job.id) is runtime and not runtime["cancel"].is_set() else None)
        try:
            self._start_worker(worker)
        except Exception:
            self.youtube_jobs.pop(job.id, None)
            raise

    def _cancel_youtube_job(self, job):
        runtime = self.youtube_jobs.get(job.id)
        if runtime:
            runtime["cancel"].set()

    def _retry_youtube_job(self, job):
        if not self._downloads_allowed():
            return QMessageBox.warning(self, "Permission required", "Check the saved download-permission checkbox at the top of Downloads.")
        if not self.download_queue.retry(job.id):
            QMessageBox.information(self, "Already queued", "Another download of this video is already queued or active.")

    def _youtube_progress_update(self, job, runtime, values) -> None:
        if self._closing or self.youtube_jobs.get(job.id) is not runtime or runtime["cancel"].is_set():
            return
        received, total, stage = values
        self.download_queue.update(job.id, received=received, total=total,
                                   status="Verifying" if "Adding to" in stage else "Preparing" if "Preparing" in stage else "Downloading" if received else "Connecting", detail=stage)

    def _youtube_download_finished(self, job, runtime, result) -> None:
        if self._closing or self.youtube_jobs.get(job.id) is not runtime:
            return
        self.youtube_jobs.pop(job.id)
        try:
            self._index_download_owner(job, result.destination)
        except Exception as exc:
            detail = f"Video saved, but library refresh failed: {exc}"
            self.download_queue.finish(job.id, "Failed", detail, result.destination)
            return
        prefix = "Already in your library" if result.status == "duplicate" else "Added"
        self.download_queue.finish(job.id, "Completed", prefix, result.destination)

    def _youtube_download_failed(self, job, runtime, error: str) -> None:
        if self._closing or self.youtube_jobs.get(job.id) is not runtime:
            return
        self.youtube_jobs.pop(job.id)
        self.download_queue.finish(job.id, "Cancelled" if runtime["cancel"].is_set() else "Failed", error)

    def _catalog_search(self) -> None:
        source = self.search_source.text().strip()
        query = self.catalog_query.text().strip()
        if not source or not query:
            return QMessageBox.warning(self, "Search needs two things", "Enter a source URL and an anime title.")
        self.db.set_setting("catalog_source_url", source)
        self.catalog_status.setText("Reading public catalog pages…")
        clear_layout(self.catalog_results)
        self.catalog_artwork_rows.clear()
        self.catalog_artwork_pending.clear()
        self.catalog_token += 1
        token = self.catalog_token
        if is_wco_url(source):
            try:
                self._wco_session().search(query,
                    lambda results: self._catalog_search_done(token, results),
                    lambda error: self._catalog_search_failed(token, error))
            except Exception as exc:
                self._catalog_search_failed(token, str(exc))
            return
        worker = Worker(search_catalog, source, query)
        worker.signals.done.connect(lambda results: self._catalog_search_done(token, results))
        worker.signals.failed.connect(lambda error: self._catalog_search_failed(token, error))
        self._start_worker(worker)

    def _catalog_search_done(self, token, results):
        if token == self.catalog_token and isValid(self.catalog_status):
            self._catalog_results_ready(results)

    def _catalog_search_failed(self, token, error):
        if token == self.catalog_token and isValid(self.catalog_status):
            self.catalog_status.setText(error)

    def _wco_session(self):
        session = getattr(self, "wco_session", None)
        if session is None:
            from .wco_browser import WcoCatalogSession
            session = self.wco_session = WcoCatalogSession(self)
        return session

    def _catalog_results_ready(self, results: list[CatalogResult]) -> None:
        self.catalog_quality_groups.clear()
        self._cancel_catalog_quality_probe()
        clear_layout(self.catalog_results)
        self.catalog_artwork_rows.clear()
        self.catalog_artwork_pending.clear()
        self.catalog_status.setText(f"{len(results)} matching result(s)" if results else "No matching links found.")
        for result in results:
            row = QFrame()
            row.setObjectName("catalogResult")
            row.setProperty("class", "card")
            layout = QVBoxLayout(row)
            header = QHBoxLayout()
            cover = QVBoxLayout()
            thumbnail = QLabel("Loading…"); thumbnail.setObjectName("catalogThumbnail")
            thumbnail.setFixedSize(76, 108); thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter); thumbnail.setWordWrap(True)
            year = QLabel("Loading…"); year.setObjectName("catalogReleaseYear")
            year.setAlignment(Qt.AlignmentFlag.AlignCenter); year.setStyleSheet(f"color:{MUTED};font-size:11px;")
            cover.addWidget(thumbnail); cover.addWidget(year); cover.addStretch(1)
            header.addLayout(cover)
            details = QVBoxLayout()
            title = QLabel(result.title); title.setObjectName("catalogTitle"); title.setTextFormat(Qt.TextFormat.PlainText)
            title.setWordWrap(True); title.setStyleSheet("font-size:16px;font-weight:700;")
            url = QLabel(result.url); url.setTextFormat(Qt.TextFormat.PlainText); url.setWordWrap(True)
            url.setStyleSheet(f"color:{MUTED};")
            details.addWidget(title); details.addWidget(url); details.addStretch(1)
            header.addLayout(details, 1)
            actions = QVBoxLayout()
            if result.direct_media:
                use = QPushButton("Use download URL")
                use.clicked.connect(lambda _=False, url=result.url: self._use_download_url(url))
                actions.addWidget(use)
            else:
                episodes = QPushButton("View episodes")
                actions.addWidget(episodes)
            open_page = QPushButton("Open page")
            open_page.clicked.connect(lambda _=False, url=result.url: webbrowser.open(url))
            actions.addWidget(open_page); actions.addStretch(1); header.addLayout(actions)
            layout.addLayout(header)
            episode_box = QVBoxLayout()
            layout.addLayout(episode_box)
            if not result.direct_media:
                episodes.clicked.connect(lambda _=False, item=result, box=episode_box: self._load_catalog_episodes(item, box))
            self.catalog_results.addWidget(row)
            if result.direct_media:
                thumbnail.setText("Thumbnail\nunavailable"); year.setText("Year unavailable")
            else:
                self._prepare_catalog_artwork(result.title, thumbnail, year)

    def _prepare_catalog_artwork(self, title, thumbnail, year):
        key = (self.db.path, self.library_root, title.strip().casefold())
        self.catalog_artwork_rows.setdefault(key, []).append((self.catalog_token, thumbnail, year))
        data = self.download_metadata.get(key) or self.catalog_artwork_cache.get(key[2])
        if data is None:
            try:
                series = self.db.series_for_title(title)
                if series and series["poster_path"] and Path(series["poster_path"]).is_file() and series["metadata_year_checked"]:
                    data = dict(poster_path=series["poster_path"], year=series["release_year"])
            except (OSError, sqlite3.Error):
                pass
        if data and ("id" in data or data.get("poster_path")):
            self.download_metadata[key] = data
            self.download_metadata_attempted.add(key)
            self._render_catalog_artwork(key, data)
        elif key not in self.download_metadata_pending and getattr(self, "download_metadata_inflight", None) != key:
            self.catalog_artwork_pending[key] = title
            QTimer.singleShot(0, self._auto_metadata)

    def _render_catalog_artwork(self, key, data=None):
        if self._closing or key[:2] != (self.db.path, self.library_root):
            return
        path = str((data or {}).get("poster_path") or "")
        pixmap = QPixmap(path) if path and Path(path).is_file() else QPixmap()
        for token, thumbnail, year in self.catalog_artwork_rows.get(key, []):
            if token != self.catalog_token or not isValid(thumbnail) or not isValid(year):
                continue
            if pixmap.isNull():
                thumbnail.clear(); thumbnail.setText("Thumbnail\nunavailable")
            else:
                thumbnail.setPixmap(pixmap.scaled(thumbnail.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            year.setText(str(data["year"]) if data and data.get("year") else "Year unavailable")

    def _catalog_artwork_ready(self, key, title, data):
        if self._closing:
            return
        self.catalog_artwork_cache[key[2]] = data
        self._download_metadata_ready(key, title, data)

    def _load_catalog_episodes(self, result: CatalogResult, box: QVBoxLayout) -> None:
        clear_layout(box)
        box.addWidget(QLabel("Reading public episode links…"))
        if is_wco_url(result.url):
            try:
                self._wco_session().episodes(result.url,
                    lambda episodes: self._catalog_episodes_ready(result, box, episodes) if isValid(box) else None,
                    lambda error: self._layout_message(box, error))
            except Exception as exc:
                self._layout_message(box, str(exc))
            return
        worker = Worker(load_catalog_episodes, result.url)
        worker.signals.done.connect(lambda episodes: self._catalog_episodes_ready(result, box, episodes))
        worker.signals.failed.connect(lambda error: self._layout_message(box, error))
        self._start_worker(worker)

    def _layout_message(self, layout, text: str) -> None:
        if not isValid(layout):
            return
        clear_layout(layout)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)

    def _catalog_episodes_ready(self, result: CatalogResult, box: QVBoxLayout, episodes: list[EpisodeResult]) -> None:
        if not isValid(box):
            return
        clear_layout(box)
        self.catalog_quality_groups.pop(id(box), None)
        if not episodes:
            return box.addWidget(QLabel("No public episode links were found."))
        if is_wco_url(result.url):
            title = library_title(result.title, self.db.series())
            remember_catalog(self.db, title, episodes)
            series = next((row for row in self.db.series() if row["title"] == title), None)
            local = self.db.episodes(series["id"]) if series else []
            filters = QHBoxLayout()
            seasons = QComboBox(); seasons.addItem("All seasons", None)
            seasons.setObjectName("wcoSeasonFilter")
            for season in sorted({episode.season for episode in episodes if episode.season is not None}):
                seasons.addItem(f"Season {season}", season)
            filters.addWidget(seasons)
            skip_existing = QCheckBox("Skip episodes already in library")
            skip_existing.setObjectName("wcoSkipExisting")
            skip_existing.setChecked(True)
            skip_existing.setToolTip("Skip an existing copy of this Sub/Dub version. Untick to also download the best available quality for existing episodes; files are preserved.")
            filters.addWidget(skip_existing); filters.addStretch(1)
            box.addLayout(filters)
            note = QLabel("Status refers to files in your library. Bulk downloads use the current Sub/Dub tab and season filter. Choose a season to download it in full.")
            note.setWordWrap(True)
            box.addWidget(note)
            bulk = QHBoxLayout()
            select_all = QPushButton("Select all"); select_all.setObjectName("wcoSelectAll")
            clear_selection = QPushButton("Clear selection"); clear_selection.setObjectName("wcoClearSelection")
            download_selected = QPushButton("Download selected (0)"); download_selected.setObjectName("wcoDownloadSelected")
            download_season = QPushButton("Download season"); download_season.setObjectName("wcoDownloadSeason")
            for button in (select_all, clear_selection, download_selected, download_season):bulk.addWidget(button)
            bulk.addStretch(1); box.addLayout(bulk)
            bulk_status = QLabel(""); bulk_status.setObjectName("wcoBulkStatus")
            bulk_status.setWordWrap(True); bulk_status.setTextFormat(Qt.TextFormat.PlainText)
            box.addWidget(bulk_status)
            tabs = QTabWidget()
            tabs.setObjectName("wcoEpisodeTabs")
            tabs.tabBar().setObjectName("wcoVersionTabs")
            tabs.setMinimumHeight(240)
            tabs.setMaximumHeight(560)
            version_layouts = {}
            for language in sorted({episode.language for episode in episodes}, key=lambda value: ({"Sub":0,"Dub":1}.get(value,2),value)):
                scroll, _, content = self._scroll()
                scroll.setProperty("wcoLanguage", language)
                content.setSpacing(6)
                empty = QLabel(f"No {language} episodes listed for this season.")
                empty.setVisible(False)
                content.addWidget(empty)
                index = tabs.addTab(scroll, language)
                version_layouts[language] = (content, empty, index)
            box.addWidget(tabs)
            rows = []
            quality_entries = []
            for episode in episodes:
                row = QFrame()
                layout = QHBoxLayout(row)
                slot = f"S{episode.season:02d} · Episode {episode.number}"
                select = QCheckBox()
                select.setObjectName("wcoEpisodeSelect")
                select.setProperty("season",episode.season); select.setProperty("episode",episode.number); select.setProperty("language",episode.language)
                select.setToolTip(f"Select {slot} · {episode.language}")
                select.setAccessibleName(f"Select {slot} · {episode.language}")
                select.setEnabled(bool(episode.direct_open and episode.number and episode.number.isdigit()))
                if not select.isEnabled():
                    select.setToolTip("This episode needs manual selection or a whole-number library slot. Use Open page to inspect it.")
                layout.addWidget(select)
                label = QLabel(f"{slot} · {library_status(episode, local)}")
                layout.addWidget(label, 1)
                quality_label = QLabel("Waiting to check…")
                quality_label.setObjectName("episodeBestQuality")
                quality_label.setProperty("episodeUrl", episode.url)
                quality_label.setStyleSheet(f"color:{MUTED};font-weight:700;")
                quality_label.setToolTip("Checks the highest quality offered by this episode's player. Downloads take priority; this check does not download or import a video.")
                layout.addWidget(quality_label)
                quality_entries.append((episode, quality_label))
                download = QPushButton("Download best available")
                download.setEnabled(bool(episode.number and episode.number.isdigit()))
                if not download.isEnabled():
                    download.setToolTip("This special episode needs a whole-number library slot; open its page to download manually.")
                def download_one(_=False, item=episode, name=title, tag=label, prefix=slot, button=download):
                    job = self._download_wco_episode(name, item, tag, prefix)
                    if isinstance(job, DownloadJob):
                        if isValid(tag):
                            state = job.status if job.status in FINISHED else "Added to Downloads"
                            tag.setText(f"{prefix} · {state}")
                        self._animate_download_to_tab(button)
                download.clicked.connect(download_one)
                layout.addWidget(download)
                open_page = QPushButton("Open page")
                open_page.clicked.connect(lambda _=False, url=episode.url: webbrowser.open(url))
                layout.addWidget(open_page)
                version_layouts[episode.language][0].addWidget(row)
                rows.append((row, episode, select))
            for content, _, _ in version_layouts.values():
                content.addStretch(1)
            def current_rows():
                language = tabs.currentWidget().property("wcoLanguage")
                return [(episode, select) for _, episode, select in rows
                        if episode.language == language and (seasons.currentData() is None or seasons.currentData() == episode.season) and select.isEnabled()]

            def update_bulk():
                current = current_rows()
                count = sum(select.isChecked() for _, select in current)
                download_selected.setText(f"Download selected ({count})")
                download_selected.setEnabled(count > 0)
                season = seasons.currentData()
                language = tabs.currentWidget().property("wcoLanguage")
                download_season.setText(f"Download season {season} · {language}" if season is not None else "Download season")
                download_season.setEnabled(season is not None and bool(current))
                download_season.setToolTip("Download this season's current Sub/Dub version at best available quality." if season is not None else "Choose a season first.")
                select_all.setEnabled(bool(current)); clear_selection.setEnabled(count > 0)

            def select_current():
                current = next((row for row in self.db.series() if row["title"] == title),None)
                available = self.db.episodes(current["id"]) if current else []
                eligible, _ = batch_episodes([episode for episode, _ in current_rows()], available, skip_existing.isChecked())
                urls = {episode.url for episode in eligible}
                for episode, select in current_rows():select.setChecked(episode.url in urls)

            def queue_current(selected_only):
                chosen = [episode for episode, select in current_rows() if not selected_only or select.isChecked()]
                stats = self._queue_wco_batch(title, chosen, skip_existing.isChecked())
                if stats is None:
                    return
                skipped = [f"{stats[key]} {label}" for key,label in (("in_library","already in library"),("already_queued","already queued"),("unsupported","unsupported specials"),("duplicates","duplicates")) if stats[key]]
                message = f"Queued {stats['queued']} episode(s) at best available quality."
                if skipped:message += " Skipped " + ", ".join(skipped) + "."
                bulk_status.setText(message + " Follow progress in the Downloads tab.")
                for _, select in current_rows():select.setChecked(False)

            select_all.clicked.connect(select_current)
            clear_selection.clicked.connect(lambda: [select.setChecked(False) for _,select in current_rows()])
            download_selected.clicked.connect(lambda: queue_current(True))
            download_season.clicked.connect(lambda: queue_current(False))
            tabs.currentChanged.connect(update_bulk)
            skip_existing.toggled.connect(update_bulk)
            for _, _, select in rows:select.toggled.connect(update_bulk)

            def filter_rows():
                counts = {language:0 for language in version_layouts}
                for row, episode, _ in rows:
                    visible = seasons.currentData() is None or seasons.currentData() == episode.season
                    row.setVisible(visible)
                    counts[episode.language] += int(visible)
                for language, (_, empty, index) in version_layouts.items():
                    tabs.setTabText(index, f"{language} ({counts[language]})")
                    empty.setVisible(counts[language] == 0)
                update_bulk()
            seasons.currentIndexChanged.connect(filter_rows)
            if seasons.count() == 2:seasons.setCurrentIndex(1)
            filter_rows()
            self.catalog_quality_groups[id(box)] = dict(box=box, tabs=tabs, seasons=seasons, entries=quality_entries, database=self.db.path, root=self.library_root)
            tabs.currentChanged.connect(lambda _: self._catalog_quality_tick())
            seasons.currentIndexChanged.connect(lambda _: self._catalog_quality_tick())
            self._catalog_quality_tick()
            return
        grid = QGridLayout()
        for index, episode in enumerate(episodes):
            target = episode.url if episode.direct_open else result.url
            button = QPushButton(episode.title)
            button.clicked.connect(lambda _=False, url=target: webbrowser.open(url))
            grid.addWidget(button, index // 6, index % 6)
        box.addLayout(grid)

    def _cancel_catalog_quality_probe(self):
        active, self.catalog_quality_probe = self.catalog_quality_probe, None
        if active is not None:
            active[0].stop(); active[0].deleteLater()
            if isValid(active[2]):
                active[2].setText("Waiting to check…")

    def _catalog_quality_tick(self):
        if self._closing:
            return
        groups = getattr(self, "catalog_quality_groups", {})
        tasks = []
        page = getattr(self, "_download_page", None)
        tabs = getattr(self, "download_tabs", None)
        allowed = (page is not None and isValid(page) and self.stack.currentWidget() is page
                   and tabs is not None and isValid(tabs) and tabs.currentIndex() == 0)
        busy = any(job.status not in FINISHED for job in self.download_queue.jobs.values())
        for group_id, group in list(groups.items()):
            if (not isValid(group['box']) or not isValid(group['tabs'])
                    or group['database'] != self.db.path or group['root'] != self.library_root):
                groups.pop(group_id, None); continue
            language = group['tabs'].currentWidget().property('wcoLanguage')
            season = group['seasons'].currentData()
            for episode, label in group['entries']:
                if not isValid(label):
                    continue
                key = (str(group['database']), str(group['root']), episode.url)
                cached = self.catalog_quality_cache.get(key)
                if cached is not None and cached[0] > time.monotonic():
                    label.setText(cached[1]['label']); label.setToolTip(cached[1]['detail'])
                elif allowed and episode.language == language and (season is None or episode.season == season):
                    if episode.direct_open:
                        tasks.append((key, episode, label))
                    else:
                        label.setText("Quality unavailable")
                        label.setToolTip("This entry requires manual page selection.")
        active = getattr(self, 'catalog_quality_probe', None)
        if active is not None and (busy or not any(key == active[1] and label is active[2] for key, _, label in tasks)):
            self._cancel_catalog_quality_probe(); active = None
        if busy or not tasks or active is not None:
            return
        key, episode, label = tasks[0]
        from .wco_browser import WcoQualityProbe
        try:
            probe = WcoQualityProbe(self._wco_session(), episode, self)
            self.catalog_quality_probe = (probe, key, label)
            label.setText("Checking quality…")
            probe.ready.connect(lambda result: self._catalog_quality_ready(probe, key, label, result))
            probe.failed.connect(lambda error: self._catalog_quality_ready(probe, key, label, {'label': 'Quality unavailable', 'detail': error}, success=False))
        except Exception as exc:
            self.catalog_quality_cache[key] = (time.monotonic() + 120, {'label': 'Quality unavailable', 'detail': str(exc)})

    def _catalog_quality_ready(self, probe, key, label, result, success=True):
        active = self.catalog_quality_probe
        if active is None or active[0] is not probe:
            return
        self.catalog_quality_probe = None
        probe.stop(); probe.deleteLater()
        if self._closing or key[:2] != (str(self.db.path), str(self.library_root)) or not isValid(label):
            return
        # Cache descriptions only; signed source URLs are never retained here.
        data = {'label': str(result['label']), 'detail': str(result['detail'])}
        if len(self.catalog_quality_cache) >= 500:
            self.catalog_quality_cache.pop(next(iter(self.catalog_quality_cache)))
        self.catalog_quality_cache[key] = (time.monotonic() + (1800 if success else 120), data)
        label.setText(data['label']); label.setToolTip(data['detail'])
        QTimer.singleShot(0, self._catalog_quality_tick)

    def _queue_wco_batch(self, title, episodes, skip_existing=True):
        if not self._downloads_allowed():
            QMessageBox.warning(self, "Permission required", "Check the saved download-permission checkbox at the top of Downloads.")
            return None
        root = self._require_library()
        if root is None:
            return None
        current = next((row for row in self.db.series() if row["title"] == title),None)
        local = self.db.episodes(current["id"]) if current else []
        candidates, stats = batch_episodes(episodes, local, skip_existing)
        stats.update(queued=0, already_queued=0)
        jobs = []
        for episode in candidates:
            if self.download_queue.existing("WCO", episode.url, self.db.path, root):
                stats["already_queued"] += 1
            else:
                jobs.append(self._new_wco_job(title, episode, root))
        self.download_queue.add_many(jobs)
        stats["queued"] = len(jobs)
        return stats

    def _animate_download_to_tab(self, origin):
        page = self._download_page
        if self._closing or page is None or not isValid(page) or not isValid(origin):
            return
        if self.stack.currentWidget() is not page or self.download_tabs.currentIndex() != 0:
            return
        previous = getattr(self, "_download_flyout", None)
        if previous is not None and isValid(previous):
            previous.timeline.stop()
            previous.hide()
            previous.deleteLater()
        bar = self.download_tabs.tabBar()
        start = origin.mapTo(page, origin.rect().center())
        destination = bar.mapTo(page, bar.tabRect(1).center())
        self._download_flyout = DownloadFlyout(start, destination, page)

    def _download_wco_episode(self, title, episode, status_label=None, slot=None):
        root = self._require_library()
        if root is None:
            return
        if not self._downloads_allowed():
            return QMessageBox.warning(self, "Permission required", "Check the saved download-permission checkbox at the top of Downloads.")
        existing = self.download_queue.existing("WCO", episode.url, self.db.path, root)
        if existing:
            return existing
        job = self._new_wco_job(title, episode, root, status_label, slot)
        self.download_queue.add(job)
        return job

    def _new_wco_job(self, title, episode, root, status_label=None, slot=None):
        self._cancel_catalog_quality_probe()
        job = DownloadJob(f"{title} · {episode.title}", "WCO", episode.url, self.db.path, root,
                          self.profile_manager.active.name,
                          lambda: self._start_wco_job(job, episode, title, status_label, slot),
                          lambda: self._cancel_wco_job(job.id))
        job.retry_action = lambda: self._retry_wco_job(job)
        job.retry_data = dict(title=title,episode_title=episode.title,season=episode.season,number=episode.number,language=episode.language)
        job.prepare_action = lambda: self._prepare_wco_job(job, episode, title, status_label, slot)
        return job

    def _start_wco_job(self, job, episode, title, status_label, slot):
        if job.id in self.wco_downloads:
            self.wco_downloads[job.id]["dialog"].begin_download()
            return
        self._create_wco_dialog(job, episode, title, status_label, slot)

    def _prepare_wco_job(self, job, episode, title, status_label, slot):
        if self._closing or job.status != "Queued" or job.id in self.wco_downloads:
            return
        self._create_wco_dialog(job, episode, title, status_label, slot, deferred=True)
        self.download_queue.update(job.id, detail="Preparing the next episode's player…")

    def _prepare_wco_next(self):
        if self._closing or self.download_queue.paused or self.download_queue.transfer_count == 0:
            return
        transfers = [job for job in self.download_queue.jobs.values() if job.status == "Downloading"]
        if not transfers:
            return
        # Prepare close enough to completion that a selected source stays fresh.
        # Unknown-length transfers get one prepared player without an ETA gate.
        if not any(not job.total or (job.eta_seconds is not None and job.eta_seconds <= 40) for job in transfers):
            return
        if any(self.download_queue.jobs[key].status == "Queued" for key in self.wco_downloads if key in self.download_queue.jobs):
            return
        next_job = next((job for job in self.download_queue.jobs.values() if job.status == "Queued"), None)
        if next_job is not None and next_job.prepare_action is not None:
            try:
                next_job.prepare_action()
            except Exception as exc:
                self.download_queue.finish(next_job.id, "Failed", f"Could not prepare the episode: {exc}")

    def _create_wco_dialog(self, job, episode, title, status_label, slot, deferred=False):
        from .wco_browser import WcoDownloadDialog
        options = {"defer_download": True} if deferred else {}
        if job.wco_attempt != 1:
            options["attempt"] = job.wco_attempt
        dialog = WcoDownloadDialog(self._wco_session(), title, episode, self.data_root / "downloads", job.root, self, **options)
        self.wco_downloads[job.id] = {"dialog":dialog, "last":None}
        job.open_player = lambda: (dialog.show(), dialog.raise_(), dialog.activateWindow())
        dialog.completed.connect(lambda result: self._wco_job_finished(job, result, episode, title, status_label, slot))
        dialog.failed.connect(lambda error: self._wco_job_failed(job, error))
        dialog.cancelled.connect(lambda: self._wco_job_cancelled(job))
        dialog.transfer_started.connect(lambda: self._wco_transfer_started(job, dialog))
        dialog.verification_started.connect(lambda: self.download_queue.update(job.id, status="Verifying", detail="Verifying and importing the saved video…"))
        dialog.retry_requested.connect(lambda reason, attempt: self._wco_job_auto_retry(job, dialog, reason, attempt))
        self._poll_wco_downloads()

    def _wco_job_auto_retry(self, job, dialog, reason, attempt):
        self._save_download_snapshot()
        self._dispose_wco_job(job)
        def retry():
            if self._closing or job.status in FINISHED | {"Cancelling"}:
                return
            job.wco_attempt = attempt
            self.download_queue.update(job.id, detail=reason)
            self.download_queue.retry(job.id, automatic=True)
        if dialog.worker and dialog.worker.isRunning():
            dialog.worker.finished.connect(retry)
        else:
            retry()

    def _wco_transfer_started(self, job, dialog):
        values = dict(status="Downloading", detail="Downloading the selected video…")
        if dialog.download is not None:
            values.update(received=dialog.download.receivedBytes(), total=dialog.download.totalBytes())
        self.download_queue.update(job.id, **values)
        self._prepare_wco_next()

    def _poll_wco_downloads(self):
        if self._closing:
            return
        for key, runtime in list(self.wco_downloads.items()):
            dialog = runtime["dialog"]
            if dialog.terminal:
                continue
            if self.download_queue.jobs[key].status == "Queued":
                detail = dialog.status.text()
                if detail != runtime["last"]:
                    runtime["last"] = detail
                    self.download_queue.update(key, detail=detail)
                continue
            received = dialog.download.receivedBytes() if dialog.download else 0
            total = dialog.download.totalBytes() if dialog.download else 0
            phase = "Verifying" if dialog.worker else "Downloading" if dialog.download else "Needs attention" if not dialog.auto_download else "Connecting"
            detail = dialog.status.text()
            state = (received, total, phase, detail)
            if state != runtime["last"] or phase == "Downloading":
                runtime["last"] = state
                self.download_queue.update(key, received=received, total=total, status=phase, detail=detail)
        self._prepare_wco_next()

    def _cancel_wco_job(self, key):
        runtime = self.wco_downloads.get(key)
        if runtime:
            runtime["dialog"].cancel_download()

    def _dispose_wco_job(self, job):
        runtime = self.wco_downloads.get(job.id)
        if runtime is None:
            return
        dialog = runtime["dialog"]
        def dispose():
            self.wco_downloads.pop(job.id, None)
            dialog.close()
            dialog.deleteLater()
        if dialog.worker and dialog.worker.isRunning():
            dialog.worker.finished.connect(dispose)
        else:
            dispose()

    def _wco_job_finished(self, job, result, episode, title, status_label, slot):
        try:
            self._index_download_owner(job, result.destination)
            if status_label is not None and isValid(status_label) and self.db.path == job.database:
                current = next((row for row in self.db.series() if row["title"] == title), None)
                local = self.db.episodes(current["id"]) if current else []
                status_label.setText(f"{slot} · {library_status(episode, local)}")
            self.download_queue.finish(job.id, "Completed", "Added to library" if result.status != "duplicate" else "Already in library", result.destination)
        except Exception as exc:
            self.download_queue.finish(job.id, "Failed", f"Video saved, but library refresh failed: {exc}", result.destination)
        finally:
            self._dispose_wco_job(job)

    def _wco_job_failed(self, job, error):
        self._save_download_snapshot()
        self.download_queue.finish(job.id, "Failed", error)
        self._dispose_wco_job(job)
        self._save_download_snapshot()

    def _wco_job_cancelled(self, job):
        self.download_queue.finish(job.id, "Cancelled", "Download cancelled.")
        self._dispose_wco_job(job)

    def _use_download_url(self, url: str) -> None:
        self.download_url.setText(url)
        self.download_label.setText("Direct media URL selected. Confirm permission, then download.")

    def _start_download(self) -> None:
        root = self._require_library()
        if root is None:
            return
        if not self._downloads_allowed():
            return QMessageBox.warning(self, "Permission required", "Check the saved download-permission checkbox at the top of Downloads.")
        url = self.download_url.text().strip()
        if not url:
            return
        existing = self.download_queue.existing("Direct file", url, self.db.path, root)
        if existing:
            self.download_tabs.setCurrentIndex(1)
            return
        cancel = threading.Event()
        job = DownloadJob(Path(url.split("?",1)[0]).name or "Direct video", "Direct file", url, self.db.path, root,
                          self.profile_manager.active.name, lambda: self._start_worker(worker), cancel.set)
        worker = Worker(partial(download_authorized_file, cancel=cancel), url, self.data_root / "downloads" / f"direct-{job.id}", root, with_progress=True)
        worker.signals.progress.connect(lambda values: self.download_queue.update(job.id, received=values[0], total=values[1], status="Downloading", detail="Downloading video…"))
        worker.signals.done.connect(lambda result: self._direct_job_finished(job, result))
        worker.signals.failed.connect(lambda error: self.download_queue.finish(job.id, "Cancelled" if cancel.is_set() else "Failed", error))
        self.download_queue.add(job)
        self.download_tabs.setCurrentIndex(1)

    def _direct_job_finished(self, job, result):
        try:
            self._index_download_owner(job)
            self.download_queue.finish(job.id, "Completed", "Added to library" if result.status != "duplicate" else "Already in library", result.destination)
        except Exception as exc:
            self.download_queue.finish(job.id, "Failed", f"Video saved, but library refresh failed: {exc}", result.destination)

    def show_file_manager(self) -> None:
        page, outer = self._page("File manager", "Correct anime, season, episode, and Sub/Dub identification")
        search = QLineEdit()
        search.setPlaceholderText("Search anime name or file path…")
        outer.addWidget(search)
        selection = set()
        checkboxes = {}
        controls = QHBoxLayout()
        select_all = QPushButton("Select shown"); select_all.setObjectName("selectShownFiles")
        clear = QPushButton("Clear selection")
        move_selected = QPushButton("Move selected (0)…"); move_selected.setObjectName("bulkMoveFiles")
        move_selected.setEnabled(False)
        controls.addWidget(select_all); controls.addWidget(clear); controls.addWidget(move_selected); controls.addStretch(1)
        outer.addLayout(controls)
        scroll, _, body = self._scroll()

        def changed(episode_id, checked):
            selection.add(episode_id) if checked else selection.discard(episode_id)
            move_selected.setText(f"Move selected ({len(selection)})…")
            move_selected.setEnabled(bool(selection))

        def select_shown():
            for checkbox in checkboxes.values():
                checkbox.setChecked(True)

        def clear_selection():
            selection.clear()
            for checkbox in checkboxes.values():
                checkbox.setChecked(False)
            move_selected.setText("Move selected (0)…"); move_selected.setEnabled(False)

        select_all.clicked.connect(select_shown); clear.clicked.connect(clear_selection)
        move_selected.clicked.connect(lambda: self._bulk_move_episodes(sorted(selection)))

        def render(text: str = "") -> None:
            clear_layout(body)
            checkboxes.clear()
            rows = self.db.all_episodes(text)
            for episode in rows:
                card = QFrame(); card.setProperty("class", "card")
                card_layout = QHBoxLayout(card)
                episode_id = int(episode["id"])
                checkbox = QCheckBox(); checkbox.setObjectName(f"fileSelect_{episode_id}")
                checkbox.setAccessibleName(f"Select {episode['series_title']} season {episode['season']} episode {episode['episode']}")
                checkbox.setChecked(episode_id in selection)
                checkbox.toggled.connect(lambda checked, eid=episode_id: changed(eid, checked))
                checkboxes[episode_id] = checkbox
                card_layout.addWidget(checkbox)
                description = QLabel(
                    f"{episode['series_title']}  •  S{episode['season']:02d}E{episode['episode']:02d}  •  {episode['language']}\n{episode['path']}"
                )
                description.setWordWrap(True)
                card_layout.addWidget(description, 1)
                fix = QPushButton("Fix details")
                fix.clicked.connect(lambda _=False, eid=int(episode["id"]): self._rename_episode(eid))
                move = QPushButton("Move to series")
                move.clicked.connect(lambda _=False, eid=int(episode["id"]): self._move_episode(eid))
                delete = QPushButton("Delete"); delete.setObjectName("danger")
                delete.clicked.connect(lambda _=False, eid=int(episode["id"]): self._delete_episode(eid))
                card_layout.addWidget(move); card_layout.addWidget(fix); card_layout.addWidget(delete)
                body.addWidget(card)
            if not rows:
                body.addWidget(QLabel("No matching files."))
            body.addStretch(1)

        search.textChanged.connect(render)
        render()
        outer.addWidget(scroll, 1)
        self._set_page(page, 5)

    def show_schedule(self) -> None:
        page, outer = self._page("Schedule", "See what’s airing now, or follow the shows in your library. All times are local.")
        self._schedule_page = page
        tabs = QTabWidget(); tabs.setObjectName("scheduleTabs")
        tabs.setStyleSheet("QTabWidget::pane{border:0;} QTabBar::tab{background:#181e29;color:#9aa4b3;padding:10px 20px;margin-right:6px;border-radius:6px;} QTabBar::tab:selected{background:#6d28d9;color:white;font-weight:700;}")
        self._release_calendar = ReleaseCalendar()
        scope = self.db.setting("calendar_scope", "current")
        self._release_calendar.source.setCurrentIndex(max(0, self._release_calendar.source.findData(scope)))
        view = self.db.setting("calendar_view", "week" if scope == "current" else "month")
        self._release_calendar.view.setCurrentIndex(max(0, self._release_calendar.view.findData(view)))
        self._release_calendar.month_changed.connect(self._load_calendar_month)
        self._release_calendar.refresh_requested.connect(lambda: self._load_calendar_month(force=True))
        self._release_calendar.series_requested.connect(self.show_series)
        self._release_calendar.library_requested.connect(self.show_library)
        self._release_calendar.media_requested.connect(lambda media_id: webbrowser.open(f"https://anilist.co/anime/{media_id}"))
        tabs.addTab(self._release_calendar, "Calendar")
        scroll, _, self._schedule_activity = self._scroll()
        tabs.addTab(scroll, "Recent activity")
        tabs.currentChanged.connect(lambda index: self.db.mark_notifications_read() if index == 1 else None)
        outer.addWidget(tabs, 1)
        self._set_page(page, 6)
        self._render_schedule_activity()
        self._load_calendar_month()

    def show_notifications(self) -> None:
        self.show_schedule()

    def _schedule_is_visible(self) -> bool:
        return self.stack.currentWidget() is getattr(self, "_schedule_page", None)

    def _render_schedule_activity(self) -> None:
        if not self._schedule_is_visible():
            return
        body = self._schedule_activity
        clear_layout(body)
        notifications = self.db.notifications()
        for item in notifications:
            card = QFrame(); card.setProperty("class", "card")
            layout = QVBoxLayout(card)
            title = QLabel(item["title"]); title.setStyleSheet("font-size:16px;font-weight:800;")
            body_text = QLabel(item["body"]); body_text.setWordWrap(True)
            timestamp = QLabel(item["created_at"]); timestamp.setStyleSheet(f"color:{MUTED};font-size:11px;")
            layout.addWidget(title); layout.addWidget(body_text); layout.addWidget(timestamp)
            if item["kind"] == "app-update":
                settings = QPushButton("Open application updates")
                settings.clicked.connect(self.show_settings); layout.addWidget(settings)
            elif item["series_id"]:
                open_series = QPushButton("Open series")
                open_series.clicked.connect(lambda _=False, sid=int(item["series_id"]): self.show_series(sid))
                layout.addWidget(open_series)
            body.addWidget(card)
        if not notifications:
            body.addWidget(QLabel("No recent activity. Airing alerts and newly added episodes will appear here."))
        body.addStretch(1)

    def _load_calendar_month(self, force: bool = False) -> None:
        if not self._schedule_is_visible():
            return
        calendar = self._release_calendar
        database = self.db
        linked = database.linked_series()
        scope = calendar.source.currentData()
        public = scope == "current"
        database.set_setting("calendar_scope", scope)
        database.set_setting("calendar_view", calendar.view.currentData())
        start, end = calendar.timestamp_range()
        read_events = database.public_calendar_events if public else database.calendar_events
        calendar.set_events(read_events(start, end), linked)
        if not linked and not public:
            calendar.status.setText("Link a show to AniList from its Library page to fill your calendar.")
            return
        ids = () if public else tuple(sorted({int(row["anilist_id"]) for row in linked}))
        key = (database, start, end, scope, ids)
        cache_key = f"{scope}|{start}|{end}|" + ",".join(map(str, ids))
        checked = database.setting("calendar_last_checked", {})
        last = checked.get(cache_key, 0) if isinstance(checked, dict) else 0
        if key in self.calendar_requests:
            calendar.status.setText("Refreshing confirmed airings…")
            return
        if not force and time.time() - float(last or 0) < 3600:
            calendar.status.setText("Saved schedule · Last checked " + time.strftime("%b %d at %I:%M %p", time.localtime(last)))
            return
        self.calendar_requests.add(key)
        calendar.status.setText("Refreshing confirmed airings… Saved dates remain visible.")
        worker = Worker(current_airing_schedule, start, end, with_progress=True) if public else Worker(calendar_schedule, list(ids), start, end)

        def is_current():
            return (not self._closing and self._schedule_is_visible() and self._release_calendar.timestamp_range() == (start, end)
                    and self._release_calendar.source.currentData() == scope and self.db is database)

        def progress(values):
            if is_current():
                self._release_calendar.status.setText(f"Refreshing current airings… {values[0]} confirmed episodes found.")

        if public:
            worker.signals.progress.connect(progress)

        def finished(rows=None, error=None):
            self.calendar_requests.discard(key)
            if self._closing or self.db is not database:
                return
            if error is None:
                try:
                    if public:
                        database.cache_public_calendar(start, end, rows)
                    else:
                        database.cache_calendar(list(ids), start, end, rows)
                    saved = database.setting("calendar_last_checked", {})
                    if not isinstance(saved, dict): saved = {}
                    saved[cache_key] = time.time()
                    # Bound historical month metadata without pruning actual airings.
                    saved = dict(sorted(saved.items(), key=lambda item: item[1], reverse=True)[:48])
                    database.set_setting("calendar_last_checked", saved)
                except (ValueError, TypeError, KeyError, sqlite3.Error) as exc:
                    error = str(exc)
            if not is_current():
                return
            self._release_calendar.set_events(read_events(start, end), database.linked_series())
            self._release_calendar.status.setText(
                f"Could not refresh · Showing saved dates. {error}" if error is not None else
                "Schedule refreshed · " + time.strftime("%I:%M %p") + " local time"
            )

        worker.signals.done.connect(lambda rows: finished(rows=rows))
        worker.signals.failed.connect(lambda error: finished(error=error))
        self._start_worker(worker)

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
        if self._schedule_is_visible():
            self._load_calendar_month()
            self._render_schedule_activity()

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

    def _automatic_library_backup(self):
        if self._closing or self.import_job:
            return
        try:
            backup_library(self.db, self.data_root, self.profile_manager.active.id, kind='automatic')
        except (OSError, sqlite3.Error, ValueError) as exc:
            self.backup_message = f'Automatic backup failed: {exc}'

    def _add_backup_settings(self, layout):
        layout.addSpacing(20)
        title = QLabel('Library backups'); title.setStyleSheet('font-size:18px;font-weight:800;'); layout.addWidget(title)
        note = QLabel('A verified backup is made automatically each day you use this profile. The last 7 daily backups are retained; manual and pre-restore backups are kept. Backups save organization, settings, and watch progress. Video files and thumbnails remain on their drives.')
        note.setWordWrap(True); layout.addWidget(note)
        self.backup_status = QLabel(self.backup_message); self.backup_status.setObjectName('libraryBackupStatus'); self.backup_status.setWordWrap(True); layout.addWidget(self.backup_status)
        row = QHBoxLayout(); self.backup_combo = QComboBox(); self.backup_combo.setObjectName('libraryBackupSelection')
        directory = backup_directory(self.data_root, self.profile_manager.active.id)
        for path in sorted(directory.glob('*.sqlite'), reverse=True):
            self.backup_combo.addItem(path.stem, str(path))
        create = QPushButton('Back up now'); create.setObjectName('createLibraryBackup'); create.clicked.connect(self._manual_library_backup)
        restore = QPushButton('Restore selected…'); restore.setObjectName('restoreLibraryBackup'); restore.setEnabled(self.backup_combo.count() > 0)
        restore.clicked.connect(lambda: self._review_library_restore(self.backup_combo.currentData()))
        folder = QPushButton('Open backups folder'); folder.clicked.connect(self._open_backup_folder)
        row.addWidget(self.backup_combo, 1); row.addWidget(create); row.addWidget(restore); row.addWidget(folder); layout.addLayout(row)

    def _open_backup_folder(self):
        directory = backup_directory(self.data_root, self.profile_manager.active.id); directory.mkdir(parents=True, exist_ok=True)
        os.startfile(directory)

    def _manual_library_backup(self):
        if self.import_job:
            return QMessageBox.information(self, 'Import busy', 'Wait for the import to finish before backing up.')
        try:
            path = backup_library(self.db, self.data_root, self.profile_manager.active.id)
            self.backup_message = f'Backup saved: {path.name}'
        except (OSError, sqlite3.Error, ValueError) as exc:
            self.backup_message = f'Backup failed: {exc}'
        self.show_settings()

    def _restore_busy(self):
        return bool(self.active_workers) or self.import_job is not None or self.library_refresh_job is not None or any(
            job.database == self.db.path and job.status not in FINISHED for job in self.download_queue.jobs.values())

    def _review_library_restore(self, path):
        if self._restore_busy():
            return QMessageBox.information(self, 'Library busy', 'Finish or cancel this profile’s downloads and wait for imports or refreshes before restoring.')
        try:
            info = inspect_backup(path, self.profile_manager.active.id)
        except (OSError, sqlite3.Error, ValueError) as exc:
            return QMessageBox.warning(self, 'Invalid backup', str(exc))
        dialog = QDialog(self); dialog.setWindowTitle('Restore library backup'); layout = QVBoxLayout(dialog)
        label = QLabel(f"Restore {info['series']} series and {info['videos']} video entries from {time.strftime('%b %d, %Y %H:%M', time.localtime(info['created_at']))}?\nThis replaces the current profile’s settings and watch history. A backup of the current state is saved first. Media files are not moved or recovered; files moved since the backup may need a library refresh.")
        label.setWordWrap(True); layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton('Restore this backup', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted and not self._restore_busy():
            self._restore_library_backup(path)

    def _restore_library_backup(self, path):
        if self._restore_busy():
            raise ValueError('The library is busy. Restore after all transfers and imports finish.')
        self._save_progress(stop=True)
        try:
            recovery = restore_library(self.db, path, self.data_root, self.profile_manager.active.id)
            self.library_root = library_root_from_setting(self.db.setting('library_root', ''))
            self.sidebar_status.setText(str(self.library_root) if self.library_root else 'No library selected')
            limit = self.db.setting('download_parallel', 3)
            self.download_queue.set_limit(limit if isinstance(limit, int) and 1 <= limit <= 6 else 3)
            self.download_metadata.clear(); self.download_metadata_attempted.clear(); self.catalog_artwork_cache.clear()
            if hasattr(self, 'player_page') and isValid(self.player_page):
                self._install_player_shortcuts(self.player_page)
            missing = sum(not Path(row['path']).is_file() for row in self.db.all_episodes())
            self.backup_message = f'Restored library and watch progress. Current-state backup: {recovery.name}. {missing} stored video path(s) are unavailable.'
        except (OSError, sqlite3.Error, ValueError) as exc:
            self.backup_message = f'Restore failed: {exc}'
        self.show_settings()

    def show_settings(self) -> None:
        page, outer = self._page("Settings", "Profiles, library, playback, AniList, and provider bookmarks")
        scroll, _, settings_body = self._scroll()
        panel = QFrame()
        panel.setProperty("class", "panel")
        layout = QVBoxLayout(panel)
        update_title = QLabel("Application updates")
        update_title.setStyleSheet("font-size:18px;font-weight:800;")
        layout.addWidget(update_title)
        self.app_update_status = QLabel(self.app_update_message or self._app_update_status_text())
        self.app_update_status.setWordWrap(True)
        self.app_update_status.setStyleSheet(f"color:{MUTED};")
        layout.addWidget(self.app_update_status)
        self.app_update_progress = QProgressBar()
        self.app_update_progress.setTextVisible(False)
        self.app_update_progress.setFixedHeight(8)
        layout.addWidget(self.app_update_progress)
        self.app_update_auto_check = QCheckBox("Check automatically at startup and every 6 hours")
        self.app_update_auto_check.setChecked(bool(self.db.setting("app_update_auto_check", True)))
        self.app_update_auto_check.toggled.connect(lambda checked: self.db.set_setting("app_update_auto_check", checked))
        layout.addWidget(self.app_update_auto_check)
        update_buttons = QHBoxLayout()
        check_update = self.check_update_button = QPushButton("Check now")
        check_update.clicked.connect(lambda: self._check_for_app_update(manual=True))
        self.install_update_button = QPushButton("Download & install")
        self.install_update_button.setObjectName("accent")
        self.install_update_button.clicked.connect(self._start_app_update_download)
        self.install_update_button.setVisible(self.available_app_update is not None)
        releases = QPushButton("View GitHub releases")
        releases.clicked.connect(lambda: webbrowser.open(GITHUB_RELEASES_URL))
        update_buttons.addWidget(check_update)
        update_buttons.addWidget(self.install_update_button)
        update_buttons.addWidget(releases)
        update_buttons.addStretch(1)
        layout.addLayout(update_buttons)
        self._refresh_app_update_button()
        update_note = QLabel("Click Update once to download, verify, install, and reopen automatically. Progress appears here and in the sidebar. Updates are verified against GitHub's SHA-256 digest. Your profiles and library stay in their existing locations.")
        update_note.setWordWrap(True); update_note.setStyleSheet(f"color:{MUTED};font-size:11px;")
        layout.addWidget(update_note)
        layout.addSpacing(20)
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
        self._add_backup_settings(layout)
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
        saved_limit = self.db.setting("download_parallel", 3)
        self.download_queue.set_limit(saved_limit if isinstance(saved_limit, int) and 1 <= saved_limit <= 6 else 3)
        self.profile_status.setText(f"Profile: {profile.name}")
        self.sidebar_status.setText(str(self.library_root) if self.library_root else "No library selected")
        self.show_home()
        self._refresh_release_schedule()
        self._automatic_library_backup()

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

    def _app_update_status_text(self) -> str:
        if self.staged_app_update is not None:
            return f"Anime Watcher {self.staged_app_update.release.version} is downloaded and ready to install."
        if self.available_app_update is not None:
            return f"Anime Watcher {self.available_app_update.version} is available. You have {__version__}."
        return f"You have Anime Watcher {__version__}."

    def _set_app_update_status(self, text: str) -> None:
        self.app_update_message = text
        for name in ("app_update_status", "sidebar_update_status"):
            label = getattr(self, name, None)
            if label is not None and isValid(label):
                label.setText(text)
                label.setToolTip(text)
                label.setStyleSheet(f"color:{'#fca5a5' if self.app_update_phase == 'error' else MUTED};font-size:{10 if name.startswith('sidebar') else 13}px;")
        self.sidebar_update_status.setVisible(bool(text))

    def _refresh_app_update_button(self) -> None:
        if self.app_update_message:
            self._set_app_update_status(self.app_update_message)
        notice = self.sidebar_update_button
        release = self.staged_app_update.release if self.staged_app_update is not None else self.available_app_update
        notice.setVisible(release is not None)
        notice.setEnabled(not self.app_update_download_in_progress)
        if release is not None:
            if self.app_update_download_in_progress:
                text = {"verifying": "Verifying update…", "installing": "Preparing restart…", "restarting": "Restarting…", 'waiting': 'Finishing import…'}.get(self.app_update_phase)
                notice.setText(text or f"↓  Updating… {self.app_update_percent}%")
                tooltip = self.app_update_message
            elif self.staged_app_update is not None:
                notice.setText("↑  Restart to update")
                tooltip = f"Anime Watcher {release.version} is ready. Click to install and reopen."
            else:
                notice.setText("↓  Update available")
                tooltip = f"Anime Watcher {release.version} is available. Click to download and install."
            notice.setToolTip(tooltip)
            notice.setAccessibleName(tooltip)
        busy = self.app_update_download_in_progress or self.app_update_check_in_progress
        for name in ("sidebar_update_progress", "app_update_progress"):
            progress = getattr(self, name, None)
            if progress is not None and isValid(progress):
                progress.setVisible(busy)
                progress.setRange(0, 100 if self.app_update_phase == "downloading" else 0)
                progress.setValue(self.app_update_percent)
                progress.setAccessibleName(self.app_update_message)
        check = getattr(self, "check_update_button", None)
        if check is not None and isValid(check):
            check.setEnabled(not busy)
        button = getattr(self, "install_update_button", None)
        if button is None or not isValid(button):
            return
        button.setVisible(release is not None)
        button.setEnabled(not self.app_update_download_in_progress)
        if self.staged_app_update is not None:
            button.setText(f"Install {self.staged_app_update.release.version}")
        elif self.available_app_update is not None:
            button.setText(f"Download & install {self.available_app_update.version}")

    def _auto_check_for_app_update(self) -> None:
        if (self._closing or not bool(self.db.setting("app_update_auto_check", True))
                or self.app_update_check_in_progress or self.app_update_download_in_progress
                or self.staged_app_update is not None or time.time() < self._app_update_retry_at):
            return
        last_check = float(self.db.setting("app_update_last_check", 0) or 0)
        if not self._app_update_checked_this_session or time.time() - last_check >= 6 * 3600:
            self._check_for_app_update(manual=False)

    def _check_for_app_update(self, manual: bool = True) -> None:
        if self.app_update_download_in_progress or self.staged_app_update is not None:
            return
        if self.app_update_check_in_progress:
            if manual:
                self._set_app_update_status("An update check is already running…")
            return
        self.app_update_check_in_progress = True
        self._app_update_checked_this_session = True
        self.app_update_phase = "checking"
        self._set_app_update_status("Checking the official GitHub release…")
        self._refresh_app_update_button()
        worker = Worker(fetch_latest_release)
        worker.signals.done.connect(lambda release, requested=manual: self._app_update_check_ready(release, requested))
        worker.signals.failed.connect(lambda error, requested=manual: self._app_update_check_failed(error, requested))
        self._start_worker(worker)

    def _app_update_check_ready(self, release, manual: bool) -> None:
        self.app_update_check_in_progress = False
        if self.app_update_download_in_progress or self.staged_app_update is not None:
            return
        self.app_update_phase = ""
        try:
            newer = is_newer_version(release.version, __version__)
        except ValueError as exc:
            return self._app_update_check_failed(str(exc), manual)
        self.db.set_setting("app_update_last_check", time.time())
        self._app_update_retry_at = 0.0
        if not newer:
            self.available_app_update = None
            self.staged_app_update = None
            self._set_app_update_status(f"Anime Watcher {__version__} is up to date.")
            self._refresh_app_update_button()
            return
        self.available_app_update = release
        self._set_app_update_status(self._app_update_status_text())
        self._refresh_app_update_button()
        body = f"Version {release.version} is available. Use the blue Update available button in the sidebar to download and install it."
        self.db.add_notification("app-update", f"Anime Watcher {release.version} available", body, None, f"app-update|{release.version}")

    def _app_update_check_failed(self, error: str, manual: bool) -> None:
        self.app_update_check_in_progress = False
        self._app_update_checked_this_session = False
        self._app_update_retry_at = time.time() + 15 * 60
        if self.app_update_download_in_progress or self.staged_app_update is not None:
            return
        self.app_update_phase = "error"
        self._set_app_update_status(f"Update check failed: {error}")
        self._refresh_app_update_button()

    def _start_app_update_download(self) -> None:
        if self.app_update_download_in_progress:
            return
        if self.staged_app_update is not None:
            return self._install_staged_app_update()
        release = self.available_app_update
        if release is None or self.app_update_download_in_progress:
            return
        try:
            install_dir = application_install_dir()
        except Exception as exc:
            return self._app_update_download_failed(str(exc))
        self.app_update_download_in_progress = True
        self.app_update_percent = 0
        self.app_update_phase = "downloading"
        self._set_app_update_status(f"Downloading Anime Watcher {release.version}…")
        self._refresh_app_update_button()
        worker = Worker(stage_update, release, install_dir, with_progress=True)
        worker.signals.progress.connect(self._app_update_download_progress)
        worker.signals.done.connect(self._app_update_staged)
        worker.signals.failed.connect(self._app_update_download_failed)
        self._start_worker(worker)

    def _app_update_download_progress(self, values) -> None:
        received, total = values
        percent = round(received / total * 100) if total else 0
        self.app_update_percent = max(0, min(100, percent))
        self.app_update_phase = "verifying" if total and received >= total else "downloading"
        self._set_app_update_status("Verifying and preparing update…" if self.app_update_phase == "verifying" else f"Downloading update… {self.app_update_percent}%")
        self._refresh_app_update_button()

    def _app_update_download_failed(self, error: str) -> None:
        self.app_update_download_in_progress = False
        self.app_update_phase = "error"
        self._set_app_update_status(f"Update download failed: {error}. Click Update to retry.")
        self._refresh_app_update_button()

    def _app_update_staged(self, staged) -> None:
        self.app_update_download_in_progress = False
        self.staged_app_update = staged
        self._install_staged_app_update()

    def _install_staged_app_update(self) -> None:
        staged = self.staged_app_update
        if staged is None or self.app_update_download_in_progress:
            return
        if self.import_job is not None:
            self.app_update_download_in_progress = True
            self.app_update_phase = 'waiting'
            self._set_app_update_status('Finishing the import before installing and reopening…')
            self._refresh_app_update_button()
            QTimer.singleShot(1000, self._resume_update_after_import)
            return
        self.app_update_download_in_progress = True
        self.app_update_phase = "installing"
        self._set_app_update_status("Preparing to install and reopen Anime Watcher…")
        self._refresh_app_update_button()
        worker = Worker(launch_staged_update, staged, __version__)
        worker.signals.done.connect(self._app_update_installer_ready)
        worker.signals.failed.connect(self._app_update_install_failed)
        self._start_worker(worker)

    def _resume_update_after_import(self):
        if self._closing:
            return
        if self.import_job is not None:
            QTimer.singleShot(1000, self._resume_update_after_import)
            return
        self.app_update_download_in_progress = False
        self._install_staged_app_update()

    def _app_update_install_failed(self, error: str) -> None:
        self.app_update_download_in_progress = False
        self.app_update_phase = "error"
        self._set_app_update_status(f"Update could not start: {error}. Click Restart to update to retry.")
        self._refresh_app_update_button()

    def _app_update_installer_ready(self, _backup) -> None:
        self.app_update_phase = "restarting"
        self._set_app_update_status("Installing update and reopening Anime Watcher…")
        self._refresh_app_update_button()
        self.close()

    def _report_pending_app_update(self) -> None:
        receipt = read_update_receipt()
        if not receipt:
            return
        mark_update_receipt_reported(receipt)
        if receipt.get("success"):
            self.app_update_phase = "complete"
            self._set_app_update_status(f"Updated to Anime Watcher {receipt.get('version', __version__)} successfully.")
        else:
            self.app_update_phase = "error"
            self._set_app_update_status(f"Update rolled back; previous version restored. {receipt.get('error', 'Unknown update error')}")
        self._refresh_app_update_button()

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
        if self.import_job or self.library_refresh_job:
            return QMessageBox.information(self, 'Library busy', 'Wait for the import or library refresh before changing the library folder.')
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
        dialog.resize(780, 210 + 82 * len(episode_ids))
        layout = QVBoxLayout(dialog)
        title = QLabel("Episode versions")
        title.setStyleSheet("font-size:22px;font-weight:800;")
        layout.addWidget(title)
        note = QLabel("Sub and Dub share one episode when their season and episode numbers match. Use Edit episode / version to correct them or group with another episode.")
        note.setWordWrap(True)
        layout.addWidget(note)
        for episode_id in episode_ids:
            episode = self.db.episode(episode_id)
            if not episode:
                continue
            row = QHBoxLayout()
            label = QLabel(f"Episode {episode['episode']:02d}   •   {episode['language']}\n{Path(episode['path']).name}")
            label.setWordWrap(True)
            row.addWidget(label, 1)
            rename = QPushButton("Edit episode / version")
            rename.setObjectName(f"editEpisodeVersion_{episode_id}")
            delete = QPushButton("Delete")
            delete.setObjectName("danger")
            rename.clicked.connect(lambda _=False, eid=episode_id, dlg=dialog: (dlg.accept(), self._edit_episode_version(eid)))
            delete.clicked.connect(lambda _=False, eid=episode_id, dlg=dialog: (dlg.accept(), self._delete_episode(eid)))
            row.addWidget(rename)
            replace = QPushButton('Replace / upgrade'); replace.setObjectName(f'replaceEpisode_{episode_id}')
            replace.clicked.connect(lambda _=False, eid=episode_id, dlg=dialog: (dlg.accept(), self._replace_episode(eid)))
            row.addWidget(replace)
            move = QPushButton("Move to series")
            move.clicked.connect(lambda _=False, eid=episode_id, dlg=dialog: (dlg.accept(), self._move_episode(eid)))
            row.addWidget(move)
            row.addWidget(delete)
            layout.addLayout(row)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def _edit_episode_version(self, episode_id: int) -> None:
        root = self._require_library()
        episode = self.db.episode(episode_id)
        if root is None or episode is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit episode and version")
        dialog.resize(680, 370)
        form = QFormLayout(dialog)
        note = QLabel("Choose the episode this file belongs to and its Sub/Dub version. Files with the same season and episode appear together and count as one episode. Watch progress and subtitles stay attached.")
        note.setWordWrap(True)
        form.addRow(note)
        filename = QLabel(Path(episode["path"]).name); filename.setWordWrap(True)
        form.addRow("File", filename)
        group = QComboBox(); group.setObjectName("versionGroupEpisode")
        group.addItem("Keep / enter season and episode below", None)
        slots = defaultdict(set)
        for row in self.db.episodes(int(episode["series_id"])):
            if int(row["id"]) != episode_id:
                slots[(int(row["season"]), int(row["episode"]))].add(str(row["language"]))
        for slot, languages in sorted(slots.items()):
            group.addItem(f"Season {slot[0]:02d} · Episode {slot[1]:02d} · {' / '.join(sorted(languages))}", slot)
        season = QSpinBox(); season.setObjectName("versionSeason"); season.setRange(0, 999); season.setValue(int(episode["season"]))
        number = QSpinBox(); number.setObjectName("versionEpisode"); number.setRange(0, 9999); number.setValue(int(episode["episode"]))
        language = QComboBox(); language.setObjectName("versionLanguage"); language.addItems(["Sub", "Dub", "Unknown"]); language.setCurrentText(str(episode["language"]))
        form.addRow("Group with episode", group)
        form.addRow("Season", season); form.addRow("Episode", number); form.addRow("Version", language)
        preview = QLabel(); preview.setObjectName("versionPreview"); preview.setWordWrap(True)
        form.addRow(preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        def update_preview():
            try:
                plan = plan_episode_version_update(self.db, root, episode_id, season.value(), number.value(), language.currentText())
                versions = sorted(slots.get((plan.season, plan.episode), set()) | {plan.language})
                preview.setText(f"Season {plan.season:02d} · Episode {plan.episode:02d} · {' / '.join(versions)}\nThese versions count as one episode.\nSave as: {plan.destination.name}")
                save.setEnabled(True)
            except Exception as exc:
                preview.setText(str(exc)); save.setEnabled(False)

        def select_group():
            slot = group.currentData()
            season.setEnabled(slot is None); number.setEnabled(slot is None)
            if slot is not None:
                season.setValue(slot[0]); number.setValue(slot[1])
            update_preview()

        group.currentIndexChanged.connect(select_group)
        season.valueChanged.connect(update_preview); number.valueChanged.connect(update_preview)
        language.currentTextChanged.connect(update_preview)
        update_preview()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if self.current_episode_id == episode_id:
            self._save_progress(stop=True)
        try:
            series_id = update_episode_version(self.db, root, episode_id, season.value(), number.value(), language.currentText())
        except Exception as exc:
            return QMessageBox.critical(self, "Version update failed", str(exc))
        self.show_series(series_id)

    def _move_episode(self, episode_id: int) -> None:
        root = self._require_library()
        row = self.db.episode(episode_id)
        if root is None or row is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Move to series")
        dialog.resize(620, 230)
        form = QFormLayout(dialog)
        note = QLabel("Choose an existing series or type a new one. Watch progress and subtitles stay attached.")
        note.setWordWrap(True)
        form.addRow(note)
        target = QComboBox(); target.setEditable(True)
        for series in self.db.series():
            target.addItem(series["display_title"] or series["title"], series["title"])
        current = self.db.get_series(int(row["series_id"]))
        target.setCurrentIndex(target.findData(current["title"]))
        season = QSpinBox(); season.setRange(0, 999)
        number = QSpinBox(); number.setRange(0, 9999)
        source_title = str(read_youtube_metadata(row["path"]).get("title") or video_title(Path(row["path"]).stem))

        def selected_title():
            index = target.currentIndex()
            return target.currentData() if index >= 0 and target.currentText() == target.itemText(index) else target.currentText().strip()

        def update_slot():
            title = selected_title()
            existing = next((series for series in self.db.series() if series["title"] == title), None)
            episodes = [episode for episode in self.db.episodes(existing["id"]) if int(episode["id"]) != episode_id] if existing else []
            suggested_season, suggested_episode = suggested_slot(source_title, episodes, int(row["season"]))
            season.setValue(suggested_season)
            number.setValue(suggested_episode)

        target.currentTextChanged.connect(update_slot)
        update_slot()
        form.addRow("Series", target)
        form.addRow("Season", season)
        form.addRow("Episode", number)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted or not selected_title():
            return
        if self.current_episode_id == episode_id:
            self._save_progress(stop=True)
        try:
            target_id = move_library_episode(self.db, root, episode_id, selected_title(), season.value(), number.value())
        except Exception as exc:
            return QMessageBox.critical(self, "Move failed", str(exc))
        self.show_series(target_id)

    def _bulk_move_episodes(self, episode_ids) -> None:
        root = self._require_library()
        rows = [self.db.episode(eid) for eid in dict.fromkeys(episode_ids)]
        if root is None or not rows or any(row is None for row in rows):
            return
        rows.sort(key=lambda row: (row["series_id"], row["season"], row["episode"], row["language"], row["path"]))
        dialog = QDialog(self); dialog.setWindowTitle("Move episodes to series"); dialog.resize(820, 650)
        layout = QVBoxLayout(dialog)
        note = QLabel("Choose the episodes and destination. Episode numbers, versions, subtitles, and watch progress stay attached.")
        note.setWordWrap(True); layout.addWidget(note)
        form = QFormLayout()
        target = QComboBox(); target.setEditable(True); target.setObjectName("bulkMoveTarget")
        for series in self.db.series():
            target.addItem(series["display_title"] or series["title"], series["title"])
        current = self.db.get_series(int(rows[0]["series_id"]))
        target.setCurrentIndex(target.findData(current["title"]))
        same_season = QCheckBox("Set season for all selected episodes"); same_season.setObjectName("bulkSetSeason")
        same_season.setChecked(True)
        season = QSpinBox(); season.setObjectName("bulkMoveSeason"); season.setRange(0, 999); season.setValue(int(rows[0]["season"]))
        same_season.toggled.connect(season.setEnabled)
        renumber = QCheckBox("Renumber episodes in order, starting at"); renumber.setObjectName("bulkRenumber")
        first = QSpinBox(); first.setObjectName("bulkFirstEpisode"); first.setRange(0, 9999); first.setValue(1); first.setEnabled(False)
        renumber.toggled.connect(first.setEnabled)
        form.addRow("Series", target); form.addRow(same_season, season); form.addRow(renumber, first)
        layout.addLayout(form)
        controls = QHBoxLayout()
        filter_season = QComboBox(); filter_season.addItem("All source seasons", None)
        for value in sorted({int(row["season"]) for row in rows}):
            filter_season.addItem(f"Source season {value}", value)
        filter_season.setObjectName("bulkSourceSeason")
        all_button = QPushButton("Select shown"); clear = QPushButton("Clear selection")
        controls.addWidget(filter_season); controls.addWidget(all_button); controls.addWidget(clear); controls.addStretch(1)
        layout.addLayout(controls)
        scroll, _, body = self._scroll(); layout.addWidget(scroll, 1)
        boxes = {}
        for row in rows:
            checkbox = QCheckBox(f"{row['series_title']} · S{row['season']:02d}E{row['episode']:02d} · {row['language']}\n{Path(row['path']).name}")
            checkbox.setObjectName(f"bulkEpisode_{row['id']}"); checkbox.setChecked(True)
            boxes[int(row["id"])] = checkbox; body.addWidget(checkbox)
        body.addStretch(1)
        preview = QLabel(); preview.setWordWrap(True); layout.addWidget(preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save = buttons.button(QDialogButtonBox.StandardButton.Save); save.setText("Move episodes")
        layout.addWidget(buttons)

        def selected_title():
            index = target.currentIndex()
            return target.currentData() if index >= 0 and target.currentText() == target.itemText(index) else target.currentText().strip()

        def selected_ids():
            value = filter_season.currentData()
            return [int(row["id"]) for row in rows if boxes[int(row["id"])].isChecked() and (value is None or row["season"] == value)]

        def update_preview():
            source_season = filter_season.currentData()
            for row in rows:
                boxes[int(row["id"])].setVisible(source_season is None or row["season"] == source_season)
            try:
                plans = plan_library_episode_moves(self.db, root, selected_ids(), selected_title(),
                    season.value() if same_season.isChecked() else None, first.value() if renumber.isChecked() else None)
                slots = sorted({(plan.season, plan.episode) for plan in plans})
                example = plans[0].destination.relative_to(root)
                preview.setText(f"{len(plans)} files / {len(slots)} episodes → {selected_title()}\nExample: {example}")
                save.setEnabled(True)
            except Exception as exc:
                preview.setText(str(exc)); save.setEnabled(False)

        def select_shown():
            value = filter_season.currentData()
            for row in rows:
                if value is None or row["season"] == value:
                    with QSignalBlocker(boxes[int(row["id"])]):
                        boxes[int(row["id"])].setChecked(True)
            update_preview()

        def clear_selection():
            for box in boxes.values():
                with QSignalBlocker(box):
                    box.setChecked(False)
            update_preview()

        all_button.clicked.connect(select_shown)
        clear.clicked.connect(clear_selection)
        for box in boxes.values(): box.toggled.connect(update_preview)
        target.currentTextChanged.connect(update_preview); season.valueChanged.connect(update_preview)
        first.valueChanged.connect(update_preview); renumber.toggled.connect(update_preview)
        same_season.toggled.connect(update_preview); filter_season.currentIndexChanged.connect(update_preview)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        update_preview()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        ids = selected_ids()
        if not ids:
            return
        if self.current_episode_id in ids:
            self._save_progress(stop=True)
        try:
            target_id = move_library_episodes(self.db, root, ids, selected_title(),
                season.value() if same_season.isChecked() else None, first.value() if renumber.isChecked() else None)
        except Exception as exc:
            return QMessageBox.critical(self, "Bulk move failed", str(exc))
        self.show_series(target_id)

    def _rename_series(self, series_id: int) -> None:
        series = self.db.get_series(series_id)
        root = self._require_library()
        if not series or root is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Rename series" if series["library_type"] == "YouTube" else "Rename anime")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Rename the series and all episode files. Watch progress stays attached."))
        entry = QLineEdit(series["title"])
        layout.addWidget(entry)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted or not entry.text().strip():
            return
        if self.current_episode_id:
            playing = self.db.episode(self.current_episode_id)
            if playing and int(playing["series_id"]) == series_id:
                self._save_progress(stop=True)
        plans = None
        try:
            plans = rename_series_files(self.db.episodes(series_id), root, entry.text().strip())
            clean_title = next(iter(plans.values()))[1].relative_to(root).parts[0]
            self.db.rename_series(series_id, clean_title, {eid: dst for eid, (_, dst) in plans.items()})
            self.db.scan_library(root)
        except Exception as exc:
            if plans:
                try:
                    rollback_series_files(plans, root)
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
        if self.current_episode_id == episode_id:
            self._save_progress(stop=True)
        destination = None
        try:
            destination = rename_episode_file(source, root, title.text().strip(), season.value(), number.value(), language.currentText())
            clean_title = destination.relative_to(root).parts[0]
            target_series = self.db.relocate_episode(episode_id, destination, clean_title, season.value(), number.value(), language.currentText())
            self.db.scan_library(root)
        except Exception as exc:
            if destination is not None and destination != source and destination.exists() and not source.exists():
                move_episode_bundle(destination, source, root)
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
        if self.current_episode_id == episode_id:
            self._save_progress(stop=True)
        try:
            send_to_recycle_bin(path, root)
            self.db.scan_library(root)
        except Exception as exc:
            return QMessageBox.critical(self, "Delete failed", str(exc))
        series_id = int(episode["series_id"])
        self.show_series(series_id) if self.db.get_series(series_id) else self.show_library()

    def _refresh_metadata(self, series_id: int, title: str | None = None) -> None:
        series = self.db.get_series(series_id)
        if not series or series["library_type"] == "YouTube":
            return
        lookup_title = title or series["title"]
        worker = Worker(fetch_metadata, lookup_title, self.data_root / "posters")
        worker.signals.done.connect(lambda data, database=self.db.path, expected=series["title"]: self._metadata_ready(series_id, data, database, expected))
        worker.signals.failed.connect(lambda error: QMessageBox.warning(self, "Metadata lookup failed", error))
        self._start_worker(worker)

    def _metadata_ready(self, series_id: int, data: dict, database=None, expected_title=None) -> None:
        if self._closing:
            return
        owner = self.db if database is None or self.db.path == database else LibraryDatabase(database) if Path(database).is_file() else None
        try:
            series = owner.get_series(series_id) if owner else None
            if not series or series["library_type"] == "YouTube" or expected_title is not None and series["title"] != expected_title:
                return
            owner.update_metadata(series_id, data["title"], data["synopsis"], data["poster_path"], data["id"], data.get("year"))
            for key in list(self.download_metadata):
                if key[0] == owner.path and key[2] == series["title"].casefold():
                    self.download_metadata[key] = data
                    self._render_catalog_artwork(key, data)
                    for job in list(self.download_queue.jobs.values()):
                        if self._download_metadata_key(job) == key:
                            self._download_queue_changed(job.id)
        finally:
            if owner is not None and owner is not self.db:
                owner.close()
        if owner is self.db and self.visible_series_id == series_id and self.stack.currentWidget() is getattr(self, "_series_page", None):
            self.show_series(series_id)

    def _auto_metadata(self) -> None:
        if self._closing or self.metadata_lookup_in_progress:
            return
        for key in list(self.catalog_artwork_pending):
            if self.stack.currentWidget() is not self._download_page or key[:2] != (self.db.path, self.library_root) or not any(token == self.catalog_token and isValid(thumbnail) for token, thumbnail, _year in self.catalog_artwork_rows.get(key, [])):
                self.catalog_artwork_pending.pop(key)
        if self.download_metadata_pending:
            key = next(iter(self.download_metadata_pending))
            title = self.download_metadata_pending.pop(key)
            self.download_metadata_inflight = key
            worker = Worker(fetch_metadata, title, self.data_root / "posters")
            worker.signals.done.connect(lambda data: self._download_metadata_ready(key, title, data))
            worker.signals.failed.connect(lambda _error: self._render_catalog_artwork(key))
        elif self.catalog_artwork_pending:
            key = next(iter(self.catalog_artwork_pending))
            title = self.catalog_artwork_pending.pop(key)
            self.download_metadata_inflight = key
            worker = Worker(fetch_metadata, title, self.data_root / "posters")
            worker.signals.done.connect(lambda data: self._catalog_artwork_ready(key, title, data))
            worker.signals.failed.connect(lambda _error: self._render_catalog_artwork(key))
        else:
            missing = [row for row in self.db.series(library_type="Anime") if (not row["metadata_updated"] or not row["metadata_year_checked"]) and (self.db.path, int(row["id"])) not in self.metadata_attempted]
            if not missing:
                return
            series = missing[0]
            self.metadata_attempted.add((self.db.path, int(series["id"])))
            worker = Worker(fetch_metadata, series["title"], self.data_root / "posters")
            worker.signals.done.connect(lambda data, sid=int(series["id"]), database=self.db.path, expected=series["title"]: self._metadata_ready(sid, data, database, expected))
        self.metadata_lookup_in_progress = True
        worker.signals.done.connect(lambda _data: self._metadata_lookup_finished())
        worker.signals.failed.connect(lambda _error: self._metadata_lookup_finished())
        self._start_worker(worker)

    def _metadata_lookup_finished(self):
        self.metadata_lookup_in_progress = False
        self.download_metadata_inflight = None
        QTimer.singleShot(600, self._auto_metadata)

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
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        self.video_frame = CompositedVideoSurface()
        self.video_frame.setMouseTracking(True)
        self.video_frame.installEventFilter(self)
        self.video_frame.viewport().setMouseTracking(True)
        self.video_frame.viewport().installEventFilter(self)
        page_layout.addWidget(self.video_frame)

        self.player_top = QFrame(page)
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
        self.player_controls = QFrame(page)
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
        self.controls_visible = False
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
        render_width, render_height = capped_ass_frame_size(content_width, content_height)
        try:
            result = self.ass_renderer.render(
                position - self.subtitle_delay_ms,
                render_width,
                render_height,
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
        pixmap = QPixmap.fromImage(image)
        scale_x = content_width / render_width
        scale_y = content_height / render_height
        if render_width != content_width or render_height != content_height:
            pixmap = pixmap.scaled(
                max(1, round(bitmap.width * scale_x)),
                max(1, round(bitmap.height * scale_y)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.video_frame.show_subtitle_bitmap(
            pixmap,
            content_x + round(bitmap.x * scale_x),
            content_y + round(bitmap.y * scale_y),
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
        top_height = self.player_top.sizeHint().height()
        controls_height = self.player_controls.sizeHint().height()
        self.player_top.setGeometry(0, 0, page.width(), top_height)
        self.player_controls.setGeometry(
            0,
            max(0, page.height() - controls_height),
            page.width(),
            controls_height,
        )
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
        player_page = getattr(self, "player_page", None)
        if player_page is not None and watched is player_page and event.type() == QEvent.Type.Resize:
            self.player_layout_timer.start()
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
        if self.controls_visible and self.player_controls.isVisible():
            if self.player_settings.isVisible():
                self.hide_timer.stop()
            else:
                self.hide_timer.start(3000)
            return
        self.controls_visible = True
        self.player_top.setVisible(not self.pip_active)
        self.player_controls.show()
        self.player_top.raise_()
        self.player_controls.raise_()
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
        if self.ass_renderer is None:
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
                self.current_episode_id = None
                self.current_video_path = None
                self.player.stop()

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
            self.player_layout_timer.start()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self._toggle_fullscreen()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.import_job is not None:
            self.import_message = 'Finishing the verified import before closing…'; self._render_import_status()
            QTimer.singleShot(250, self.close); event.ignore(); return
        self.download_queue.stop()
        if any(runtime["dialog"].worker and runtime["dialog"].worker.isRunning() for runtime in self.wco_downloads.values()):
            QTimer.singleShot(250, self.close)
            event.ignore()
            return
        self._closing = True
        self.catalog_quality_timer.stop()
        self.catalog_quality_groups.clear()
        self._cancel_catalog_quality_probe()
        self._save_download_snapshot()
        self.download_snapshot_timer.stop()
        self.wco_download_timer.stop()
        for runtime in self.youtube_jobs.values():
            runtime["cancel"].set()
        self._save_progress(stop=True)
        self._clear_external_subtitles()
        self.tray.hide()
        self.player.release()
        session = getattr(self, "wco_session", None)
        if session is not None:
            session.close()
        self.db.close()
        event.accept()


def _install_ui_hang_watchdog(app: QApplication) -> None:
    """Dump all Python stacks locally if the Qt event loop stalls for eight seconds."""
    try:
        data_root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "AnimeWatcher"
        data_root.mkdir(parents=True, exist_ok=True)
        log_file = (data_root / "crash.log").open("a", encoding="utf-8", buffering=1)
    except OSError:
        return

    heartbeat = QTimer(app)
    heartbeat.setInterval(2000)
    heartbeat.setTimerType(Qt.TimerType.CoarseTimer)

    def arm() -> None:
        faulthandler.cancel_dump_traceback_later()
        faulthandler.dump_traceback_later(8, repeat=False, file=log_file)

    def stop() -> None:
        faulthandler.cancel_dump_traceback_later()
        log_file.close()

    heartbeat.timeout.connect(arm)
    app.aboutToQuit.connect(stop)
    heartbeat.start()
    arm()
    app._anime_watcher_hang_watchdog = (heartbeat, log_file)


def run() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Anime Watcher")
    app.setOrganizationName("AnimeWatcher")
    app.setStyle("Fusion")
    _install_ui_hang_watchdog(app)
    window = AnimeWatcherWindow()
    window.show()
    return app.exec()
