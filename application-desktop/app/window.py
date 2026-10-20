"""Jendela utama: daftar event di kiri, tab Kunci / Scan & Nilai / Cek Manual di kanan."""
import shutil

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
                               QSplitter, QTabWidget, QVBoxLayout, QWidget)

from app.kunci_tab import KunciTab
from app.latih_tab import LatihTab
from app.review_tab import ReviewTab
from app.scan_tab import ScanTab


class EventDialog(QDialog):
    def __init__(self, parent=None, nama="", tanggal=""):
        super().__init__(parent)
        self.setWindowTitle("Event")
        self.nama = QLineEdit(nama)
        self.nama.setPlaceholderText("mis. FSN PROVINSI PAKET 1")
        self.tanggal = QLineEdit(tanggal)
        self.tanggal.setPlaceholderText("mis. 24 September 2026")
        form = QFormLayout(self)
        form.addRow("Nama event", self.nama)
        form.addRow("Tanggal", self.tanggal)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.resize(420, 120)

    def _ok(self):
        if not self.nama.text().strip() or not self.tanggal.text().strip():
            QMessageBox.warning(self, "Event", "Nama event dan tanggal wajib diisi.")
            return
        self.accept()

    def values(self):
        return self.nama.text().strip(), self.tanggal.text().strip()


class MainWindow(QMainWindow):
    def __init__(self, db, data_dir):
        super().__init__()
        self.db, self.data_dir = db, data_dir
        self.event_id = None
        self.setWindowTitle("LJK Reader - POSI")
        self.resize(1400, 860)

        # Panel kiri: event
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("<b>Event</b>"))
        self.events = QListWidget()
        self.events.currentItemChanged.connect(self._event_selected)
        lv.addWidget(self.events)
        row = QHBoxLayout()
        for text, slot in (("Baru", self._new_event), ("Ubah", self._edit_event), ("Hapus", self._delete_event)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lv.addLayout(row)
        folder = QPushButton("Buka folder data")
        folder.setToolTip(str(data_dir))
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_dir))))
        lv.addWidget(folder)

        # Panel kanan: tab
        self.tabs = QTabWidget()
        self.kunci = KunciTab(db)
        self.scan = ScanTab(db, data_dir)
        self.review = ReviewTab(db)
        self.latih = LatihTab(db, data_dir)
        self.tabs.addTab(self.kunci, "1. Kunci Jawaban")
        self.tabs.addTab(self.scan, "2. Scan && Nilai")
        self.tabs.addTab(self.review, "3. Cek Manual")
        self.tabs.addTab(self.latih, "4. Latih Model")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.kunci.changed.connect(self.scan.refresh)
        self.scan.open_review.connect(self._open_review)
        self.review.changed.connect(self.scan.refresh)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        split.setSizes([240, 1160])
        self.setCentralWidget(split)
        self._load_events()

    # ---- event
    def _load_events(self, select=None):
        self.events.blockSignals(True)
        self.events.clear()
        for ev in self.db.events():
            it = QListWidgetItem(f"{ev['nama']}\n{ev['tanggal']}")
            it.setData(Qt.UserRole, ev["id"])
            self.events.addItem(it)
        self.events.blockSignals(False)
        if self.events.count():
            idx = 0
            for i in range(self.events.count()):
                if self.events.item(i).data(Qt.UserRole) == select:
                    idx = i
            self.events.setCurrentRow(idx)
        else:
            self._set_event(None)

    def _event_selected(self, cur, _prev):
        self._set_event(cur.data(Qt.UserRole) if cur else None)

    def _set_event(self, event_id):
        self.event_id = event_id
        self.tabs.setEnabled(event_id is not None)
        self.latih.load(event_id)
        self.kunci.load(event_id)
        self.scan.load(event_id)
        self.review.load(event_id)

    def _new_event(self):
        d = EventDialog(self)
        if d.exec():
            eid = self.db.add_event(*d.values())
            self._load_events(select=eid)
            self.tabs.setCurrentIndex(0)

    def _edit_event(self):
        if self.event_id is None:
            return
        ev = self.db.event(self.event_id)
        d = EventDialog(self, ev["nama"], ev["tanggal"])
        if d.exec():
            self.db.update_event(self.event_id, *d.values())
            self._load_events(select=self.event_id)

    def _delete_event(self):
        if self.event_id is None:
            return
        ev = self.db.event(self.event_id)
        n = len(self.db.lembar(self.event_id))
        if QMessageBox.question(self, "Hapus event",
                                f"Hapus event '{ev['nama']}' beserta kunci dan {n} lembar hasil scan?\n"
                                "Foto asli tidak ikut terhapus.") != QMessageBox.Yes:
            return
        shutil.rmtree(self.data_dir / "event" / str(self.event_id), ignore_errors=True)
        self.db.delete_event(self.event_id)
        self._load_events()

    # ---- tab
    def _tab_changed(self, idx):
        if self.tabs.widget(idx) is self.scan:
            self.scan.refresh()
        elif self.tabs.widget(idx) is self.review:
            self.review.activate()

    def _open_review(self, lembar_id):
        self.tabs.setCurrentWidget(self.review)
        self.review.show_lembar(lembar_id)

    def closeEvent(self, e):
        if self.scan.busy():
            QMessageBox.information(self, "LJK Reader", "Tunggu proses scan selesai dulu.")
            e.ignore()
            return
        if not self.review.confirm_leave():
            e.ignore()
            return
        super().closeEvent(e)
