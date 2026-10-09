import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from anime_watcher.wco import offered_quality
from anime_watcher.wco_browser import WcoQualityProbe


class OfferedQualityTests(unittest.TestCase):
    def test_highest_offered_fhd_and_numeric_resolutions_are_ranked(self):
        result = offered_quality({'choices': ['SD', 'HD', 'FHD']})
        self.assertEqual(result['label'], 'Best: FHD (1080p)')
        self.assertTrue(result['offered']); self.assertIn('less than advertised', result['detail'])
        self.assertEqual(offered_quality({'choices': ['FHD', '2160p']})['height'], 2160)

    def test_sd_menu_does_not_claim_480p_and_announcement_is_not_ready(self):
        self.assertEqual(offered_quality({'choices': ['SD']})['label'], 'Best: SD')
        self.assertIsNone(offered_quality({'choices': ['FHD'], 'closeReady': True}))
        self.assertIsNone(offered_quality({'choices': [], 'height': 1080}))

    def test_declared_single_source_reports_actual_dimensions_or_unknown(self):
        state = {'singleSource': True, 'choices': [], 'selected': '', 'src': 'https://embed.wcostream.com/getvid?x=1', 'mp4Support': '', 'height': 0}
        self.assertEqual(offered_quality(state)['label'], 'Best: SD (resolution unknown)')
        state.update(readyState=2, width=640, height=360, duration=1200)
        self.assertEqual(offered_quality(state)['label'], 'Best: 360p')

    def context(self):
        return SimpleNamespace(closed=False, polling=True, started=0, action_time=0, play_requested=False, stop=Mock(), ready=Mock(), failed=Mock(), _player_frame=Mock(return_value=Mock()))

    def test_probe_only_reports_offered_quality_and_never_selects_or_downloads(self):
        context = self.context()
        WcoQualityProbe._state_ready(context, json.dumps({'choices': ['FHD', 'HD'], 'selected': 'HD'}))
        context.stop.assert_called_once(); context.ready.emit.assert_called_once()
        context._player_frame.assert_not_called()

    def test_late_or_malformed_player_results_do_not_emit(self):
        context = self.context(); context.closed = True
        WcoQualityProbe._state_ready(context, json.dumps({'choices': ['FHD']}))
        context.ready.emit.assert_not_called()
        context.closed = False
        WcoQualityProbe._state_ready(context, 'not JSON')
        context.ready.emit.assert_not_called()

    def test_timeout_is_bounded_and_stops_probe(self):
        context = self.context(); context.TIMEOUT = 30; context._fail = Mock()
        with patch('anime_watcher.wco_browser.time.monotonic', return_value=31):
            WcoQualityProbe._poll(context)
        context._fail.assert_called_once()


if __name__ == '__main__':
    unittest.main()
