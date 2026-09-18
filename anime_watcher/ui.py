from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections import defaultdict
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw

from .database import LibraryDatabase
from .downloader import CatalogResult, EpisodeResult, download_authorized_file, load_catalog_episodes, search_catalog
from .library_actions import (
    LANGUAGES,
    rename_episode_file,
    rename_series_files,
    rollback_series_files,
    send_to_recycle_bin,
)
from .metadata import fetch_metadata
from .organizer import VIDEO_EXTENSIONS, organize_files, scan_video_files
from .player import VLCPlayer
from .preview import (
    cached_video_preview,
    generate_video_preview,
    nearest_cached_video_preview,
    preview_bucket,
    preview_cache_path,
    preview_warmup_targets,
)
from .text_helpers import marquee_frame
from .windowing import geometry_for_bounds, monitor_bounds_for_window


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG = "#090B10"
PANEL = "#11151D"
PANEL_2 = "#181E29"
TEXT = "#F5F7FB"
MUTED = "#9AA4B3"
ACCENT = "#8B5CF6"
ACCENT_HOVER = "#7C3AED"
PINK = "#EC4899"
OVERLAY_TRANSPARENT = "#010203"
# Video encoders commonly require even dimensions. 240×136 is effectively a
# 25% reduction from the old 320×180 preview without producing blank frames.
PREVIEW_IMAGE_SIZE = (240, 136)
PREVIEW_POPUP_SIZE = (248, 170)


def library_root_from_setting(value: object) -> Path | None:
    """Return a configured library path without inventing a first-run default."""
    text = str(value or "").strip()
    return Path(text) if text else None


