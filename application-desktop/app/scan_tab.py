"""Tab 2: tambah foto LJK, proses di latar belakang, lihat status & nilai, ekspor Excel."""
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from app.colors import paint
from ljk import service as SV

EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
STATUS_COLOR = {"OK": QColor(212, 237, 218), "Perlu cek": QColor(255, 229, 180),
                "Sudah dicek": QColor(207, 226, 255), "Gagal": QColor(248, 196, 196)}
HEAD = ["Urutan", "File", "Status", "Nama", "Nomor", "Kode", "Bidang", "B", "S", "K", "Nilai",
        "Hal yang perlu dicek"]


class Worker(QThread):
    one = Signal(int, object)          # urutan, rekaman hasil baca
    progress = Signal(int, int, str)   # selesai, total, nama file

    def __init__(self, items, out_dir):
        super().__init__()
        self.items, self.out_dir = items, out_dir

    def run(self):
        n = len(self.items)
        for k, (urutan, path) in enumerate(self.items):
            if self.isInterruptionRequested():
                break
            self.progress.emit(k, n, Path(path).name)
            try:
                rec = SV.process_photo(path, self.out_dir)
            except Exception as e:  # foto rusak dsb.: dicatat, proses lanjut
                rec = {"file": str(path), "error": f"Gagal diproses: {e}", "baca": {}}
            self.one.emit(urutan, rec)
        self.progress.emit(n, n, "")


