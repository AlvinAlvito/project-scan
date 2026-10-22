"""Tab Scan & Nilai: tambah foto LJK, proses di latar belakang, lihat status & nilai, ekspor Excel."""
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QProgressBar,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from app import server_client as SC
from app import theme
from app.colors import paint
from app import server_link as SL
from app.server_dialog import ServerDialog
from app.widgets import EmptyState, StatCard, divider, setup_table, toolbar
from ljk import service as SV

EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
STATUS_TONE = {"OK": "ok", "Perlu cek": "warn", "Sudah dicek": "info", "Gagal": "error"}
HEAD = ["#", "Sumber", "Status", "Nama", "Nomor", "Kode", "Bidang", "Lokasi", "Foto", "Benar", "Salah", "Kosong",
        "Nilai", "Catatan"]
COL_STATUS, COL_FOTO, COL_NILAI = 2, 8, 12
CENTER = (0, 8, 9, 10, 11, 12)


class Worker(QThread):
    """Baca foto satu per satu di latar belakang.

    items: [(urutan, path, srv)]; srv None untuk foto lokal, atau dict untuk lembar dari server:
    {"server_id", "server": meta, "download": url foto (bila belum diunduh)}."""
    one = Signal(int, object)          # urutan, rekaman hasil baca
    progress = Signal(int, int, str)   # selesai, total, nama file

    def __init__(self, items, out_dir):
        super().__init__()
        self.items, self.out_dir = items, out_dir

    def run(self):
        n = len(self.items)
        for k, (urutan, path, srv) in enumerate(self.items):
            if self.isInterruptionRequested():
                break
            self.progress.emit(k, n, f"server #{srv['server_id']}" if srv else Path(path).name)
            try:
                if srv and srv.get("download") and not Path(path).exists():
                    SC.download(srv["download"], path)
                rec = SV.process_photo(path, self.out_dir)
            except SC.ServerError as e:
                rec = {"file": str(path), "error": f"Gagal mengunduh dari server: {e}", "baca": {}, "unduh_gagal": True}
            except Exception as e:  # foto rusak dsb.: dicatat, proses lanjut
                rec = {"file": str(path), "error": f"Gagal diproses: {e}", "baca": {}}
            if srv:
                rec["server_id"], rec["server"] = srv["server_id"], srv["server"]
                # data yang dikoreksi admin daerah menggantikan hasil baca (hasil baca asli tetap
                # tersimpan di 'baca', sehingga layar Cek Manual menampilkan perbedaannya)
                for key, val in ((srv["server"].get("konfirmasi") or {}).get("koreksi") or {}).items():
                    if key in ("nama", "nomor", "kode") and val and not rec.get("error"):
                        rec[key] = val
            self.one.emit(urutan, rec)
        self.progress.emit(n, n, "")


