"""Tab Scan & Nilai: tambah foto LJK, proses di latar belakang, antrean lembar menurut status, dan cek manual
lembar yang dipilih di sampingnya; ekspor Excel."""
import shutil
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QRectF, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QProgressBar, QSplitter, QStackedWidget, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from app import server_client as SC
from app import server_link as SL
from app import theme
from app.review_tab import ReviewTab
from app.server_dialog import ServerDialog
from app.widgets import CountCard, EmptyState, toolbar
from ljk import service as SV

EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
STATUS_TONE = {"OK": "ok", "Perlu cek": "warn", "Sudah dicek": "info", "Gagal": "error"}
FILTERS = ("Semua", "Perlu cek", "Gagal", "Sudah dicek", "OK")
KOSONG = {"Semua": "Belum ada lembar.", "Perlu cek": "Tidak ada lembar yang perlu dicek.",
          "Gagal": "Tidak ada lembar yang gagal dibaca.", "Sudah dicek": "Belum ada lembar yang dicek manual.",
          "OK": "Belum ada lembar yang terbaca tanpa catatan."}
SORTS = [("urutan", "Nomor urut"), ("nilai", "Nilai tertinggi"), ("kode", "Kode naskah")]
DATA = Qt.UserRole + 1          # isi baris antrean (dict) untuk QueueDelegate
MEJA_TEGAK = 860                # lebar tab di bawah ini: antrean di atas panel cek, bukan di sampingnya
# Normalisasi kontras baca per event (ljk/omr.py KONTRAS): lembar pudar (mis. foto dari web HP)
# dikuatkan supaya isian tipis tetap terbaca. Server selalu memakai "standar".
KONTRAS_PILIHAN = [("mati", "Kontras baca: mati"), ("rendah", "Kontras baca: rendah"),
                   ("standar", "Kontras baca: standar"), ("tinggi", "Kontras baca: tinggi")]


class Worker(QThread):
    """Baca foto satu per satu di latar belakang.

    items: [(urutan, path, srv)]; srv None untuk foto lokal, atau dict untuk lembar dari server:
    {"server_id", "server": meta, "download": url foto (bila belum diunduh)}."""
    one = Signal(int, object)          # urutan, rekaman hasil baca
    progress = Signal(int, int, str)   # selesai, total, nama file

    def __init__(self, items, out_dir, kontras="standar"):
        super().__init__()
        self.items, self.out_dir, self.kontras = items, out_dir, kontras

    def run(self):
        n = len(self.items)
        for k, (urutan, path, srv) in enumerate(self.items):
            if self.isInterruptionRequested():
                break
            self.progress.emit(k, n, f"server #{srv['server_id']}" if srv else Path(path).name)
            try:
                if srv and srv.get("download") and not Path(path).exists():
                    SC.download(srv["download"], path)
                rec = SV.process_photo(path, self.out_dir, kontras=self.kontras)
            except SC.ServerError as e:
                rec = {"file": str(path), "error": f"Gagal mengunduh dari server: {e}", "baca": {}, "unduh_gagal": True}
            except Exception as e:  # foto rusak dsb.: dicatat, proses lanjut
                rec = {"file": str(path), "error": f"Gagal diproses: {e}", "baca": {}}
            if srv:
                rec["server_id"], rec["server"] = srv["server_id"], srv["server"]
                # data yang dikoreksi admin daerah menggantikan hasil baca (hasil baca asli tetap
                # tersimpan di 'baca', sehingga panel cek menampilkan perbedaannya)
                for key, val in ((srv["server"].get("konfirmasi") or {}).get("koreksi") or {}).items():
                    if key in ("nama", "nomor", "kode") and val and not rec.get("error"):
                        rec[key] = val
            self.one.emit(urutan, rec)
        self.progress.emit(n, n, "")


