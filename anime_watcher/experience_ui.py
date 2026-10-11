"""Portable and living-room workflows layered on the existing window handlers."""
from __future__ import annotations

import http.client
import json
import sqlite3
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from shiboken6 import isValid

from .controller import ControllerNavigation
from .database import LibraryDatabase
from .library_extras import (WATCH_STATES, file_inventory, library_view, storage_review, recycle_reviewed,
    save_skip_marker, custom_skip_markers, download_groups)
from .portable_library import sync_portable, portable_profiles, load_portable, find_portable, new_portable_record, _map_value
from .media_quality import probe_video_size


def size_text(size):
    return f'{size / (1024**3):.1f} GB' if size >= 1024**3 else f'{size / 1024**2:.1f} MB'


def phone_diagnostics(address, port):
    result=[]
    for name,host in [('Local server','127.0.0.1'),('Selected network',address)]:
        connection=http.client.HTTPConnection(host,port,timeout=3)
        try:
            connection.request('GET','/'); response=connection.getresponse(); response.read(1024)
            result.append(f'{name}: responding ({response.status}).' if response.status==200 else f'{name}: HTTP {response.status}; check the selected connection.')
        except OSError as exc: result.append(f'{name}: unreachable ({exc}).')
        finally: connection.close()
    result.append('This checks the PC. Open the pairing link in Safari to confirm the phone can reach it; Wi-Fi guest isolation or the firewall may still block the phone.')
    return '\n'.join(result)


