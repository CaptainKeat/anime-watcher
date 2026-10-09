"""Review widgets for imports, playlists, and draggable pending downloads."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QMimeData, QPoint, QTimer
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                              QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
                              QTableWidget, QTableWidgetItem, QHeaderView, QVBoxLayout)

from .import_review import ImportEntry


class FileDropPanel(QFrame):
    files_dropped = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent); self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths); event.acceptProposedAction()


class DownloadJobFrame(QFrame):
    reordered = Signal(str, str)
    MIME = 'application/x-anime-watcher-queued-job'

    def __init__(self, job, parent=None):
        super().__init__(parent); self.job = job; self.origin = QPoint(); self.setAcceptDrops(True)

    def mousePressEvent(self, event):
        self.origin = event.position().toPoint(); super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.job.status == 'Queued' and event.buttons() & Qt.MouseButton.LeftButton and (event.position().toPoint() - self.origin).manhattanLength() >= 10:
            drag = QDrag(self); mime = QMimeData(); mime.setData(self.MIME, self.job.id.encode())
            drag.setMimeData(mime); drag.exec(Qt.DropAction.MoveAction)
        else:
            super().mouseMoveEvent(event)

    def dragEnterEvent(self, event):
        if self.job.status == 'Queued' and event.mimeData().hasFormat(self.MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.job.status == 'Queued' and event.mimeData().hasFormat(self.MIME):
            source = bytes(event.mimeData().data(self.MIME)).decode('ascii', errors='ignore')
            self.reordered.emit(source, self.job.id); event.acceptProposedAction()


class ImportReviewDialog(QDialog):
    review_changed = Signal()
    def __init__(self, entries, series, *, youtube=False, replacement_id=None, parent=None):
        super().__init__(parent); self.setWindowTitle('Review import'); self.resize(1280, 700)
        self.entries = entries; self.replacement_id = replacement_id
        layout = QVBoxLayout(self)
        note = QLabel('Review every destination before moving. Replace matching version verifies higher resolution and preserves watch progress. Old copies stay recoverable unless you select Recycle below.')
        note.setWordWrap(True); layout.addWidget(note)
        bulk = QHBoxLayout()
        self.series = QComboBox(); self.series.setEditable(True); self.series.addItem(''); self.series.setMinimumWidth(180)
        for item in series: self.series.addItem(item['title'])
        self.season = QSpinBox(); self.season.setRange(0, 999); self.season.setValue(1)
        self.first = QSpinBox(); self.first.setRange(0, 9999); self.first.setValue(1)
        self.language = QComboBox(); self.language.addItems(['Sub', 'Dub', 'Unknown'])
        apply = QPushButton('Apply to selected rows'); apply.clicked.connect(self.apply_bulk)
        for widget in (QLabel('Series'), self.series, QLabel('Season'), self.season, QLabel('First episode'), self.first,
                       QLabel('Language'), self.language, apply): bulk.addWidget(widget)
        layout.addLayout(bulk)
        self.table = QTableWidget(len(entries), 8); self.table.setObjectName('importReviewTable')
        self.table.setHorizontalHeaderLabels(['Import', 'Source file', 'Series', 'Season', 'Episode', 'Language', 'Action', 'Resolution'])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for index, entry in enumerate(entries):
            check = QCheckBox(); check.setChecked(True); self.table.setCellWidget(index, 0, check)
            item = QTableWidgetItem(entry.source.name); item.setToolTip(str(entry.source)); self.table.setItem(index, 1, item)
            title = QLineEdit(entry.title); self.table.setCellWidget(index, 2, title)
            season = QSpinBox(); season.setRange(0, 999); season.setValue(entry.season); self.table.setCellWidget(index, 3, season)
            episode = QSpinBox(); episode.setRange(0, 9999); episode.setValue(entry.episode); self.table.setCellWidget(index, 4, episode)
            language = QComboBox(); language.addItems(['Sub', 'Dub', 'Unknown']); language.setCurrentText(entry.language); self.table.setCellWidget(index, 5, language)
            action = QComboBox(); action.addItems(['Keep copy', 'Replace matching version']); action.setCurrentIndex(int(entry.replace)); self.table.setCellWidget(index, 6, action)
            resolution = QLabel('Checking…'); resolution.setWordWrap(True); self.table.setCellWidget(index, 7, resolution)
        self.review_timer = QTimer(self); self.review_timer.setSingleShot(True); self.review_timer.setInterval(350)
        self.review_timer.timeout.connect(self.review_changed.emit)
        for index in range(len(entries)):
            self.table.cellWidget(index, 2).textChanged.connect(lambda _: self.review_timer.start())
            for column in (3, 4): self.table.cellWidget(index, column).valueChanged.connect(lambda _: self.review_timer.start())
            for column in (5, 6): self.table.cellWidget(index, column).currentIndexChanged.connect(lambda _: self.review_timer.start())
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(6, 215); self.table.setColumnWidth(7, 140)
        self.table.verticalHeader().setDefaultSectionSize(64)
        layout.addWidget(self.table, 1)
        self.youtube = QCheckBox('Put these videos in the YouTube library'); self.youtube.setChecked(youtube); layout.addWidget(self.youtube)
        self.recycle = QCheckBox('Recycle replaced files after the verified import succeeds'); layout.addWidget(self.recycle)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.import_button = buttons.addButton('Import reviewed files', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def show_qualities(self, results):
        for index, result in results.items():
            label = self.table.cellWidget(index, 7)
            label.setText('New: ' + result['new'] + '\nExisting: ' + (' / '.join(result['old']) or 'None'))
            label.setToolTip('Actual video dimensions. Replacements also verify duration and a complete byte-for-byte copy before changing the library.')

    def apply_bulk(self):
        selected = sorted({item.row() for item in self.table.selectedIndexes()})
        for offset, index in enumerate(selected):
            if self.series.currentText().strip(): self.table.cellWidget(index, 2).setText(self.series.currentText().strip())
            self.table.cellWidget(index, 3).setValue(self.season.value())
            self.table.cellWidget(index, 4).setValue(self.first.value() + offset)
            self.table.cellWidget(index, 5).setCurrentText(self.language.currentText())

    def reviewed_entries(self, *, include_unchecked=False):
        return [ImportEntry(entry.source, self.table.cellWidget(index, 2).text().strip(),
                            self.table.cellWidget(index, 3).value(), self.table.cellWidget(index, 4).value(),
                            self.table.cellWidget(index, 5).currentText(), self.table.cellWidget(index, 6).currentIndex() == 1,
                            self.replacement_id)
                for index, entry in enumerate(self.entries) if include_unchecked or self.table.cellWidget(index, 0).isChecked()]


class PlaylistReviewDialog(QDialog):
    def __init__(self, result, series, parent=None):
        super().__init__(parent); self.setWindowTitle('Review YouTube playlist'); self.resize(1000, 620)
        self.result = result; layout = QVBoxLayout(self)
        label = QLabel(f"{result['title']} · {len(result['videos'])} available · {result['skipped']} unavailable or repeated entries skipped" + (' · Preview limited to 500 entries' if result.get('limited') else ''))
        label.setWordWrap(True); layout.addWidget(label)
        controls = QHBoxLayout(); self.series = QComboBox(); self.series.setEditable(True); self.series.setMinimumWidth(180); self.series.addItem(result['title'])
        for item in series: self.series.addItem(item['title'])
        self.season = QSpinBox(); self.season.setRange(1, 999); self.season.setValue(1)
        self.first = QSpinBox(); self.first.setRange(0, 9999); self.first.setSpecialValueText('Next available'); self.first.setValue(0)
        self.quality = QComboBox()
        for label, value in [('Best available', 'best'), ('1080p', '1080p'), ('720p', '720p'), ('480p', '480p')]: self.quality.addItem(label, value)
        for widget in (QLabel('Series'), self.series, QLabel('Season'), self.season, QLabel('First video'), self.first, self.quality): controls.addWidget(widget)
        layout.addLayout(controls)
        self.table = QTableWidget(len(result['videos']), 2); self.table.setHorizontalHeaderLabels(['Download', 'Video'])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for index, video in enumerate(result['videos']):
            check = QCheckBox(); check.setChecked(True); self.table.setCellWidget(index, 0, check)
            self.table.setItem(index, 1, QTableWidgetItem(f"{index + 1}. {video['title']}"))
        layout.addWidget(self.table, 1)
        selection = QHBoxLayout()
        for label, checked in [('Select all', True), ('Clear selection', False)]:
            button = QPushButton(label); button.clicked.connect(lambda _, value=checked: [self.table.cellWidget(index, 0).setChecked(value) for index in range(self.table.rowCount())]); selection.addWidget(button)
        layout.addLayout(selection)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton('Queue selected videos', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def selected_videos(self):
        return [video for index, video in enumerate(self.result['videos']) if self.table.cellWidget(index, 0).isChecked()]