class QueueDelegate(QStyledItemDelegate):
    """Baris antrean dua tingkat: nama & nilai, lalu catatan pertama & nomor lembar (atau status di 'Semua').
    Terpilih: latar abu-abu dengan garis 2 px warna merek di tepi kiri."""

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 64)

    def paint(self, p, option, index):
        d = index.data(DATA) or {}
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        selected = option.state & QStyle.State_Selected
        if selected:
            p.fillRect(r, QColor(theme.c("selection")))
            p.fillRect(r.left(), r.top(), 2, r.height(), QColor(theme.c("accent")))
        elif option.state & QStyle.State_MouseOver:
            p.fillRect(r, QColor(theme.c("hover")))
        p.fillRect(r.left(), r.bottom(), r.width(), 1, QColor(theme.c("rule")))

        base = QFont(option.font)
        small = QFont(option.font)
        small.setPointSizeF(base.pointSizeF() * 0.9)
        left, right = r.left() + 14, r.right() - 12
        y1, y2 = r.top() + 11, r.top() + 34
        text, muted = QColor(theme.c("text")), QColor(theme.c("muted"))

        # baris 1: nilai di kanan ("150 /240" atau "—"), nama di kiri
        p.setFont(small)
        maks = d.get("maks", "")
        w_maks = p.fontMetrics().horizontalAdvance(maks) if maks else 0
        p.setFont(base)
        nilai = d.get("nilai", "—")
        w_nilai = p.fontMetrics().horizontalAdvance(nilai)
        x = right - w_maks - (4 if maks else 0) - w_nilai
        p.setPen(text if nilai != "—" else muted)
        p.drawText(QRectF(x, y1, w_nilai, 20), Qt.AlignLeft | Qt.AlignVCenter, nilai)
        if maks:
            p.setFont(small)
            p.setPen(muted)
            p.drawText(QRectF(right - w_maks, y1, w_maks, 20), Qt.AlignLeft | Qt.AlignVCenter, maks)
        p.setFont(base)
        p.setPen(text if d.get("nama_ok", True) else muted)
        p.drawText(QRectF(left, y1, x - left - 12, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(d.get("nama", ""), Qt.ElideRight, int(x - left - 12)))

        # baris 2: status (di 'Semua') atau nomor lembar di kanan, catatan di kiri
        p.setFont(small)
        fm = p.fontMetrics()
        pill = d.get("pill")
        if pill:
            bg, fg = theme.tone(STATUS_TONE.get(pill, "neutral"))
            w = fm.horizontalAdvance(pill) + 16
            pr = QRectF(right - w, y2 + 1, w, 18)
            path = QPainterPath()
            path.addRoundedRect(pr, 9, 9)
            p.fillPath(path, bg)
            p.setPen(fg)
            p.drawText(pr, Qt.AlignCenter, pill)
        else:
            meta = d.get("meta", "")
            w = fm.horizontalAdvance(meta)
            p.setPen(muted)
            p.drawText(QRectF(right - w, y2, w, 20), Qt.AlignLeft | Qt.AlignVCenter, meta)
        p.setPen(muted)
        avail = int(right - w - left - 12)
        p.drawText(QRectF(left, y2, avail, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(d.get("why", ""), Qt.ElideRight, avail))
        p.restore()


class ScanTab(QWidget):
    linked = Signal()                  # event dihubungkan ke kompetisi server
    running = Signal(bool)             # proses baca berjalan / selesai
    summary = Signal(dict)             # jumlah lembar per status (untuk judul event dan sidebar)

    def __init__(self, db, data_dir):
        super().__init__()
        self.db, self.data_dir = db, data_dir
        self.event_id = None
        self.worker = None
        self._pending = 0
        self._pulled = []
        self._filter = "Perlu cek"
        self._query = ""
        self._order = []               # [(id, status)] antrean yang sedang tampil, berurutan

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 16, 0, 0)
        v.setSpacing(16)

        # ---- tombol yang ditempatkan jendela utama di kepala halaman (sejajar nama event)
        self.btn_add = theme.button("Tambah foto", "image-plus", tip="Tambah foto LJK ke event ini")
        add_menu = QMenu(self.btn_add)
        self.act_files = add_menu.addAction("Pilih foto…", self._add_files)
        self.act_folder = add_menu.addAction("Semua foto di satu folder…", self._add_folder)
        self.btn_add.setMenu(add_menu)
        self.btn_export = theme.button("Ekspor nilai", "download", tip="Simpan daftar nilai ke Excel",
                                       slot=self._export)
        self.kontras = QComboBox()
        for key, text in KONTRAS_PILIHAN:
            self.kontras.addItem(text, key)
        self.kontras.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.kontras.setToolTip(
            "Penguatan isian tipis pada foto yang pudar (mis. foto dari web HP), berlaku untuk event ini.\n"
            "Standar: lembar normal tidak berubah; lembar pudar dikuatkan setara foto HP biasa.\n"
            "Tinggi: penguatan lebih kuat. Rendah: lebih hati-hati. Mati: tanpa penguatan (cara lama).")
        self.kontras.currentIndexChanged.connect(self._kontras_changed)

        # ---- kartu hitung: sekaligus penyaring antrean
        counts = toolbar(8)
        self.cards = {}
        self.card_group = QButtonGroup(self)
        self.card_group.setExclusive(True)
        for f in FILTERS:
            card = self.cards[f] = CountCard(f)
            card.clicked.connect(lambda _c=False, ff=f: self.set_filter(ff))
            self.card_group.addButton(card)
            counts.addWidget(card, 1)
        v.addLayout(counts)

        self.prog_box = QFrame()
        self.prog_box.setProperty("role", "card")
        pb = QHBoxLayout(self.prog_box)
        pb.setContentsMargins(16, 8, 8, 8)
        pb.setSpacing(14)
        self.progress_label = QLabel("")
        self.progress_label.setMinimumWidth(160)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.btn_stop = theme.button("Hentikan", "stop", "ghost", slot=self._stop)
        pb.addWidget(self.progress_label)
        pb.addWidget(self.progress, 1)
        pb.addWidget(self.btn_stop)
        self.prog_box.setVisible(False)
        v.addWidget(self.prog_box)

        # ---- meja periksa: antrean di kiri, lembar yang dibuka di kanan
        queue = QWidget()
        qv = QVBoxLayout(queue)
        qv.setContentsMargins(0, 0, 0, 0)
        qv.setSpacing(10)
        head = toolbar(8)
        self.q_title = QLabel("")
        self.q_title.setProperty("role", "h2")
        self.sort = QComboBox()
        for key, text in SORTS:
            self.sort.addItem(text, key)
        self.sort.setToolTip("Urutan antrean")
        self.sort.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.sort.setMinimumWidth(150)
        self.sort.currentIndexChanged.connect(lambda _i: self.refresh())
        self.btn_more = theme.button("", "more", "ghost", "Tindakan untuk lembar terpilih")
        self.row_menu = QMenu(self)
        self.act_redo = self.row_menu.addAction("Proses ulang lembar terpilih", self._reprocess)
        self.row_menu.addSeparator()
        self.act_del = self.row_menu.addAction("Hapus lembar terpilih…", self._delete)
        self.btn_more.setMenu(self.row_menu)
        self.btn_more.setProperty("menu", False)          # ikon saja, tanpa panah menu
        self.btn_more.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0; }")
        head.addWidget(self.q_title)
        head.addStretch()
        head.addWidget(self.sort)
        head.addWidget(self.btn_more)
        qv.addLayout(head)
        self.queue = QListWidget()
        self.queue.setObjectName("queue")
        self.queue.setItemDelegate(QueueDelegate(self.queue))
        self.queue.setMouseTracking(True)
        self.queue.setUniformItemSizes(True)
        self.queue.setSelectionMode(QListWidget.ExtendedSelection)
        self.queue.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.queue.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.queue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(lambda pos: self.row_menu.exec(self.queue.mapToGlobal(pos)))
        self.queue.currentItemChanged.connect(self._queue_current)
        self.q_empty = QLabel("")
        self.q_empty.setProperty("role", "muted")
        self.q_empty.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.q_empty.setWordWrap(True)
        self.q_empty.setContentsMargins(12, 24, 12, 12)
        self.q_stack = QStackedWidget()
        self.q_stack.addWidget(self.queue)
        self.q_stack.addWidget(self.q_empty)
        qv.addWidget(self.q_stack, 1)
        queue.setMinimumWidth(260)

        self.review = ReviewTab(db)
        self.review.next_id = self.next_id
        self.review.shown.connect(self._review_shown)
        self.review.step_requested.connect(self._step)
        self.review.changed.connect(self.refresh)

        self.desk = QSplitter(Qt.Horizontal)
        self.desk.setChildrenCollapsible(False)
        self.desk.addWidget(queue)
        self.desk.addWidget(self.review)
        self.desk.setStretchFactor(0, 0)
        self.desk.setStretchFactor(1, 1)
        self.desk.setSizes([320, 900])

        add = QWidget()
        ah = QHBoxLayout(add)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.addWidget(theme.button("Semua foto di folder", "folder-plus", slot=self._add_folder))
        ah.addWidget(theme.button("Pilih foto", "image-plus", "primary", slot=self._add_files))
        self.empty = EmptyState("image-plus", "Belum ada lembar",
                                "Tambahkan foto LJK, atau tarik lembar yang dikirim admin daerah lewat Sinkron.", add)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.desk)
        v.addWidget(self.stack, 1)

    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def load(self, event_id):
        self.event_id = event_id
        self.kontras.blockSignals(True)
        self.kontras.setCurrentIndex(max(0, self.kontras.findData(self._kontras())))
        self.kontras.blockSignals(False)
        self.kontras.setEnabled(event_id is not None and not self.busy())
        self._filter = None                         # dipilih ulang menurut isi event (lihat refresh)
        self.refresh()
        self.review.load(event_id)
        if self.review.cur is not None and self._pos(self.review.cur["id"]) == 0 and self.queue.count():
            self._select(0)                         # lembar pertama yang perlu dicek tidak ada di penyaring ini

    def activate(self):
        """Tab dibuka: segarkan antrean dan lembar yang tampil (kunci mungkin berubah di tab Kunci)."""
        self.refresh()
        self.review.activate()

    def _kontras(self):
        ev = self.db.event(self.event_id) if self.event_id is not None else None
        return (ev["kontras"] if ev is not None else None) or "standar"

    def _kontras_changed(self, _idx):
        new = self.kontras.currentData()
        if self.event_id is None or new == self._kontras():
            return
        self.db.set_kontras(self.event_id, new)
        rows = [r for r in self.db.lembar(self.event_id) if not r["dicek"]]
        if not rows or self.busy():
            return
        label = self.kontras.currentText().split(": ")[-1]
        if QMessageBox.question(self, "Kontras baca",
                                f"Baca ulang {len(rows)} lembar yang belum dicek dengan kontras {label}?\n"
                                "Lembar yang sudah dicek tidak diubah (bisa diproses ulang manual).") \
                == QMessageBox.Yes:
            self._reread(rows)

    def _out_dir(self):
        return self.data_dir / "event" / str(self.event_id)

    # ---- antrean
    def set_filter(self, f):
        self._filter = f
        self.refresh()
        if self.review.cur is not None and self._pos(self.review.cur["id"]) == 0 and self.queue.count():
            self._select(0)

    def _select(self, row):
        """Pilih satu baris antrean (pilihan lain dilepas) dan buka lembarnya."""
        self.queue.setCurrentRow(row, QItemSelectionModel.ClearAndSelect)

    def set_query(self, text):
        self._query = text.strip().lower()
        self.refresh()

    def refresh(self):
        if self.event_id is None:
            self.queue.clear()
            self._order = []
            return
        views = SV.event_views(self.db, self.event_id)
        counts = {f: 0 for f in FILTERS}
        counts["Semua"] = len(views)
        for v in views:
            counts[v.status] = counts.get(v.status, 0) + 1
        if self._filter is None:
            self._filter = next((f for f in ("Perlu cek", "Gagal") if counts[f]), "Semua")
        for f, card in self.cards.items():
            card.set(counts[f])
        self.cards[self._filter].setChecked(True)
        self.summary.emit(dict(counts, tanpa_nilai=sum(1 for v in views if v.status != "Gagal" and v.skor is None)))
        self.stack.setCurrentWidget(self.desk if views else self.empty)

        rows = [v for v in views if self._filter == "Semua" or v.status == self._filter]
        if self._query:
            rows = [v for v in rows if self._query in " ".join(
                str(x) for x in (v.row["nama"], v.row["nomor"], v.row["kode"], Path(v.row["file"]).name,
                                 SV.server_info(v.row).get("kota", ""))).lower()]
        key = self.sort.currentData()
        if key == "nilai":
            rows.sort(key=lambda v: (v.skor is None, -(v.skor.nilai if v.skor else 0), v.row["urutan"]))
        elif key == "kode":
            rows.sort(key=lambda v: (v.row["kode"] or "~", v.row["urutan"]))
        self.q_title.setText(("Semua lembar" if self._filter == "Semua" else self._filter) +
                             (f" · {len(rows)} cocok" if self._query else ""))

        cur = self.review.cur["id"] if self.review.cur is not None else None
        self.queue.blockSignals(True)
        self.queue.clear()
        self._order = []
        for v in rows:
            r, sk, srv = v.row, v.skor, SV.server_info(v.row)
            why = v.issues[0]["text"] if v.issues else (r["error"] or (f"{r['kode']} {v.soal.bidang}" if v.soal else r["kode"]))
            it = QListWidgetItem()
            it.setData(Qt.UserRole, r["id"])
            it.setData(DATA, {
                "nama": r["nama"] or ("Gagal dibaca" if v.status == "Gagal" else "Nama tidak terbaca"),
                "nama_ok": bool(r["nama"]),
                "nilai": str(sk.nilai) if sk is not None else "—",
                "maks": f"/{4 * v.soal.jumlah}" if sk is not None and v.soal else "",
                "why": why,
                "meta": f"#{r['urutan']}" + (" · HP" if srv else ""),
                "pill": v.status if self._filter == "Semua" and v.status != "OK" else None,
            })
            it.setToolTip(f"#{r['urutan']} · {Path(r['file']).name}" +
                          "".join(f"\n{i['text']}" for i in v.issues))
            self.queue.addItem(it)
            self._order.append((r["id"], v.status))
            if r["id"] == cur:
                self.queue.setCurrentItem(it, QItemSelectionModel.ClearAndSelect)
        self.queue.blockSignals(False)
        self.q_empty.setText(f"Tidak ada lembar yang cocok dengan “{self._query}”." if self._query and not rows
                             else KOSONG[self._filter])
        self.q_stack.setCurrentWidget(self.queue if rows else self.q_empty)
        self.review.refresh_list()
        self._update_position()

    def _pos(self, lembar_id):
        """Posisi lembar di antrean (mulai 1), 0 bila tidak ada."""
        for i, (lid, _st) in enumerate(self._order):
            if lid == lembar_id:
                return i + 1
        return 0

    def _update_position(self):
        cur = self.review.cur["id"] if self.review.cur is not None else None
        self.review.set_position(self._pos(cur), len(self._order))

    def _queue_current(self, item, _prev):
        if item is None:
            return
        lid = item.data(Qt.UserRole)
        if self.review.cur is None or self.review.cur["id"] != lid:
            self.review.show_lembar(lid)

    def _review_shown(self, lembar_id):
        i = self._pos(lembar_id)
        self.queue.blockSignals(True)
        if i:
            self.queue.setCurrentRow(i - 1, QItemSelectionModel.ClearAndSelect)
            self.queue.scrollToItem(self.queue.item(i - 1))
        else:
            self.queue.clearSelection()
        self.queue.blockSignals(False)
        self.queue.viewport().update()
        self._update_position()

    def _step(self, d):
        cur = self.review.cur["id"] if self.review.cur is not None else None
        i = self._pos(cur) - 1 + d
        if 0 <= i < len(self._order):
            self._select(i)

    def next_id(self, cur_id):
        """Lembar berikutnya yang masih perlu dicek sesudah cur_id, menurut urutan antrean (berputar ke awal)."""
        i = self._pos(cur_id)
        order = self._order[i:] + self._order[:max(0, i - 1)]
        return next((lid for lid, st in order if lid != cur_id and st in ("Perlu cek", "Gagal")), None)

    def _selected_ids(self):
        return [it.data(Qt.UserRole) for it in self.queue.selectedItems()]

    def resizeEvent(self, e):
        super().resizeEvent(e)
        tegak = self.width() < MEJA_TEGAK
        if tegak != (self.desk.orientation() == Qt.Vertical):
            self.desk.setOrientation(Qt.Vertical if tegak else Qt.Horizontal)
            self.desk.setSizes([220, 600] if tegak else [320, 900])

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
        self.worker = Worker(items, self._out_dir(), self._kontras())
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
        self.review.activate()          # lembar yang tampil mungkin baru saja dibaca ulang
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
        for w in (self.btn_add, self.btn_export, self.kontras, self.act_redo, self.act_del):
            w.setEnabled(not running)
        self.prog_box.setVisible(running)
        if not running:
            self.progress_label.setText("")
        self.running.emit(running)

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
        self._reread(rows)

    def _reread(self, rows):
        """Baca ulang lembar yang sudah ada (urutan & data server tetap)."""
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
        if self.review.cur is not None and self.review.cur["id"] in ids:
            self.review.dirty = False   # lembar yang sedang dibuka ikut dihapus: perubahannya tidak ditanyakan
        for i in ids:
            r = self.db.lembar_by_id(i)
            if r and r["gambar"]:
                shutil.rmtree(Path(r["gambar"]).parent, ignore_errors=True)
        self.db.delete_lembar(ids)
        self.refresh()
        self.review.activate()

    # ---- sinkron server
    def sync(self):
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
            # semua=True: termasuk lembar yang pernah ditarik, supaya lembar yang terhapus di sini bisa ditarik ulang
            res = SC.pending(kid, semua=True)
        except SC.ServerError as e:
            QMessageBox.warning(self, "Sinkron server", str(e))
            return
        have = self.db.server_ids(self.event_id)
        again = [i["id"] for i in res["items"] if i["id"] in have and not i.get("ditarik_at")]
        if again:                       # sudah ada di sini, tapi status 'ditarik' belum tercatat di server
            try:
                SC.mark_pulled(again)
            except SC.ServerError:
                pass
        new = [i for i in res["items"] if i["id"] not in have and not i.get("ditarik_at")]
        gone = [i for i in res["items"] if i["id"] not in have and i.get("ditarik_at")]
        if gone and QMessageBox.question(
                self, "Sinkron server",
                f"{len(gone)} lembar dari server pernah ditarik tetapi tidak ada lagi di event ini "
                "(mungkin terhapus).\nTarik ulang lembar itu?") == QMessageBox.Yes:
            new = sorted(new + gone, key=lambda i: i["id"])
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
