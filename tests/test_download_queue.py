import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from anime_watcher.download_queue import DownloadJob, DownloadQueue


def job(number, start=None, cancel=None):
    return DownloadJob(f'Episode {number}', 'WCO', f'https://www.wco.tv/episode-{number}', Path('owner.db'), Path('library'), 'Default', start or Mock(), cancel or Mock())


class DownloadQueueTests(unittest.TestCase):
    def test_retry_preserves_identity_resets_progress_and_waits_behind_older_jobs(self):
        queue=DownloadQueue(limit=1);first=queue.add(job(1));second=queue.add(job(2));third=queue.add(job(3))
        first.received=first.total=100;first.diagnostics={'attempt':4}
        queue.finish(first.id,'Failed','Wrong resolution');self.assertTrue(queue.retry(first.id))
        self.assertEqual(len(queue.jobs),3);self.assertIs(queue.jobs[first.id],first)
        self.assertEqual((first.status,first.received,first.total),('Queued',0,0));self.assertEqual(first.attempt_history[0]['attempt'],4)
        queue.finish(second.id,'Completed','Saved');third.start.assert_called_once();self.assertEqual(first.start.call_count,1)
        queue.finish(third.id,'Completed','Saved');self.assertEqual(first.start.call_count,2)
        self.assertFalse(queue.retry(first.id));queue.stop();self.assertFalse(queue.retry(first.id))

    def test_retry_does_not_duplicate_an_existing_transfer_of_the_same_episode(self):
        queue=DownloadQueue(limit=1);first=queue.add(job(1));queue.finish(first.id,'Failed','Error');new=queue.add(job(1))
        self.assertFalse(queue.retry(first.id));self.assertEqual(first.status,'Failed');self.assertEqual(new.status,'Connecting')

    def test_transfer_rate_eta_and_reset_for_another_stream(self):
        queue=DownloadQueue();item=queue.add(job(1))
        with patch('anime_watcher.download_queue.time.monotonic',return_value=10):
            queue.update(item.id,status='Downloading',received=0,total=10*1048576)
        with patch('anime_watcher.download_queue.time.monotonic',return_value=12):
            queue.update(item.id,received=2*1048576)
            self.assertEqual(item.bytes_per_second,1048576);self.assertEqual(item.eta_seconds,8)
        with patch('anime_watcher.download_queue.time.monotonic',return_value=14):
            queue.update(item.id,received=0)
            self.assertEqual(item.bytes_per_second,0);self.assertIsNone(item.eta_seconds)
        queue.update(item.id,status='Verifying')
        self.assertEqual(item.bytes_per_second,0);self.assertIsNone(item.eta_seconds)

    def test_increasing_limit_starts_waiters_and_lowering_does_not_cancel(self):
        queue=DownloadQueue(limit=1);items=[queue.add(job(n)) for n in range(5)]
        queue.set_limit(3);self.assertEqual(queue.active_count,3)
        queue.set_limit(1);self.assertEqual(queue.active_count,3)
        for item in items[:2]:queue.finish(item.id,'Completed','Saved')
        self.assertEqual(queue.queued_count,2)
        queue.finish(items[2].id,'Completed','Saved');self.assertEqual(items[3].status,'Connecting')
        for item in items:item.cancel_action.assert_not_called()
        for invalid in (0,7,'3'):
            with self.assertRaises(ValueError):queue.set_limit(invalid)

    def test_capacity_counts_and_fifo_after_completion(self):
        queue=DownloadQueue(limit=2)
        jobs=[queue.add(job(n)) for n in range(4)]
        self.assertEqual((queue.active_count,queue.queued_count),(2,2))
        jobs[2].start.assert_not_called()
        queue.finish(jobs[0].id,'Completed','Saved',Path('episode.mp4'))
        jobs[2].start.assert_called_once();jobs[3].start.assert_not_called()
        self.assertEqual((queue.active_count,queue.queued_count),(2,1))

    def test_cancel_queued_never_starts_and_active_stays_counted_until_ack(self):
        queue=DownloadQueue(limit=1)
        active=queue.add(job(1));queued=queue.add(job(2))
        queue.cancel(queued.id)
        queued.start.assert_not_called();queued.cancel_action.assert_called_once()
        self.assertEqual(queued.status,'Cancelled')
        queue.cancel(active.id)
        self.assertEqual(queue.active_count,1)
        queue.update(active.id,status='Downloading',detail='Late progress',received=5)
        self.assertEqual(active.status,'Cancelling')
        self.assertIn('Cancelling',active.detail)
        queue.finish(active.id,'Cancelled','Stopped')
        self.assertEqual(queue.active_count,0)

    def test_late_progress_cannot_reopen_finished_job(self):
        queue=DownloadQueue();item=queue.add(job(1))
        queue.finish(item.id,'Completed','Saved')
        queue.update(item.id,status='Downloading',received=2)
        self.assertEqual(item.status,'Completed')
        self.assertEqual(queue.active_count,0)
        queue.clear_finished();self.assertFalse(queue.jobs)

    def test_duplicate_is_scoped_to_owner_and_destination(self):
        queue=DownloadQueue();first=queue.add(job(1));duplicate=job(1)
        self.assertIs(queue.add(duplicate),first);duplicate.start.assert_not_called()
        other=job(1);other.database=Path('other.db')
        self.assertIs(queue.add(other),other)
        self.assertEqual(queue.active_count,2)

    def test_shutdown_does_not_start_queued_jobs_and_verification_finishes(self):
        queue=DownloadQueue(limit=1);active=queue.add(job(1));pending=queue.add(job(2));waiting=queue.add(job(3))
        queue.update(active.id,status='Verifying')
        pending.start.assert_called_once()
        queue.stop()
        active.cancel_action.assert_not_called();waiting.start.assert_not_called()
        pending.cancel_action.assert_called_once()
        queue.finish(active.id,'Completed','Saved')
        queue.finish(pending.id,'Cancelled','Stopped')
        self.assertEqual(queue.active_count,0);self.assertEqual(waiting.status,'Cancelled')

    def test_verification_overlaps_transfer_with_bounded_backlog(self):
        queue=DownloadQueue(limit=1);items=[queue.add(job(n)) for n in range(3)]
        queue.update(items[0].id,status='Verifying')
        self.assertEqual((queue.verifying_count,queue.transfer_count),(1,1))
        queue.update(items[1].id,status='Verifying');items[2].start.assert_not_called()
        self.assertEqual(queue.verifying_count,2)
        queue.finish(items[0].id,'Failed','Invalid video');items[2].start.assert_called_once()
        self.assertEqual((queue.verifying_count,queue.transfer_count),(1,1))

    def test_failed_start_releases_capacity(self):
        queue=DownloadQueue(limit=1);failed=job(1,start=Mock(side_effect=RuntimeError('Missing browser')))
        queue.add(failed);next_job=queue.add(job(2))
        self.assertEqual(failed.status,'Failed');next_job.start.assert_called_once()

    def test_batch_is_admitted_once_and_respects_capacity_and_duplicates(self):
        queue=DownloadQueue(limit=3);events=[];queue.changed.connect(events.append)
        jobs=[job(n) for n in range(24)]
        accepted=queue.add_many(jobs+[job(0)])
        self.assertEqual(len(queue.jobs),24);self.assertIs(accepted[-1],jobs[0])
        self.assertEqual(events[0],'');self.assertEqual(len(events),4)
        self.assertEqual((queue.active_count,queue.queued_count),(3,21))
        for item in jobs[:3]:item.start.assert_called_once()
        for item in jobs[3:]:item.start.assert_not_called()
        queue.finish(jobs[0].id,'Failed','Timeout')
        jobs[3].start.assert_called_once();self.assertEqual(queue.active_count,3)


if __name__=='__main__':unittest.main()
