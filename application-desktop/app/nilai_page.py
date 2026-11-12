"""Menu Nilai hasil: nilai peserta per event & mata pelajaran (susunan seperti aplikasi LJK lama).

Kiri atas daftar event, kanan atas mata pelajaran event terpilih (semua mata pelajaran paketnya, plus
"Belum dinilai" untuk lembar gagal / kode naskah tak terdaftar), bawah tabel peserta mata pelajaran terpilih.
Nilai memakai kunci yang dibekukan saat lembar di-scan (lembar.soal_beku); "Hitung ulang" sengaja menggantinya
dengan kunci paket terbaru. Cetak nilai = perbandingan jawaban peserta terpilih dengan kunci (pratinjau ->
printer / PDF), Ekspor Excel = format Daftar Nilai yang sudah ada."""
import html
import json
import os
from collections import Counter
from pathlib import Path

from PySide6.QtCore import QMarginsF, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHeaderView, QLabel, QMenu, QMessageBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget)

from app import theme
from app.colors import paint
from app.paket_page import ringkas_kode
from app.widgets import setup_table, toolbar
from ljk import export as EX
from ljk import service as SV

STATUS_TONE = {"OK": "ok", "Perlu cek": "warn", "Sudah dicek": "info", "Gagal": "error", "Belum dinilai": "error"}
SORT = Qt.UserRole + 5
BELUM = "belum"
BIRU, MERAH = "#1d3fcf", "#d01f1f"          # cetak nilai: jawaban benar / salah & kosong
PER_BARIS = 15                              # nomor per baris di cetak nilai


def angka(x):
    """2 desimal dengan koma (seperti cetakan aplikasi lama): -2,00."""
    return f"{x:.2f}".replace(".", ",")


class Item(QTableWidgetItem):
    """Sel tabel yang bisa diurutkan menurut kunci urut (angka tetap urut sebagai angka; kosong di akhir)."""

    def __init__(self, text, key=None, align=None, tip=None):
        super().__init__(text)
        self.setFlags(self.flags() & ~Qt.ItemIsEditable)
        self.setData(SORT, (0, key) if key is not None else (1, text))
        if align is not None:
            self.setTextAlignment(align)
        if tip:
            self.setToolTip(tip)

    def __lt__(self, other):
        a, b = self.data(SORT), other.data(SORT)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


def _label(text, role="h3"):
    lb = QLabel(text)
    lb.setProperty("role", role)
    return lb


