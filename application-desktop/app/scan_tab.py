"""Tab Scan & Nilai: tambah foto LJK, proses di latar belakang, antrean lembar menurut status, dan cek manual
lembar yang dipilih di sampingnya; ekspor Excel."""
import html
import os
import shutil
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QRectF, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QProgressBar, QSizePolicy, QSplitter, QStackedWidget,
                               QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from app import server_client as SC
from app import server_link as SL
from app import theme
from app.paket_page import pilih_paket, ringkas_kode
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
                # folder gambar per nomor urut: foto bernama sama dari folder lain (Ruang1/001.jpg,
                # Ruang2/001.jpg) tidak berbagi gambar cek; baca ulang menimpa folder lembar itu sendiri
                rec = SV.process_photo(path, Path(self.out_dir) / f"{urutan:04d}", kontras=self.kontras)
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
    Terpilih: latar abu-abu dengan garis 2 px warna merek di tepi kiri. Baris judul bidang (saat 'Semua bidang'):
    nama bidang tebal + jumlah lembar, tidak bisa dipilih."""
    HEADER_H = 40

    def sizeHint(self, option, index):
        d = index.data(DATA) or {}
        return QSize(option.rect.width(), self.HEADER_H if d.get("header") else 64)

    def _paint_header(self, p, option, d):
        r = option.rect
        p.fillRect(r, QColor(theme.c("surface2")))
        p.fillRect(r.left(), r.bottom(), r.width(), 1, QColor(theme.c("border")))
        f = QFont(option.font)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        fm = p.fontMetrics()
        info = d.get("info", "")
        small = QFont(option.font)
        small.setPointSizeF(f.pointSizeF() * 0.9)
        p.setFont(small)
        w_info = p.fontMetrics().horizontalAdvance(info)
        right = r.right() - 12
        p.setPen(QColor(theme.c("muted")))
        p.drawText(QRectF(right - w_info, r.top(), w_info, r.height()), Qt.AlignRight | Qt.AlignVCenter, info)
        p.setFont(f)
        p.setPen(QColor(theme.c("text")))
        avail = int(right - w_info - 12 - (r.left() + 14))
        p.drawText(QRectF(r.left() + 14, r.top(), avail, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(d.get("judul", ""), Qt.ElideRight, avail))

    def paint(self, p, option, index):
        d = index.data(DATA) or {}
        if d.get("header"):
            p.save()
            self._paint_header(p, option, d)
            p.restore()
            return
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
    paket_dipilih = Signal()           # paket kunci event dipilih sebelum scan (tab Kunci & judul perlu dimuat ulang)
    buka_kunci = Signal()              # panitia ingin membuat/mengisi paket di menu Kunci jawaban

    def __init__(self, db, data_dir):
        super().__init__()
        self.db, self.data_dir = db, data_dir
        self.event_id = None
        self.worker = None
        self._run_event, self._run_nama, self._hilang = None, "", []
        self._pending = 0
        self._pulled = []
        self._filter = "Perlu cek"
        self._query = ""
        self._order = []               # [(id, status)] antrean yang sedang tampil, berurutan
        self._baris = []               # nomor baris QListWidget tiap lembar di _order (ada baris judul bidang)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 16, 0, 0)
        v.setSpacing(16)

        # ---- tombol yang ditempatkan jendela utama di kepala halaman (sejajar nama event)
        self.btn_add = theme.button("Tambah foto", "image-plus", tip="Tambah foto LJK ke event ini")
        add_menu = QMenu(self.btn_add)
        self.act_files = add_menu.addAction("Pilih foto…", self._add_files)
        self.act_folder = add_menu.addAction("Semua foto di folder (termasuk sub-folder)…", self._add_folder)
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
        # bidang (mata pelajaran) dari paket kunci: menyaring antrean, kartu hitung, dan "simpan lalu lanjut"
        brow = toolbar(8)
        lb_bidang = QLabel("Bidang")
        lb_bidang.setProperty("role", "muted")
        self.bidang = QComboBox()
        self.bidang.setToolTip("Tampilkan lembar satu bidang saja (bidang dari paket kunci jawaban event ini)")
        self.bidang.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.bidang.setMinimumContentsLength(14)
        self.bidang.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.bidang.setMaxVisibleItems(16)
        self.bidang.currentIndexChanged.connect(self._bidang_changed)
        brow.addWidget(lb_bidang)
        brow.addWidget(self.bidang, 1)
        qv.addLayout(brow)
        self._bidang_key = None                     # None = semua bidang; selain itu str(kunci kelompok)
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
        self.queue.setUniformItemSizes(False)       # baris judul bidang lebih pendek dari baris lembar
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
        self._bidang_key = None                     # event lain: mulai dari semua bidang
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
            if not self._boleh_baca_ulang([r["id"] for r in rows]):
                return
            self._reread([r for r in self.db.lembar(self.event_id) if not r["dicek"]])   # mungkin baru disimpan

    def _boleh_baca_ulang(self, ids):
        """Lembar yang sedang dicek dan belum disimpan ikut dibaca ulang: tawarkan simpan dulu (Simpan/Buang/Batal),
        supaya ketikannya tidak hilang diam-diam."""
        cur = self.review.cur
        if cur is None or not self.review.dirty or cur["id"] not in ids:
            return True
        if not self.review.confirm_leave():
            return False
        self.review.dirty = False           # Simpan sudah menyimpan; Buang: isian lama memang dibuang
        return True

    def _out_dir(self):
        return self.data_dir / "event" / str(self.event_id)

    # ---- antrean
    def set_filter(self, f):
        self._filter = f
        self.refresh()
        if self.review.cur is not None and self._pos(self.review.cur["id"]) == 0 and self.queue.count():
            self._select(0)

    def _bidang_changed(self, _idx):
        if self._isi_bidang_jalan:
            return
        self._bidang_key = self.bidang.currentData()
        self.refresh()
        if self.review.cur is not None and self._pos(self.review.cur["id"]) == 0 and self._order:
            self._select(0)                         # lembar yang terbuka bukan bidang ini: buka lembar pertamanya

    _isi_bidang_jalan = False

    def set_bidang(self, key):
        """Pilih bidang (None = semua bidang; selain itu kunci kelompok dari service.kelompok_bidang) dari luar,
        mis. saat lembar dibuka dari menu Nilai hasil."""
        self._bidang_key = None if key is None else str(key)
        self.refresh()

    def _isi_bidang(self, groups, total):
        """Isi dropdown Bidang: Semua bidang + semua bidang paket (jumlah lembar) + lembar tanpa bidang (bila ada)."""
        self._isi_bidang_jalan = True
        self.bidang.clear()
        self.bidang.addItem(f"Semua bidang ({total})", None)
        for g in groups:
            n = len(g["views"])
            if g["key"] == SV.BELUM:
                teks = f"Tanpa bidang: gagal dibaca / kode tak terdaftar ({n})"
            else:
                kode = ringkas_kode(g["kode"])
                teks = f"{g['nama']}" + (f" · {kode}" if kode else "") + f" ({n})"
            self.bidang.addItem(teks, str(g["key"]))      # teks: QComboBox.findData tidak bisa mencari tuple
        i = self.bidang.findData(self._bidang_key) if self._bidang_key is not None else 0
        if i < 0:                                   # bidang hilang (mis. paket diganti): kembali ke semua bidang
            self._bidang_key, i = None, 0
        self.bidang.setCurrentIndex(i)
        self.bidang.setEnabled(bool(groups))
        self._isi_bidang_jalan = False

    def _select(self, i):
        """Pilih lembar ke-i antrean (urutan lembar, tanpa baris judul bidang) dan buka lembarnya."""
        if 0 <= i < len(self._baris):
            self.queue.setCurrentRow(self._baris[i], QItemSelectionModel.ClearAndSelect)

    def set_query(self, text):
        self._query = text.strip().lower()
        self.refresh()

    @staticmethod
    def _hitung(views):
        counts = {f: 0 for f in FILTERS}
        counts["Semua"] = len(views)
        for v in views:
            counts[v.status] = counts.get(v.status, 0) + 1
        return counts

    def _urut(self, rows):
        key = self.sort.currentData()
        if key == "nilai":
            rows.sort(key=lambda v: (v.skor is None, -(v.skor.nilai if v.skor else 0), v.row["urutan"]))
        elif key == "kode":
            rows.sort(key=lambda v: (v.row["kode"] or "~", v.row["urutan"]))
        return rows

    def refresh(self):
        if self.event_id is None:
            self.queue.clear()
            self._order, self._baris = [], []
            return
        views = SV.event_views(self.db, self.event_id)
        groups = SV.kelompok_bidang(self.db, self.event_id, views)
        self._isi_bidang(groups, len(views))
        sel = next((g for g in groups if str(g["key"]) == self._bidang_key), None) if self._bidang_key is not None else None
        pilih = views if sel is None else sel["views"]          # lembar bidang terpilih
        # judul event & sidebar: seluruh event; kartu hitung & antrean: bidang terpilih
        self.summary.emit(dict(self._hitung(views),
                               tanpa_nilai=sum(1 for v in views if v.status != "Gagal" and v.skor is None)))
        counts = self._hitung(pilih)
        if self._filter is None:
            self._filter = next((f for f in ("Perlu cek", "Gagal") if counts[f]), "Semua")
        for f, card in self.cards.items():
            card.set(counts[f])
        self.cards[self._filter].setChecked(True)
        self.stack.setCurrentWidget(self.desk if views else self.empty)

        rows = [v for v in pilih if self._filter == "Semua" or v.status == self._filter]
        if self._query:
            rows = [v for v in rows if self._query in " ".join(
                str(x) for x in (v.row["nama"], v.row["nomor"], v.row["kode"], Path(v.row["file"]).name,
                                 SV.server_info(v.row).get("kota", ""))).lower()]
        self.q_title.setText(("Semua lembar" if self._filter == "Semua" else self._filter) +
                             (f" · {len(rows)} cocok" if self._query else ""))
        # Semua bidang: dikelompokkan per bidang (judul + lembarnya); satu bidang: daftar biasa
        if sel is None and groups:
            masuk = {v.row["id"] for v in rows}
            urutan = []
            for g in groups:
                gv = self._urut([v for v in g["views"] if v.row["id"] in masuk])
                if gv:
                    urutan.append((g, gv))
        else:
            urutan = [(None, self._urut(rows))]

        cur = self.review.cur["id"] if self.review.cur is not None else None
        self.queue.blockSignals(True)
        self.queue.clear()
        self._order, self._baris = [], []
        for g, gv in urutan:
            if g is not None:
                judul = "Tanpa bidang (gagal dibaca / kode tak terdaftar)" if g["key"] == SV.BELUM else (
                    g["nama"] + (f" · {ringkas_kode(g['kode'])}" if g["kode"] else ""))
                hd = QListWidgetItem()
                hd.setFlags(Qt.NoItemFlags)                     # judul: tidak bisa dipilih / dibuka
                hd.setData(DATA, {"header": True, "judul": judul, "info": f"{len(gv)} lembar"})
                self.queue.addItem(hd)
            for v in gv:
                self._tambah_baris(v, cur)
        self.queue.blockSignals(False)
        kosong = KOSONG[self._filter]
        if sel is not None and not sel["views"]:
            kosong = "Belum ada lembar untuk bidang ini."
        self.q_empty.setText(f"Tidak ada lembar yang cocok dengan “{self._query}”." if self._query and not rows
                             else kosong)
        self.q_stack.setCurrentWidget(self.queue if rows else self.q_empty)
        self.review.refresh_list()
        self._update_position()

    def _tambah_baris(self, v, cur):
        """Satu baris lembar di antrean (dicatat di _order & _baris untuk navigasi)."""
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
        self._baris.append(self.queue.count() - 1)
        if r["id"] == cur:
            self.queue.setCurrentItem(it, QItemSelectionModel.ClearAndSelect)

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
        if lid is None:                     # baris judul bidang
            return
        if self.review.cur is None or self.review.cur["id"] != lid:
            self.review.show_lembar(lid)

    def _review_shown(self, lembar_id):
        i = self._pos(lembar_id)
        self.queue.blockSignals(True)
        if i:
            # klik di antrean sendiri: pilihan (Ctrl/Shift+klik) dan posisi gulir diurus Qt; menggulir di tengah
            # klik membuat pilihan jatuh ke baris lain. Hanya perpindahan dari luar antrean (tombol, simpan
            # lalu lanjut) yang memilih dan menggulir ke lembarnya.
            row = self._baris[i - 1]
            if self.queue.currentRow() != row:
                self.queue.setCurrentRow(row, QItemSelectionModel.ClearAndSelect)
                self.queue.scrollToItem(self.queue.item(row))
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
        return [it.data(Qt.UserRole) for it in self.queue.selectedItems() if it.data(Qt.UserRole) is not None]

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._atur_meja()

    def set_lebar(self, lebar):
        """Lebar yang tersedia dari jendela (halaman ada di area gulir, jadi tab ini tidak pernah lebih sempit dari
        ukuran minimumnya sendiri; keputusan susunan memakai lebar yang benar-benar terlihat)."""
        self._lebar = lebar
        self._atur_meja()

    def _atur_meja(self):
        lebar = min(self.width(), getattr(self, "_lebar", self.width()))
        tegak = lebar < MEJA_TEGAK
        if tegak != (self.desk.orientation() == Qt.Vertical):
            self.desk.setOrientation(Qt.Vertical if tegak else Qt.Horizontal)
            self.desk.setSizes([220, 600] if tegak else [320, 900])
            # antrean di atas panel cek: panel cek tetap cukup tinggi untuk gambar + data (halaman yang bergulir
            # bila jendela pendek), jangan dijepit sampai datanya hanya terlihat sejengkal
            self.review.set_di_bawah(tegak)
            self.queue.setMinimumHeight(150 if tegak else 0)

    # ---- tambah & proses
    def _pastikan_paket(self):
        """Sebelum memindai foto, event wajib sudah memakai paket kunci jawaban. Bila belum, panitia diminta
        memilih paket dulu; False bila batal (foto tidak ditambahkan)."""
        if self.event_id is None or self.busy():
            return False
        if self.db.event_paket(self.event_id) is not None:
            return True
        r = pilih_paket(self, self.db, self.event_id,
                        "Sebelum memindai, pilih dulu paket kunci jawaban yang dipakai event ini.")
        if r == "buka":
            self.buka_kunci.emit()
        if r != "dipilih":
            return False
        self.paket_dipilih.emit()
        self.refresh()
        return True

    @staticmethod
    def _foto_dalam(folder):
        """Semua foto LJK di folder ini dan semua sub-foldernya (mis. satu sub-folder per bidang)."""
        return [p for p in Path(folder).rglob("*") if p.is_file() and p.suffix.lower() in EXTS]

    def _add_folder(self):
        if not self._pastikan_paket():
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder foto LJK (sub-folder ikut dibaca)")
        if not folder:
            return
        folder = Path(folder)
        paths = self._foto_dalam(folder)
        if not paths:
            QMessageBox.information(self, "Tambah foto", "Tidak ada foto LJK (jpg, png, bmp, tif) di folder itu "
                                                         "maupun di sub-foldernya.")
            return
        per = {}
        for p in paths:
            per[p.parent] = per.get(p.parent, 0) + 1
        if any(d != folder for d in per):            # ada foto di sub-folder: tunjukkan ringkasannya dulu
            def nama(d):
                return "(folder ini)" if d == folder else str(d.relative_to(folder))
            baris = [f"•  {nama(d)}: {n} foto" for d, n in sorted(per.items(), key=lambda kv: str(kv[0]).casefold())]
            if len(baris) > 25:
                baris = baris[:25] + [f"•  … dan {len(per) - 25} folder lain"]
            if QMessageBox.question(
                    self, "Tambah foto",
                    f"Ditemukan {len(paths)} foto di {len(per)} folder:\n\n" + "\n".join(baris) +
                    "\n\nBidang tiap lembar tetap ditentukan dari kode naskah di LJK. Foto yang sudah ada di event "
                    "ini dilewati.\n\nProses semuanya?") != QMessageBox.Yes:
                return
        self._start(paths)

    def _add_files(self):
        if not self._pastikan_paket():
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Foto LJK", "", "Gambar (*.jpg *.jpeg *.png *.bmp *.tif *.tiff)")
        if files:
            self._start([Path(f) for f in files])

    def _start(self, paths, urutan=None, srv=None, hilang=()):
        if self.event_id is None or self.busy():
            return
        if urutan is None:
            have = self.db.files(self.event_id)
            # urut per folder lalu nama file: foto dari sub-folder yang sama berurutan nomornya
            new = sorted((p for p in paths if str(p) not in have),
                         key=lambda p: (str(p.parent).casefold(), p.name.casefold()))
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
        self._run(items, hilang)

    def _run(self, items, hilang=()):
        self._pulled = []
        self._hilang = list(hilang)
        # hasil scan selalu masuk ke event tempat scan dimulai, walau panitia membuka event lain selama proses
        self._run_event = self.event_id
        self._run_nama = self.db.event(self.event_id)["nama"]
        self.worker = Worker(items, self._out_dir(), self._kontras())
        self.worker.one.connect(self._one_done)
        self.worker.progress.connect(self._progress)
        self.worker.finished.connect(self._finished)
        self._set_running(True)
        self.worker.start()

    def _one_done(self, urutan, rec):
        if rec.get("unduh_gagal"):
            return                      # tidak disimpan; dicoba lagi pada sinkron berikutnya
        if rec.get("error") and not Path(rec["file"]).exists():
            # foto asli hilang (dipindah / flashdisk dicabut): hasil baca lama tidak ditimpa "Gagal"
            self._hilang.append(Path(rec["file"]).name)
            return
        if rec.get("server_id"):
            self._pulled.append(rec["server_id"])
        self.db.add_lembar(self._run_event, urutan, rec)
        self._pending += 1
        if self._pending >= 5:
            self._pending = 0
            if self.event_id == self._run_event:
                self.refresh()

    def _progress(self, done, total, name):
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        lain = "" if self.event_id == self._run_event else f"&nbsp;&nbsp;·&nbsp;&nbsp;event {html.escape(self._run_nama)}"
        self.progress_label.setText(f"<b>Membaca {done}/{total}</b>&nbsp;&nbsp;{html.escape(name)}{lain}")

    def _finished(self):
        self._set_running(False)
        self._pending = 0
        self.refresh()
        self.review.activate()          # lembar yang tampil mungkin baru saja dibaca ulang
        self._lapor_hilang()
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
        if not self._boleh_baca_ulang(ids):
            return
        rows = [self.db.lembar_by_id(i) for i in ids]
        if any(r["dicek"] for r in rows) and QMessageBox.question(
                self, "Proses ulang", "Sebagian lembar sudah dicek manual. Hasil cek akan hilang. Lanjutkan?"
        ) != QMessageBox.Yes:
            return
        self._reread(rows)

    def _reread(self, rows):
        """Baca ulang lembar yang sudah ada (urutan & data server tetap). Lembar yang foto aslinya sudah tidak ada
        dilewati: hasil bacanya tetap, tidak berubah menjadi "Gagal"."""
        ada = [r for r in rows if Path(r["file"]).exists()]
        hilang = [Path(r["file"]).name for r in rows if not Path(r["file"]).exists()]
        if not ada:
            self._hilang = hilang
            self._lapor_hilang()
            return
        srv = [{"server_id": r["server_id"], "server": SV.server_info(r)} if r["server_id"] else None for r in ada]
        self._start([Path(r["file"]) for r in ada], urutan=[r["urutan"] for r in ada], srv=srv, hilang=hilang)

    def _lapor_hilang(self):
        if not self._hilang:
            return
        n = len(self._hilang)
        contoh = ", ".join(self._hilang[:5]) + (f", dan {n - 5} lainnya" if n > 5 else "")
        QMessageBox.warning(self, "Foto asli tidak ditemukan",
                            f"{n} foto asli tidak ditemukan lagi (mungkin dipindah, diganti nama, atau flashdisk-nya "
                            f"dicabut), jadi tidak dibaca:\n{contoh}\n\nHasil baca lembar itu yang sudah ada tidak diubah.")
        self._hilang = []

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
        # lembar lama (sebelum folder per nomor urut) bisa berbagi folder gambar dengan foto bernama sama
        dipakai = {Path(r["gambar"]).parent for r in self.db.lembar(self.event_id) if r["gambar"] and r["id"] not in ids}
        for i in ids:
            r = self.db.lembar_by_id(i)
            if r and r["gambar"] and Path(r["gambar"]).parent not in dipakai:
                d = Path(r["gambar"]).parent
                shutil.rmtree(d, ignore_errors=True)
                if d.parent != self._out_dir() and d.parent.is_dir() and not any(d.parent.iterdir()):
                    d.parent.rmdir()            # folder nomor urut yang kini kosong
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
        if nokode + gagal == len(views):
            sebab = ("event ini belum memakai paket kunci jawaban, atau paketnya belum berisi kode naskah "
                     "(tab Kunci jawaban)" if not self.db.naskah(self.event_id)
                     else "semua lembar gagal dibaca atau kode naskahnya belum terdaftar di kunci")
            QMessageBox.information(self, "Ekspor", f"Belum ada lembar yang bisa diekspor: {sebab}.")
            return
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
        # tulis ke file sementara dulu, baru menggantikan file tujuan: bila gagal, Daftar Nilai lama tetap utuh
        tmp = Path(path).with_name(f"~{Path(path).stem}.ekspor.xlsx")
        try:
            n, _skipped = SV.export_event(self.db, self.event_id, str(tmp))
            os.replace(tmp, path)
        except PermissionError:
            tmp.unlink(missing_ok=True)
            QMessageBox.warning(self, "Ekspor", "File tidak bisa ditulis. Tutup dulu file itu di Excel.")
            return
        except Exception as e:  # noqa: BLE001  ekspor gagal karena hal lain: beri tahu, file lama tidak disentuh
            tmp.unlink(missing_ok=True)
            QMessageBox.warning(self, "Ekspor", f"Ekspor gagal, file lama tidak diubah.\n\n{e}")
            return
        if QMessageBox.question(self, "Ekspor", f"{n} lembar tersimpan di:\n{path}\n\nBuka file sekarang?") \
                == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
