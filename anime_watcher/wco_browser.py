"""A normal, isolated Qt browser session for WCO catalogs and video downloads."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QByteArray, QObject, QThread, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEngineHttpRequest, QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from .downloader import MAX_CATALOG_BYTES, EpisodeResult, extract_catalog_results, extract_episode_results, is_wco_url, wco_search_request
from .wco import VideoVerificationError, best_quality, downloadable_media, import_wco_video, playable_media, quality_height, single_stream_media
from .organizer import DOWNLOAD_STAGING_DIRECTORY


class WcoRequestFilter(QWebEngineUrlRequestInterceptor):
    """Keep this dedicated browser on WCO and its player/static dependencies."""
    def interceptRequest(self, info):
        url = info.requestUrl()
        host = url.host().casefold()
        allowed = (host in {"wco.tv", "www.wco.tv", "cdn.jsdelivr.net", "cdnjs.cloudflare.com", "fonts.googleapis.com", "fonts.gstatic.com", "www.gstatic.com", "code.jquery.com", "maxcdn.bootstrapcdn.com"}
                   or host == "wcostream.com" or host.endswith(".wcostream.com")
                   or host == "cloudflare.com" or host.endswith(".cloudflare.com"))
        if url.scheme() in {"http", "https"} and not allowed:
            info.block(True)


class WcoPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        # Embedded players retain ordinary cross-origin browser behavior; popups
        # and unrelated top-level ad navigation do not replace the selected show.
        return not is_main_frame or is_wco_url(url.toString()) or url.toString() == "about:blank"


class WcoCatalogSession(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = QWebEngineProfile(self)  # off the record; no Chrome cookies
        self.request_filter = WcoRequestFilter(self.profile)
        self.profile.setUrlRequestInterceptor(self.request_filter)
        self.page = WcoPage(self.profile, self)
        self.page.permissionRequested.connect(lambda permission: permission.deny())
        self.job = None
        self.token = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self._fail("WCO did not finish loading. Open its browser connection and try again."))
        self.page.loadFinished.connect(self._loaded)

    def search(self, query, done, failed):
        url, body = wco_search_request(query)
        request = QWebEngineHttpRequest(QUrl(url), QWebEngineHttpRequest.Method.Post)
        request.setHeader(QByteArray(b"Content-Type"), QByteArray(b"application/x-www-form-urlencoded"))
        request.setPostData(QByteArray(body))
        self._load(request, "search", query, done, failed)

    def episodes(self, url, done, failed):
        if not is_wco_url(url):
            return failed("This is not a WCO show page.")
        self._load(QWebEngineHttpRequest(QUrl(url)), "episodes", "", done, failed)

    def _load(self, request, kind, query, done, failed):
        self.token += 1
        self.job = (self.token, kind, query, done, failed)
        self.timer.start(45000)
        self.page.load(request)

    def _fail(self, message):
        job, self.job = self.job, None
        self.timer.stop()
        if job:
            job[4](message)

    def _loaded(self, ok):
        if not self.job:
            return
        token = self.job[0]
        self.page.toHtml(lambda html: self._html_ready(token, html, ok))

    def _html_ready(self, token, html, ok=True):
        if not self.job or self.job[0] != token:
            return
        if len(html.encode("utf-8")) > MAX_CATALOG_BYTES:
            return self._fail("The WCO catalog page is too large.")
        if any(marker in html.casefold() for marker in ("<title>just a moment", "<title>access denied", "<title>attention required")):
            return self._fail("WCO needs browser verification. Open its browser connection, then retry the search.")
        _, kind, query, done, _ = self.job
        url = self.page.url().toString()
        results = extract_catalog_results(html, url, query) if kind == "search" else extract_episode_results(html, url)
        if not results and not ok:
            return self._fail("WCO could not load in the browser. Open its browser connection and try again.")
        self.job = None
        self.timer.stop()
        QTimer.singleShot(0, lambda: done(results))

    def open_connection(self, parent):
        dialog = QDialog(parent)
        dialog.setWindowTitle("WCO browser connection")
        dialog.resize(1000, 760)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Browse WCO here, then return to Downloads to search. This session stays inside Anime Watcher."))
        view = QWebEngineView(dialog)
        view.setPage(self.page)
        layout.addWidget(view)
        if not is_wco_url(self.page.url().toString()):
            self.page.load(QUrl("https://www.wco.tv/"))
        dialog.exec()

    def close(self):
        self.job = None
        self.timer.stop()
        self.page.triggerAction(QWebEnginePage.WebAction.Stop)
        self.page.setUrl(QUrl("about:blank"))


PLAYER_STATE = """JSON.stringify((() => {
 const video = document.querySelector('video');
 const close = document.querySelector('#close-btn');
 const announcement = document.querySelector('#announcement');
 const buttons = Array.from(document.querySelectorAll('button'));
 const menu = Array.from(document.querySelectorAll('.vjs-quality-dropdown li[data-code]'));
 const choices = (menu.length ? menu.filter(li => !li.classList.contains('disabled') && li.getAttribute('aria-disabled') !== 'true') : Array.from(document.querySelectorAll('a:not(.vjs-brand-quality-link)'))).map(a => a.textContent.trim()).filter(t => /^(FHD|HD|SD|[0-9]{3,4}p)$/i.test(t));
 const selected = document.querySelector('.vjs-brand-quality-link');
 const player = typeof videojs !== 'undefined' && typeof videojs.getPlayer === 'function'
   ? videojs.getPlayer('video-js') : null;
 // Missing controls alone are insufficient: wait for the normal player's
 // source response and require it to declare no HD/FHD alternative.
 const singleSource = location.hostname === 'embed.wcostream.com'
   && location.pathname === '/inc/embed/video-js.php'
   && !announcement && !selected && !document.querySelector('.vjs-quality-dropdown')
   && typeof vsd !== 'undefined' && !!vsd
   && typeof vhd !== 'undefined' && !vhd
   && typeof vfhd !== 'undefined' && !vfhd
   && !!player && typeof player.currentSources === 'function'
   && player.currentSources().length === 1;
 return {closeReady:!!(close && !close.disabled && announcement && getComputedStyle(announcement).display !== 'none'),
 playReady:buttons.some(b => (b.title === 'Play Video' || b.textContent.trim() === 'Play Video') && getComputedStyle(b).display !== 'none'),
 choices, selected:selected ? selected.textContent.trim() : '', singleSource,
 src:video ? (video.src || video.currentSrc) : '', readyState:video ? video.readyState : 0,
 mp4Support:video ? video.canPlayType('video/mp4; codecs="avc1.42E01E"') : null,
 width:video ? video.videoWidth : 0, height:video ? video.videoHeight : 0,
 duration:video && Number.isFinite(video.duration) ? video.duration : 0,
 error:video && video.error ? video.error.message : '', errorCode:video && video.error ? video.error.code : null};
})())"""


class ImportThread(QThread):
    done = Signal(object)
    failed = Signal(str)
    retryable_failed = Signal(str)

    def __init__(self, path, root, title, episode, height, parent):
        super().__init__(parent)
        self.arguments = (path, root, title, episode, height)

    def run(self):
        try:
            self.done.emit(import_wco_video(*self.arguments))
        except VideoVerificationError as exc:
            self.retryable_failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class WcoDownloadDialog(QDialog):
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    transfer_started = Signal()
    verification_started = Signal()
    retry_requested = Signal(str, int)
    QUALITY_TIMEOUT = 120
    TRANSFER_TIMEOUT = 120
    MAX_ATTEMPTS = 4

    def __init__(self, session, title, episode: EpisodeResult, download_dir, library_root, parent=None, *, defer_download=False, attempt=1):
        super().__init__(parent)
        self.setWindowTitle(f"Download · {title} · {episode.title}")
        self.resize(1040, 800)
        self.session, self.title, self.episode = session, title, episode
        self.download_dir, self.library_root = Path(download_dir), Path(library_root)
        self.page = WcoPage(session.profile, self)
        self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        self.page.renderProcessTerminated.connect(self._renderer_stopped)
        self.page.permissionRequested.connect(lambda permission: permission.deny())
        self.download = None
        self.pending_url = None
        self.pending_since = 0.0
        self.worker = None
        self.polling = False
        self.closed = False
        self.terminal = False
        self.cancel_requested = False
        self.requested_quality = None
        self.attempt = attempt
        self.generation = 0
        self.selection_attempts = 0
        self.quality_source_before = None
        self.quality_confirmation = None
        self.quality_candidate = None
        self.last_received = 0
        self.last_activity = time.monotonic()
        self.started = time.monotonic()
        self.action_time = 0.0
        self.play_requested = False
        self.media_state = {}
        self.auto_download = True
        self.defer_download = defer_download
        self.prepared_at = 0.0
        layout = QVBoxLayout(self)
        self.status = QLabel("Loading the player and selecting its best available quality…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.view = QWebEngineView(self)
        self.view.setPage(self.page)
        layout.addWidget(self.view, 1)
        self.progress = QProgressBar(); self.progress.setRange(0, 1000)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.save_button = QPushButton("Download selected video")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save_selected)
        buttons.addWidget(self.save_button)
        hide = QPushButton("Keep downloading in background")
        hide.clicked.connect(self.hide)
        buttons.addWidget(hide)
        close = QPushButton("Cancel download")
        close.clicked.connect(self.cancel_download)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        session.profile.downloadRequested.connect(self._download_requested)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self.page.load(QUrl(episode.url))

    def begin_download(self):
        """Admit a prepared player only after the queue gives it a transfer slot."""
        self.defer_download = False
        if self.closed or self.terminal:
            return
        if self.prepared_at:
            if time.monotonic() - self.prepared_at > 30:
                # Do not reuse an old selected URL after a long queue wait.
                self._retry_player("Refreshing the prepared player", refresh=True)
            else:
                self._save_selected()
        else:
            self._poll()

    def _release_preview(self):
        frame = self._player_frame()
        if frame:
            frame.runJavaScript("(() => { const v=document.querySelector('video'); if(v){v.pause();v.removeAttribute('src');v.querySelectorAll('source').forEach(s=>s.removeAttribute('src'));v.load();} })()", lambda _value: None)

    def _renderer_stopped(self, reason, code):
        self.auto_download = False
        self.timer.stop()
        self.save_button.setEnabled(False)
        self._failed("The browser player stopped unexpectedly. Retry the episode from its catalog.")

    def _failed(self, message):
        self.status.setText(message)
        if not self.terminal:
            self.terminal = True
            self.timer.stop()
            self.save_button.setEnabled(False)
            self.failed.emit(message)

    def _retry_player(self, reason, *, refresh=False):
        if self.closed or self.terminal or self.download or self.worker:
            return
        if not refresh and self.attempt >= self.MAX_ATTEMPTS:
            return self._failed(f"{reason} after {self.attempt} attempts. Use Retry to try this episode again; other downloads can continue.")
        if not refresh:
            self.attempt += 1
        self.generation += 1
        self.started = time.monotonic()
        self.action_time = 0.0
        self.pending_url = None
        self.polling = False
        self.media_state = {}
        self.requested_quality = None
        self.selection_attempts = 0
        self.quality_source_before = None
        self.quality_confirmation = None
        self.quality_candidate = None
        self.play_requested = False
        self.auto_download = True
        self.prepared_at = 0.0
        self.timer.setInterval(1000)
        self.save_button.setEnabled(False)
        self.status.setText(f"{reason}. Reloading the player ({self.attempt}/{self.MAX_ATTEMPTS})…")
        self.page.triggerAction(QWebEnginePage.WebAction.Stop)
        self.page.load(QUrl(self.episode.url))

    def _queue_retry(self, reason):
        if self.closed or self.terminal or self.cancel_requested:
            return
        if self.attempt >= self.MAX_ATTEMPTS:
            self._failed(f"{reason} after {self.attempt} attempts. Use Retry to try again.")
            if self.download and not self.download.isFinished():
                self.download.cancel()
            return
        self.terminal = True
        self.auto_download = False
        self.timer.stop()
        self.save_button.setEnabled(False)
        if self.download and not self.download.isFinished():
            self.download.cancel()
        self.status.setText(f"{reason} Retrying ({self.attempt + 1}/{self.MAX_ATTEMPTS})…")
        self.retry_requested.emit(reason, self.attempt + 1)

    def cancel_download(self):
        self.cancel_requested = True
        self.close()

    def _player_frame(self):
        pending = list(self.page.mainFrame().children())
        while pending:
            frame = pending.pop()
            if not frame.isValid():
                continue
            if frame.url().host() == "embed.wcostream.com":
                return frame
            pending.extend(frame.children())
        return None

    def _poll(self):
        if self.closed or self.terminal or self.worker:
            return
        if getattr(self, "defer_download", False) and self.prepared_at:
            return
        now = time.monotonic()
        if self.download:
            received = self.download.receivedBytes()
            if received != self.last_received:
                self.last_received, self.last_activity = received, now
            if not self.download.isFinished() and now - self.last_activity > self.TRANSFER_TIMEOUT:
                self._queue_retry("The video transfer stopped making progress for two minutes.")
            return
        if self.pending_url:
            if now - self.pending_since > 60:
                self._retry_player("The server did not start the video download")
            return
        if now - self.started > self.QUALITY_TIMEOUT:
            self._retry_player("Could not confirm the player's highest available quality")
            return
        if self.polling:
            return
        if self.quality_candidate is not None:
            # Qt cannot decode this source. Keep the normal player's selected
            # URL while its preview is stopped, then let FFprobe verify the file.
            self._state_ready(json.dumps(self.quality_candidate), self.generation)
            return
        frame = self._player_frame()
        if not frame:
            return
        self.polling = True
        generation = self.generation
        frame.runJavaScript(PLAYER_STATE, lambda value: self._state_ready(value, generation))

    def _click(self, script):
        frame = self._player_frame()
        if frame:
            self.action_time = time.monotonic()
            frame.runJavaScript(script, lambda _value: None)

    def _state_ready(self, value, generation=None):
        if generation is not None and generation != self.generation:
            return
        self.polling = False
        if self.closed or self.terminal or self.download or self.worker:
            return
        try:
            state = json.loads(value) if isinstance(value, str) else {}
        except (ValueError, TypeError):
            return
        if not isinstance(state, dict):
            return
        self.media_state = state
        if time.monotonic() - self.started > self.QUALITY_TIMEOUT:
            self._retry_player("Could not confirm the player's highest available quality")
            return
        if time.monotonic() - self.action_time < 2:
            return
        if state.get("closeReady"):
            self._click("document.querySelector('#close-btn').click()")
            return
        quality = best_quality(state.get("choices", []))
        selected = state.get("selected")
        expected = quality_height(str(quality or ""))
        downloadable = downloadable_media(state)
        single_source = (single_stream_media(state) and self.requested_quality is None
                         and not self.selection_attempts)
        lost_source = bool(state.get("src") and self.selection_attempts and not downloadable)
        needs_selection = (self.requested_quality != quality or selected != quality
                           or (self.quality_source_before is not None and state.get("src") == self.quality_source_before)
                           or (playable_media(state) and int(state.get("height", 0)) < expected)
                           or lost_source)
        if lost_source:
            # The player can replace an unsupported video with its error clip
            # while leaving the FHD badge visible. Discard the old confirmation
            # and retry the normal quality control instead of waiting two minutes.
            self.quality_confirmation = None
            if self.selection_attempts >= 3 and time.monotonic() - self.action_time >= 8:
                self._retry_player("The selected video source could not load")
                return
        if quality and needs_selection and self.auto_download and self.selection_attempts < 3 and (not self.selection_attempts or time.monotonic() - self.action_time >= 8):
            self.requested_quality = quality
            self.selection_attempts += 1
            if selected != quality:
                self.quality_source_before = state.get("src")
            self.quality_confirmation = None
            self.play_requested = False
            self.status.setText(f"Selecting {quality} through the player…")
            self._click("(() => { const q=" + json.dumps(quality) + "; const li=Array.from(document.querySelectorAll('.vjs-quality-dropdown li[data-code]')).find(li=>li.textContent.trim()===q && !li.classList.contains('disabled') && li.getAttribute('aria-disabled')!=='true'); const choice=li ? (li.querySelector('a') || li) : Array.from(document.querySelectorAll('a:not(.vjs-brand-quality-link)')).find(a=>a.textContent.trim()===q); choice?.click(); })()")
            return
        if state.get("playReady") and not self.play_requested and self.auto_download and not downloadable_media(state):
            self.play_requested = True
            self._click("Array.from(document.querySelectorAll('button')).find(b => b.title === 'Play Video' || b.textContent.trim() === 'Play Video')?.click()")
            return
        self.save_button.setEnabled(downloadable)
        if not downloadable:
            self.quality_confirmation = None
            if state.get("error"):
                self.status.setText(f"The player could not load this video: {state['error']}")
            return
        confirmed = single_source or (quality is not None and selected == self.requested_quality == quality
                     and (self.quality_source_before is None or state.get("src") != self.quality_source_before)
                     and (int(state.get("height", 0)) >= expected or not playable_media(state)))
        if self.auto_download and confirmed:
            signature = (quality, state.get("src"))
            if self.quality_confirmation is None or self.quality_confirmation[0] != signature:
                self.quality_confirmation = (signature, time.monotonic())
                if single_source:
                    self.status.setText("One available stream; verifying resolution after saving…")
                if state.get("mp4Support") == "" and not playable_media(state):
                    self.quality_candidate = state.copy()
                    self._release_preview()
            elif time.monotonic() - self.quality_confirmation[1] >= 3:
                if getattr(self, "defer_download", False):
                    self.prepared_at = time.monotonic()
                    self.status.setText("Player ready; waiting for a download slot…")
                    self.save_button.setEnabled(False)
                    self.timer.setInterval(1000)
                    self._release_preview()
                else:
                    self._save_selected()
        else:
            self.quality_confirmation = None

    def _save_selected(self):
        if self.closed or self.defer_download or self.pending_url or self.download or self.worker or not downloadable_media(self.media_state):
            return
        url = self.media_state["src"]
        host = urlparse(url).hostname or ""
        if host != "wcostream.com" and not host.endswith(".wcostream.com"):
            return self.status.setText("The selected media does not belong to the WCO player.")
        self.pending_url = url
        self.pending_since = time.monotonic()
        self.selected_height = max(int(self.media_state["height"]), quality_height(str(self.media_state.get("selected", ""))))
        self.save_button.setEnabled(False)
        quality_label = f"{self.selected_height}p" if self.selected_height else "available stream"
        self.status.setText(f"Downloading the selected {quality_label}; verifying resolution after saving…")
        self.page.download(QUrl(url), "episode.mp4")

    def _download_requested(self, download):
        if self.closed or download.page() != self.page:
            return
        host = download.url().host().casefold()
        if not self.pending_url or not (host == "wcostream.com" or host.endswith(".wcostream.com")):
            download.cancel()
            return
        if not (download.mimeType().startswith("video/") or download.mimeType() == "application/octet-stream"):
            download.cancel()
            self._failed("The server returned something other than a video. Nothing was imported.")
            self.pending_url = None
            self.auto_download = False
            return
        # Keep the verified import on the library volume: a rename instead of a
        # second whole-video copy from APPDATA. Scans exclude this staging area.
        self.staging = self.library_root / DOWNLOAD_STAGING_DIRECTORY / ("wco-" + uuid.uuid4().hex)
        self.staging.mkdir(parents=True, exist_ok=True)
        self.download = download
        self.last_received = 0
        self.last_activity = time.monotonic()
        download.setDownloadDirectory(str(self.staging))
        download.setDownloadFileName("episode.mp4")
        download.receivedBytesChanged.connect(self._progress)
        download.stateChanged.connect(self._download_state)
        download.accept()
        self.timer.setInterval(1000)
        self._release_preview()
        self.transfer_started.emit()

    def _progress(self):
        if self.closed or not self.download:
            return
        received, total = self.download.receivedBytes(), self.download.totalBytes()
        if received != self.last_received:
            self.last_received, self.last_activity = received, time.monotonic()
        self.progress.setValue(round(received / total * 1000) if total else 0)
        quality_label = f"{self.selected_height}p" if self.selected_height else "available stream"
        self.status.setText(f"Downloading {quality_label} · {received / 1048576:.1f} MB" + (f" / {total / 1048576:.1f} MB" if total else ""))

    def _download_state(self, state):
        if self.closed or self.terminal:
            return
        if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            self.status.setText("Verifying the saved video before library import…")
            self.timer.stop()
            self.worker = ImportThread(self.staging / "episode.mp4", self.library_root, self.title, self.episode, self.selected_height, self)
            self.worker.done.connect(self._imported)
            self.worker.failed.connect(self._failed)
            self.worker.retryable_failed.connect(self._queue_retry)
            self.verification_started.emit()
            self.worker.start()
        elif state in {QWebEngineDownloadRequest.DownloadState.DownloadInterrupted, QWebEngineDownloadRequest.DownloadState.DownloadCancelled}:
            message = "Download stopped: " + self.download.interruptReasonString()
            if state == QWebEngineDownloadRequest.DownloadState.DownloadCancelled:
                self.status.setText("Download cancelled.")
                if not self.terminal:
                    self.terminal = True
                    self.cancelled.emit()
            else:
                self._queue_retry(message)
            self.auto_download = False

    def _imported(self, result):
        # The destination includes the actual FFprobe-verified quality, even
        # when the source offered no resolution label before downloading.
        self.status.setText(f"Added: {result.destination}")
        self.progress.setValue(1000)
        self.terminal = True
        self.completed.emit(result)

    def closeEvent(self, event):
        if self.closed:
            event.accept()
            return
        if not self.terminal and not self.cancel_requested:
            self.hide()
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            self.status.setText("Finishing video verification and import…")
            event.ignore()
            return
        self.closed = True
        self.timer.stop()
        self.session.profile.downloadRequested.disconnect(self._download_requested)
        if self.download and not self.download.isFinished():
            self.download.cancel()
        self.page.triggerAction(QWebEnginePage.WebAction.Stop)
        self.page.setUrl(QUrl("about:blank"))
        if not self.terminal:
            self.terminal = True
            self.cancelled.emit()
        event.accept()