class ScanTab(QWidget):
    open_review = Signal(int)

    def __init__(self, db, data_dir):
        super().__init__()
        self.db, self.data_dir = db, data_dir
        self.event_id = None
        self.worker = None
        self._pending = 0

        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btn_folder = QPushButton("Tambah foto dari folder...")
        self.btn_folder.clicked.connect(self._add_folder)
        self.btn_files = QPushButton("Tambah foto...")
        self.btn_files.clicked.connect(self._add_files)
        self.btn_redo = QPushButton("Proses ulang")
        self.btn_redo.clicked.connect(self._reprocess)
        self.btn_del = QPushButton("Hapus lembar")
        self.btn_del.clicked.connect(self._delete)
        self.only_check = QCheckBox("Hanya yang perlu cek")
        self.only_check.toggled.connect(self.refresh)
        self.btn_export = QPushButton("Ekspor Daftar Nilai...")
        self.btn_export.setStyleSheet("font-weight: bold")
        self.btn_export.clicked.connect(self._export)
        for w in (self.btn_folder, self.btn_files, self.btn_redo, self.btn_del, self.only_check):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.btn_export)
        v.addLayout(bar)

        prog = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress_label = QLabel("")
        self.btn_stop = QPushButton("Hentikan")
        self.btn_stop.setVisible(False)
        self.btn_stop.clicked.connect(self._stop)
        prog.addWidget(self.progress, 1)
        prog.addWidget(self.progress_label)
        prog.addWidget(self.btn_stop)
        v.addLayout(prog)

        self.summary = QLabel("")
        v.addWidget(self.summary)
        self.table = QTableWidget(0, len(HEAD))
        self.table.setHorizontalHeaderLabels(HEAD)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        h = self.table.horizontalHeader()
        for c in range(len(HEAD) - 1):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(len(HEAD) - 1, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._double_click)
        v.addWidget(self.table)
        v.addWidget(QLabel("Klik dua kali sebuah baris untuk membuka lembar di tab Cek Manual."))

    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def load(self, event_id):
        self.event_id = event_id
        self.refresh()

    def _out_dir(self):
        return self.data_dir / "event" / str(self.event_id)

    # ---- tabel
    def refresh(self):
        self.table.setRowCount(0)
        if self.event_id is None:
            self.summary.setText("")
            return
        views = SV.event_views(self.db, self.event_id)
        counts = {}
        for v in views:
            counts[v.status] = counts.get(v.status, 0) + 1
        self.summary.setText(
            f"<b>{len(views)}</b> lembar &nbsp;|&nbsp; OK {counts.get('OK', 0)} &nbsp;|&nbsp; "
            f"Perlu cek <b>{counts.get('Perlu cek', 0)}</b> &nbsp;|&nbsp; Sudah dicek {counts.get('Sudah dicek', 0)}"
            f" &nbsp;|&nbsp; Gagal {counts.get('Gagal', 0)}")
        if self.only_check.isChecked():
            views = [v for v in views if v.status in ("Perlu cek", "Gagal")]
        self.table.setRowCount(len(views))
        for r, v in enumerate(views):
            row = v.row
            sk = v.skor
            vals = [row["urutan"], Path(row["file"]).name, v.status, row["nama"], row["nomor"], row["kode"],
                    v.soal.bidang if v.soal else "",
                    "" if sk is None else sk.benar, "" if sk is None else sk.salah,
                    "" if sk is None else sk.kosong, "" if sk is None else sk.nilai,
                    "; ".join(i["text"] for i in v.issues)]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                if c in (0, 7, 8, 9, 10):
                    it.setTextAlignment(Qt.AlignCenter)
                if c == 0:
                    it.setData(Qt.UserRole, row["id"])
                if c == 2:
                    paint(it, STATUS_COLOR.get(v.status))
                self.table.setItem(r, c, it)

    def _selected_ids(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.table.item(r, 0).data(Qt.UserRole) for r in rows]

    def _double_click(self, r, _c):
        self.open_review.emit(self.table.item(r, 0).data(Qt.UserRole))

    # ---- tambah & proses
    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder foto LJK")
        if folder:
            self._start([p for p in Path(folder).iterdir() if p.suffix.lower() in EXTS])

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Foto LJK", "", "Gambar (*.jpg *.jpeg *.png *.bmp *.tif *.tiff)")
        if files:
            self._start([Path(f) for f in files])

    def _start(self, paths, urutan=None):
        if self.event_id is None or self.busy():
            return
        if urutan is None:
            have = self.db.files(self.event_id)
            new = sorted((p for p in paths if str(p) not in have), key=lambda p: p.name)
            skipped = len(paths) - len(new)
            if not new:
                QMessageBox.information(self, "Tambah foto", "Semua foto itu sudah ada di event ini.")
                return
            start = self.db.next_urutan(self.event_id)
            items = [(start + i, p) for i, p in enumerate(new)]
            if skipped:
                QMessageBox.information(self, "Tambah foto", f"{skipped} foto dilewati karena sudah ada di event ini.")
        else:
            items = list(zip(urutan, paths))
        self.worker = Worker(items, self._out_dir())
        self.worker.one.connect(self._one_done)
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self._finished)
        self._set_running(True)
        self.worker.start()

    def _one_done(self, urutan, rec):
        self.db.add_lembar(self.event_id, urutan, rec)
        self._pending += 1
        if self._pending >= 5:
            self._pending = 0
            self.refresh()

    def _progress(self, done, total, name):
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        self.progress_label.setText(f"{done}/{total}  {name}")

    def _finished(self):
        self._set_running(False)
        self._pending = 0
        self.refresh()

    def _stop(self):
        if self.busy():
            self.worker.requestInterruption()

    def _set_running(self, running):
        for w in (self.btn_folder, self.btn_files, self.btn_redo, self.btn_del, self.btn_export):
            w.setEnabled(not running)
        self.progress.setVisible(running)
        self.btn_stop.setVisible(running)
        if not running:
            self.progress_label.setText("")

    def _reprocess(self):
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(self, "Proses ulang", "Pilih dulu lembar yang akan diproses ulang.")
            return
        rows = [self.db.lembar_by_id(i) for i in ids]
        if any(r["dicek"] for r in rows) and QMessageBox.question(
                self, "Proses ulang", "Sebagian lembar sudah dicek manual. Hasil cek akan hilang. Lanjutkan?"
        ) != QMessageBox.Yes:
            return
        self._start([Path(r["file"]) for r in rows], urutan=[r["urutan"] for r in rows])

    def _delete(self):
        ids = self._selected_ids()
        if not ids:
            return
        if QMessageBox.question(self, "Hapus lembar", f"Hapus {len(ids)} lembar dari event ini?\n"
                                "Foto asli tidak ikut terhapus.") != QMessageBox.Yes:
            return
        for i in ids:
            r = self.db.lembar_by_id(i)
            if r and r["gambar"]:
                shutil.rmtree(Path(r["gambar"]).parent, ignore_errors=True)
        self.db.delete_lembar(ids)
        self.refresh()

    # ---- ekspor
    def _export(self):
        if self.event_id is None:
            return
        views = SV.event_views(self.db, self.event_id)
        if not views:
            QMessageBox.information(self, "Ekspor", "Belum ada lembar.")
            return
        cek = sum(1 for v in views if v.status == "Perlu cek" and v.skor is not None)
        nokode = sum(1 for v in views if v.status != "Gagal" and v.skor is None)
        gagal = sum(1 for v in views if v.status == "Gagal")
        if cek or nokode or gagal:
            parts = []
            if cek:
                parts.append(f"- {cek} lembar masih perlu cek; nilainya memakai hasil baca/tebakan sementara.")
            if nokode:
                parts.append(f"- {nokode} lembar dengan kode naskah belum terdaftar TIDAK ikut diekspor.")
            if gagal:
                parts.append(f"- {gagal} lembar gagal dibaca TIDAK ikut diekspor.")
            if QMessageBox.question(self, "Ekspor", "\n".join(parts) + "\n\nTetap ekspor sekarang?") != QMessageBox.Yes:
                return
        ev = self.db.event(self.event_id)
        default = str(Path.home() / "Documents" / f"{ev['nama']} Daftar Nilai.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "Simpan Daftar Nilai", default, "Excel (*.xlsx)")
        if not path:
            return
        try:
            n, _skipped = SV.export_event(self.db, self.event_id, path)
        except PermissionError:
            QMessageBox.warning(self, "Ekspor", "File tidak bisa ditulis. Tutup dulu file itu di Excel.")
            return
        if QMessageBox.question(self, "Ekspor", f"{n} lembar tersimpan di:\n{path}\n\nBuka file sekarang?") \
                == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
