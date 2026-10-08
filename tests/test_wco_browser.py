import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from types import MethodType
from PySide6.QtCore import QUrl
from anime_watcher.wco_browser import WcoDownloadDialog


class WcoDownloadRequestTests(unittest.TestCase):
    def request(self, host='u11.wcostream.com', mime='video/mp4'):
        page=object()
        request=Mock();request.page.return_value=page
        request.url.return_value=QUrl('https://'+host+'/getvid?redirected=1')
        request.mimeType.return_value=mime
        return page,request

    def context(self, page, tmp):
        context=SimpleNamespace(closed=False,page=page,pending_url='https://neptun.wcostream.com/getvid?selected=1',download_dir=Path(tmp),library_root=Path(tmp)/'library',status=Mock(),_progress=Mock(),_download_state=Mock(),_failed=Mock(),auto_download=True,_player_frame=Mock(return_value=Mock()),timer=Mock(),transfer_started=Mock())
        context._release_preview=MethodType(WcoDownloadDialog._release_preview,context)
        return context

    def test_same_player_redirect_is_accepted_and_saved_in_separate_folder(self):
        page,request=self.request()
        with tempfile.TemporaryDirectory() as tmp:
            context=self.context(page,tmp)
            WcoDownloadDialog._download_requested(context,request)
            request.accept.assert_called_once()
            self.assertTrue(context.staging.is_dir())
            self.assertEqual(context.staging.parent,Path(tmp)/'library'/'.anime-watcher-downloads')
            request.setDownloadFileName.assert_called_once_with('episode.mp4')
            context.transfer_started.emit.assert_called_once()
            context._player_frame().runJavaScript.assert_called_once()
            self.assertIn("removeAttribute('src')",context._player_frame().runJavaScript.call_args.args[0])

    def test_wrong_domain_or_html_response_is_cancelled(self):
        for host,mime in [('evil.example','video/mp4'),('u11.wcostream.com','text/html')]:
            with tempfile.TemporaryDirectory() as tmp:
                page,request=self.request(host,mime)
                WcoDownloadDialog._download_requested(self.context(page,tmp),request)
                request.cancel.assert_called_once();request.accept.assert_not_called()
                self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_unrelated_page_download_is_not_consumed(self):
        page,request=self.request()
        with tempfile.TemporaryDirectory() as tmp:
            context=self.context(object(),tmp)
            WcoDownloadDialog._download_requested(context,request)
            request.accept.assert_not_called();request.cancel.assert_not_called()

    def test_browser_action_passes_required_result_callback(self):
        frame=Mock()
        context=SimpleNamespace(_player_frame=lambda:frame)
        WcoDownloadDialog._click(context,'document.querySelector("button").click()')
        self.assertEqual(len(frame.runJavaScript.call_args.args),2)
        self.assertTrue(callable(frame.runJavaScript.call_args.args[1]))