class ScanTab(QWidget):
    open_review = Signal(int)
    linked = Signal()                  # event dihubungkan ke kompetisi server

    def __init__(self, db, data_dir):
        super().__init__()
        self.db, self.data_dir = db, data_dir
        self.event_id = None
        self.worker = None
        self._pending = 0
        self._pulled = []

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 18, 0, 0)
        v.setSpacing(14)

        bar = toolbar()
        self.btn_folder = theme.button("Tambah folder", "folder-plus", tip="Proses semua foto di satu folder",
                                       slot=self._add_folder)
        self.btn_files = theme.button("Tambah foto", "image-plus", tip="Pilih beberapa foto", slot=self._add_files)
        self.btn_redo = theme.button("Proses ulang", "refresh", tip="Baca ulang lembar yang dipilih",
                                     slot=self._reprocess)
        self.btn_del = theme.button("Hapus", "trash", "danger", "Hapus lembar yang dipilih (foto asli tetap ada)",
                                    self._delete)
        self.btn_sync = theme.button("Sinkron server", "cloud-download", "primary",
                                     "Tarik LJK yang dikirim admin daerah lewat HP", self._sync)
        self.only_check = theme.button("Perlu cek saja", "filter", tip="Tampilkan hanya lembar yang perlu dicek")
        self.only_check.setCheckable(True)
        self.only_check.toggled.connect(self.refresh)
        self.btn_export = theme.button("Ekspor nilai", "download", tip="Simpan daftar nilai ke Excel",
                                       slot=self._export)
        for w in (self.btn_sync, divider(), self.btn_folder, self.btn_files, divider(), self.btn_redo, self.btn_del):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.only_check)
        bar.addWidget(self.btn_export)
        v.addLayout(bar)

        stats = toolbar(12)
        self.cards = {"total": StatCard("Lembar"), "OK": StatCard("OK", "ok"),
                      "Perlu cek": StatCard("Perlu cek", "warn"), "Sudah dicek": StatCard("Sudah dicek", "info"),
                      "Gagal": StatCard("Gagal", "error")}
        for card in self.cards.values():
            stats.addWidget(card, 1)
        v.addLayout(stats)

        self.prog_box = QFrame()
        self.prog_box.setProperty("role", "card")
        pb = QHBoxLayout(self.prog_box)
        pb.setContentsMargins(16, 10, 10, 10)
        pb.setSpacing(14)
        self.progress_label = QLabel("")
        self.progress_label.setMinimumWidth(260)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.btn_stop = theme.button("Hentikan", "stop", "ghost", slot=self._stop)
        pb.addWidget(self.progress_label)
        pb.addWidget(self.progress, 1)
        pb.addWidget(self.btn_stop)
        self.prog_box.setVisible(False)
        v.addWidget(self.prog_box)

        self.table = QTableWidget(0, len(HEAD))
        self.table.setHorizontalHeaderLabels(HEAD)
        setup_table(self.table, pill=True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setToolTip("Klik dua kali untuk membuka lembar di Cek Manual")
        h = self.table.horizontalHeader()
        for c in range(len(HEAD) - 1):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(len(HEAD) - 1, QHeaderView.Stretch)
        for c in CENTER:
            self.table.horizontalHeaderItem(c).setTextAlignment(Qt.AlignCenter)
        self.table.cellDoubleClicked.connect(self._double_click)

        self.empty = EmptyState("image-plus", "Belum ada lembar",
                                "Tambahkan folder berisi foto LJK untuk mulai membaca.")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.table)
        v.addWidget(self.stack, 1)

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
            return
        views = SV.event_views(self.db, self.event_id)
        counts = {}
        for v in views:
            counts[v.status] = counts.get(v.status, 0) + 1
        self.cards["total"].set(len(views))
        for k in ("OK", "Perlu cek", "Sudah dicek", "Gagal"):
            self.cards[k].set(counts.get(k, 0))
        if self.only_check.isChecked():
            views = [v for v in views if v.status in ("Perlu cek", "Gagal")]
        if not views:
            self.empty.set_text(*(("Semua beres", "Tidak ada lembar yang perlu dicek.")
                                  if self.only_check.isChecked() else
                                  ("Belum ada lembar", "Tambahkan folder berisi foto LJK untuk mulai membaca.")))
        self.stack.setCurrentWidget(self.table if views else self.empty)
        self.table.setRowCount(len(views))
        for r, v in enumerate(views):
            row = v.row
            sk = v.skor
            srv = SV.server_info(row)
            q = srv.get("skor_kualitas")
            vals = [row["urutan"], f"server #{srv['id']}" if srv else Path(row["file"]).name, v.status,
                    row["nama"], row["nomor"], row["kode"], v.soal.bidang if v.soal else "", srv.get("kota", ""),
                    "" if q is None else f"{q}%",
                    "" if sk is None else sk.benar, "" if sk is None else sk.salah,
                    "" if sk is None else sk.kosong, "" if sk is None else sk.nilai,
                    "; ".join(i["text"] for i in v.issues)]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                if c in CENTER:
                    it.setTextAlignment(Qt.AlignCenter)
                if c == 0:
                    it.setData(Qt.UserRole, row["id"])
                if c == 1 and srv:
                    it.setToolTip(f"Dikirim {srv.get('uploader', '')} dari {srv.get('kota', '')} - {srv.get('dibuat', '')}\n"
                                  f"Keyakinan baca server: {srv.get('keyakinan', '?')}%")
                if c == COL_STATUS:
                    it.setTextAlignment(Qt.AlignCenter)
                    paint(it, STATUS_TONE.get(v.status))
                if c == COL_FOTO and q is not None:
                    paint(it, "ok" if q >= 90 else "warn" if q >= SV.KUALITAS_MIN else "error")
                if c == COL_NILAI and val != "":
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                if c == len(vals) - 1:
                    it.setToolTip(str(val))
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

    def _start(self, paths, urutan=None, srv=None):
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
            items = [(start + i, p, None) for i, p in enumerate(new)]
            if skipped:
                QMessageBox.information(self, "Tambah foto", f"{skipped} foto dilewati karena sudah ada di event ini.")
        else:
            items = list(zip(urutan, paths, srv or [None] * len(paths)))
        self._run(items)

    def _run(self, items):
        self._pulled = []
        self.worker = Worker(items, self._out_dir())
        self.worker.one.connect(self._one_done)
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self._finished)
        self._set_running(True)
        self.worker.start()

    def _one_done(self, urutan, rec):
        if rec.get("unduh_gagal"):
            return                      # tidak disimpan; dicoba lagi pada sinkron berikutnya
        if rec.get("server_id"):
            self._pulled.append(rec["server_id"])
        self.db.add_lembar(self.event_id, urutan, rec)
        self._pending += 1
        if self._pending >= 5:
            self._pending = 0
            self.refresh()

    def _progress(self, done, total, name):
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        self.progress_label.setText(f"<b>Membaca {done}/{total}</b>&nbsp;&nbsp;{name}")

    def _finished(self):
        self._set_running(False)
        self._pending = 0
        self.refresh()
        if self._pulled:
            n = len(self._pulled)
            try:
                SC.mark_pulled(self._pulled)
            except SC.ServerError as e:
                QMessageBox.warning(self, "Sinkron server", "Lembar sudah tersimpan, tetapi status 'ditarik' belum "
                                    f"terkirim ke server:\n{e}\n\nAkan dicoba lagi saat sinkron berikutnya.")
            self._pulled = []
            QMessageBox.information(self, "Sinkron server", f"{n} lembar dari server sudah dibaca dan masuk ke event ini.")

    def _stop(self):
        if self.busy():
            self.worker.requestInterruption()

    def _set_running(self, running):
        for w in (self.btn_sync, self.btn_folder, self.btn_files, self.btn_redo, self.btn_del, self.btn_export):
            w.setEnabled(not running)
        self.prog_box.setVisible(running)
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
        srv = [{"server_id": r["server_id"], "server": SV.server_info(r)} if r["server_id"] else None for r in rows]
        self._start([Path(r["file"]) for r in rows], urutan=[r["urutan"] for r in rows], srv=srv)

    def _delete(self):
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(self, "Hapus lembar", "Pilih dulu lembar yang akan dihapus.")
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

    # ---- sinkron server
    def _sync(self):
        """Laporkan lembar yang sudah dicek, lalu tarik lembar baru dari server dan baca di sini."""
        if self.event_id is None or self.busy():
            return
        if not SC.logged_in() and not ServerDialog(self).exec():
            return
        ev = self.db.event(self.event_id)
        url = SC.config()["url"]
        kid = ev["server_kompetisi_id"] if ev["server_url"] == url else None
        if not kid:                     # pertama kali: hubungkan ke kompetisi baru atau yang sudah ada
            kid = SL.kirim(self, self.db, self.data_dir, self.event_id)
            if kid is None:
                return
            self.linked.emit()
        done = []
        try:
            done = self.db.dicek_unsynced(self.event_id)
            if done:
                SC.mark_checked(done)
                self.db.mark_server_dicek(self.event_id, done)
            res = SC.pending(kid)
        except SC.ServerError as e:
            QMessageBox.warning(self, "Sinkron server", str(e))
            return
        have = self.db.server_ids(self.event_id)
        again = [i["id"] for i in res["items"] if i["id"] in have]
        if again:                       # sudah ada di sini, tapi status 'ditarik' belum tercatat di server
            try:
                SC.mark_pulled(again)
            except SC.ServerError:
                pass
        new = [i for i in res["items"] if i["id"] not in have]
        if not new:
            wait = res.get("menunggu_konfirmasi", 0)
            QMessageBox.information(self, "Sinkron server", "Tidak ada lembar baru dari server." +
                                    (f"\n{wait} lembar masih menunggu konfirmasi admin daerah." if wait else "") +
                                    (f"\n{len(done)} status 'sudah dicek' dikirim ke server." if done else ""))
            return
        start = self.db.next_urutan(self.event_id)
        folder = self._out_dir() / "server"
        items = [(start + k, folder / f"{it['id']}.jpg",
                  {"server_id": it["id"], "server": SC.meta(it), "download": it["urls"]["foto"]})
                 for k, it in enumerate(new)]
        self._run(items)

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