class ExperienceUi:
    def _experience_init(self):
        self._portable_worker=None; self._portable_changes=None; self._portable_close_done=False
        self._portable_message=''; self._watch_snapshot=None; self._watch_candidate=None; self._watch_key=None; self._watch_worker=False
        self._quality_worker=False; self._storage_busy=False; self._storage_dialog=None
        self._experience_timer=QTimer(self); self._experience_timer.setInterval(15000)
        self._experience_timer.timeout.connect(self._experience_tick); self._experience_timer.start()
        self.controller=ControllerNavigation(self)
        self._apply_controller_mode()

    def _experience_work(self,function,done,failed,*args):
        from .qt_ui import Worker
        worker=Worker(function,*args); worker.signals.done.connect(done); worker.signals.failed.connect(failed)
        try: self._start_worker(worker)
        except Exception as exc: failed(str(exc))
        return worker

    def _experience_busy(self):
        return bool(self.import_job or self.library_transfer_job or self.library_refresh_job or self.download_queue.remaining_count)

    def _add_library_filters(self,outer):
        self._library_render=None; self.library_filters={}
        saved=self.db.setting('library_filters',{}); saved=saved if isinstance(saved,dict) else {}
        grid=QGridLayout(); grid.setHorizontalSpacing(12)
        for column,(key,label,values) in enumerate([
            ('sort','Sort',['Title','Year','Recently added','Last watched']),
            ('state','Watch status',['All',*WATCH_STATES[1:]]),
            ('language','Version',['All','Sub','Dub','Unknown']),
            ('quality','Verified quality',['Any','480p+','720p+','1080p+']),
            ('year','Release year',['All','Unknown',*sorted({str(row['release_year']) for row in self.db.series() if 'release_year' in row.keys() and row['release_year']},reverse=True)]),
        ]):
            combo=QComboBox(); combo.setObjectName('libraryFilter_'+key); combo.setAccessibleName(label); combo.addItems(values)
            combo.setCurrentText(saved.get(key,values[0])); self.library_filters[key]=combo
            grid.addWidget(QLabel(label),0,column); grid.addWidget(combo,1,column)
            combo.currentTextChanged.connect(self._library_filters_changed)
        favorite=QCheckBox('Favorites'); favorite.setChecked(bool(saved.get('favorite'))); favorite.setObjectName('libraryFavoritesFilter')
        favorite.toggled.connect(self._library_filters_changed); self.library_filters['favorite']=favorite; grid.addWidget(favorite,0,5)
        scan=QPushButton('Check qualities'); scan.setObjectName('checkLibraryQualities'); scan.clicked.connect(self._check_library_qualities); grid.addWidget(scan,1,5)
        outer.addLayout(grid)

    def _library_filters_changed(self,*_):
        values={key:(widget.isChecked() if key=='favorite' else widget.currentText()) for key,widget in self.library_filters.items()}
        self.db.set_setting('library_filters',values)
        if callable(self._library_render): self._library_render(self._library_search.text())

    def _filtered_library(self,text,category):
        filters=self.library_filters
        quality={'Any':0,'480p+':480,'720p+':720,'1080p+':1080}[filters['quality'].currentText()]
        return library_view(self.db,text,category=category,favorite=filters['favorite'].isChecked(),state=filters['state'].currentText(),year=filters['year'].currentText(),
                            language=filters['language'].currentText(),quality=quality,sort=filters['sort'].currentText())

    def _add_series_preferences(self,layout,series):
        row=QHBoxLayout(); favorite=QCheckBox('★ Favorite'); favorite.setObjectName('seriesFavorite')
        favorite.setChecked(bool(series['favorite'])); favorite.toggled.connect(lambda checked:self.db.set_series_preferences(series['id'],favorite=checked))
        state=QComboBox(); state.setObjectName('seriesWatchState'); state.setAccessibleName('Watch status'); state.addItems(WATCH_STATES); state.setCurrentText(series['watch_state'])
        state.currentTextChanged.connect(lambda value:self.db.set_series_preferences(series['id'],watch_state=value))
        row.addWidget(favorite); row.addWidget(QLabel('Watch status')); row.addWidget(state); row.addStretch(1); layout.addLayout(row)

    def _add_experience_library_settings(self,body):
        layout=self._settings_card(body,'Portable library','Carry organization, artwork, and watch progress with your media drive. A local working copy preserves progress if the drive disconnects; snapshots sync while connected. Account credentials stay on this computer.')
        self.portable_status=QLabel(); self.portable_status.setObjectName('portableLibraryStatus'); self.portable_status.setWordWrap(True); layout.addWidget(self.portable_status)
        row=QGridLayout()
        for index,(label,name,callback) in enumerate([('Enable for this library','enablePortableLibrary',self._enable_portable),('Open portable library…','openPortableLibrary',self._open_portable),('Sync now','syncPortableLibrary',lambda:self._sync_portable(force=True)),('Use local copy only','detachPortableLibrary',self._detach_portable)]):
            button=QPushButton(label); button.setObjectName(name); button.clicked.connect(callback); row.addWidget(button,index//2,index%2)
        layout.addLayout(row); self._refresh_portable_status()
        layout=self._settings_card(body,'Storage and automatic refresh','Review space used by shows and old replaced copies. Reconnect a disconnected drive to resume monitoring without clearing your library.')
        watch=QCheckBox('Watch library folders for changes'); watch.setObjectName('watchLibraryFolders'); watch.setChecked(bool(self.db.setting('watch_library',True)))
        watch.toggled.connect(lambda value:self.db.set_setting('watch_library',value)); layout.addWidget(watch)
        storage=QPushButton('Review storage…'); storage.setObjectName('reviewLibraryStorage'); storage.clicked.connect(self._show_storage); layout.addWidget(storage)

    def _add_controller_settings(self,body):
        layout=self._settings_card(body,'Controller and handheld','Use the Ally in Gamepad mode: D-pad or left stick to browse, A to select, B to go back, and LB/RB to change tabs. During playback: X plays/pauses, Y opens player settings, and Start toggles fullscreen. Input stays inside the active Anime Watcher window.')
        enabled=QCheckBox('Enable controller navigation'); enabled.setObjectName('controllerNavigationEnabled'); enabled.setChecked(bool(self.db.setting('controller_enabled',True)))
        enabled.toggled.connect(lambda value:self.db.set_setting('controller_enabled',value)); layout.addWidget(enabled)
        large=QCheckBox('Larger controls for handheld and TV use'); large.setObjectName('controllerLargeControls'); large.setChecked(bool(self.db.setting('controller_large',False)))
        large.toggled.connect(lambda value:(self.db.set_setting('controller_large',value),self._apply_controller_mode())); layout.addWidget(large)

    def _apply_controller_mode(self):
        large=bool(self.db.setting('controller_large',False)); previous=self.property('controllerLarge'); self.setProperty('controllerLarge',large)
        self.setMinimumSize(960 if large else 1080,540 if large else 680)
        if bool(previous)==large: return
        self.style().unpolish(self); self.style().polish(self)
        for widget in self.findChildren(QWidget): widget.style().unpolish(widget); widget.style().polish(widget)

    def _refresh_portable_status(self):
        label=getattr(self,'portable_status',None)
        if label is not None and isValid(label):
            record=self.profile_manager.portable()
            label.setText(self._portable_message or (f"Portable snapshots enabled · {record['root']}" if record else 'Using this computer’s local profile. Enable portable mode or open a portable library from its drive.'))

    def _enable_portable(self):
        if self.library_root is None or self._experience_busy() or self._portable_worker:
            self._portable_message='Choose a library and wait for downloads, imports, or transfers to finish.'; self._refresh_portable_status(); return
        if self.profile_manager.portable(): return self._sync_portable(force=True)
        try: record=new_portable_record(self.library_root,self.profile_manager.active.id)
        except (OSError,ValueError,KeyError) as exc: self._portable_message=str(exc); self._refresh_portable_status(); return
        self._sync_portable(force=True,record=record)

    def _sync_portable(self,*,force=False,record=None):
        if self._closing or self._portable_worker or self.library_transfer_job or self.import_job or self._storage_busy: return False
        record=record or self.profile_manager.portable()
        if not record: return False
        try: root=find_portable(record) if record.get('sha256') else Path(record['root'])
        except (OSError,ValueError) as exc: self._portable_message=str(exc); self._refresh_portable_status(); return False
        if root is None or not root.is_dir():
            self._portable_message='Drive disconnected — progress stays in the local working copy and will sync when reconnected.'; self._refresh_portable_status(); return False
        if root != self.library_root:
            if self._experience_busy(): return False
            self._rebase_portable_root(root)
        changes=(self.db.path,self.db.connection.total_changes,self.db.connection.execute('PRAGMA data_version').fetchone()[0])
        if not force and changes==self._portable_changes: return False
        profile_id=self.profile_manager.active.id; key=self.db.path; self._portable_worker=key
        self._portable_message='Syncing a verified portable snapshot…'; self._refresh_portable_status()
        def complete(updated):
            self.profile_manager.attach_portable(updated,profile_id); self._portable_worker=None
            if self.db.path==key: self._portable_changes=changes; self._portable_message='Portable snapshot synced. Safely eject the drive after closing the app.'; self._refresh_portable_status()
            if getattr(self,'_portable_closing',False): self._portable_close_done=True; QTimer.singleShot(0,self.close)
        def failed(error):
            self._portable_worker=None; self._portable_message=f'Portable sync paused: {error}'; self._refresh_portable_status()
            if getattr(self,'_portable_closing',False): self._portable_close_done=True; QTimer.singleShot(0,self.close)
        self._experience_work(sync_portable,complete,failed,key,root,record,self.profile_manager.active.name)
        return True

    def _rebase_portable_root(self,root):
        old=self.library_root; self._save_progress(stop=True); self._stop_phone_access()
        def transform(value):
            try: return str(root/Path(value).relative_to(old))
            except (ValueError,TypeError): return value
        with self.db.connection:
            for row in self.db.all_episodes(): self.db.connection.execute('UPDATE episodes SET path=? WHERE id=?',(transform(row['path']),row['id']))
            for key,raw in self.db.connection.execute('SELECT key,value FROM settings').fetchall():
                try: value=json.loads(raw)
                except json.JSONDecodeError: continue
                self.db.connection.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(_map_value(value,transform)),key))
        self.library_root=Path(root); self.db.set_setting('library_root',str(root)); self.sidebar_status.setText(str(root))
        self._watch_snapshot=None; self._watch_key=None

    def _open_portable(self):
        if self._experience_busy() or self._portable_worker: self._portable_message='Finish library work before opening a portable profile.'; self._refresh_portable_status(); return
        folder=QFileDialog.getExistingDirectory(self,'Open portable library',str(self.library_root or ''))
        if not folder: return
        try: identity,profiles=portable_profiles(folder)
        except (OSError,ValueError,KeyError) as exc: self._portable_message=str(exc); self._refresh_portable_status(); return
        dialog=QDialog(self); dialog.setWindowTitle('Open portable profile'); layout=QVBoxLayout(dialog)
        note=QLabel('Load the saved drive snapshot into a new local profile. Existing local profiles and unsynced progress are preserved.'); note.setWordWrap(True); layout.addWidget(note)
        select=QComboBox()
        for key,name in profiles: select.addItem(name,key)
        layout.addWidget(select); buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Open|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if not profiles or dialog.exec()!=QDialog.DialogCode.Accepted: return
        name='Portable · '+select.currentText(); original=name; number=2
        while any(row.name.casefold()==name.casefold() for row in self.profile_manager.profiles()): name=f'{original} ({number})'; number+=1
        profile=self.profile_manager.create(name); destination=self.profile_manager.database_path(profile.id); self._portable_worker=destination
        def complete(record):
            self._portable_worker=None; self.profile_manager.attach_portable(record,profile.id)
            self._save_progress(stop=True); self._stop_phone_access(); self.db.close(); self.profile_manager.set_active(profile.id)
            self.db=LibraryDatabase(destination); self.library_root=Path(folder); self._portable_changes=None
            self.profile_status.setText('Profile: '+name); self.sidebar_status.setText(folder); self._portable_message='Portable profile loaded; organization and watch progress are ready.'
            self._apply_controller_mode(); self.show_library()
        def failed(error): self._portable_worker=None; self._portable_message='Could not open portable library: '+error; self._refresh_portable_status()
        self._experience_work(load_portable,complete,failed,folder,select.currentData(),destination,self.data_root/'portable-artwork'/identity)

    def _detach_portable(self):
        if self._portable_worker: return
        self.profile_manager.attach_portable(None); self._portable_message='Using the local copy. The portable snapshot remains on the drive.'; self._refresh_portable_status()

    def _experience_can_close(self):
        if self._portable_worker: self._portable_closing=True; QTimer.singleShot(250,self.close); return False
        if not self._portable_close_done and self.profile_manager.portable():
            self._portable_closing=True
            if self._sync_portable(force=True): return False
        self._experience_timer.stop(); self.controller.timer.stop(); return True

    def _experience_tick(self):
        if self._closing: return
        self._sync_portable()
        if self._watch_worker or self._experience_busy() or self._portable_worker or not self.library_root or not self.db.setting('watch_library',True): return
        key=(self.db.path,self.library_root)
        if key!=self._watch_key: self._watch_key=key; self._watch_snapshot=None; self._watch_candidate=None
        self._watch_worker=True
        def complete(snapshot):
            self._watch_worker=False
            if key!=(self.db.path,self.library_root) or self._closing: return
            if self._watch_snapshot is None:
                self._watch_snapshot=snapshot
                self.library_refresh_messages[key]='Drive connected · automatic folder monitoring on.'
                # A reconnect should pick up changes made while disconnected.
                indexed={str(Path(row['path']).relative_to(self.library_root).as_posix()) for row in self.db.all_episodes() if Path(row['path']).is_relative_to(self.library_root)}
                from .organizer import VIDEO_EXTENSIONS
                present={name for name in snapshot if Path(name).suffix.lower() in VIDEO_EXTENSIONS}
                if getattr(self,'_drive_was_offline',False) or indexed!=present: self._drive_was_offline=False; self._refresh_library()
            elif snapshot!=self._watch_snapshot:
                if snapshot==self._watch_candidate:
                    self._watch_snapshot=snapshot; self._watch_candidate=None; self._refresh_library()
                else: self._watch_candidate=snapshot
            else: self._watch_candidate=None
            self._refresh_library_controls()
        def failed(error):
            self._watch_worker=False
            if key!=(self.db.path,self.library_root) or self._closing: return
            self._watch_snapshot=None; self._watch_candidate=None; self._drive_was_offline=True
            self.library_refresh_messages[key]=str(error); self._refresh_library_controls()
        self._experience_work(file_inventory,complete,failed,self.library_root,)

    def _check_library_qualities(self):
        if self._quality_worker or not self.library_root or self._experience_busy(): return
        paths=[row['path'] for row in self.db.all_episodes()]; key=self.db.path; self._quality_worker=True
        self.library_refresh_messages[(key,self.library_root)]='Checking actual video resolutions in the background…'; self._refresh_library_controls()
        def probe():
            result={}
            for path in paths:
                try:
                    stat=Path(path).stat(); _,height=probe_video_size(path)
                    if height: result[path]=[height,stat.st_size,stat.st_mtime_ns]
                except OSError: pass
            return result
        def complete(results):
            self._quality_worker=False
            if self._closing or not key.is_file(): return
            owner=self.db if self.db.path==key else LibraryDatabase(key)
            try:
                heights=owner.setting('verified_video_heights',{}); heights=heights if isinstance(heights,dict) else {}
                heights.update({path:value[0] for path,value in results.items()}); owner.set_setting('verified_video_heights',heights)
                signatures=owner.setting('verified_video_signatures',{}); signatures=signatures if isinstance(signatures,dict) else {}; signatures.update(results); owner.set_setting('verified_video_signatures',signatures)
            finally:
                if owner is not self.db: owner.close()
            if key==self.db.path and callable(getattr(self,'_library_render',None)) and self.stack.currentWidget() is getattr(self,'_library_page',None):
                self._library_render(self._library_search.text()); self.library_refresh_messages[(key,self.library_root)]=f'Verified quality for {len(results)} videos; unknown qualities are excluded by quality filters.'; self._refresh_library_controls()
        def failed(error): self._quality_worker=False
        self._experience_work(probe,complete,failed)

    def _show_storage(self):
        if not self.library_root or self._storage_busy: return
        dialog=QDialog(self); dialog.setWindowTitle('Library storage'); dialog.resize(900,650); layout=QVBoxLayout(dialog)
        status=QLabel('Scanning file sizes…'); status.setWordWrap(True); layout.addWidget(status)
        table=QTableWidget(0,3); table.setHorizontalHeaderLabels(['Show / recovery folder','Size','Recycle']); table.horizontalHeader().setStretchLastSection(True); layout.addWidget(table)
        recycle=QPushButton('Recycle selected replaced copies'); recycle.setEnabled(False); layout.addWidget(recycle)
        close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(dialog.reject); layout.addWidget(close)
        self._storage_dialog=dialog; self._storage_busy=True; key=(self.db.path,self.library_root); choices=[]
        def ready(review):
            self._storage_busy=False
            if not isValid(dialog): return
            status.setText(f"Library: {size_text(review['used'])} · Free: {size_text(review['free'])} of {size_text(review['capacity'])} · Replaced-file recovery: {size_text(review['recovery_bytes'])}\nSelect only old copies you want sent to the Windows Recycle Bin.")
            for name,size in review['series']:
                row=table.rowCount(); table.insertRow(row); table.setItem(row,0,QTableWidgetItem(name)); table.setItem(row,1,QTableWidgetItem(size_text(size)))
            for entry in review['recovery']:
                row=table.rowCount(); table.insertRow(row); table.setItem(row,0,QTableWidgetItem('Replaced copies: '+str(Path(entry['path']).parent.name))); table.setItem(row,1,QTableWidgetItem(size_text(entry['size'])))
                check=QCheckBox(); table.setCellWidget(row,2,check); choices.append((check,entry))
            table.resizeColumnsToContents(); recycle.setEnabled(bool(choices))
        def failed(error):
            self._storage_busy=False
            if isValid(status): status.setText('Storage review failed: '+error)
        def cleanup():
            selected=[entry for check,entry in choices if check.isChecked()]
            if not selected: status.setText('Select replaced copies before recycling.'); return
            if key!=(self.db.path,self.library_root) or self._experience_busy() or self._portable_worker:
                status.setText('Finish library work before cleanup, and keep this profile selected.'); return
            recycle.setEnabled(False); self._storage_busy=True; status.setText('Moving reviewed replaced copies to the Recycle Bin…')
            def cleaned(result):
                self._storage_busy=False
                if isValid(status): status.setText(f"Recycled {len(result['recycled'])} recovery folders."+('\n'+'\n'.join(result['errors']) if result['errors'] else ''))
            self._experience_work(recycle_reviewed,cleaned,failed,self.library_root,selected,[row['path'] for row in self.db.all_episodes()])
        recycle.clicked.connect(cleanup)
        self._experience_work(storage_review,ready,failed,self.library_root,[row['path'] for row in self.db.all_episodes()]); dialog.exec()

    def _add_phone_diagnostics(self,layout):
        button=QPushButton('Test connection'); button.setObjectName('testPhoneConnection'); layout.addWidget(button)
        self.phone_test_status=QLabel(); self.phone_test_status.setWordWrap(True); self.phone_test_status.setObjectName('phoneConnectionTestStatus'); layout.addWidget(self.phone_test_status)
        def test():
            if not self.phone_server: self.phone_test_status.setText('Enable Phone access first.'); return
            address=self.phone_address.currentData()
            if not address: self.phone_test_status.setText('No physical connection is available. Connect Ethernet, Wi-Fi, or the phone hotspot.'); return
            self.phone_test_status.setText('Checking the local server and selected network…'); button.setEnabled(False)
            server=self.phone_server
            label=self.phone_test_status
            def complete(message):
                if isValid(button): button.setEnabled(True)
                if isValid(label) and server is self.phone_server: label.setText(message+'\n'+f'{len(server.sessions)} paired devices. Refresh the code if Safari reports it expired.')
            self._experience_work(phone_diagnostics,complete,complete,address,server.port)
        button.clicked.connect(test)

    def _download_season_summary(self):
        groups=download_groups(self.download_queue.jobs.values(),self.db.path)
        lines=[]
        for group in groups:
            title=group['title']+(f" · Season {group['season']}" if group['season'] else '')+(' · '+group['language'] if group['language'] else '')
            text=f"{title}: {group['completed']} of {group['total']} complete · {group['active']} active · {group['queued']} queued"
            if group['failed']: text+=f" · {group['failed']} failed"
            text+=f" · {group['progress']/10:.0f}% overall"
            if group['eta'] is not None: text+=f" · about {group['eta']//60}m {group['eta']%60}s remaining"
            elif group['active'] or group['queued']: text+=' · total ETA pending video sizes'
            if group['lower_quality']: text+=f" · {group['lower_quality']} below preferred quality"
            lines.append(text)
        return '\n'.join(lines)

    def _refresh_download_batches(self):
        groups=[row for row in download_groups(self.download_queue.jobs.values(),self.db.path) if row['season'] or row['total']>1]
        keys=[(row['title'],row['season'],row['language']) for row in groups]
        if keys!=getattr(self,'_download_batch_keys',None):
            from .qt_ui import clear_layout
            clear_layout(self.download_batch_layout); self._download_batch_widgets=[]; self._download_batch_keys=keys
            for row in groups:
                label=QLabel(); label.setWordWrap(True); label.setObjectName('downloadBatchStatus'); self.download_batch_layout.addWidget(label)
                bar=QProgressBar(); bar.setRange(0,1000); bar.setFixedHeight(8); bar.setTextVisible(False); bar.setObjectName('downloadBatchProgress'); self.download_batch_layout.addWidget(bar)
                self._download_batch_widgets.append((label,bar))
        for row,(label,bar) in zip(groups,self._download_batch_widgets):
            text=f"{row['title']} · Season {row['season']} · {row['language']}: {row['completed']} of {row['total']} complete · {row['active']} active · {row['queued']} queued"
            if row['failed']: text+=f" · {row['failed']} failed"
            if row['lower_quality']: text+=f" · {row['lower_quality']} below preferred quality"
            if row['eta'] is not None: text+=f" · about {row['eta']//60}m {row['eta']%60}s remaining"
            elif row['active'] or row['queued']: text+=' · total ETA pending video sizes'
            label.setText(text); bar.setValue(row['progress']); bar.setAccessibleName(f"{row['title']} overall download progress")
            bar.setStyleSheet('QProgressBar::chunk{background:'+('#ef596b' if row['failed'] else '#35c779' if row['completed']==row['total'] else '#8b5cf6')+';}')

    def _remember_download_quality(self,job):
        if not job.destination or job.retry_data.get('_quality_check_pending'): return
        try: stat=job.destination.stat()
        except OSError: return
        signature=[stat.st_size,stat.st_mtime_ns]
        if job.retry_data.get('quality_signature')==signature: return
        job.retry_data['_quality_check_pending']=True; key=job.database; path=str(job.destination)
        def complete(size):
            job.retry_data.pop('_quality_check_pending',None)
            if self._closing or not key.is_file(): return
            try:
                current=Path(path).stat()
                if signature!=[current.st_size,current.st_mtime_ns]: return
            except OSError: return
            height=int(size[1]); job.retry_data['quality_signature']=signature; job.retry_data['verified_height']=height
            quality=str(job.retry_data.get('quality','best')); job.retry_data['preferred_height']=int(quality[:-1]) if quality in {'480p','720p','1080p'} else 1080
            owner=self.db if self.db.path==key else LibraryDatabase(key)
            try:
                heights=owner.setting('verified_video_heights',{}); heights=heights if isinstance(heights,dict) else {}; heights[path]=height; owner.set_setting('verified_video_heights',heights)
                signatures=owner.setting('verified_video_signatures',{}); signatures=signatures if isinstance(signatures,dict) else {}; signatures[path]=[height,*signature]; owner.set_setting('verified_video_signatures',signatures)
            finally:
                if owner is not self.db: owner.close()
            self._download_queue_changed(job.id)
        def failed(_): job.retry_data.pop('_quality_check_pending',None)
        self._experience_work(probe_video_size,complete,failed,path)

    def _edit_skip_markers(self):
        episode=self.db.episode(self.current_episode_id) if self.current_episode_id else None
        if not episode: return
        episode=dict(episode); episode['duration_ms']=self.known_duration_ms or self.player.duration() or episode['duration_ms']
        dialog=QDialog(self); dialog.setWindowTitle('Custom intro and outro'); form=QFormLayout(dialog)
        note=QLabel('Use your own timings for this version. Season timings apply only to this season and Sub/Dub language; episode-specific timings take priority.'); note.setWordWrap(True); form.addRow(note)
        kind=QComboBox(); kind.addItems(['Intro','Outro']); form.addRow('Skip section',kind)
        start=QDoubleSpinBox(); end=QDoubleSpinBox()
        for spin in (start,end): spin.setDecimals(3); spin.setRange(0,max(episode['duration_ms']/1000,86400)); spin.setSuffix(' seconds')
        start.setObjectName('customSkipStart'); end.setObjectName('customSkipEnd'); form.addRow('Start',start); form.addRow('End',end)
        row=QHBoxLayout(); current_start=QPushButton('Set start here'); current_end=QPushButton('Set end here')
        current_start.clicked.connect(lambda:start.setValue(self.player.time()/1000)); current_end.clicked.connect(lambda:end.setValue(self.player.time()/1000)); row.addWidget(current_start); row.addWidget(current_end); form.addRow(row)
        season=QCheckBox('Reuse for this season and language'); form.addRow(season)
        status=QLabel(); status.setWordWrap(True); form.addRow(status)
        def fill():
            marker=next((row for row in custom_skip_markers(self.db,episode) if row.kind==kind.currentText().lower()),None)
            start.setValue(marker.start_ms/1000 if marker else max(0,self.player.time()/1000)); end.setValue(marker.end_ms/1000 if marker else min(episode['duration_ms']/1000 or 86400,start.value()+90))
        kind.currentTextChanged.connect(fill); fill()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel); form.addRow(buttons)
        clear=QPushButton('Clear this custom marker'); form.addRow(clear)
        def save():
            try: save_skip_marker(self.db,episode,kind.currentText().lower(),round(start.value()*1000),round(end.value()*1000),season=season.isChecked())
            except ValueError as exc: status.setText(str(exc)); return
            self._intro_ready(self.intro_probe_token,getattr(self,'_embedded_media_chapters',[])); dialog.accept()
        def remove():
            key=f"custom_skip:{episode['series_id']}:{episode['season']}:{episode['language']}" if season.isChecked() else f"custom_skip_episode:{episode['id']}"
            saved=self.db.setting(key,{}); saved=saved if isinstance(saved,dict) else {}; saved.pop(kind.currentText().lower(),None); self.db.set_setting(key,saved)
            self._intro_ready(self.intro_probe_token,getattr(self,'_embedded_media_chapters',[])); fill(); status.setText('Custom marker cleared for the selected scope.')
        clear.clicked.connect(remove); buttons.accepted.connect(save); buttons.rejected.connect(dialog.reject); dialog.exec()
