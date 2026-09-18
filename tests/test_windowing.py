import unittest

from anime_watcher.windowing import geometry_for_bounds


class WindowGeometryTests(unittest.TestCase):
    def test_primary_monitor_geometry(self):
        self.assertEqual(geometry_for_bounds((0, 0, 1920, 1080)), "1920x1080+0+0")

    def test_monitor_left_of_primary_uses_negative_position(self):
        self.assertEqual(geometry_for_bounds((-2560, 0, 0, 1440)), "2560x1440-2560+0")

    def test_monitor_above_primary_uses_negative_position(self):
        self.assertEqual(geometry_for_bounds((0, -1080, 1920, 0)), "1920x1080+0-1080")