class NilaiPage(QWidget):
    buka_lembar = Signal(int, int)      # (event_id, lembar_id): buka lembar di panel cek Scan & nilai
    changed = Signal()                  # kunci beku lembar diganti (hitung ulang)

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.event_id = None
        self._groups = []
        self._group = None
        self._keep_group = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 16, 0, 0)
        v.setSpacing(12)

        bar = toolbar(8)
        self.b_cetak = theme.button("Cetak nilai", "file-text", "primary",
                                    "Bandingkan jawaban peserta terpilih dengan kunci (pratinjau, printer, PDF)",
                                    self._cetak)
        self.b_ekspor = theme.button("Ekspor Excel", "download", tip="Simpan Daftar Nilai ke Excel", slot=self._ekspor)
        self.chk_semua = QCheckBox("Semua pelajaran dalam 1 file")
        self.chk_semua.setToolTip("Ekspor Excel: satu sheet per mata pelajaran untuk seluruh event")
        self.b_hitung = theme.button("Hitung ulang", "refresh", tip="Ganti kunci beku lembar dengan kunci paket terbaru")
        menu = QMenu(self.b_hitung)
        self.act_hitung_mapel = menu.addAction("Hitung ulang mata pelajaran ini dengan kunci terbaru",
                                               lambda: self._hitung_ulang(False))
        self.act_hitung_event = menu.addAction("Hitung ulang semua lembar event ini dengan kunci terbaru",
                                               lambda: self._hitung_ulang(True))
        self.b_hitung.setMenu(menu)
        for w in (self.b_cetak, self.b_ekspor, self.chk_semua):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.b_hitung)
        v.addLayout(bar)

        # ---- atas: event | mata pelajaran
        self.t_event = QTableWidget(0, 4)
        self.t_event.setHorizontalHeaderLabels(["Event", "Tanggal", "Paket kunci", "Lembar"])
        setup_table(self.t_event, 34)
        self.t_event.setSelectionMode(QTableWidget.SingleSelection)
        h = self.t_event.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.t_event.itemSelectionChanged.connect(self._event_selected)

        self.t_mapel = QTableWidget(0, 5)
        self.t_mapel.setHorizontalHeaderLabels(["Mata pelajaran", "Kode naskah", "Soal", "Peserta", "Rata-rata"])
        setup_table(self.t_mapel, 34)
        self.t_mapel.setSelectionMode(QTableWidget.SingleSelection)
        h = self.t_mapel.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3, 4):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.t_mapel.itemSelectionChanged.connect(self._mapel_selected)

        def box(title, table):
            w = QWidget()
            bv = QVBoxLayout(w)
            bv.setContentsMargins(0, 0, 0, 0)
            bv.setSpacing(8)
            bv.addWidget(_label(title))
            bv.addWidget(table, 1)
            return w

        top = QSplitter(Qt.Horizontal)
        top.setChildrenCollapsible(False)
        top.addWidget(box("Event", self.t_event))
        top.addWidget(box("Mata pelajaran", self.t_mapel))
        top.setSizes([520, 620])

        # ---- bawah: peserta
        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(8)
        head = toolbar(8)
        self.p_title = _label("Peserta")
        self.p_info = _label("", "muted")
        head.addWidget(self.p_title)
        head.addWidget(self.p_info)
        head.addStretch()
        hint = _label("Ctrl/Shift+klik: pilih beberapa peserta  ·  klik dua kali: buka lembar di panel cek", "muted")
        head.addWidget(hint)
        bv.addLayout(head)
        cols = ["No", "Tgl. periksa", "Nomor peserta", "Nama peserta", "Nilai", "B", "S", "K", "Kode naskah",
                "Status", "Jawaban", "Kunci"]
        self.t_peserta = QTableWidget(0, len(cols))
        self.t_peserta.setHorizontalHeaderLabels(cols)
        setup_table(self.t_peserta, 32, pill=True)
        self.t_peserta.setSelectionMode(QTableWidget.ExtendedSelection)
        self.t_peserta.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        h = self.t_peserta.horizontalHeader()
        for c in range(len(cols)):
            h.setSectionResizeMode(c, QHeaderView.Interactive)
        for c, wdt in enumerate((52, 150, 120, 230, 70, 44, 44, 44, 100, 150, 420, 420)):
            self.t_peserta.setColumnWidth(c, wdt)
        h.setStretchLastSection(True)
        self.t_peserta.setSortingEnabled(True)
        self.t_peserta.cellDoubleClicked.connect(self._double_click)
        mono = theme.mono(9)
        self._mono = mono
        bv.addWidget(self.t_peserta, 1)

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(top)
        split.addWidget(bottom)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        split.setSizes([250, 560])
        v.addWidget(split, 1)

    # ---- data
    def summary(self):
        n = len(self.db.events())
        return (f"{n} event &nbsp;·&nbsp; nilai memakai kunci saat lembar di-scan "
                "(Hitung ulang untuk memakai kunci paket terbaru)")

    def reload(self, select=None):
        """Muat ulang daftar event; pilih event `select` (bila ada) atau tetap event terpilih."""
        keep = select if select is not None else self.event_id
        if keep == self.event_id and self._group is not None:
            self._keep_group = self._group["key"]
        self.t_event.blockSignals(True)
        self.t_event.setRowCount(0)
        row = 0
        for i, ev in enumerate(self.db.events()):
            self.t_event.insertRow(i)
            paket = self.db.event_paket(ev["id"])
            if paket is not None:
                pk = paket["nama"]
            else:
                pk = "kunci lama" if self.db.naskah_lama(ev["id"]) else "—"
            n = len(self.db.lembar(ev["id"]))
            it = Item(ev["nama"], tip=ev["nama"])
            it.setData(Qt.UserRole, ev["id"])
            self.t_event.setItem(i, 0, it)
            self.t_event.setItem(i, 1, Item(ev["tanggal"]))
            self.t_event.setItem(i, 2, Item(pk, tip=pk))
            self.t_event.setItem(i, 3, Item(str(n), n, Qt.AlignCenter))
            if ev["id"] == keep:
                row = i
        if self.t_event.rowCount():
            self.t_event.selectRow(row)
            self.t_event.scrollTo(self.t_event.model().index(row, 0))
        self.t_event.blockSignals(False)
        self._event_selected()

    def _event_selected(self):
        rows = self.t_event.selectionModel().selectedRows()
        it = self.t_event.item(rows[0].row(), 0) if rows else None
        eid = it.data(Qt.UserRole) if it is not None else None
        if eid != self.event_id:
            self._keep_group = None
        self.event_id = eid
        self._groups = self._build_groups(eid) if eid is not None else []
        keep = self._keep_group
        self._keep_group = None
        self.t_mapel.blockSignals(True)
        self.t_mapel.setRowCount(0)
        row = next((i for i, g in enumerate(self._groups) if g["key"] == keep), None) if keep is not None else None
        if row is None:                                     # mata pelajaran pertama yang sudah ada pesertanya
            row = next((i for i, g in enumerate(self._groups) if g["views"] and g["key"] != BELUM), 0)
        for i, g in enumerate(self._groups):
            self.t_mapel.insertRow(i)
            nilai = [x.skor.nilai for x in g["views"] if x.skor is not None]
            belum = g["key"] == BELUM
            ni = Item(g["nama"], tip=g["nama"])
            if belum:
                paint(ni, "error")
            self.t_mapel.setItem(i, 0, ni)
            kode = Item(ringkas_kode(g["kode"]) or "—", tip=", ".join(g["kode"]))
            kode.setFont(self._mono)
            self.t_mapel.setItem(i, 1, kode)
            self.t_mapel.setItem(i, 2, Item(str(g["jumlah"]) if g["jumlah"] else "", g["jumlah"] or None, Qt.AlignCenter))
            self.t_mapel.setItem(i, 3, Item(str(len(g["views"])), len(g["views"]), Qt.AlignCenter))
            rata = angka(sum(nilai) / len(nilai)) if nilai and not belum else "—"
            self.t_mapel.setItem(i, 4, Item(rata, align=Qt.AlignRight | Qt.AlignVCenter))
        if self._groups:
            self.t_mapel.selectRow(row)
            self.t_mapel.scrollTo(self.t_mapel.model().index(row, 0))
        self.t_mapel.blockSignals(False)
        for w in (self.b_cetak, self.b_ekspor, self.b_hitung, self.chk_semua):
            w.setEnabled(eid is not None)
        self._mapel_selected()

    def _build_groups(self, eid):
        """Mata pelajaran event (semua mata pelajaran paketnya) beserta lembarnya, plus kelompok Belum dinilai."""
        views = SV.event_views(self.db, eid)
        paket = self.db.event_paket(eid)
        groups, kode2g = [], {}
        if paket is not None:
            for m in self.db.mapel(paket["id"]):
                g = {"key": ("m", m["id"]), "nama": m["nama"], "kode": list(m["kode"]), "jumlah": len(m["kunci"]),
                     "views": []}
                groups.append(g)
                for k in m["kode"]:
                    kode2g[k] = g
        else:                                               # event lama: kunci per event, dikelompokkan per bidang
            by = {}
            for s in self.db.naskah_lama(eid):
                g = by.get(s.bidang.casefold())
                if g is None:
                    g = by[s.bidang.casefold()] = {"key": ("b", s.bidang.casefold()), "nama": s.bidang, "kode": [],
                                                   "jumlah": s.jumlah, "views": []}
                    groups.append(g)
                g["kode"].append(s.kode)
                kode2g[s.kode] = g
        belum = {"key": BELUM, "nama": "Belum dinilai", "kode": [], "jumlah": 0, "views": []}
        for v in views:
            if v.skor is None:
                belum["views"].append(v)
                continue
            g = kode2g.get(v.row["kode"])
            if g is None:                                   # kode sudah tidak ada di paket, tapi punya kunci beku
                nama = v.soal.bidang
                g = next((x for x in groups if x["nama"].casefold() == nama.casefold()), None)
                if g is None:
                    g = {"key": ("x", nama.casefold()), "nama": nama, "kode": [], "jumlah": v.soal.jumlah, "views": []}
                    groups.append(g)
                if v.row["kode"] not in g["kode"]:
                    g["kode"].append(v.row["kode"])
            g["views"].append(v)
        if belum["views"]:
            groups.append(belum)
        return groups

    def _mapel_selected(self):
        rows = self.t_mapel.selectionModel().selectedRows()
        self._group = self._groups[rows[0].row()] if rows and rows[0].row() < len(self._groups) else None
        self._fill_peserta()

    def _fill_peserta(self):
        g = self._group
        t = self.t_peserta
        t.setSortingEnabled(False)
        t.setRowCount(0)
        if g is None:
            self.p_title.setText("Peserta")
            self.p_info.setText("")
            t.setSortingEnabled(True)
            return
        self.p_title.setText(f"Peserta · {g['nama']}")
        st = Counter(v.status for v in g["views"])
        lama = sum(1 for v in g["views"] if v.kunci_lama)
        info = [f"{len(g['views'])} lembar"]
        if st.get("Perlu cek"):
            info.append(f"{st['Perlu cek']} perlu cek (nilai sementara)")
        if lama:
            info.append(f"{lama} memakai kunci lama")
        self.p_info.setText(" · ".join(info))
        for i, v in enumerate(sorted(g["views"], key=lambda x: x.row["urutan"])):
            r, sk, s = v.row, v.skor, v.soal
            t.insertRow(i)
            no = Item(str(r["urutan"]), r["urutan"], Qt.AlignCenter)
            no.setData(Qt.UserRole, r["id"])
            t.setItem(i, 0, no)
            tgl = (r["dipindai"] or "") if "dipindai" in r.keys() else ""
            t.setItem(i, 1, Item(tgl or "—", tgl or None))
            nomor = Item(r["nomor"])
            nomor.setFont(self._mono)
            t.setItem(i, 2, nomor)
            t.setItem(i, 3, Item(r["nama"] or ("Gagal dibaca" if r["error"] else "Nama tidak terbaca"), tip=r["nama"]))
            if sk is not None:
                t.setItem(i, 4, Item(angka(sk.nilai), sk.nilai, Qt.AlignRight | Qt.AlignVCenter))
                for c, n in ((5, sk.benar), (6, sk.salah), (7, sk.kosong)):
                    t.setItem(i, c, Item(str(n), n, Qt.AlignCenter))
            else:
                for c in range(4, 8):
                    t.setItem(i, c, Item(""))
            kd = Item(r["kode"])
            kd.setFont(self._mono)
            t.setItem(i, 8, kd)
            status = v.status if sk is not None or v.status == "Gagal" else "Belum dinilai"
            teks = status + (" · kunci lama" if v.kunci_lama else "")
            sit = Item(teks, tip="\n".join(x["text"] for x in v.issues) or None)
            paint(sit, STATUS_TONE.get(status, "neutral"))
            t.setItem(i, 9, sit)
            jawab = json.loads(r["jawaban"] or "[]")
            n = s.jumlah if s is not None else 0
            ja = Item(",".join(jawab[:n]) if n else "")
            ja.setFont(self._mono)
            t.setItem(i, 10, ja)
            ku = Item(",".join(s.kunci) if s is not None else "")
            ku.setFont(self._mono)
            t.setItem(i, 11, ku)
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.AscendingOrder)

    def _view_of(self, lembar_id):
        return next((v for v in (self._group["views"] if self._group else []) if v.row["id"] == lembar_id), None)

    def _table_views(self, selected_only):
        """Lembar di tabel peserta menurut urutan tampil (mengikuti urutan kolom yang dipilih)."""
        rows = sorted({i.row() for i in self.t_peserta.selectedIndexes()}) if selected_only else \
            range(self.t_peserta.rowCount())
        out = []
        for r in rows:
            it = self.t_peserta.item(r, 0)
            v = self._view_of(it.data(Qt.UserRole)) if it is not None else None
            if v is not None:
                out.append(v)
        return out

    def _double_click(self, r, _c):
        it = self.t_peserta.item(r, 0)
        if it is not None and self.event_id is not None:
            self.buka_lembar.emit(self.event_id, it.data(Qt.UserRole))

    # ---- hitung ulang
    def _hitung_ulang(self, semua):
        if self.event_id is None:
            return
        ev = self.db.event(self.event_id)
        if semua:
            views = [v for g in self._groups for v in g["views"]]
            kodes, nama = None, f"semua lembar event {ev['nama']}"
        else:
            g = self._group
            if g is None:
                QMessageBox.information(self, "Hitung ulang", "Pilih dulu mata pelajarannya.")
                return
            views = g["views"]
            kodes = set(g["kode"]) | {v.row["kode"] for v in views}
            nama = f"{len(views)} lembar {g['nama']}"
        lama = sum(1 for v in views if v.kunci_lama)
        if QMessageBox.question(
                self, "Hitung ulang",
                f"Hitung ulang {nama} dengan kunci terbaru di paket?\n\n"
                f"{lama} lembar saat ini memakai kunci yang berbeda dari paket. Nilai lembar yang kuncinya berubah "
                "akan ikut berubah (juga di Scan & nilai dan Ekspor).") != QMessageBox.Yes:
            return
        n = self.db.hitung_ulang(self.event_id, kodes)
        self.reload()
        self.changed.emit()
        QMessageBox.information(self, "Hitung ulang",
                                f"Kunci {n} lembar diganti dengan kunci terbaru." if n else
                                "Semua lembar sudah memakai kunci terbaru; tidak ada nilai yang berubah.")

    # ---- ekspor Excel
    def _ekspor(self):
        if self.event_id is None:
            return
        ev = self.db.event(self.event_id)
        if self.chk_semua.isChecked():
            groups = [g for g in self._groups if g["key"] != BELUM and g["views"]]
            default = f"{ev['nama']} Daftar Nilai.xlsx"
        else:
            g = self._group
            if g is None or g["key"] == BELUM or not g["views"]:
                QMessageBox.information(self, "Ekspor Excel", "Pilih mata pelajaran yang sudah ada pesertanya, atau "
                                                              "centang 'Semua pelajaran dalam 1 file'.")
                return
            groups = [g]
            default = f"{ev['nama']} - {g['nama']} Daftar Nilai.xlsx"
        if not groups:
            QMessageBox.information(self, "Ekspor Excel", "Belum ada lembar yang dinilai di event ini.")
            return
        cek = sum(1 for g in groups for v in g["views"] if v.status == "Perlu cek")
        if cek and QMessageBox.question(self, "Ekspor Excel",
                                        f"{cek} lembar masih perlu cek; nilainya memakai hasil baca/tebakan sementara."
                                        "\n\nTetap ekspor sekarang?") != QMessageBox.Yes:
            return
        safe = "".join(ch for ch in default if ch not in '<>:"/\\|?*')
        path, _ = QFileDialog.getSaveFileName(self, "Simpan Daftar Nilai", str(Path.home() / "Documents" / safe),
                                              "Excel (*.xlsx)")
        if not path:
            return
        data = [(g["nama"], [(v.row["nomor"], v.row["nama"], v.skor)
                             for v in sorted(g["views"], key=lambda x: x.row["urutan"])]) for g in groups]
        tmp = Path(path).with_name(f"~{Path(path).stem}.ekspor.xlsx")
        try:
            EX.daftar_nilai(str(tmp), ev["nama"], ev["tanggal"], data)
            os.replace(tmp, path)
        except PermissionError:
            tmp.unlink(missing_ok=True)
            QMessageBox.warning(self, "Ekspor Excel", "File tidak bisa ditulis. Tutup dulu file itu di Excel.")
            return
        except Exception as e:  # noqa: BLE001  file lama tidak disentuh
            tmp.unlink(missing_ok=True)
            QMessageBox.warning(self, "Ekspor Excel", f"Ekspor gagal, file lama tidak diubah.\n\n{e}")
            return
        n = sum(len(x[1]) for x in data)
        if QMessageBox.question(self, "Ekspor Excel", f"{n} lembar tersimpan di:\n{path}\n\nBuka file sekarang?") \
                == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ---- cetak nilai
    def _cetak(self):
        g = self._group
        if self.event_id is None or g is None or g["key"] == BELUM:
            QMessageBox.information(self, "Cetak nilai", "Pilih dulu mata pelajaran yang sudah dinilai.")
            return
        views = [v for v in self._table_views(True) if v.skor is not None]
        if not views:
            semua = [v for v in self._table_views(False) if v.skor is not None]
            if not semua:
                QMessageBox.information(self, "Cetak nilai", "Belum ada peserta yang dinilai di mata pelajaran ini.")
                return
            if QMessageBox.question(self, "Cetak nilai",
                                    f"Belum ada peserta yang dipilih. Cetak semua {len(semua)} peserta {g['nama']}?") \
                    != QMessageBox.Yes:
                return
            views = semua
        ev = self.db.event(self.event_id)
        doc = QTextDocument()
        doc.setDefaultFont(QFont("Arial", 10))
        doc.setHtml(cetak_html(ev, g["nama"], views))
        printer = _printer()
        dlg = QPrintPreviewDialog(printer, self)
        dlg.setWindowTitle(f"Cetak nilai · {g['nama']}")
        dlg.paintRequested.connect(lambda p: doc.print_(p))
        tb = dlg.findChild(QToolBar)
        if tb is not None:
            tb.addSeparator()
            act = tb.addAction("Simpan PDF")
            act.setToolTip("Simpan hasil cetak sebagai file PDF")
            name = "".join(ch for ch in f"{ev['nama']} - {g['nama']} Cetak Nilai.pdf" if ch not in '<>:"/\\|?*')
            act.triggered.connect(lambda: self._simpan_pdf(dlg, doc, name))
        dlg.resize(1000, 820)
        dlg.exec()

    def _simpan_pdf(self, parent, doc, name):
        path, _ = QFileDialog.getSaveFileName(parent, "Simpan PDF", str(Path.home() / "Documents" / name), "PDF (*.pdf)")
        if not path:
            return
        p = _printer()
        p.setOutputFormat(QPrinter.PdfFormat)
        p.setOutputFileName(path)
        doc.print_(p)
        if QMessageBox.question(parent, "Simpan PDF", f"PDF tersimpan di:\n{path}\n\nBuka file sekarang?") \
                == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def _printer():
    """A4 mendatar seperti cetakan aplikasi lama (15 nomor per baris muat lega); bisa diganti di pratinjau."""
    p = QPrinter(QPrinter.HighResolution)
    p.setPageSize(QPageSize(QPageSize.A4))
    p.setPageOrientation(QPageLayout.Landscape)
    p.setPageMargins(QMarginsF(14, 14, 14, 14), QPageLayout.Millimeter)
    return p


