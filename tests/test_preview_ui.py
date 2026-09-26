import inspect
import unittest

from PySide6.QtWidgets import QMainWindow, QWidget

from anime_watcher.qt_ui import AnimeWatcherWindow, CompositedVideoSurface, PlayerOverlay, PreviewSlider


class SingleWindowArchitectureTests(unittest.TestCase):
    def test_app_has_one_qt_main_window(self):
        self.assertTrue(issubclass(AnimeWatcherWindow, QMainWindow))

    def test_player_overlay_is_a_child_widget_not_another_window(self):
        self.assertTrue(issubclass(PlayerOverlay, QWidget))
        self.assertFalse(issubclass(PlayerOverlay, QMainWindow))

    def test_player_uses_one_stacked_page_for_video_and_controls(self):
        source = inspect.getsource(AnimeWatcherWindow._build_player_page)
        self.assertIn("StackingMode.StackAll", source)
        self.assertIn("PlayerOverlay()", source)
        self.assertIn("CompositedVideoSurface()", source)
        self.assertIn("stack.setCurrentWidget(self.player_overlay)", source)
        self.assertNotIn("QVideoWidget", source)
        self.assertNotIn("WA_NativeWindow", source)
        self.assertNotIn("QDialog", source)

    def test_ass_subtitles_stay_in_the_existing_graphics_scene(self):
        surface_source = inspect.getsource(CompositedVideoSurface)
        select_source = inspect.getsource(AnimeWatcherWindow._select_external_subtitle)
        self.assertIn("QGraphicsPixmapItem", surface_source)
        self.assertIn("LibassRenderer", select_source)
        self.assertNotIn("QVideoWidget", surface_source)
        self.assertNotIn("createWindowContainer", surface_source)

    def test_ass_render_timer_stops_before_player_page_is_destroyed(self):
        source = inspect.getsource(AnimeWatcherWindow._save_progress)
        self.assertIn("self._clear_external_subtitles()", source)
        self.assertLess(source.index("self._clear_external_subtitles()"), source.index("self.player.stop()"))

    def test_player_controls_are_restored_above_video_on_activity(self):
        show_source = inspect.getsource(AnimeWatcherWindow._show_controls)
        filter_source = inspect.getsource(AnimeWatcherWindow.eventFilter)
        self.assertIn("self.player_stack.setCurrentWidget(self.player_overlay)", show_source)
        self.assertIn("QEvent.Type.MouseMove", filter_source)
        self.assertIn("self._toggle_play()", filter_source)

    def test_player_uses_streaming_style_core_controls_and_settings_panel(self):
        source = inspect.getsource(AnimeWatcherWindow._build_player_page)
        self.assertIn('QPushButton("↶ 10")', source)
        self.assertIn('QPushButton("10 ↷")', source)
        self.assertIn('QPushButton("⚙")', source)
        self.assertIn('QFrame(page)', source)
        self.assertIn('settings_layout.addRow("Audio"', source)
        self.assertIn('settings_layout.addRow("Subtitles"', source)
        self.assertIn('settings_layout.addRow("Quality"', source)
        self.assertIn('settings_layout.addRow("Playback speed"', source)
        self.assertIn('QPushButton("Import file…")', source)
        self.assertIn('QPushButton("Generate English")', source)

    def test_external_subtitles_are_updated_during_playback(self):
        load_source = inspect.getsource(AnimeWatcherWindow._load_tracks)
        tick_source = inspect.getsource(AnimeWatcherWindow._player_tick)
        self.assertIn("find_sidecar_subtitles", load_source)
        self.assertIn("self._update_external_subtitle(position)", tick_source)

    def test_quality_switch_preserves_playback_position(self):
        source = inspect.getsource(AnimeWatcherWindow._quality_changed)
        self.assertIn("self.play_episode(episode_id, self.player.time())", source)

    def test_arrow_keys_seek_ten_seconds(self):
        source = inspect.getsource(AnimeWatcherWindow._install_player_shortcuts)
        self.assertIn('"seek_back": lambda: self._seek_relative(-10000)', source)
        self.assertIn("self._seek_relative(-10000)", source)
        self.assertIn('"seek_forward": lambda: self._seek_relative(10000)', source)
        self.assertIn("self._seek_relative(10000)", source)
        self.assertIn("WidgetWithChildrenShortcut", source)

    def test_timeline_click_sets_the_actual_seek_position(self):
        press_source = inspect.getsource(PreviewSlider.mousePressEvent)
        release_source = inspect.getsource(PreviewSlider.mouseReleaseEvent)
        self.assertIn("self.setSliderPosition(value)", press_source)
        self.assertIn("self.setSliderPosition(value)", release_source)
        self.assertIn("self.setSliderDown(False)", release_source)

    def test_skip_intro_uses_detected_chapter_end(self):
        load_source = inspect.getsource(AnimeWatcherWindow._load_episode)
        skip_source = inspect.getsource(AnimeWatcherWindow._skip_intro)
        tick_source = inspect.getsource(AnimeWatcherWindow._update_skip_intro)
        self.assertIn("probe_chapter_ranges", load_source)
        self.assertIn("self.player.seek(self.active_skip_chapter.end_ms)", skip_source)
        self.assertIn("chapter.start_ms <= position < chapter.end_ms", tick_source)

    def test_old_manual_monitor_positioning_is_not_in_player(self):
        source = inspect.getsource(AnimeWatcherWindow)
        self.assertNotIn("set_native_window_bounds", source)
        self.assertNotIn("monitor_bounds_for_window", source)
        self.assertNotIn("overrideredirect", source)

    def test_qt_player_replaces_the_vlc_native_window_path(self):
        source = inspect.getsource(AnimeWatcherWindow)
        self.assertIn("QtMediaPlayer(self)", source)
        self.assertNotIn("VLCPlayer", source)
        self.assertNotIn("winId()", source)

    def test_background_workers_are_retained_until_signal_delivery(self):
        source = inspect.getsource(AnimeWatcherWindow._start_worker)
        self.assertIn("active_workers.add", source)
        self.assertIn("setAutoDelete(False)", source)


if __name__ == "__main__":
    unittest.main()
