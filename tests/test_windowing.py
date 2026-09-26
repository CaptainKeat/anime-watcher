import unittest

from anime_watcher.windowing import geometry_for_bounds, overlay_bounds_for_video


class WindowGeometryTests(unittest.TestCase):
    def test_primary_monitor_geometry(self):
        self.assertEqual(geometry_for_bounds((0, 0, 1920, 1080)), "1920x1080+0+0")

    def test_monitor_left_of_primary_uses_negative_position(self):
        self.assertEqual(geometry_for_bounds((-2560, 0, 0, 1440)), "2560x1440-2560+0")

    def test_monitor_above_primary_uses_negative_position(self):
        self.assertEqual(geometry_for_bounds((0, -1080, 1920, 0)), "1920x1080+0-1080")

    def test_high_dpi_fallback_divides_physical_monitor_size(self):
        self.assertEqual(
            geometry_for_bounds((-3840, -742, 0, 1418), 3.0),
            "1280x720-3840-742",
        )

    def test_scaled_tv_overlays_stay_inside_physical_video_bounds(self):
        video = (-3840, -742, 0, 1418)
        topbar, controls, input_layer = overlay_bounds_for_video(video, 3.0)

        self.assertEqual(topbar, (-3840, -742, 0, -514))
        self.assertEqual(controls, (-3840, 908, 0, 1418))
        self.assertEqual(input_layer, (-3840, -514, 0, 908))
        for bounds in (topbar, controls, input_layer):
            self.assertGreaterEqual(bounds[0], video[0])
            self.assertLessEqual(bounds[2], video[2])
            self.assertGreaterEqual(bounds[1], video[1])
            self.assertLessEqual(bounds[3], video[3])

    def test_overlay_regions_collapse_safely_for_tiny_windows(self):
        topbar, controls, input_layer = overlay_bounds_for_video((10, 20, 110, 120), 2.0)

        self.assertEqual(topbar, (10, 20, 110, 120))
        self.assertEqual(controls, (10, 120, 110, 120))
        self.assertEqual(input_layer, (10, 120, 110, 120))