CELL = f"width='{100 / PER_BARIS:.2f}%' style='white-space:nowrap'"     # sel nomor: lebar tetap, tidak terpotong


def _grid_kunci(kunci):
    """Kunci 1..N dalam baris berisi 15 nomor: '1. B   2. D ...'."""
    rows = []
    for s in range(0, len(kunci), PER_BARIS):
        cells = "".join(f"<td {CELL}>{q + 1}.&nbsp;{html.escape(ch)}</td>"
                        for q, ch in enumerate(kunci[s:s + PER_BARIS], s))
        rows.append(f"<tr>{cells}</tr>")
    return f"<table width='100%' cellspacing='0' cellpadding='1'>{''.join(rows)}</table>"


def _grid_jawaban(jawaban, kunci):
    """Jawaban peserta per nomor: biru = benar, merah = salah, '-' merah = kosong ('?' ragu dihitung kosong,
    '*' ganda dihitung salah)."""
    rows = []
    for s in range(0, len(kunci), PER_BARIS):
        cells = []
        for q in range(s, min(s + PER_BARIS, len(kunci))):
            a = jawaban[q] if q < len(jawaban) else ""
            ch, col = (a, BIRU) if a == kunci[q] else ((a or "-"), MERAH)
            cells.append(f"<td {CELL}>{q + 1}.&nbsp;<span style='color:{col}'>"
                         f"{html.escape(ch)}</span></td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table width='100%' cellspacing='0' cellpadding='1'>{''.join(rows)}</table>"


def cetak_html(ev, mapel, views):
    """Isi Cetak nilai: kepala, kotak kunci, lalu tiap peserta (nomor, nama, kode soal, jawaban berwarna, nilai).
    Kunci yang tidak sama untuk semua peserta (sebagian sudah dihitung ulang) dicetak juga per peserta."""
    e = html.escape
    kunci = Counter(v.soal.kunci for v in views).most_common(1)[0][0]
    out = [
        "<div align='center'>"
        "<span style='font-size:17pt; font-weight:bold'>DAFTAR NILAI</span><br>"
        "<span style='font-size:17pt; font-weight:bold'>POSI Indonesia</span><br>"
        f"<span style='font-size:11.5pt; font-weight:bold'>{e(ev['nama'])} - {e(mapel)} ({e(ev['tanggal'])})</span>"
        "</div>",
        "<table width='100%' cellspacing='0' cellpadding='0' style='margin-top:8px'>"
        "<tr><td bgcolor='#000000' style='font-size:3pt'>&nbsp;</td></tr></table>",
        "<table width='100%' border='1' cellspacing='0' cellpadding='8' style='margin-top:14px; "
        "border-color:#000000; border-style:solid'><tr><td>"
        "<table width='100%' cellspacing='0' cellpadding='0'><tr><td width='9%' valign='top' "
        "style='white-space:nowrap'>Kunci&nbsp;:</td>"
        f"<td>{_grid_kunci(kunci)}</td></tr></table></td></tr></table><br>",
    ]
    nw = "style='white-space:nowrap'"
    for i, v in enumerate(views, 1):
        r, sk, s = v.row, v.skor, v.soal
        jawab = json.loads(r["jawaban"] or "[]")
        beda = "" if s.kunci == kunci else (
            f"<tr><td></td><td valign='top' {nw}>Kunci lembar</td><td colspan='3'>"
            f"<span style='font-size:9pt'>{_grid_kunci(s.kunci)}</span></td></tr>")
        out.append(
            "<table width='100%' cellspacing='0' cellpadding='2' style='margin-top:6px'>"
            f"<tr><td width='4%' valign='top' {nw}>{i}.</td><td width='15%' {nw}>Nomor Peserta</td>"
            f"<td width='45%' {nw}>:&nbsp; {e(r['nomor'])}</td><td width='12%' {nw}>Kode Soal</td>"
            f"<td {nw}>:&nbsp; {e(r['kode'])}</td></tr>"
            f"<tr><td></td><td {nw}>Nama Peserta</td><td colspan='3'>:&nbsp; {e(r['nama'])}</td></tr>"
            f"<tr><td></td><td valign='top' {nw}>Jawaban</td><td colspan='3'>{_grid_jawaban(jawab, s.kunci)}</td></tr>"
            f"{beda}"
            f"<tr><td></td><td {nw}>Nilai</td><td colspan='3'>:&nbsp; {angka(sk.nilai)} (Benar = {sk.benar}, "
            f"Salah = {sk.salah}, Kosong = {sk.kosong})</td></tr>"
            "</table><br>")
    return "".join(out)
