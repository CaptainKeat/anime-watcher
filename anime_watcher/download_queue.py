"""Session download jobs, independent of any page or active library profile."""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
import math
import time
from pathlib import Path
from typing import Callable
from uuid import uuid4
from PySide6.QtCore import QObject, Signal


FINISHED = {"Completed", "Failed", "Cancelled"}


@dataclass
class DownloadJob:
    title: str
    source: str
    url: str
    database: Path
    root: Path
    profile: str
    start: Callable
    cancel_action: Callable
    id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "Queued"
    detail: str = "Waiting for a download slot…"
    received: int = 0
    total: int = 0
    destination: Path | None = None
    open_player: Callable | None = None
    retry_action: Callable | None = None
    prepare_action: Callable | None = None
    diagnostics: dict = field(default_factory=dict)
    retry_data: dict = field(default_factory=dict)
    artwork: dict = field(default_factory=dict)
    attempt_history: list = field(default_factory=list)
    wco_attempt: int = 1
    _samples: deque = field(default_factory=deque, repr=False)

    @property
    def bytes_per_second(self):
        if self.status != "Downloading" or len(self._samples) < 2:
            return 0.0
        now = time.monotonic()
        while len(self._samples) > 2 and self._samples[1][0] < now - 5:
            self._samples.popleft()
        start, received = self._samples[0]
        elapsed = now - start
        return (self.received - received) / elapsed if elapsed >= 1 else 0.0

    @property
    def eta_seconds(self):
        speed = self.bytes_per_second
        ready = self._samples and time.monotonic() - self._samples[0][0] >= 2
        return math.ceil(max(0, self.total - self.received) / speed) if ready and speed > 0 and self.total else None

    @property
    def active(self):
        return self.status not in FINISHED | {"Queued"}