def resource_path(*parts: str) -> Path:
    """Resolve bundled assets in both source and PyInstaller builds."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)


def format_time(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


class AnimeWatcherApp(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=BG)
        self.title("Anime Watcher")
        self.geometry("1420x900")
        self.minsize(1180, 720)
        self._set_app_icon()

        data_root = Path(os.environ.get("ANIME_WATCHER_DATA_DIR") or
                         Path(os.environ.get("APPDATA", Path.home())) / "AnimeWatcher")
        data_root.mkdir(parents=True, exist_ok=True)
        self.data_root = data_root
        self.db = LibraryDatabase(data_root / "library.db")
        self.library_root = library_root_from_setting(self.db.setting("library_root", ""))

        try:
            self.player = VLCPlayer()
        except Exception as exc:
            messagebox.showerror("VLC is required", f"Anime Watcher could not start VLC.\n\n{exc}\n\nInstall VLC from videolan.org.")
            raise

        self.current_episode_id: int | None = None
        self._last_saved = 0
        self._seeking = False
        self._timeline_hovered = False
        self._known_duration_ms = 0
        self._images: list[ctk.CTkImage] = []
        self._fullscreen = False
        self._fullscreen_restore: tuple[str, str] | None = None
        self._controls_hide_job = None
        self._last_pointer_pos = None
        self._overlay_sync_job = None
        self._last_overlay_geometry = None
        self._controls_visible = False
        self._overlays_suspended = False
        self._current_video_path: str | None = None
        self._preview_request_job = None
        self._preview_wait_job = None
        self._preview_hide_job = None
        self._preview_request_token = 0
        self._preview_requested_bucket = None
        self._preview_loaded_bucket = None
        self._preview_displayed_path: Path | None = None
        self._preview_ctk_image = None
        self._pending_seek_ms = 0
        self._preview_generation_lock = threading.Lock()
        self._preview_failures: dict[int, str] = {}
        self._preview_warmup_token = 0
        self._visible_series_id: int | None = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        self.bind("<space>", lambda _e: self._toggle_play())
        self.bind("<Left>", lambda _e: self._seek_relative(-10000))
        self.bind("<Right>", lambda _e: self._seek_relative(10000))
        self.bind("<Key-k>", lambda _e: self._toggle_play())
        self.bind("<Key-j>", lambda _e: self._seek_relative(-10000))
        self.bind("<Key-l>", lambda _e: self._seek_relative(10000))
        self.bind("<Key-f>", lambda _e: self._toggle_fullscreen() if self.current_episode_id else None)
        self.bind("<Key-n>", lambda _e: self._change_episode(1))
        self.bind("<Motion>", self._player_motion, add="+")
        self.bind("<Configure>", self._player_window_configure, add="+")
        self.bind("<Escape>", lambda _e: self._leave_fullscreen())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if self.library_root:
            self._scan(show_status=False)
            self.show_home()
        else:
            self.show_settings()
        self.after(1000, self._player_tick)
        self.after(150, self._poll_player_pointer)

    def _set_app_icon(self) -> None:
        """Use the project logo for the title bar, taskbar, and packaged app."""
        icon_file = resource_path("assets", "anime_watcher.ico")
        logo_file = resource_path("assets", "anime_watcher_logo.png")
        try:
            if icon_file.is_file():
                self.iconbitmap(default=str(icon_file))
        except Exception:
            pass
        try:
            if logo_file.is_file():
                from tkinter import PhotoImage

                self._app_icon = PhotoImage(file=str(logo_file))
                self.iconphoto(True, self._app_icon)
        except Exception:
            pass
        self.after(1800, self._auto_metadata)

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(self, width=230, fg_color=PANEL, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        ctk.CTkLabel(self.sidebar, text="桜  ANIME", font=ctk.CTkFont(size=23, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=25, pady=(28, 4))
        ctk.CTkLabel(self.sidebar, text="WATCHER", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=PINK).pack(anchor="w", padx=58, pady=(0, 34))

        self.nav_buttons = {}
        for label, command in [
            ("⌂   Home", self.show_home),
            ("▦   Library", self.show_library),
            ("▶   Continue", self.show_continue),
            ("＋   Import", self.show_import),
            ("↓   Downloads", self.show_downloads),
            ("⚙   Settings", self.show_settings),
        ]:
            button = ctk.CTkButton(self.sidebar, text=label, command=command, anchor="w", height=44,
                                   corner_radius=10, fg_color="transparent", hover_color=PANEL_2,
                                   font=ctk.CTkFont(size=15), text_color=MUTED)
            button.pack(fill="x", padx=14, pady=3)
            self.nav_buttons[label] = button

        ctk.CTkLabel(self.sidebar, text="LOCAL LIBRARY", text_color="#626C7A",
                     font=ctk.CTkFont(size=10, weight="bold")).pack(side="bottom", anchor="w", padx=25, pady=(0, 4))
        self.sidebar_status = ctk.CTkLabel(self.sidebar, text=self._library_status_text(), wraplength=180,
                                           justify="left", text_color=MUTED, font=ctk.CTkFont(size=11))
        self.sidebar_status.pack(side="bottom", anchor="w", padx=25, pady=(0, 25))

    def _library_status_text(self) -> str:
        return str(self.library_root) if self.library_root else "No library folder selected"

    def _require_library_root(self) -> Path | None:
        if self.library_root:
            return self.library_root
        messagebox.showwarning(
            "Choose a library folder",
            "Open Settings and choose where Anime Watcher should keep your anime library first.",
        )
        self.show_settings()
        return None

    def _clear(self) -> None:
        self._save_current_progress()
        self._set_player_mode(False)
        self._visible_series_id = None
        for child in self.content.winfo_children():
            child.destroy()
        self._images.clear()
        self.content.grid_rowconfigure(0, weight=0)
        self.content.grid_rowconfigure(1, weight=1)

    def _set_player_mode(self, enabled: bool) -> None:
        if enabled:
            self.sidebar.grid_remove()
            self.content.grid_configure(column=0, columnspan=2)
        else:
            if self._controls_hide_job is not None:
                try:
                    self.after_cancel(self._controls_hide_job)
                except ValueError:
                    pass
                self._controls_hide_job = None
            self.configure(cursor="")
            self._destroy_player_overlays()
            self.sidebar.grid()
            self.content.grid_configure(column=1, columnspan=1)

    def _marquee_label(
        self,
        parent,
        text: str,
        visible_chars: int,
        *,
        start_delay: int = 1500,
        interval: int = 125,
        **label_options,
    ) -> ctk.CTkLabel:
        """Create a title label that only scrolls when its text is too long."""
        preview = text if len(text) <= visible_chars else f"{text[:visible_chars - 1]}…"
        label = ctk.CTkLabel(parent, text=preview, **label_options)
        if len(text) <= visible_chars:
            return label

        state = {"offset": 0}

        def advance() -> None:
            try:
                if not label.winfo_exists():
                    return
                label.configure(text=marquee_frame(text, state["offset"], visible_chars))
                state["offset"] += 1
                label.after(interval, advance)
            except Exception:
                # A page change can destroy the label between the existence check
                # and the configure call. The marquee can simply stop in that case.
                return

        label.after(start_delay, advance)
        return label

    def _header(self, title: str, subtitle: str = "", search: bool = False) -> ctk.CTkFrame:
        header = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0, height=108)
        header.grid(row=0, column=0, sticky="ew", padx=34, pady=(22, 4))
        header.grid_columnconfigure(0, weight=1)
        self._marquee_label(header, title, 52, text_color=TEXT, anchor="w",
                            font=ctk.CTkFont(size=30, weight="bold")).grid(row=0, column=0, sticky="w")
        if subtitle:
            ctk.CTkLabel(header, text=subtitle, text_color=MUTED,
                         font=ctk.CTkFont(size=13)).grid(row=1, column=0, sticky="w", pady=(5, 0))
        if search:
            entry = ctk.CTkEntry(header, width=300, height=40, placeholder_text="Search your collection…",
                                 fg_color=PANEL_2, border_width=0)
            entry.grid(row=0, column=1, rowspan=2, padx=(20, 0))
            entry.bind("<KeyRelease>", lambda _e: self._render_library(entry.get()))
        return header

    def _scroll_area(self) -> ctk.CTkScrollableFrame:
        area = ctk.CTkScrollableFrame(self.content, fg_color=BG, corner_radius=0,
                                      scrollbar_button_color="#303848")
        area.grid(row=1, column=0, sticky="nsew", padx=22, pady=(0, 18))
        return area

    def _placeholder(self, size=(210, 300)) -> ctk.CTkImage:
        image = Image.new("RGB", size, "#242A37")
        draw = ImageDraw.Draw(image)
        draw.ellipse((size[0] // 2 - 28, size[1] // 2 - 28, size[0] // 2 + 28, size[1] // 2 + 28), fill="#8B5CF6")
        draw.polygon([(size[0] // 2 - 8, size[1] // 2 - 15), (size[0] // 2 - 8, size[1] // 2 + 15),
                      (size[0] // 2 + 18, size[1] // 2)], fill="white")
        result = ctk.CTkImage(image, size=size)
        self._images.append(result)
        return result

    def _poster(self, path: str | None, size=(180, 255)) -> ctk.CTkImage:
        if path and Path(path).exists():
            try:
                image = Image.open(path).convert("RGB")
                target_ratio = size[0] / size[1]
                ratio = image.width / image.height
                if ratio > target_ratio:
                    width = int(image.height * target_ratio)
                    left = (image.width - width) // 2
                    image = image.crop((left, 0, left + width, image.height))
                else:
                    height = int(image.width / target_ratio)
                    top = (image.height - height) // 2
                    image = image.crop((0, top, image.width, top + height))
                result = ctk.CTkImage(image, size=size)
                self._images.append(result)
                return result
            except OSError:
                pass
        return self._placeholder(size)

    def show_home(self) -> None:
        self._clear()
        all_series = self.db.series()
        continues = self.db.continue_watching(8)
        self._header("Welcome back", f"{len(all_series)} series • {sum(row['episode_count'] for row in all_series)} episodes ready")
        area = self._scroll_area()
        area.grid_columnconfigure(0, weight=1)
        if continues:
            ctk.CTkLabel(area, text="Continue watching", text_color=TEXT,
                         font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 14))
            strip = ctk.CTkFrame(area, fg_color="transparent")
            strip.grid(row=1, column=0, sticky="ew")
            for index, episode in enumerate(continues[:4]):
                self._continue_card(strip, episode, index)
        ctk.CTkLabel(area, text="Your collection", text_color=TEXT,
                     font=ctk.CTkFont(size=20, weight="bold")).grid(row=2, column=0, sticky="w", padx=12, pady=(28, 14))
        grid = ctk.CTkFrame(area, fg_color="transparent")
        grid.grid(row=3, column=0, sticky="ew")
        for index, series in enumerate(all_series[:10]):
            self._series_card(grid, series, index)
        if not all_series:
            self._empty_library(area, 4)

    def _continue_card(self, parent, episode, index: int) -> None:
        card = ctk.CTkButton(parent, text="", command=lambda eid=episode["id"]: self.play_episode(eid),
                            width=250, height=140, fg_color=PANEL_2, hover_color="#252D3B", corner_radius=14)
        card.grid(row=0, column=index, padx=8, sticky="nw")
        card.grid_columnconfigure(0, weight=1)
        self._marquee_label(card, episode["series_title"], 27, text_color=TEXT, anchor="w", width=215,
                            font=ctk.CTkFont(size=14, weight="bold")).grid(
                                row=0, column=0, sticky="w", padx=16, pady=(17, 4))
        ctk.CTkLabel(card, text=f"S{episode['season']:02d} • Episode {episode['episode']} • {episode['language']}",
                     text_color=MUTED, font=ctk.CTkFont(size=11)).grid(row=1, column=0, sticky="w", padx=16)
        progress = (episode["progress_ms"] / episode["duration_ms"]) if episode["duration_ms"] else 0
        bar = ctk.CTkProgressBar(card, width=215, height=6, progress_color=PINK, fg_color="#343B49")
        bar.grid(row=2, column=0, padx=16, pady=(23, 5))
        bar.set(progress)
        ctk.CTkLabel(card, text=f"{format_time(episode['progress_ms'])} / {format_time(episode['duration_ms'])}",
                     text_color=MUTED, font=ctk.CTkFont(size=10)).grid(row=3, column=0, sticky="w", padx=16)

    def show_library(self) -> None:
        self._clear()
        self._header("Library", "Every series, season, and episode in one place", search=True)
        self.library_area = self._scroll_area()
        self._render_library("")

    def _render_library(self, search: str) -> None:
        if not hasattr(self, "library_area") or not self.library_area.winfo_exists():
            return
        for child in self.library_area.winfo_children():
            child.destroy()
        rows = self.db.series(search)
        for column in range(5):
            self.library_area.grid_columnconfigure(column, weight=1)
        for index, series in enumerate(rows):
            self._series_card(self.library_area, series, index)
        if not rows:
            self._empty_library(self.library_area, 0)

    def _series_card(self, parent, series, index: int) -> None:
        card = ctk.CTkFrame(parent, width=195, height=340, fg_color="transparent")
        card.grid(row=index // 5, column=index % 5, padx=10, pady=12, sticky="n")
        card.grid_propagate(False)
        image = self._poster(series["poster_path"], (180, 255))
        poster = ctk.CTkButton(card, image=image, text="", width=180, height=255, corner_radius=12,
                              fg_color=PANEL_2, hover_color="#2B3342", command=lambda sid=series["id"]: self.show_series(sid))
        poster.pack()
        title = series["display_title"] or series["title"]
        self._marquee_label(card, title, 25, text_color=TEXT, anchor="w", width=182,
                            font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", pady=(9, 2))
        ctk.CTkLabel(card, text=f"{series['episode_count']} episodes",
                     text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w")

    def _empty_library(self, parent, row: int) -> None:
        empty = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=18, height=260)
        empty.grid(row=row, column=0, columnspan=5, sticky="ew", padx=12, pady=20)
        configured = self.library_root is not None
        title = "Your library is ready for its first arc" if configured else "Choose your anime library folder"
        detail = ("Import episode files or choose a folder to start watching." if configured else
                  "Anime Watcher will not create or scan a drive until you choose a folder in Settings.")
        button_text = "Import episodes" if configured else "Choose library folder"
        button_command = self.show_import if configured else self.show_settings
        ctk.CTkLabel(empty, text=title, text_color=TEXT,
                     font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(55, 8))
        ctk.CTkLabel(empty, text=detail, text_color=MUTED).pack()
        ctk.CTkButton(empty, text=button_text, command=button_command, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, height=40).pack(pady=22)

    def show_series(self, series_id: int) -> None:
        self._clear()
        series = self.db.get_series(series_id)
        if not series:
            return self.show_library()
        self._visible_series_id = series_id
        header = self._header(series["display_title"] or series["title"], "Choose an episode or continue where you left off")
        header_actions = ctk.CTkFrame(header, fg_color="transparent")
        header_actions.grid(row=0, column=1, rowspan=2)
        ctk.CTkButton(header_actions, text="Rename anime", command=lambda: self._rename_series_dialog(series_id),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, width=126).pack(side="left", padx=(0, 8))
        ctk.CTkButton(header_actions, text="↻  Fetch poster & details", command=lambda: self._refresh_metadata(series_id),
                      fg_color=PANEL_2, hover_color="#283142", width=180).pack(side="left")
        area = self._scroll_area()
        area.grid_columnconfigure(1, weight=1)
        poster = self._poster(series["poster_path"], (230, 325))
        ctk.CTkLabel(area, image=poster, text="").grid(row=0, column=0, sticky="nw", padx=(12, 28), pady=10)
        info = ctk.CTkFrame(area, fg_color="transparent")
        info.grid(row=0, column=1, sticky="nsew", pady=10)
        synopsis = series["synopsis"] or "Fetch metadata to add the official title, synopsis, and poster."
        ctk.CTkLabel(info, text=synopsis, wraplength=760, justify="left", anchor="nw", text_color=MUTED,
                     font=ctk.CTkFont(size=13)).pack(fill="x", pady=(0, 22))
        episodes = self.db.episodes(series_id)
        grouped = defaultdict(list)
        for episode in episodes:
            grouped[episode["season"]].append(episode)
        for season, season_episodes in grouped.items():
            ctk.CTkLabel(info, text=f"Season {season:02d}", text_color=TEXT,
                         font=ctk.CTkFont(size=19, weight="bold")).pack(anchor="w", pady=(12, 8))
            for episode in season_episodes:
                self._episode_row(info, episode)

    def _episode_row(self, parent, episode) -> None:
        row = ctk.CTkButton(parent, text="", command=lambda eid=episode["id"]: self.play_episode(eid),
                            fg_color=PANEL, hover_color=PANEL_2, corner_radius=10, height=60)
        row.pack(fill="x", pady=4)
        row.grid_columnconfigure(1, weight=1)
        watched = "✓" if episode["completed"] else "▶"
        ctk.CTkLabel(row, text=watched, text_color=PINK if episode["completed"] else ACCENT,
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=16)
        ctk.CTkLabel(row, text=f"Episode {episode['episode']:02d}", text_color=TEXT,
                     font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(row, text=episode["language"], text_color=MUTED,
                     font=ctk.CTkFont(size=11)).grid(row=0, column=2, padx=12)
        if episode["progress_ms"]:
            ctk.CTkLabel(row, text=f"Resume {format_time(episode['progress_ms'])}", text_color=PINK,
                         font=ctk.CTkFont(size=11)).grid(row=0, column=3, padx=(4, 12))
        ctk.CTkButton(row, text="Rename", width=72, height=32,
                      command=lambda eid=episode["id"]: self._rename_episode_dialog(eid),
                      fg_color="#2B3340", hover_color="#3A4556", text_color=TEXT,
                      font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=4, padx=4, pady=12)
        ctk.CTkButton(row, text="Delete", width=66, height=32,
                      command=lambda eid=episode["id"]: self._delete_episode(eid),
                      fg_color="transparent", border_width=1, border_color="#7F1D1D",
                      hover_color="#451A1A", text_color="#FCA5A5",
                      font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=5, padx=(4, 12), pady=12)

    def _rename_series_dialog(self, series_id: int) -> None:
        series = self.db.get_series(series_id)
        if not series:
            return messagebox.showerror("Anime missing", "That anime is no longer in the library.")
        episode_count = len(self.db.episodes(series_id))
        dialog = ctk.CTkToplevel(self, fg_color=BG)
        dialog.title("Rename anime")
        dialog.geometry("560x310")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        ctk.CTkLabel(dialog, text="Rename the entire anime", text_color=TEXT,
                     font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", padx=30, pady=(28, 6))
        ctk.CTkLabel(
            dialog,
            text=f"This changes the main library name and reorganizes all {episode_count} episode file"
                 f"{'s' if episode_count != 1 else ''}. Watch progress stays attached, then the poster and details are refreshed.",
            text_color=MUTED, wraplength=490, justify="left",
        ).pack(anchor="w", padx=30, pady=(0, 22))
        ctk.CTkLabel(dialog, text="NEW ANIME NAME", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w", padx=30)
        title_entry = ctk.CTkEntry(dialog, height=44)
        title_entry.insert(0, series["title"])
        title_entry.pack(fill="x", padx=30, pady=(6, 24))
        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(fill="x", padx=30)
        ctk.CTkButton(buttons, text="Cancel", command=dialog.destroy, width=110, height=42,
                      fg_color=PANEL_2, hover_color="#283142").pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            buttons, text="Rename anime", width=145, height=42, fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            command=lambda: self._apply_series_rename(dialog, series_id, title_entry.get()),
        ).pack(side="right")
        title_entry.focus_set()

    def _apply_series_rename(self, dialog, series_id: int, title: str) -> None:
        library_root = self._require_library_root()
        if library_root is None:
            return
        if not title.strip():
            return messagebox.showwarning("Name required", "Enter the new anime name.", parent=dialog)
        episodes = self.db.episodes(series_id)
        if not episodes:
            return messagebox.showerror("Anime empty", "This anime has no episode files to rename.", parent=dialog)
        plans = None
        try:
            plans = rename_series_files(episodes, library_root, title.strip())
            clean_title = next(iter(plans.values()))[1].relative_to(library_root).parts[0]
            self.db.rename_series(
                series_id, clean_title, {episode_id: destination for episode_id, (_, destination) in plans.items()}
            )
        except Exception as exc:
            if plans:
                try:
                    rollback_series_files(plans)
                except OSError:
                    pass
            return messagebox.showerror("Anime rename failed", str(exc), parent=dialog)
        dialog.destroy()
        self.db.scan_library(library_root)
        self.show_series(series_id)
        self._toast("Searching for the new poster & details…")
        messagebox.showinfo(
            "Anime renamed",
            f"The anime and all episode files are now named:\n{clean_title}\n\n"
            "Anime Watcher is searching for the matching poster and details now.",
        )
        self._refresh_metadata_after_rename(series_id, clean_title)

    def _refresh_metadata_after_rename(self, series_id: int, renamed_title: str) -> None:
        def work() -> None:
            try:
                data = fetch_metadata(renamed_title, self.data_root / "posters")

                def apply() -> None:
                    current = self.db.get_series(series_id)
                    if not current or current["title"].casefold() != renamed_title.casefold():
                        return
                    self.db.update_metadata(
                        series_id, data["title"], data["synopsis"], data["poster_path"], data["id"]
                    )
                    if self._visible_series_id == series_id:
                        self.show_series(series_id)
                    self._toast("Poster & details updated")

                self.after(0, apply)
            except Exception as exc:
                def failed(error=str(exc)) -> None:
                    current = self.db.get_series(series_id)
                    if not current or current["title"].casefold() != renamed_title.casefold():
                        return
                    self._toast("Renamed • metadata will retry later")
                    messagebox.showwarning(
                        "Anime renamed — details pending",
                        f"The files were renamed successfully, but the new poster and details could not be found yet.\n\n"
                        f"{error}\n\nUse ‘Fetch poster & details’ to try again.",
                    )

                self.after(0, failed)

        threading.Thread(target=work, daemon=True).start()

    def _rename_episode_dialog(self, episode_id: int) -> None:
        library_root = self._require_library_root()
        if library_root is None:
            return
        episode = self.db.episode(episode_id)
        if not episode:
            return messagebox.showerror("Episode missing", "That episode is no longer in the library.")
        source = Path(episode["path"])
        try:
            folder_title = source.relative_to(library_root).parts[0]
        except (ValueError, IndexError):
            folder_title = episode["series_title"]

        dialog = ctk.CTkToplevel(self, fg_color=BG)
        dialog.title("Rename episode")
        dialog.geometry("560x470")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        ctk.CTkLabel(dialog, text="Rename & reorganize episode", text_color=TEXT,
                     font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", padx=30, pady=(26, 6))
        ctk.CTkLabel(dialog, text="Changing these fields moves the file into the correct anime and season folder.",
                     text_color=MUTED, wraplength=490, justify="left").pack(anchor="w", padx=30, pady=(0, 18))

        ctk.CTkLabel(dialog, text="ANIME TITLE", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w", padx=30)
        title_entry = ctk.CTkEntry(dialog, height=42)
        title_entry.insert(0, folder_title)
        title_entry.pack(fill="x", padx=30, pady=(5, 14))

        number_row = ctk.CTkFrame(dialog, fg_color="transparent")
        number_row.pack(fill="x", padx=30)
        season_box = ctk.CTkFrame(number_row, fg_color="transparent")
        season_box.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkLabel(season_box, text="SEASON", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w")
        season_entry = ctk.CTkEntry(season_box, height=42)
        season_entry.insert(0, str(episode["season"]))
        season_entry.pack(fill="x", pady=(5, 14))
        episode_box = ctk.CTkFrame(number_row, fg_color="transparent")
        episode_box.pack(side="left", fill="x", expand=True, padx=(8, 0))
        ctk.CTkLabel(episode_box, text="EPISODE", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w")
        episode_entry = ctk.CTkEntry(episode_box, height=42)
        episode_entry.insert(0, str(episode["episode"]))
        episode_entry.pack(fill="x", pady=(5, 14))

        ctk.CTkLabel(dialog, text="VERSION", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w", padx=30)
        language_menu = ctk.CTkOptionMenu(dialog, values=sorted(LANGUAGES), height=42,
                                          fg_color=PANEL_2, button_color="#2B3340")
        language_menu.set(episode["language"] if episode["language"] in LANGUAGES else "Unknown")
        language_menu.pack(fill="x", padx=30, pady=(5, 22))

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(fill="x", padx=30)
        ctk.CTkButton(buttons, text="Cancel", command=dialog.destroy, width=110, height=42,
                      fg_color=PANEL_2, hover_color="#283142").pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            buttons, text="Save & move file", width=150, height=42, fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            command=lambda: self._apply_episode_rename(
                dialog, episode_id, title_entry.get(), season_entry.get(), episode_entry.get(), language_menu.get()
            ),
        ).pack(side="right")
        title_entry.focus_set()

    def _apply_episode_rename(self, dialog, episode_id: int, title: str,
                              season_text: str, episode_text: str, language: str) -> None:
        library_root = self._require_library_root()
        if library_root is None:
            return
        episode = self.db.episode(episode_id)
        if not episode:
            return messagebox.showerror("Episode missing", "That episode is no longer in the library.", parent=dialog)
        if not title.strip():
            return messagebox.showwarning("Title required", "Enter the correct anime title.", parent=dialog)
        try:
            season = int(season_text)
            episode_number = int(episode_text)
        except ValueError:
            return messagebox.showwarning("Invalid number", "Season and episode must be whole numbers.", parent=dialog)

        source = Path(episode["path"])
        destination = None
        try:
            destination = rename_episode_file(
                source, library_root, title.strip(), season, episode_number, language
            )
            clean_title = destination.relative_to(library_root).parts[0]
            new_series_id = self.db.relocate_episode(
                episode_id, destination, clean_title, season, episode_number, language
            )
        except Exception as exc:
            if destination is not None and destination != source and destination.exists() and not source.exists():
                try:
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(destination), str(source))
                except OSError:
                    pass
            return messagebox.showerror("Rename failed", str(exc), parent=dialog)
        dialog.destroy()
        self.db.scan_library(library_root)
        messagebox.showinfo("Episode renamed", f"Moved to:\n{destination}")
        self.show_series(new_series_id)

    def _delete_episode(self, episode_id: int) -> None:
        library_root = self._require_library_root()
        if library_root is None:
            return
        episode = self.db.episode(episode_id)
        if not episode:
            return messagebox.showerror("Episode missing", "That episode is no longer in the library.")
        path = Path(episode["path"])
        if not messagebox.askyesno(
            "Move episode to Recycle Bin?",
            f"Move this video to the Windows Recycle Bin?\n\n{path.name}\n\nYou can restore it later from the Recycle Bin.",
        ):
            return
        series_id = episode["series_id"]
        try:
            send_to_recycle_bin(path, library_root)
            self.db.scan_library(library_root)
        except Exception as exc:
            return messagebox.showerror("Delete failed", str(exc))
        messagebox.showinfo("Episode removed", "The video was moved to the Windows Recycle Bin.")
        if self.db.get_series(series_id):
            self.show_series(series_id)
        else:
            self.show_library()

    def _refresh_metadata(self, series_id: int) -> None:
        series = self.db.get_series(series_id)
        if not series:
            return
        self._toast("Looking up metadata…")
        def work():
            try:
                data = fetch_metadata(series["title"], self.data_root / "posters")
                def apply():
                    self.db.update_metadata(series_id, data["title"], data["synopsis"], data["poster_path"], data["id"])
                    self.show_series(series_id)
                self.after(0, apply)
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Metadata lookup failed", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _auto_metadata(self) -> None:
        missing = [row for row in self.db.series() if not row["metadata_updated"]]
        if not missing:
            return
        def work():
            for series in missing:
                try:
                    data = fetch_metadata(series["title"], self.data_root / "posters")
                    def apply(sid=series["id"], item=data):
                        self.db.update_metadata(sid, item["title"], item["synopsis"], item["poster_path"], item["id"])
                    self.after(0, apply)
                except Exception:
                    pass
                time.sleep(0.45)
        threading.Thread(target=work, daemon=True).start()

    def show_continue(self) -> None:
        self._clear()
        self._header("Continue watching", "Your resume points are stored automatically")
        area = self._scroll_area()
        episodes = self.db.continue_watching(100)
        for index, episode in enumerate(episodes):
            row = ctk.CTkButton(area, text="", command=lambda eid=episode["id"]: self.play_episode(eid),
                                height=74, fg_color=PANEL, hover_color=PANEL_2, corner_radius=12)
            row.pack(fill="x", padx=12, pady=5)
            row.grid_columnconfigure(0, weight=1)
            self._marquee_label(row, episode["series_title"], 62, text_color=TEXT, anchor="w",
                                font=ctk.CTkFont(size=14, weight="bold")).grid(
                                    row=0, column=0, sticky="w", padx=18, pady=(12, 2))
            ctk.CTkLabel(row, text=f"S{episode['season']:02d}E{episode['episode']:02d} • {episode['language']}",
                         text_color=MUTED, font=ctk.CTkFont(size=11)).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 10))
            ctk.CTkLabel(row, text=f"Resume at {format_time(episode['progress_ms'])}", text_color=PINK,
                         font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=1, rowspan=2, padx=18)
        if not episodes:
            self._empty_library(area, 0)

    def show_import(self) -> None:
        self._clear()
        self._header("Import & organize", "Files are moved into Title / Season folders with collision protection")
        area = self._scroll_area()
        panel = ctk.CTkFrame(area, fg_color=PANEL, corner_radius=18)
        panel.pack(fill="x", padx=12, pady=12)
        ctk.CTkLabel(panel, text="Add episodes you already own", text_color=TEXT,
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", padx=28, pady=(28, 8))
        ctk.CTkLabel(panel, text="Anime Watcher detects title, season, episode, and Sub/Dub labels from filenames.\n"
                                      "Nothing is overwritten: identical files are skipped and name collisions are numbered.",
                     justify="left", text_color=MUTED).pack(anchor="w", padx=28)
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.pack(anchor="w", padx=22, pady=26)
        ctk.CTkButton(actions, text="Choose episode files", command=self._import_files, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, height=44).pack(side="left", padx=6)
        ctk.CTkButton(actions, text="Choose a folder", command=self._import_folder, fg_color=PANEL_2,
                      hover_color="#283142", height=44).pack(side="left", padx=6)
        ctk.CTkButton(actions, text="Rescan library", command=self._scan, fg_color=PANEL_2,
                      hover_color="#283142", height=44).pack(side="left", padx=6)

    def _import_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTENSIONS))
        paths = filedialog.askopenfilenames(title="Choose anime episodes", filetypes=[("Video files", patterns), ("All files", "*.*")])
        if paths:
            self._organize(paths)

    def _import_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose a folder containing anime episodes")
        if folder:
            self._organize(scan_video_files(folder))

    def _organize(self, paths) -> None:
        library_root = self._require_library_root()
        if library_root is None:
            return
        results = organize_files(paths, library_root)
        moved = sum(result.status == "moved" for result in results)
        duplicates = sum(result.status == "duplicate" for result in results)
        self._scan(show_status=False)
        messagebox.showinfo("Import complete", f"Moved {moved} episode(s).\nSkipped {duplicates} identical duplicate(s).")
        self.show_library()

    def show_downloads(self) -> None:
        self._clear()
        self._header("Find & download", "Search public catalog pages, then download authorized direct media files")
        area = self._scroll_area()

        search_panel = ctk.CTkFrame(area, fg_color=PANEL, corner_radius=18)
        search_panel.pack(fill="x", padx=12, pady=12)
        ctk.CTkLabel(search_panel, text="Search a source website", text_color=TEXT,
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", padx=28, pady=(28, 8))
        ctk.CTkLabel(search_panel,
                     text="Paste a catalog or search-page URL, then enter all or part of an anime title.\n"
                          "Open a matching anime to browse its public episode links.",
                     text_color=MUTED, justify="left").pack(anchor="w", padx=28)
        self.search_source_url = ctk.CTkEntry(
            search_panel, placeholder_text="https://example.com/catalog  or  https://example.com/search?q={query}", height=44)
        saved_source = self.db.setting("catalog_source_url", self.db.setting("provider_url", ""))
        if saved_source:
            self.search_source_url.insert(0, saved_source)
        self.search_source_url.pack(fill="x", padx=28, pady=(20, 10))
        search_row = ctk.CTkFrame(search_panel, fg_color="transparent")
        search_row.pack(fill="x", padx=28)
        self.catalog_query = ctk.CTkEntry(search_row, placeholder_text="Anime title or part of it…", height=44)
        self.catalog_query.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.catalog_query.bind("<Return>", lambda _e: self._start_catalog_search())
        self.catalog_search_button = ctk.CTkButton(
            search_row, text="Search source", command=self._start_catalog_search,
            width=140, height=44, fg_color=ACCENT, hover_color=ACCENT_HOVER)
        self.catalog_search_button.pack(side="left")
        self.catalog_status = ctk.CTkLabel(search_panel, text="", text_color=MUTED)
        self.catalog_status.pack(anchor="w", padx=28, pady=(10, 2))
        self.catalog_results_frame = ctk.CTkFrame(search_panel, fg_color="transparent")
        self.catalog_results_frame.pack(fill="x", padx=22, pady=(4, 24))

        panel = ctk.CTkFrame(area, fg_color=PANEL, corner_radius=18)
        panel.pack(fill="x", padx=12, pady=12)
        ctk.CTkLabel(panel, text="Download a direct media file", text_color=TEXT,
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w", padx=28, pady=(28, 8))
        ctk.CTkLabel(panel, text="Use a direct HTTP(S) file URL only when you own the media or have permission to download it.\n"
                                      "The completed file is renamed, organized, and added to your library automatically.",
                     text_color=MUTED, justify="left").pack(anchor="w", padx=28)
        self.download_url = ctk.CTkEntry(panel, placeholder_text="https://example.com/Show.S01E01.mkv", height=44)
        self.download_url.pack(fill="x", padx=28, pady=(22, 10))
        self.rights_check = ctk.CTkCheckBox(panel, text="I own this file or have permission to download it",
                                           fg_color=ACCENT, hover_color=ACCENT_HOVER)
        self.rights_check.pack(anchor="w", padx=28, pady=8)
        self.download_progress = ctk.CTkProgressBar(panel, progress_color=PINK, fg_color="#343B49")
        self.download_progress.pack(fill="x", padx=28, pady=(10, 4))
        self.download_progress.set(0)
        self.download_label = ctk.CTkLabel(panel, text="", text_color=MUTED)
        self.download_label.pack(anchor="w", padx=28)
        ctk.CTkButton(panel, text="Download & organize", command=self._start_download, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, height=44).pack(anchor="w", padx=28, pady=(16, 28))

    def _start_catalog_search(self) -> None:
        source_url = self.search_source_url.get().strip()
        query = self.catalog_query.get().strip()
        if not source_url or not query:
            return messagebox.showwarning("Search needs two things", "Enter a source URL and an anime title to search.")
        self.db.set_setting("catalog_source_url", source_url)
        self.catalog_search_button.configure(state="disabled", text="Searching…")
        self.catalog_status.configure(text="Reading the source's public catalog pages…")
        for child in self.catalog_results_frame.winfo_children():
            child.destroy()

        def work():
            try:
                results = search_catalog(source_url, query)
                self.after(0, lambda: self._catalog_search_done(results))
            except Exception as exc:
                self.after(0, lambda error=str(exc): self._catalog_search_failed(error))

        threading.Thread(target=work, daemon=True).start()

    def _catalog_search_failed(self, error: str) -> None:
        if not hasattr(self, "catalog_search_button") or not self.catalog_search_button.winfo_exists():
            return
        self.catalog_search_button.configure(state="normal", text="Search source")
        self.catalog_status.configure(text=error, text_color="#FCA5A5")

    def _catalog_search_done(self, results: list[CatalogResult]) -> None:
        if not hasattr(self, "catalog_search_button") or not self.catalog_search_button.winfo_exists():
            return
        self.catalog_search_button.configure(state="normal", text="Search source")
        self.catalog_status.configure(
            text=f"{len(results)} matching result{'s' if len(results) != 1 else ''}" if results else
                 "No matching links found. Try a broader title or the website's search-page URL.",
            text_color=MUTED,
        )
        for child in self.catalog_results_frame.winfo_children():
            child.destroy()
        for result in results:
            row = ctk.CTkFrame(self.catalog_results_frame, fg_color=PANEL_2, corner_radius=12)
            row.pack(fill="x", padx=6, pady=5)
            row.grid_columnconfigure(0, weight=1)
            details = ctk.CTkFrame(row, fg_color="transparent")
            details.grid(row=0, column=0, sticky="ew", padx=16, pady=12)
            ctk.CTkLabel(details, text=result.title, text_color=TEXT, anchor="w",
                         font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
            url_text = result.url if len(result.url) <= 110 else result.url[:107] + "…"
            ctk.CTkLabel(details, text=url_text, text_color=MUTED, anchor="w",
                         font=ctk.CTkFont(size=10)).pack(anchor="w", pady=(3, 0))
            if result.direct_media:
                ctk.CTkButton(row, text="Use download URL", width=138, height=36,
                              command=lambda url=result.url: self._use_download_url(url),
                              fg_color=ACCENT, hover_color=ACCENT_HOVER).grid(row=0, column=1, padx=(6, 4))
            else:
                episodes_frame = ctk.CTkFrame(row, fg_color="transparent")
                episodes_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))
                episode_button = ctk.CTkButton(
                    row, text="View episodes", width=118, height=36,
                    fg_color=ACCENT, hover_color=ACCENT_HOVER,
                )
                episode_button.configure(
                    command=lambda item=result, frame=episodes_frame, button=episode_button:
                        self._start_episode_lookup(item, frame, button)
                )
                episode_button.grid(row=0, column=1, padx=(6, 4))
            ctk.CTkButton(row, text="Open page", width=96, height=36,
                          command=lambda url=result.url: webbrowser.open(url),
                          fg_color="#2B3340", hover_color="#3A4556").grid(row=0, column=2, padx=(4, 14))

    def _start_episode_lookup(self, result: CatalogResult, frame, button) -> None:
        if not frame.winfo_exists() or not button.winfo_exists():
            return
        for child in frame.winfo_children():
            child.destroy()
        button.configure(state="disabled", text="Reading…")
        ctk.CTkLabel(frame, text="Reading the anime page's public episode links…", text_color=MUTED).pack(
            anchor="w", padx=4, pady=4)

        def work():
            try:
                episodes = load_catalog_episodes(result.url)
                self.after(0, lambda: self._episode_lookup_done(result, episodes, frame, button))
            except Exception as exc:
                self.after(0, lambda error=str(exc): self._episode_lookup_failed(error, frame, button))

        threading.Thread(target=work, daemon=True).start()

    def _episode_lookup_failed(self, error: str, frame, button) -> None:
        if not frame.winfo_exists() or not button.winfo_exists():
            return
        button.configure(state="normal", text="Try episodes again")
        for child in frame.winfo_children():
            child.destroy()
        ctk.CTkLabel(frame, text=error, text_color="#FCA5A5", anchor="w").pack(anchor="w", padx=4, pady=4)

    def _episode_lookup_done(self, result: CatalogResult, episodes: list[EpisodeResult], frame, button) -> None:
        if not frame.winfo_exists() or not button.winfo_exists():
            return
        button.configure(state="normal", text="Refresh episodes")
        for child in frame.winfo_children():
            child.destroy()
        if not episodes:
            ctk.CTkLabel(
                frame, text="No public episode links were found on that page.",
                text_color=MUTED, anchor="w",
            ).pack(anchor="w", padx=4, pady=4)
            return

        site_managed = any(not episode.direct_open for episode in episodes)
        message = f"{len(episodes)} episode{'s' if len(episodes) != 1 else ''} found"
        if site_managed:
            message += " • this site selects episodes with a browser cookie, so choose it once more on the opened anime page"
        ctk.CTkLabel(frame, text=message, text_color=MUTED, anchor="w", wraplength=900,
                     justify="left").pack(anchor="w", padx=4, pady=(3, 8))

        episode_grid = ctk.CTkFrame(frame, fg_color="transparent")
        episode_grid.pack(fill="x")
        for column in range(6):
            episode_grid.grid_columnconfigure(column, weight=1)
        for index, episode in enumerate(episodes):
            target_url = episode.url if episode.direct_open else result.url
            ctk.CTkButton(
                episode_grid,
                text=episode.title,
                command=lambda url=target_url: webbrowser.open(url),
                height=34,
                fg_color="#252D3B" if episode.direct_open else "#303746",
                hover_color="#3A4556",
                text_color=TEXT,
            ).grid(row=index // 6, column=index % 6, sticky="ew", padx=4, pady=4)

    def _use_download_url(self, url: str) -> None:
        self.download_url.delete(0, "end")
        self.download_url.insert(0, url)
        self.download_label.configure(text="Direct media URL selected. Confirm permission, then download.")

    def _start_download(self) -> None:
        library_root = self._require_library_root()
        if library_root is None:
            return
        url = self.download_url.get().strip()
        if not self.rights_check.get():
            return messagebox.showwarning("Permission required", "Confirm that you are authorized to download this file.")
        if not url:
            return
        self.download_label.configure(text="Connecting…")
        def progress(received, total):
            self.after(0, lambda: self._download_progress(received, total))
        def work():
            try:
                result = download_authorized_file(url, self.data_root / "downloads", library_root, progress)
                self.after(0, lambda: self._download_done(result))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Download failed", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _download_progress(self, received: int, total: int) -> None:
        self.download_progress.set(received / total if total else 0)
        self.download_label.configure(text=f"{received / 1048576:.1f} MB" + (f" / {total / 1048576:.1f} MB" if total else ""))

    def _download_done(self, result) -> None:
        self._scan(show_status=False)
        self.download_progress.set(1)
        self.download_label.configure(text=f"Added: {result.destination}")

    def show_settings(self) -> None:
        self._clear()
        self._header("Settings", "Library location, VLC, and lawful provider bookmarks")
        area = self._scroll_area()
        panel = ctk.CTkFrame(area, fg_color=PANEL, corner_radius=18)
        panel.pack(fill="x", padx=12, pady=12)
        ctk.CTkLabel(panel, text="Library folder", text_color=TEXT,
                     font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=28, pady=(26, 7))
        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=28)
        self.library_entry = ctk.CTkEntry(row, height=42)
        if self.library_root:
            self.library_entry.insert(0, str(self.library_root))
        self.library_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row, text="Browse", width=90, height=42, command=self._choose_library,
                      fg_color=PANEL_2, hover_color="#283142").pack(side="left")
        ctk.CTkButton(panel, text="Save & rescan", command=self._save_settings, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER).pack(anchor="w", padx=28, pady=16)

        ctk.CTkLabel(panel, text="Provider bookmarks", text_color=TEXT,
                     font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=28, pady=(18, 7))
        ctk.CTkLabel(panel, text="These open official services in your browser. Downloads remain subject to each provider's terms.",
                     text_color=MUTED).pack(anchor="w", padx=28)
        bookmarks = ctk.CTkFrame(panel, fg_color="transparent")
        bookmarks.pack(anchor="w", padx=22, pady=(14, 26))
        for name, url in [("Crunchyroll", "https://www.crunchyroll.com/"), ("HIDIVE", "https://www.hidive.com/"),
                          ("Netflix", "https://www.netflix.com/browse/genre/7424")]:
            ctk.CTkButton(bookmarks, text=f"Open {name}", command=lambda u=url: webbrowser.open(u),
                          fg_color=PANEL_2, hover_color="#283142").pack(side="left", padx=6)
        custom = ctk.CTkFrame(panel, fg_color="transparent")
        custom.pack(fill="x", padx=28, pady=(0, 28))
        self.provider_entry = ctk.CTkEntry(custom, placeholder_text="Optional custom provider website", height=40)
        self.provider_entry.insert(0, self.db.setting("provider_url", ""))
        self.provider_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(custom, text="Open", command=self._open_custom_provider, width=80, height=40,
                      fg_color=PANEL_2, hover_color="#283142").pack(side="left")

    def _open_custom_provider(self) -> None:
        url = self.provider_entry.get().strip()
        if not url.startswith(("http://", "https://")):
            return messagebox.showwarning("Invalid website", "Enter a complete http:// or https:// address.")
        self.db.set_setting("provider_url", url)
        webbrowser.open(url)

    def _choose_library(self) -> None:
        options = {"title": "Choose your anime library folder"}
        if self.library_root:
            options["initialdir"] = str(self.library_root)
        folder = filedialog.askdirectory(**options)
        if folder:
            self.library_entry.delete(0, "end")
            self.library_entry.insert(0, folder)

    def _save_settings(self) -> None:
        selected = self.library_entry.get().strip()
        if not selected:
            return messagebox.showwarning(
                "Library folder required",
                "Choose a folder before saving. Anime Watcher will not select a drive automatically.",
            )
        candidate = Path(selected)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return messagebox.showerror("Invalid folder", str(exc))
        self.library_root = candidate
        self.db.set_setting("library_root", str(candidate))
        self.sidebar_status.configure(text=str(candidate))
        self._scan()

    def _scan(self, show_status: bool = True) -> None:
        if not self.library_root:
            if show_status:
                self._require_library_root()
            return
        stats = self.db.scan_library(self.library_root)
        if show_status:
            self._toast(f"Library refreshed • {stats['files']} episodes")

    def _toast(self, text: str) -> None:
        self.sidebar_status.configure(text=f"{self._library_status_text()}\n\n{text}")
        self.after(4000, lambda: self.sidebar_status.configure(text=self._library_status_text()) if self.sidebar_status.winfo_exists() else None)

    def play_episode(self, episode_id: int) -> None:
        self._save_current_progress()
        episode = self.db.episode(episode_id)
        if not episode or not Path(episode["path"]).exists():
            return messagebox.showerror("Episode missing", "The episode file is no longer available. Rescan the library.")
        self._clear()
        self._set_player_mode(True)
        self.current_episode_id = episode_id
        self._current_video_path = episode["path"]
        self._last_saved = episode["progress_ms"]
        self._known_duration_ms = int(episode["duration_ms"] or 0)
        self.autoplay_enabled = True

        theater = ctk.CTkFrame(self.content, fg_color="#030507", corner_radius=0)
        theater.grid(row=0, column=0, rowspan=2, sticky="nsew")
        theater.grid_columnconfigure(0, weight=1)
        theater.grid_rowconfigure(0, weight=1)

        video_shell = ctk.CTkFrame(theater, fg_color="black", corner_radius=0)
        video_shell.grid(row=0, column=0, sticky="nsew")
        video_shell.grid_rowconfigure(0, weight=1)
        video_shell.grid_columnconfigure(0, weight=1)
        self.video_frame = ctk.CTkFrame(video_shell, fg_color="black", corner_radius=0)
        self.video_frame.grid(row=0, column=0, sticky="nsew")
        self.video_frame.bind("<Button-1>", lambda _e: self._toggle_play())

        self.player_input = self._video_input_window()

        self.player_topbar = self._overlay_window()
        self.player_topbar.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(self.player_topbar, text="‹  BACK", command=self.show_library, width=92, height=38,
                      fg_color="transparent", hover_color=PANEL_2, text_color=TEXT,
                      font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, padx=(22, 10), pady=18)
        title_box = ctk.CTkFrame(self.player_topbar, fg_color="transparent")
        title_box.grid(row=0, column=1, sticky="w")
        self._marquee_label(title_box, episode["series_title"], 56, text_color=TEXT, anchor="w",
                            font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(title_box, text=f"SEASON {episode['season']:02d}  •  EPISODE {episode['episode']:02d}  •  {episode['language'].upper()}",
                     text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w", pady=(3, 0))
        ctk.CTkLabel(self.player_topbar, text="ANIME  WATCHER", text_color=PINK,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=2, padx=26)

        self.player_controls = self._overlay_window()
        self.player_controls.grid_columnconfigure(0, weight=1)

        timeline = ctk.CTkFrame(self.player_controls, fg_color="transparent")
        timeline.grid(row=0, column=0, sticky="ew", padx=26, pady=(16, 5))
        timeline.grid_columnconfigure(0, weight=1)
        self.seek_slider = ctk.CTkSlider(timeline, from_=0, to=1000, height=16,
                                        progress_color=PINK, fg_color="#3A404B", button_color=PINK,
                                        button_hover_color="#F472B6", command=self._slider_seek)
        self.seek_slider.grid(row=0, column=0, sticky="ew")
        self.seek_slider.set(0)
        self.seek_slider.bind("<Enter>", self._timeline_enter, add="+")
        self.seek_slider.bind("<Motion>", self._timeline_motion, add="+")
        self.seek_slider.bind("<ButtonPress-1>", self._timeline_press, add="+")
        self.seek_slider.bind("<B1-Motion>", self._timeline_motion, add="+")
        self.seek_slider.bind("<ButtonRelease-1>", self._timeline_release, add="+")
        self.seek_slider.bind("<Leave>", self._timeline_leave, add="+")
        self.time_label = ctk.CTkLabel(timeline, text="0:00  /  0:00", text_color="#C4CAD4", width=118,
                                       font=ctk.CTkFont(size=11))
        self.time_label.grid(row=0, column=1, padx=(14, 0))

        identity = ctk.CTkFrame(self.player_controls, fg_color="transparent")
        identity.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 5))
        identity.grid_columnconfigure(0, weight=1)
        self.now_title = ctk.CTkLabel(identity, text=f"Episode {episode['episode']:02d}", text_color=TEXT,
                                      font=ctk.CTkFont(size=16, weight="bold"))
        self.now_title.grid(row=0, column=0, sticky="w")
        next_episode = self.db.next_episode(episode_id, 1)
        if next_episode:
            ctk.CTkButton(identity, text=f"UP NEXT  •  EPISODE {next_episode['episode']:02d}  ›",
                          command=lambda eid=next_episode["id"]: self.play_episode(eid), width=190, height=32,
                          fg_color="transparent", hover_color=PANEL_2, text_color="#D8DDE6",
                          font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=1, sticky="e")

        buttons = ctk.CTkFrame(self.player_controls, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", padx=24, pady=(4, 16))
        self.play_button = ctk.CTkButton(buttons, text="❚❚", command=self._toggle_play, width=48, height=44,
                                         corner_radius=22, fg_color=TEXT, hover_color="#DDE2EA", text_color="#080B10",
                                         font=ctk.CTkFont(size=18, weight="bold"))
        self.play_button.pack(side="left", padx=(2, 10))
        for text, command, width in [
            ("│‹", lambda: self._change_episode(-1), 42),
            ("↶ 10", lambda: self._seek_relative(-10000), 54),
            ("10 ↷", lambda: self._seek_relative(10000), 54),
            ("›│", lambda: self._change_episode(1), 42),
        ]:
            ctk.CTkButton(buttons, text=text, command=command, width=width, height=38,
                          fg_color="transparent", hover_color=PANEL_2, text_color=TEXT,
                          font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=2)

        self.skip_intro_button = ctk.CTkButton(buttons, text="SKIP INTRO  ››", command=self._skip_intro,
                                               width=116, height=36, corner_radius=5, fg_color="#F1F3F6",
                                               hover_color="white", text_color="#0B0E13",
                                               font=ctk.CTkFont(size=10, weight="bold"))
        self.skip_intro_button.pack(side="left", padx=(14, 4))

        ctk.CTkButton(buttons, text="⛶", command=self._toggle_fullscreen, width=40, height=38,
                      fg_color="transparent", hover_color=PANEL_2, text_color=TEXT,
                      font=ctk.CTkFont(size=19)).pack(side="right", padx=2)
        self.speed_menu = ctk.CTkOptionMenu(buttons, values=["0.75×", "1.0×", "1.25×", "1.5×", "2.0×"],
                                             width=78, height=34, command=self._select_speed,
                                             fg_color=PANEL_2, button_color="#2B3340", button_hover_color="#3A4556")
        self.speed_menu.set("1.0×")
        self.speed_menu.pack(side="right", padx=4)
        self.subtitle_menu = ctk.CTkOptionMenu(buttons, values=["CC"], width=104, height=34,
                                               command=self._select_subtitle, fg_color=PANEL_2,
                                               button_color="#2B3340", button_hover_color="#3A4556")
        self.subtitle_menu.pack(side="right", padx=4)
        self.audio_menu = ctk.CTkOptionMenu(buttons, values=["Audio"], width=104, height=34,
                                            command=self._select_audio, fg_color=PANEL_2,
                                            button_color="#2B3340", button_hover_color="#3A4556")
        self.audio_menu.pack(side="right", padx=4)
        self.volume_slider = ctk.CTkSlider(buttons, from_=0, to=100, width=95, height=14,
                                           command=lambda value: self.player.set_volume(int(value)),
                                           progress_color=TEXT, button_color=TEXT, fg_color="#3A404B")
        self.volume_slider.set(85)
        self.volume_slider.pack(side="right", padx=(4, 10))
        ctk.CTkLabel(buttons, text="VOL", text_color=MUTED,
                     font=ctk.CTkFont(size=9, weight="bold")).pack(side="right", padx=(10, 0))
        self.autoplay_switch = ctk.CTkSwitch(buttons, text="AUTOPLAY", width=94, command=self._toggle_autoplay,
                                             fg_color="#3A404B", progress_color=ACCENT,
                                             font=ctk.CTkFont(size=9, weight="bold"))
        self.autoplay_switch.select()
        self.autoplay_switch.pack(side="right", padx=8)

        self.player_preview = self._preview_window()

        variants = self.db.episode_variants(episode_id)
        self._variant_map = {f"{row['language']} • {Path(row['path']).suffix[1:].upper()}": row["id"] for row in variants}
        if len(self._variant_map) > 1:
            variant_menu = ctk.CTkOptionMenu(buttons, values=list(self._variant_map), width=115,
                                             command=lambda label: self.play_episode(self._variant_map[label]),
                                             fg_color=PANEL_2, button_color="#2B3340")
            variant_menu.pack(side="right", padx=4)
            current_label = next((label for label, eid in self._variant_map.items() if eid == episode_id), list(self._variant_map)[0])
            variant_menu.set(current_label)

        self.update_idletasks()
        self.player.attach(self.video_frame.winfo_id())
        self.player.play(episode["path"], episode["progress_ms"])
        self.player.set_volume(85)
        self._preview_warmup_token += 1
        warmup_token = self._preview_warmup_token
        self._show_player_controls()
        self.after(250, self._raise_player_overlays)
        self.after(1200, lambda: self._start_preview_warmup(episode["path"], warmup_token))
        self.after(1800, self._load_tracks)

    def _player_motion(self, _event=None) -> None:
        if self.current_episode_id:
            self._show_player_controls()

    def _overlay_window(self) -> ctk.CTkToplevel:
        overlay = ctk.CTkToplevel(self, fg_color=OVERLAY_TRANSPARENT)
        overlay.withdraw()
        overlay.overrideredirect(True)
        overlay.transient(self)
        try:
            # Windows color-key transparency keeps the controls crisp while the
            # video and embedded subtitles remain fully visible behind the deck.
            overlay.wm_attributes("-transparentcolor", OVERLAY_TRANSPARENT)
        except Exception:
            # Other Tk builds may not support color-key transparency.
            overlay.wm_attributes("-alpha", 0.86)
        overlay.bind("<Motion>", self._player_motion, add="+")
        return overlay

    def _video_input_window(self) -> ctk.CTkToplevel:
        """Create a nearly invisible center layer that reliably receives VLC clicks."""
        layer = ctk.CTkToplevel(self, fg_color="black")
        layer.withdraw()
        layer.overrideredirect(True)
        layer.transient(self)
        layer.wm_attributes("-alpha", 0.01)
        layer.bind("<Button-1>", self._video_clicked, add="+")
        layer.bind("<Motion>", self._player_motion, add="+")
        return layer

    def _preview_window(self) -> ctk.CTkToplevel:
        popup = ctk.CTkToplevel(self, fg_color="#080B10")
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(self)
        try:
            # VLC creates its native video surface shortly after playback starts.
            # Keep the preview above that HWND instead of letting it fall behind.
            popup.wm_attributes("-topmost", True)
        except Exception:
            pass
        popup.configure(width=PREVIEW_POPUP_SIZE[0], height=PREVIEW_POPUP_SIZE[1])
        popup.grid_propagate(False)
        self.preview_image_label = ctk.CTkLabel(
            popup,
            text="Move across the timeline",
            width=PREVIEW_IMAGE_SIZE[0],
            height=PREVIEW_IMAGE_SIZE[1],
            fg_color="black",
            text_color=MUTED,
        )
        self.preview_image_label.grid(row=0, column=0, padx=4, pady=(4, 0))
        self.preview_time_label = ctk.CTkLabel(
            popup,
            text="0:00",
            height=26,
            text_color=TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.preview_time_label.grid(row=1, column=0, sticky="ew")
        return popup

    def _video_clicked(self, _event=None) -> None:
        self.focus_force()
        self._toggle_play()

    def _destroy_player_overlays(self) -> None:
        if self._overlay_sync_job is not None:
            try:
                self.after_cancel(self._overlay_sync_job)
            except ValueError:
                pass
            self._overlay_sync_job = None
        for job_name in ("_preview_request_job", "_preview_wait_job", "_preview_hide_job"):
            job = getattr(self, job_name, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except ValueError:
                    pass
                setattr(self, job_name, None)
        self._preview_request_token += 1
        self._preview_warmup_token += 1
        self._preview_failures.clear()
        for name in ("player_topbar", "player_controls", "player_input", "player_preview"):
            overlay = getattr(self, name, None)
            if overlay is not None:
                try:
                    if overlay.winfo_exists():
                        overlay.destroy()
                except Exception:
                    pass
                delattr(self, name)
        self._last_overlay_geometry = None
        self._controls_visible = False
        self._overlays_suspended = False
        self._timeline_hovered = False
        self._preview_requested_bucket = None
        self._preview_loaded_bucket = None
        self._preview_displayed_path = None
        self._preview_ctk_image = None

    def _player_window_configure(self, event=None) -> None:
        """Debounce overlay movement so dragging resizes one window, not three."""
        if event is not None and event.widget is not self:
            return
        if not self.current_episode_id or not hasattr(self, "player_controls"):
            return
        if not self._overlays_suspended:
            overlays = [self.player_input, self.player_preview]
            if self._controls_visible:
                overlays.extend((self.player_topbar, self.player_controls))
            for overlay in overlays:
                try:
                    overlay.withdraw()
                except Exception:
                    pass
            self._overlays_suspended = True
        if self._overlay_sync_job is not None:
            try:
                self.after_cancel(self._overlay_sync_job)
            except ValueError:
                pass
        self._overlay_sync_job = self.after(70, self._finish_overlay_reposition)

    def _finish_overlay_reposition(self) -> None:
        self._overlay_sync_job = None
        if not self.current_episode_id or not hasattr(self, "player_controls"):
            return
        self._sync_player_overlays()
        self._overlays_suspended = False
        self.player_input.deiconify()
        self.player_input.lift()
        if self._controls_visible:
            for overlay in (self.player_topbar, self.player_controls):
                overlay.deiconify()
                overlay.lift()

    def _sync_player_overlays(self) -> None:
        if not self.current_episode_id or not hasattr(self, "video_frame"):
            return
        try:
            x = self.video_frame.winfo_rootx()
            y = self.video_frame.winfo_rooty()
            width = max(1, self.video_frame.winfo_width())
            height = max(1, self.video_frame.winfo_height())
            signature = (x, y, width, height)
            if signature == self._last_overlay_geometry:
                return
            self._last_overlay_geometry = signature
            self.player_topbar.geometry(f"{width}x76{x:+d}{y:+d}")
            controls_y = y + max(0, height - 170)
            self.player_controls.geometry(f"{width}x170{x:+d}{controls_y:+d}")
            input_y = y + min(76, height)
            input_height = max(1, height - 246)
            self.player_input.geometry(f"{width}x{input_height}{x:+d}{input_y:+d}")
        except Exception:
            return

    def _poll_player_pointer(self) -> None:
        if self.current_episode_id:
            try:
                position = (self.winfo_pointerx(), self.winfo_pointery())
                inside = (self.winfo_rootx() <= position[0] < self.winfo_rootx() + self.winfo_width() and
                          self.winfo_rooty() <= position[1] < self.winfo_rooty() + self.winfo_height())
                if inside and position != self._last_pointer_pos:
                    self._show_player_controls()
                self._last_pointer_pos = position
            except Exception:
                pass
        self.after(150, self._poll_player_pointer)

    def _raise_player_overlays(self) -> None:
        if not self.current_episode_id:
            return
        self._show_player_controls()
        self.player_input.lift()
        for overlay in (self.player_topbar, self.player_controls):
            overlay.lift()

    def _show_player_controls(self) -> None:
        if not self.current_episode_id or not hasattr(self, "player_controls"):
            return
        if self._controls_hide_job is not None:
            try:
                self.after_cancel(self._controls_hide_job)
            except ValueError:
                pass
            self._controls_hide_job = None
        self.configure(cursor="")
        was_visible = self._controls_visible
        self._controls_visible = True
        if not self._overlays_suspended and not was_visible:
            self._sync_player_overlays()
            self.player_input.deiconify()
            self.player_input.lift()
            for overlay in (self.player_topbar, self.player_controls):
                overlay.deiconify()
                overlay.lift()
        if self.player.is_playing() and not self._timeline_hovered and not self._seeking:
            self._controls_hide_job = self.after(3000, self._hide_player_controls)

    def _hide_player_controls(self) -> None:
        self._controls_hide_job = None
        if not self.current_episode_id:
            return
        if self._timeline_hovered or self._seeking:
            self._controls_visible = True
            return
        if not self.player.is_playing():
            self._show_player_controls()
            return
        self._controls_visible = False
        self._hide_timeline_preview()
        self.player_topbar.withdraw()
        self.player_controls.withdraw()
        self.configure(cursor="none")

    def _load_tracks(self) -> None:
        if not self.current_episode_id:
            return
        self._audio_map = {name: track_id for track_id, name in self.player.audio_tracks()}
        self._subtitle_map = {name: track_id for track_id, name in self.player.subtitle_tracks()}
        audio_values = list(self._audio_map) or ["Default audio"]
        subtitle_values = list(self._subtitle_map) or ["No subtitles"]
        if hasattr(self, "audio_menu") and self.audio_menu.winfo_exists():
            self.audio_menu.configure(values=audio_values)
            self.audio_menu.set(audio_values[0])
            self.subtitle_menu.configure(values=subtitle_values)
            self.subtitle_menu.set(subtitle_values[0])

    def _select_audio(self, name: str) -> None:
        if name in getattr(self, "_audio_map", {}):
            self.player.set_audio_track(self._audio_map[name])

    def _select_subtitle(self, name: str) -> None:
        if name in getattr(self, "_subtitle_map", {}):
            self.player.set_subtitle_track(self._subtitle_map[name])

    def _toggle_play(self) -> None:
        if self.current_episode_id:
            self.player.toggle()
            self.after(120, self._show_player_controls)

    def _seek_relative(self, milliseconds: int) -> None:
        if self.current_episode_id:
            self.player.seek_relative(milliseconds)

    def _skip_intro(self) -> None:
        if self.current_episode_id:
            self.player.seek(max(self.player.time(), 90000))

    def _select_speed(self, label: str) -> None:
        try:
            self.player.set_rate(float(label.rstrip("×")))
        except ValueError:
            self.player.set_rate(1.0)

    def _toggle_autoplay(self) -> None:
        self.autoplay_enabled = bool(self.autoplay_switch.get())

    def _slider_seek(self, value: float) -> None:
        duration = self._timeline_duration()
        if self.current_episode_id and duration > 0:
            self._pending_seek_ms = int(value / 1000 * duration)

    def _timeline_duration(self) -> int:
        """Keep previews usable while VLC briefly reports zero during buffering."""
        duration = self.player.duration()
        if duration > 0:
            self._known_duration_ms = duration
        return self._known_duration_ms

    def _timeline_target(self, event, duration: int | None = None) -> int:
        duration = self._timeline_duration() if duration is None else duration
        width = max(1, self.seek_slider.winfo_width())
        fraction = max(0.0, min(1.0, event.x / width))
        return int(duration * fraction) if duration > 0 else 0

    def _timeline_enter(self, _event=None) -> None:
        self._timeline_hovered = True
        if self._preview_hide_job is not None:
            try:
                self.after_cancel(self._preview_hide_job)
            except ValueError:
                pass
            self._preview_hide_job = None
        self._show_player_controls()

    def _timeline_press(self, event) -> None:
        self._timeline_hovered = True
        self._seeking = True
        self._pending_seek_ms = self._timeline_target(event)
        self._timeline_motion(event)

    def _timeline_motion(self, event) -> None:
        if not self.current_episode_id or not hasattr(self, "player_preview"):
            return
        self._timeline_hovered = True
        duration = self._timeline_duration()
        if duration <= 0:
            return
        target_ms = self._timeline_target(event, duration)
        if self._preview_hide_job is not None:
            try:
                self.after_cancel(self._preview_hide_job)
            except ValueError:
                pass
            self._preview_hide_job = None
        self._show_player_controls()
        self.preview_time_label.configure(text=format_time(target_ms))

        popup_width, popup_height = PREVIEW_POPUP_SIZE
        video_left = self.video_frame.winfo_rootx()
        video_right = video_left + self.video_frame.winfo_width()
        desired_x = self.seek_slider.winfo_rootx() + event.x - popup_width // 2
        popup_x = max(video_left, min(desired_x, max(video_left, video_right - popup_width)))
        popup_y = max(self.video_frame.winfo_rooty(), self.player_controls.winfo_rooty() - popup_height - 8)
        self.player_preview.geometry(f"{popup_width}x{popup_height}{popup_x:+d}{popup_y:+d}")

        bucket = preview_bucket(target_ms)
        video_path = self._current_video_path
        if not video_path:
            return
        cache_dir = self.data_root / "previews"
        if bucket == self._preview_loaded_bucket and self._preview_ctk_image is not None:
            self._raise_timeline_preview()
            return
        exact = cached_video_preview(video_path, bucket, cache_dir)
        if exact is not None:
            self._show_timeline_preview_image(exact, bucket)
            self._preview_requested_bucket = None
            return
        nearby = nearest_cached_video_preview(video_path, bucket, cache_dir)
        if nearby is not None:
            self._show_timeline_preview_image(nearby, None)
        elif self._preview_ctk_image is not None:
            # Keep the last real frame visible during a fast continuous scrub;
            # the exact frame replaces it as soon as FFmpeg finishes.
            self._preview_loaded_bucket = None
            self._raise_timeline_preview()
        else:
            self.player_preview.withdraw()
            self.preview_image_label.configure(image=None, text="")
            self._preview_ctk_image = None
            self._preview_displayed_path = None
            self._preview_loaded_bucket = None
        if bucket == self._preview_requested_bucket:
            return
        self._preview_requested_bucket = bucket
        self._preview_request_token += 1
        token = self._preview_request_token
        if self._preview_request_job is not None:
            try:
                self.after_cancel(self._preview_request_job)
            except ValueError:
                pass
        if self._preview_wait_job is not None:
            try:
                self.after_cancel(self._preview_wait_job)
            except ValueError:
                pass
            self._preview_wait_job = None
        self._preview_failures.clear()
        self._preview_request_job = self.after(
            35,
            lambda: self._start_timeline_preview_request(token, target_ms, bucket),
        )

    def _start_timeline_preview_request(self, token: int, target_ms: int, bucket: int) -> None:
        self._preview_request_job = None
        video_path = self._current_video_path
        if not video_path:
            return
        cache_dir = self.data_root / "previews"
        target_path = preview_cache_path(video_path, target_ms, cache_dir)

        def work() -> None:
            try:
                with self._preview_generation_lock:
                    if token != self._preview_request_token:
                        return
                    preview_path = generate_video_preview(
                        video_path,
                        target_ms,
                        cache_dir,
                        width=PREVIEW_IMAGE_SIZE[0],
                        height=PREVIEW_IMAGE_SIZE[1],
                    )
            except Exception as exc:
                self._preview_failures[token] = str(exc)

        threading.Thread(target=work, daemon=True).start()
        self._wait_for_preview_file(token, bucket, target_path)

    def _wait_for_preview_file(self, token: int, bucket: int, target_path: Path, attempt: int = 0) -> None:
        """Let Tk observe FFmpeg's output directly; no cross-thread UI callback is needed."""
        self._preview_wait_job = None
        if token != self._preview_request_token or not hasattr(self, "preview_image_label"):
            return
        try:
            if target_path.is_file() and target_path.stat().st_size > 0:
                self._timeline_preview_ready(token, bucket, target_path)
                return
        except OSError:
            pass
        error = self._preview_failures.pop(token, None)
        if error is not None or attempt >= 120:
            self._timeline_preview_failed(token, error or "Preview timed out")
            return
        self._preview_wait_job = self.after(
            50,
            lambda: self._wait_for_preview_file(token, bucket, target_path, attempt + 1),
        )

    def _show_timeline_preview_image(self, preview_path: Path, loaded_bucket: int | None) -> bool:
        if not hasattr(self, "preview_image_label"):
            return False
        if self._preview_displayed_path == preview_path and self._preview_ctk_image is not None:
            self._preview_loaded_bucket = loaded_bucket
            self._raise_timeline_preview()
            return True
        try:
            with Image.open(preview_path) as source:
                image = source.convert("RGB").copy()
            self._preview_ctk_image = ctk.CTkImage(image, size=PREVIEW_IMAGE_SIZE)
            self.preview_image_label.configure(image=self._preview_ctk_image, text="")
            self._preview_loaded_bucket = loaded_bucket
            self._preview_displayed_path = preview_path
            self._raise_timeline_preview()
            return True
        except Exception:
            return False

    def _raise_timeline_preview(self) -> None:
        """Keep the preview above VLC's separately-created native video HWND."""
        if not hasattr(self, "player_preview"):
            return
        try:
            if not self.player_preview.winfo_exists():
                return
            self.player_preview.deiconify()
            self.player_preview.wm_attributes("-topmost", True)
            self.player_preview.lift()
            self.after_idle(
                lambda popup=self.player_preview: popup.lift() if popup.winfo_exists() else None
            )
        except Exception:
            pass

    def _timeline_preview_ready(self, token: int, bucket: int, preview_path: Path) -> None:
        if token != self._preview_request_token or not hasattr(self, "preview_image_label"):
            return
        self._preview_requested_bucket = None
        if not self._show_timeline_preview_image(preview_path, bucket):
            self._timeline_preview_failed(token, "Could not display preview")

    def _timeline_preview_failed(self, token: int, error: str) -> None:
        if token != self._preview_request_token or not hasattr(self, "preview_image_label"):
            return
        self._preview_requested_bucket = None
        if self._preview_ctk_image is None:
            self.player_preview.withdraw()

    def _start_preview_warmup(self, video_path: str, token: int, retry: int = 0) -> None:
        """Automatically prepare broad timeline coverage while the episode plays."""
        if token != self._preview_warmup_token or video_path != self._current_video_path:
            return
        duration = self._timeline_duration()
        if duration <= 0:
            if retry < 6:
                self.after(600, lambda: self._start_preview_warmup(video_path, token, retry + 1))
            return
        cache_dir = self.data_root / "previews"
        targets = preview_warmup_targets(duration)

        def work() -> None:
            for target_ms in targets:
                if token != self._preview_warmup_token or video_path != self._current_video_path:
                    return
                if cached_video_preview(video_path, target_ms, cache_dir) is not None:
                    continue
                try:
                    with self._preview_generation_lock:
                        if token != self._preview_warmup_token:
                            return
                        generate_video_preview(
                            video_path,
                            target_ms,
                            cache_dir,
                            width=PREVIEW_IMAGE_SIZE[0],
                            height=PREVIEW_IMAGE_SIZE[1],
                        )
                except Exception:
                    continue
                time.sleep(0.06)

        threading.Thread(target=work, daemon=True).start()

    def _timeline_release(self, event) -> None:
        duration = self._timeline_duration()
        if self.current_episode_id and duration > 0:
            self._pending_seek_ms = self._timeline_target(event, duration)
            self.player.seek(self._pending_seek_ms)
            self.seek_slider.set(self._pending_seek_ms / duration * 1000)
        self._seeking = False
        if not self._timeline_hovered:
            if self._preview_hide_job is not None:
                try:
                    self.after_cancel(self._preview_hide_job)
                except ValueError:
                    pass
            self._preview_hide_job = self.after(450, self._hide_timeline_preview)
        self._show_player_controls()

    def _timeline_leave(self, _event=None) -> None:
        self._timeline_hovered = False
        if self._seeking:
            return
        if self._preview_hide_job is not None:
            try:
                self.after_cancel(self._preview_hide_job)
            except ValueError:
                pass
        self._preview_hide_job = self.after(120, self._hide_timeline_preview)
        self._show_player_controls()

    def _hide_timeline_preview(self) -> None:
        self._preview_hide_job = None
        if hasattr(self, "player_preview"):
            try:
                self.player_preview.withdraw()
                self.player_preview.wm_attributes("-topmost", False)
            except Exception:
                pass

    def _change_episode(self, direction: int) -> None:
        if not self.current_episode_id:
            return
        episode = self.db.next_episode(self.current_episode_id, direction)
        if episode:
            self.play_episode(episode["id"])

    def _player_tick(self) -> None:
        if self.current_episode_id:
            position, duration = self.player.time(), self._timeline_duration()
            if hasattr(self, "time_label") and self.time_label.winfo_exists():
                self.time_label.configure(text=f"{format_time(position)} / {format_time(duration)}")
                if duration > 0 and not self._seeking:
                    self.seek_slider.set(position / duration * 1000)
                if hasattr(self, "play_button") and self.play_button.winfo_exists():
                    self.play_button.configure(text="❚❚" if self.player.is_playing() else "▶")
                if position > 180000 and hasattr(self, "skip_intro_button") and self.skip_intro_button.winfo_exists():
                    self.skip_intro_button.pack_forget()
            if abs(position - self._last_saved) >= 10000:
                self.db.save_progress(self.current_episode_id, position, duration)
                self._last_saved = position
            if self.autoplay_enabled and duration > 0 and position >= duration - 1500:
                next_episode = self.db.next_episode(self.current_episode_id, 1)
                if next_episode:
                    self.play_episode(next_episode["id"])
        self.after(1000, self._player_tick)

    def _save_current_progress(self) -> None:
        if self.current_episode_id:
            self.db.save_progress(self.current_episode_id, self.player.time(), self._timeline_duration())
            self.player.stop()
            self.current_episode_id = None

    def _toggle_fullscreen(self) -> None:
        if self._fullscreen:
            self._leave_fullscreen()
            return
        self.update_idletasks()
        bounds = monitor_bounds_for_window(self.winfo_id())
        if bounds is None:
            self._fullscreen = True
            self.attributes("-fullscreen", True)
        else:
            self._fullscreen_restore = (self.geometry(), self.state())
            self._fullscreen = True
            if self.state() != "normal":
                self.state("normal")
            self.overrideredirect(True)
            self.geometry(geometry_for_bounds(bounds))
        self._last_overlay_geometry = None
        if self.current_episode_id:
            self.after(90, self._finish_overlay_reposition)

    def _leave_fullscreen(self) -> None:
        if self._fullscreen:
            self._fullscreen = False
            if self._fullscreen_restore is None:
                self.attributes("-fullscreen", False)
            else:
                geometry, previous_state = self._fullscreen_restore
                self.overrideredirect(False)
                self.state("normal")
                self.geometry(geometry)
                if previous_state != "normal":
                    self.after(20, lambda state=previous_state: self.state(state))
                self._fullscreen_restore = None
            self._last_overlay_geometry = None
            if self.current_episode_id:
                self.after(90, self._finish_overlay_reposition)

    def _on_close(self) -> None:
        self._save_current_progress()
        self.player.release()
        self.db.close()
        self.destroy()