class WcoRecoveryTests(unittest.TestCase):
    def test_refreshing_stale_prepared_source_does_not_reset_retry_budget(self):
        context=self.context();context.attempt=4;context.prepared_at=10;context.defer_download=True
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=50):WcoDownloadDialog.begin_download(context)
        self.assertEqual(context.attempt,4);context.page.load.assert_called_once();context.failed.emit.assert_not_called()
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=171):context._poll()
        context.failed.emit.assert_called_once();self.assertIn('4 attempts',context.failed.emit.call_args.args[0])

    def test_prepared_player_waits_for_admission_and_old_source_is_refreshed(self):
        context=self.context();context.defer_download=True;context.prepared_at=0;context._release_preview=Mock()
        context.requested_quality='FHD'
        state=dict(choices=['SD','FHD'],selected='FHD',src='https://u11.wcostream.com/getvid?fhd',mp4Support='',height=0,width=0,readyState=0,error='')
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=10):context._state_ready(json.dumps(state))
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=14):context._state_ready(json.dumps(state))
        self.assertEqual(context.prepared_at,14);context._save_selected.assert_not_called();self.assertTrue(context._release_preview.called)
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=200):context._poll()
        self.assertFalse(context.terminal);self.assertEqual(context.attempt,1)
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=20):WcoDownloadDialog.begin_download(context)
        context._save_selected.assert_called_once();self.assertFalse(context.defer_download)
        context._save_selected.reset_mock()
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=50):WcoDownloadDialog.begin_download(context)
        context._save_selected.assert_not_called();context.page.load.assert_called_once();self.assertEqual(context.prepared_at,0)

    def context(self):
        context=SimpleNamespace(closed=False,terminal=False,download=None,worker=None,polling=False,
            pending_url=None,pending_since=0,started=0,action_time=0,attempt=1,generation=0,
            requested_quality=None,selection_attempts=0,quality_source_before=None,
            quality_confirmation=None,quality_candidate=None,media_state={},play_requested=False,auto_download=True,
            last_received=0,last_activity=0,status=Mock(),save_button=Mock(),timer=Mock(),
            page=Mock(),episode=SimpleNamespace(url='https://www.wco.tv/ep'),failed=Mock(),retry_requested=Mock(),cancel_requested=False,
            QUALITY_TIMEOUT=120,TRANSFER_TIMEOUT=120,MAX_ATTEMPTS=WcoDownloadDialog.MAX_ATTEMPTS,
            _player_frame=Mock(return_value=None),_click=Mock(),_save_selected=Mock(),_release_preview=Mock())
        for name in ('_failed','_retry_player','_queue_retry','_state_ready','_poll'):
            setattr(context,name,MethodType(getattr(WcoDownloadDialog,name),context))
        return context

    def test_quality_timeout_is_bounded_at_four_attempts_even_if_js_callback_is_lost(self):
        context=self.context();context.polling=True
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=121):context._poll()
        self.assertEqual(context.attempt,2);context.page.load.assert_called_once()
        self.assertFalse(context.polling);self.assertTrue(context.auto_download)
        for number in (2,3):
            context.polling=True
            with patch('anime_watcher.wco_browser.time.monotonic',return_value=121*number):context._poll()
            self.assertEqual(context.attempt,number+1);context.failed.emit.assert_not_called()
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=484):context._poll()
        self.assertTrue(context.terminal);context.failed.emit.assert_called_once()
        self.assertIn('highest available quality',context.failed.emit.call_args.args[0])
        context.timer.stop.assert_called_once()

    def test_download_handshake_timeout_is_bounded_and_reloads(self):
        context=self.context();context.pending_url='https://u11.wcostream.com/getvid'
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=61):context._poll()
        self.assertEqual(context.attempt,2);self.assertIsNone(context.pending_url)

    def test_stalled_transfer_fails_but_slow_progress_resets_deadline(self):
        context=self.context();context.download=Mock()
        context.download.receivedBytes.return_value=1;context.download.isFinished.return_value=False
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=121):context._poll()
        context.failed.emit.assert_not_called()
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=242):context._poll()
        self.assertTrue(context.terminal);context.retry_requested.emit.assert_called_once()
        context.download.cancel.assert_called_once();context.failed.emit.assert_not_called()

    def test_automatic_transfer_retry_stops_at_four_and_cancel_never_retries(self):
        context=self.context();context.attempt=4;context.download=Mock();context.download.isFinished.return_value=False
        context._queue_retry('Server stopped')
        context.failed.emit.assert_called_once();context.retry_requested.emit.assert_not_called();context.download.cancel.assert_called_once()
        self.assertIn('4 attempts',context.failed.emit.call_args.args[0])
        cancelled=self.context();cancelled.cancel_requested=True
        cancelled._queue_retry('Late failure');cancelled.retry_requested.emit.assert_not_called();cancelled.failed.emit.assert_not_called()

    def test_only_video_verification_failures_are_automatically_retryable(self):
        from anime_watcher.wco import VideoVerificationError
        from anime_watcher.wco_browser import ImportThread
        for error,retryable in ((VideoVerificationError('480p instead of 1080p'),True),(OSError('Disk full'),False)):
            worker=ImportThread(Path('video.mp4'),Path('library'),'Show',None,1080,None)
            retry=Mock();failure=Mock();worker.retryable_failed.connect(retry);worker.failed.connect(failure)
            with patch('anime_watcher.wco_browser.import_wco_video',side_effect=error):worker.run()
            self.assertEqual(retry.call_count,int(retryable));self.assertEqual(failure.call_count,int(not retryable))

    def test_old_page_callback_cannot_change_new_attempt(self):
        context=self.context();context.generation=1;context.polling=True
        context._state_ready('{}',0)
        self.assertTrue(context.polling);self.assertEqual(context.media_state,{})

    def test_quality_choice_retried_and_default_video_never_auto_saved(self):
        context=self.context()
        state=dict(choices=['SD','FHD'],selected='SD',src='https://u11.wcostream.com/getvid?sd',mp4Support='',height=0,width=0,readyState=0,error='')
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=10):context._state_ready(json.dumps(state))
        self.assertEqual(context.requested_quality,'FHD');self.assertEqual(context.selection_attempts,1)
        self.assertIn('.vjs-quality-dropdown li[data-code]',context._click.call_args.args[0])
        context.action_time=10
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=19):context._state_ready(json.dumps(state))
        self.assertEqual(context.selection_attempts,2);context._save_selected.assert_not_called()
        # A displayed FHD badge with the old SD source is insufficient.
        state['selected']='FHD'
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=24):context._state_ready(json.dumps(state))
        context._save_selected.assert_not_called()
        state['src']='https://u11.wcostream.com/getvid?fhd'
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=26):context._state_ready(json.dumps(state))
        context._save_selected.assert_not_called()
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=30):context._state_ready(json.dumps(state))
        context._save_selected.assert_called_once()

    def test_missing_quality_menu_does_not_download_default_source(self):
        context=self.context()
        state=dict(choices=[],selected='SD',src='https://u11.wcostream.com/getvid?sd',mp4Support='',height=0,width=0,readyState=0,error='')
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=10):context._state_ready(json.dumps(state))
        context._save_selected.assert_not_called()

    def test_declared_single_stream_survives_unsupported_preview_and_waits_for_admission(self):
        context=self.context();context.defer_download=True;context.prepared_at=0
        state=dict(singleSource=True,choices=[],selected='',src='https://ndisk.wcostream.com/getvid?sd',
                   mp4Support='',height=0,width=0,readyState=0,error='',playReady=True)
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=10):context._state_ready(json.dumps(state))
        context._click.assert_not_called();context._release_preview.assert_called_once()
        self.assertEqual(context.quality_candidate,state);context._save_selected.assert_not_called()
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=14):context._poll()
        self.assertEqual(context.prepared_at,14);context._save_selected.assert_not_called()
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=20):WcoDownloadDialog.begin_download(context)
        context._save_selected.assert_called_once()

    def test_lost_quality_control_cannot_downgrade_previously_requested_fhd(self):
        context=self.context();context.requested_quality='FHD';context.selection_attempts=1
        state=dict(singleSource=True,choices=[],selected='',src='https://ndisk.wcostream.com/getvid?sd',
                   mp4Support='',height=0,width=0,readyState=0,error='')
        for now in (10,14):
            with patch('anime_watcher.wco_browser.time.monotonic',return_value=now):context._state_ready(json.dumps(state))
        context._save_selected.assert_not_called();self.assertIsNone(context.quality_candidate)

    def test_single_source_marker_does_not_override_offered_fhd(self):
        context=self.context()
        state=dict(singleSource=True,choices=['SD','HD','FHD'],selected='SD',src='https://ndisk.wcostream.com/getvid?sd',
                   mp4Support='',height=0,width=0,readyState=0,error='')
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=10):context._state_ready(json.dumps(state))
        self.assertEqual(context.requested_quality,'FHD');context._save_selected.assert_not_called()

    def test_unlabeled_stream_transfer_and_completion_never_claim_zero_p(self):
        context=self.context();context.defer_download=False
        context.media_state=dict(singleSource=True,choices=[],selected='',src='https://ndisk.wcostream.com/getvid?sd',
                                mp4Support='',height=0,width=0,readyState=0,error='')
        WcoDownloadDialog._save_selected(context)
        self.assertEqual(context.selected_height,0);context.page.download.assert_called_once()
        context.download=Mock();context.download.receivedBytes.return_value=1048576;context.download.totalBytes.return_value=2097152
        context.progress=Mock();context.completed=Mock()
        WcoDownloadDialog._progress(context)
        WcoDownloadDialog._imported(context,SimpleNamespace(destination=Path('Show [480p].mp4')))
        self.assertTrue(all(' 0p' not in call.args[0] for call in context.status.setText.call_args_list))
        self.assertIn('[480p]',context.status.setText.call_args.args[0])

    def test_codec_fallback_does_not_play_and_replace_real_source_with_error_video(self):
        context=self.context();context.requested_quality='FHD';context.selection_attempts=1
        state=dict(choices=['SD','FHD'],selected='FHD',src='https://u11.wcostream.com/getvid?fhd',mp4Support='',height=0,width=0,readyState=0,error='',playReady=True)
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=10):context._state_ready(json.dumps(state))
        context._click.assert_not_called()
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=14):context._state_ready(json.dumps(state))
        context._save_selected.assert_called_once()

    def test_error_clip_with_fhd_badge_reselects_without_reusing_confirmation(self):
        context=self.context();context.requested_quality='FHD';context.selection_attempts=1
        context.action_time=10;context.quality_confirmation=(('FHD','https://u11.wcostream.com/getvid?fhd'),11)
        state=dict(choices=['SD','FHD'],selected='FHD',src='https://embed.wcostream.com/error.mp4',mp4Support='',height=0,width=0,readyState=4,error='')
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=15):context._state_ready(json.dumps(state))
        self.assertIsNone(context.quality_confirmation);context._click.assert_not_called()
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=19):context._state_ready(json.dumps(state))
        self.assertEqual(context.selection_attempts,2);self.assertIn('.vjs-quality-dropdown',context._click.call_args.args[0])
        context._save_selected.assert_not_called()
        context.selection_attempts=3;context.action_time=19
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=28):context._state_ready(json.dumps(state))
        self.assertEqual(context.attempt,2);context.page.load.assert_called_once()

    def test_unsupported_selected_source_survives_preview_shutdown_until_save(self):
        context=self.context();context.requested_quality='FHD';context.selection_attempts=1
        state=dict(choices=['SD','FHD'],selected='FHD',src='https://u11.wcostream.com/getvid?fhd',mp4Support='',height=0,width=0,readyState=0,error='')
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=10):context._state_ready(json.dumps(state))
        context._release_preview.assert_called_once();self.assertEqual(context.quality_candidate,state)
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=14):context._poll()
        context._save_selected.assert_called_once();context._player_frame.assert_not_called()
        with patch('anime_watcher.wco_browser.time.monotonic',return_value=15):context._retry_player('Refresh')
        self.assertIsNone(context.quality_candidate)


if __name__=='__main__':unittest.main()