class DownloadQueue(QObject):
    changed = Signal(str)

    def __init__(self, parent=None, limit=3):
        super().__init__(parent)
        self.limit = limit
        self.jobs: dict[str, DownloadJob] = {}
        self._pumping = False
        self._stopping = False
        self.paused = False
        self._manual_order = False

    @property
    def active_count(self):
        return sum(job.active for job in self.jobs.values())

    @property
    def queued_count(self):
        return sum(job.status == "Queued" for job in self.jobs.values())

    @property
    def remaining_count(self):
        return self.active_count + self.queued_count

    @property
    def failed_count(self):
        return sum(job.status == "Failed" for job in self.jobs.values())

    @property
    def verifying_count(self):
        return sum(job.status == "Verifying" for job in self.jobs.values())

    @property
    def transfer_count(self):
        return sum(job.active and job.status != "Verifying" for job in self.jobs.values())

    def display_jobs(self):
        """Pin active jobs, then keep each series in numeric playback order."""
        groups, keys = {}, {}
        for position, job in enumerate(self.jobs.values()):
            data = job.retry_data
            try:
                series = str(data["title"]).strip().casefold()
                season, episode = int(data["season"]), int(data["number"])
                if not series or season < 0 or episode < 0:
                    raise ValueError("Invalid episode slot")
                group = (job.database, job.root, series)
                slot = (season, episode, str(data.get("language", "")))
            except (KeyError, TypeError, ValueError, OverflowError):
                # Unnumbered videos keep their original queue order.
                group, slot = job.id, (0, 0, "")
            group_order = groups.setdefault(group, len(groups))
            keys[job.id] = (not job.active, group_order, *slot, position)
        if self._manual_order:
            active = [job for job in self.jobs.values() if job.active]
            queued = [job for job in self.jobs.values() if job.status == 'Queued']
            finished = sorted((job for job in self.jobs.values() if job.status in FINISHED), key=lambda job: keys[job.id])
            return active + queued + finished
        return sorted(self.jobs.values(), key=lambda job: keys[job.id])

    def set_paused(self, paused):
        self.paused = bool(paused)
        self.changed.emit('')
        self._pump()

    def reorder(self, source_id, before_id):
        source, target = self.jobs.get(source_id), self.jobs.get(before_id)
        if source is None or target is None or source.status != 'Queued' or target.status != 'Queued' or source_id == before_id:
            return False
        rows = list(self.jobs.values()); rows.remove(source)
        rows.insert(rows.index(target), source)
        self.jobs = {job.id: job for job in rows}
        self._manual_order = True
        self.changed.emit('')
        return True

    def existing(self, source, url, database, root):
        return next((job for job in self.jobs.values() if job.status not in FINISHED
                     and (job.source, job.url, job.database, job.root) == (source, url, Path(database), Path(root))), None)

    def set_limit(self, limit):
        if not isinstance(limit, int) or not 1 <= limit <= 6:
            raise ValueError("Choose between one and six simultaneous downloads.")
        self.limit = limit
        self._pump()
        self.changed.emit("")

    def add(self, job):
        return self.add_many([job])[0]

    def add_many(self, jobs):
        accepted, added = [], []
        for job in jobs:
            existing = self.existing(job.source, job.url, job.database, job.root)
            if existing:
                accepted.append(existing)
            else:
                self.jobs[job.id] = job
                added.append(job)
                accepted.append(job)
        if added:
            # Build the list once before starting up to three transfers.
            self.changed.emit(added[0].id if len(added) == 1 else "")
            self._pump()
        return accepted

    def _pump(self):
        if self._pumping or self._stopping or self.paused:
            return
        self._pumping = True
        try:
            for job in list(self.jobs.values()):
                # Verification can overlap the next transfer, with backpressure
                # to keep a slow disk from building an unbounded import backlog.
                if self.transfer_count >= self.limit or self.verifying_count >= 2:
                    break
                if job.status == "Queued":
                    self.update(job.id, status="Connecting", detail="Connecting…")
                    try:
                        job.start()
                    except Exception as exc:
                        self.finish(job.id, "Failed", str(exc))
        finally:
            self._pumping = False

    def update(self, job_id, **changes):
        job = self.jobs.get(job_id)
        if job is None or job.status in FINISHED:
            return
        if job.status == "Cancelling":
            changes.pop("status", None)
            changes.pop("detail", None)
        status = changes.get("status", job.status)
        if status == "Downloading" and "received" in changes:
            now = time.monotonic()
            received = changes["received"]
            if not job._samples or received < job.received or job.status != "Downloading":
                job._samples.clear()
                job._samples.append((now, received))
            elif now - job._samples[-1][0] >= 0.25:
                job._samples.append((now, received))
            while len(job._samples) > 2 and job._samples[1][0] < now - 5:
                job._samples.popleft()
        for name, value in changes.items():
            setattr(job, name, value)
        self.changed.emit(job.id)
        if job.status == "Verifying":
            self._pump()

    def finish(self, job_id, status, detail, destination=None):
        if status not in FINISHED:
            raise ValueError("Use a finished download status")
        job = self.jobs.get(job_id)
        if job is None or job.status in FINISHED:
            return
        job.status, job.detail = status, detail
        job.destination = Path(destination) if destination else None
        self.changed.emit(job.id)
        self._pump()

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if job is None or job.status in FINISHED | {"Cancelling", "Verifying"}:
            return
        if job.status == "Queued":
            try:
                job.cancel_action()
            except Exception as exc:
                self.finish(job.id, "Failed", str(exc))
            else:
                self.finish(job.id, "Cancelled", "Cancelled before starting.")
        else:
            self.update(job.id, status="Cancelling", detail="Cancelling…")
            try:
                job.cancel_action()
            except Exception as exc:
                self.finish(job.id, "Failed", str(exc))

    def retry(self, job_id, *, automatic=False):
        job = self.jobs.get(job_id)
        allowed = {"Failed", "Cancelled"} if not automatic else {"Connecting", "Downloading", "Verifying"}
        if self._stopping or job is None or job.status not in allowed:
            return False
        if self.existing(job.source, job.url, job.database, job.root) not in (None, job):
            return False
        job.attempt_history.append(dict(status=job.status, detail=job.detail,
                                        received=job.received, total=job.total, **job.diagnostics))
        job.status, job.detail = "Queued", "Waiting to retry…"
        job.received = job.total = 0
        job.destination = job.open_player = None
        job.diagnostics = {}
        job._samples.clear()
        if not automatic:
            job.wco_attempt = 1
        # Keep the identity and UI block, but retry behind existing waiters.
        self.jobs.pop(job_id)
        self.jobs[job_id] = job
        self.changed.emit(job_id)
        self._pump()
        return True

    def clear_finished(self):
        self.jobs = {key: job for key, job in self.jobs.items() if job.status not in FINISHED}
        self.changed.emit("")

    def stop(self):
        self._stopping = True
        for job in list(self.jobs.values()):
            self.cancel(job.id)
