"""Pustaka kunci jawaban: paket kunci (mis. "FSN PROVINSI PAKET 1") yang dipakai bersama oleh banyak event.

Susunan seperti aplikasi LJK lama: daftar paket, mata pelajaran paket terpilih, kode naskah mata pelajaran
terpilih (satu mata pelajaran boleh punya beberapa kode; satu kode hanya milik satu mata pelajaran di paket
itu), dan di kanan urutan kunci jawaban 1..N. Setiap tindakan langsung tersimpan; mengubah kunci paket
langsung mengubah nilai semua event yang memakainya (dikonfirmasi dulu bila paket sudah dipakai event).
Juga berisi dialog "pilih paket" yang dipakai tab Kunci jawaban event dan sebelum menambah foto."""
import re
import sqlite3
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QScrollArea, QSplitter,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from app import theme
from app.colors import paint
from app.kunci_dialog import KunciDialog
from app.widgets import EmptyState, ToolbarFit, divider, setup_table, toolbar
from ljk import kunci as KU
from ljk import nilai as NI
from ljk.db import kode_sort, kunci_lengkap

LETTERS = "ABCDE"
MAKS_KODE = 10          # panjang kode naskah (sama dengan batas server)


def ringkas_kode(kode):
    """'285, 286, 287, 290' -> '285–287, 290' (deret angka berurutan diringkas)."""
    ks = sorted(kode, key=kode_sort)
    out, i = [], 0
    while i < len(ks):
        j = i
        while (j + 1 < len(ks) and ks[j].isdigit() and ks[j + 1].isdigit()
               and int(ks[j + 1]) == int(ks[j]) + 1):
            j += 1
        out.append(ks[i] if j - i < 2 else f"{ks[i]}–{ks[j]}")
        if j - i == 1:
            out.append(ks[j])
        i = j + 1
    return ", ".join(out)


def nomor_tanpa_kunci(kunci):
    return [q + 1 for q, ch in enumerate(kunci) if ch not in LETTERS]


def _item(text, align=None, tip=None):
    it = QTableWidgetItem(text)
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if align is not None:
        it.setTextAlignment(align)
    if tip:
        it.setToolTip(tip)
    return it


def kode_lembar(db, event_id):
    """Kode naskah yang terbaca/diketik di lembar event (tanpa yang masih berisi _ atau ?)."""
    out = {}
    for r in db.lembar(event_id):
        k = (r["kode"] or "").strip()
        if k and not any(ch in k for ch in "_?") and not r["error"]:
            out[k] = out.get(k, 0) + 1
    return out


# ------------------------------------------------------------------ urutan kunci (bulatan 1..N)

class KunciView(QWidget):
    """Urutan kunci jawaban seperti LJK: blok 30 nomor, pilihan A-E; kunci terisi bulat penuh.
    Hanya untuk dilihat; klik dua kali = minta edit (diteruskan lewat sinyal)."""
    edit_requested = Signal()
    ROW_H, NO_W, CELL, R = 30, 40, 30, 11
    BLOCK, GAP_X, GAP_Y = 30, 28, 18

    def __init__(self):
        super().__init__()
        self.kunci = ""
        theme.bus.changed.connect(self.update)

    def set_kunci(self, kunci):
        self.kunci = kunci or ""
        self._relayout()
        self.update()

    def _col_w(self):
        return self.NO_W + 5 * self.CELL

    def _cols(self):
        blocks = max(1, -(-len(self.kunci) // self.BLOCK))
        fit = max(1, (self.width() - 8 + self.GAP_X) // (self._col_w() + self.GAP_X))
        return min(blocks, fit)

    def _pos(self, q):
        b, r = divmod(q, self.BLOCK)
        cols = self._cols()
        bx, by = b % cols, b // cols
        x = 4 + bx * (self._col_w() + self.GAP_X)
        y = 4 + by * (self.BLOCK * self.ROW_H + self.GAP_Y) + r * self.ROW_H
        return x, y

    def _relayout(self):
        n = len(self.kunci)
        h = (self._pos(n - 1)[1] + self.ROW_H + 8) if n else 0
        self.setMinimumHeight(h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def sizeHint(self):
        return QSize(self._col_w() + 8, 400)

    def mouseDoubleClickEvent(self, e):
        self.edit_requested.emit()

    def paintEvent(self, _e):
        if not self.kunci:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        base = QFont(self.font())
        bold = QFont(base)
        bold.setWeight(QFont.DemiBold)
        small = QFont(base)
        small.setPointSizeF(base.pointSizeF() * 0.85)
        text, muted, ring = QColor(theme.c("text")), QColor(theme.c("faint")), QColor(theme.c("border_strong"))
        acc, on_acc = QColor(theme.c("accent")), QColor(theme.c("on_accent"))
        warn = QColor(theme.tone_hex("warn")[1])
        for q, ch in enumerate(self.kunci):
            x, y = self._pos(q)
            p.setFont(bold)
            p.setPen(warn if ch not in LETTERS else text)
            p.drawText(QRectF(x, y, self.NO_W - 8, self.ROW_H), Qt.AlignRight | Qt.AlignVCenter, f"{q + 1}.")
            for k, letter in enumerate(LETTERS):
                cx = x + self.NO_W + k * self.CELL + self.CELL / 2
                cy = y + self.ROW_H / 2
                rect = QRectF(cx - self.R, cy - self.R, 2 * self.R, 2 * self.R)
                if letter == ch:
                    p.setPen(Qt.NoPen)
                    p.setBrush(acc)
                    p.drawEllipse(rect)
                    p.setPen(on_acc)
                    p.setFont(bold)
                else:
                    p.setBrush(Qt.NoBrush)
                    p.setPen(ring)
                    p.drawEllipse(rect)
                    p.setPen(muted)
                    p.setFont(small)
                p.drawText(rect, Qt.AlignCenter, letter)
        p.end()


# ------------------------------------------------------------------ dialog pilih paket

class PilihPaketDialog(QDialog):
    """Pilih paket kunci untuk satu event. Kolom "Cocok" membandingkan kode naskah paket dengan kode di
    server (event terhubung) dan kode yang sudah terbaca di lembar event, supaya paket yang salah kelihatan."""
    BUKA = 2            # hasil exec(): panitia ingin membuat/mengisi paket di menu Kunci jawaban

    def __init__(self, parent, db, event_id, pesan=""):
        super().__init__(parent)
        self.db, self.event_id = db, event_id
        ev = db.event(event_id)
        self.setWindowTitle("Pilih paket kunci jawaban")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(12)
        title = QLabel("Pilih paket kunci jawaban")
        title.setProperty("role", "title")
        v.addWidget(title)
        info = QLabel((pesan + " " if pesan else "") +
                      f"Paket yang dipilih dipakai menilai semua lembar event <b>{ev['nama']}</b>. "
                      "Paket dibuat dan diisi di menu <b>Kunci jawaban</b> (kiri).")
        info.setWordWrap(True)
        info.setProperty("role", "muted")
        v.addWidget(info)

        self.pakets = list(db.pakets())
        target = {b["kode_naskah"] for b in db.server_bidang(event_id)} | set(kode_lembar(db, event_id))
        self.table = QTableWidget(0, 5 if target else 4)
        heads = ["Paket", "Mata pelajaran", "Kode naskah", "Dipakai di event"] + (["Cocok"] if target else [])
        self.table.setHorizontalHeaderLabels(heads)
        setup_table(self.table)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        cur = ev["paket_id"]
        best, best_n = None, -1
        for p in self.pakets:
            r = self.table.rowCount()
            self.table.insertRow(r)
            kode = [s.kode for s in db.paket_naskah(p["id"])]
            evs = [e["nama"] for e in db.paket_events(p["id"])]
            self.table.setItem(r, 0, _item(p["nama"]))
            self.table.setItem(r, 1, _item(str(p["n_mapel"]), Qt.AlignCenter))
            self.table.setItem(r, 2, _item(ringkas_kode(kode) or "—", tip=", ".join(kode)))
            self.table.setItem(r, 3, _item(", ".join(evs) or "—", tip="\n".join(evs)))
            if target:
                n = len(target & set(kode))
                it = _item(f"{n}/{len(target)} kode", Qt.AlignCenter,
                           "Kode naskah di server / lembar event ini yang ada di paket")
                paint(it, "ok" if n == len(target) else ("warn" if n else "error"))
                self.table.setItem(r, 4, it)
                if n > best_n:
                    best, best_n = r, n
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, self.table.columnCount()):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.cellDoubleClicked.connect(lambda *_: self._ok())

        empty = EmptyState("key", "Belum ada paket kunci jawaban",
                           "Buat paket (mis. FSN PROVINSI PAKET 1) dan impor kuncinya di menu Kunci jawaban.",
                           theme.button("Buka Kunci jawaban", "key", "primary", slot=lambda: self.done(self.BUKA)))
        stack = QStackedWidget()
        stack.addWidget(empty)
        stack.addWidget(self.table)
        stack.setCurrentWidget(self.table if self.pakets else empty)
        v.addWidget(stack, 1)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        if self.pakets:
            bar.addWidget(theme.button("Buka Kunci jawaban", "key", "ghost", "Buat atau ubah paket kunci",
                                       lambda: self.done(self.BUKA)))
        bar.addStretch()
        bar.addWidget(theme.button("Batal", variant="ghost", slot=self.reject))
        self.ok = theme.button("Pakai paket ini", "check", "primary", slot=self._ok)
        self.ok.setDefault(True)
        self.ok.setVisible(bool(self.pakets))
        bar.addWidget(self.ok)
        v.addLayout(bar)

        pre = next((r for r, p in enumerate(self.pakets) if p["id"] == cur), None)
        if pre is None and target and best_n > 0:
            pre = best                                      # paket yang kodenya paling cocok
        if pre is not None:
            self.table.selectRow(pre)
        self.resize(760, 460)

    def chosen(self):
        r = self.table.currentRow()
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if rows:
            r = rows[0].row()
        return self.pakets[r]["id"] if 0 <= r < len(self.pakets) else None

    def _ok(self):
        if self.chosen() is None:
            QMessageBox.information(self, "Paket kunci", "Pilih dulu salah satu paket.")
            return
        self.accept()


def pilih_paket(parent, db, event_id, pesan=""):
    """Dialog pilih paket untuk event. Mengembalikan "dipilih", "buka" (panitia ingin ke menu Kunci jawaban),
    atau None (batal / paket tidak berubah)."""
    d = PilihPaketDialog(parent, db, event_id, pesan)
    r = d.exec()
    if r == PilihPaketDialog.BUKA:
        return "buka"
    if r != QDialog.Accepted:
        return None
    pid = d.chosen()
    ev = db.event(event_id)
    if pid == ev["paket_id"]:
        return None
    n = len(db.lembar(event_id))
    if ev["paket_id"] is not None and n and QMessageBox.question(
            parent, "Ganti paket kunci",
            f"Nilai {n} lembar di event {ev['nama']} akan dihitung ulang dengan paket "
            f"{db.paket(pid)['nama']}. Lanjutkan?") != QMessageBox.Yes:
        return None
    db.set_event_paket(event_id, pid)
    return "dipilih"


# ------------------------------------------------------------------ halaman pustaka

class PaketPage(QWidget):
    changed = Signal()          # isi paket berubah: nilai event pemakai perlu dihitung ulang

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.paket_id = None
        self.mapel_id = None
        self._mapel = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 18, 0, 0)
        root.setSpacing(0)

        # ---- kiri: paket, mata pelajaran, kode naskah
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(10)

        self.b_paket_add = theme.button("Tambah", "plus", tip="Paket kunci baru", slot=self._add_paket)
        self.b_paket_ren = theme.button("Ubah nama", "pencil", tip="Ganti nama paket", slot=self._rename_paket)
        self.b_paket_del = theme.button("Hapus", "trash", "danger", "Hapus paket terpilih", self._del_paket)
        row_paket = self._section("Paket kunci", (self.b_paket_add, self.b_paket_ren, self.b_paket_del))
        lv.addLayout(row_paket)
        self.t_paket = QTableWidget(0, 3)
        self.t_paket.setHorizontalHeaderLabels(["Paket", "Mata pelajaran", "Dipakai di event"])
        setup_table(self.t_paket, 36)
        self.t_paket.setSelectionMode(QTableWidget.SingleSelection)
        h = self.t_paket.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        self.t_paket.itemSelectionChanged.connect(self._paket_selected)
        self.t_paket.cellDoubleClicked.connect(lambda *_: self._rename_paket())
        lv.addWidget(self.t_paket, 2)

        lv.addSpacing(6)
        self.b_pdf = theme.button("Impor PDF", "file-text", tip="Baca kunci dari folder PDF pembahasan soal",
                                  slot=self._import_pdf)
        self.b_xls = theme.button("Impor Excel", "sheet", tip="Muat kunci (dengan kode naskah) dari file Excel",
                                  slot=self._import_excel)
        self.b_mapel_add = theme.button("Tambah", "plus", tip="Mata pelajaran baru", slot=self._add_mapel)
        self.b_mapel_edit = theme.button("Edit kunci", "grid", tip="Edit nama & kunci per nomor", slot=self._edit_mapel)
        self.b_mapel_del = theme.button("Hapus", "trash", "danger", "Hapus mata pelajaran terpilih", self._del_mapel)
        self.mapel_title = QLabel("Mata pelajaran")
        row_mapel = self._section(self.mapel_title, (self.b_pdf, self.b_xls, divider(), self.b_mapel_add,
                                                     self.b_mapel_edit, self.b_mapel_del))
        lv.addLayout(row_mapel)
        # jendela sempit: tombol jadi ikon saja (nama di tooltip), yang paling jarang dipakai dulu
        ToolbarFit(left, row_paket, (self.b_paket_del, self.b_paket_ren, self.b_paket_add))
        ToolbarFit(left, row_mapel, (self.b_mapel_del, self.b_mapel_edit, self.b_mapel_add, self.b_xls, self.b_pdf))
        self.t_mapel = QTableWidget(0, 4)
        self.t_mapel.setHorizontalHeaderLabels(["Mata pelajaran", "Soal", "Kode naskah", "Catatan"])
        setup_table(self.t_mapel, 36)
        self.t_mapel.setSelectionMode(QTableWidget.SingleSelection)
        h = self.t_mapel.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        self.t_mapel.setColumnWidth(0, 230)
        self.t_mapel.itemSelectionChanged.connect(self._mapel_selected)
        self.t_mapel.cellDoubleClicked.connect(lambda *_: self._edit_mapel())
        lv.addWidget(self.t_mapel, 3)

        lv.addSpacing(6)
        self.kode_title = QLabel("Kode naskah")
        lv.addLayout(self._section(self.kode_title, ()))
        kr = QHBoxLayout()
        kr.setSpacing(10)
        self.l_kode = QListWidget()
        self.l_kode.setFixedHeight(118)
        self.l_kode.setFlow(QListWidget.LeftToRight)
        self.l_kode.setWrapping(True)
        self.l_kode.setSpacing(2)
        self.l_kode.setFont(theme.mono(10))
        self.l_kode.itemDoubleClicked.connect(lambda *_: self._rename_kode())
        self.l_kode.currentRowChanged.connect(self._kode_buttons)
        kr.addWidget(self.l_kode, 1)
        kb = QVBoxLayout()
        kb.setSpacing(6)
        self.b_kode_add = theme.button("Tambah", "plus", tip="Tambah kode naskah untuk mata pelajaran ini",
                                       slot=self._add_kode)
        self.b_kode_ren = theme.button("Ubah", "pencil", tip="Ganti kode naskah terpilih", slot=self._rename_kode)
        self.b_kode_del = theme.button("Hapus", "trash", "danger", "Hapus kode naskah terpilih", self._del_kode)
        for b in (self.b_kode_add, self.b_kode_ren, self.b_kode_del):
            kb.addWidget(b)
        kb.addStretch()
        kr.addLayout(kb)
        lv.addLayout(kr)

        # ---- kanan: urutan kunci jawaban
        right = QFrame()
        right.setProperty("role", "card")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(18, 14, 12, 12)
        rv.setSpacing(4)
        hr = QHBoxLayout()
        hr.setSpacing(8)
        tv = QVBoxLayout()
        tv.setSpacing(2)
        cap = QLabel("Kunci jawaban")
        cap.setProperty("role", "section")
        self.k_title = QLabel("")
        self.k_title.setProperty("role", "h2")
        self.k_title.setWordWrap(True)
        tv.addWidget(cap)
        tv.addWidget(self.k_title)
        hr.addLayout(tv, 1)
        self.b_k_edit = theme.button("Edit", "grid", tip="Edit kunci per nomor", slot=self._edit_mapel)
        self.b_k_pdf = theme.button("", "file-text", "icon", "Buka PDF sumber", self._open_pdf)
        hr.addWidget(self.b_k_edit, 0, Qt.AlignTop)
        hr.addWidget(self.b_k_pdf, 0, Qt.AlignTop)
        rv.addLayout(hr)
        self.k_sub = QLabel("")
        self.k_sub.setProperty("role", "muted")
        self.k_sub.setWordWrap(True)
        self.k_sub.setTextFormat(Qt.RichText)
        rv.addWidget(self.k_sub)
        rv.addSpacing(8)
        self.kview = KunciView()
        self.kview.edit_requested.connect(self._edit_mapel)
        self.k_scroll = QScrollArea()
        self.k_scroll.setWidgetResizable(True)
        self.k_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.k_scroll.setWidget(self.kview)
        self.k_empty = QLabel("Pilih mata pelajaran untuk melihat urutan kuncinya.")
        self.k_empty.setProperty("role", "muted")
        self.k_empty.setAlignment(Qt.AlignCenter)
        self.k_empty.setWordWrap(True)
        self.k_stack = QStackedWidget()
        self.k_stack.addWidget(self.k_empty)
        self.k_stack.addWidget(self.k_scroll)
        rv.addWidget(self.k_stack, 1)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([640, 440])
        left.setMinimumWidth(380)
        right.setMinimumWidth(300)

        self.empty = EmptyState("key", "Belum ada paket kunci jawaban",
                                "Satu paket (mis. FSN PROVINSI PAKET 1) bisa dipakai banyak event. Buat paket, "
                                "impor kunci dari PDF pembahasan atau Excel, lalu isi kode naskah tiap mata pelajaran.",
                                theme.button("Buat paket", "plus", "primary", slot=self._add_paket))
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(split)
        root.addWidget(self.stack, 1)

    @staticmethod
    def _section(title, buttons):
        row = toolbar(8)
        lb = title if isinstance(title, QLabel) else QLabel(title)
        lb.setProperty("role", "h3")
        row.addWidget(lb)
        row.addStretch()
        for b in buttons:
            row.addWidget(b)
        return row

    # ---- data
    def summary(self):
        """Teks singkat untuk subjudul halaman."""
        ps = list(self.db.pakets())
        if not ps:
            return "belum ada paket"
        dipakai = sum(1 for p in ps if p["n_event"])
        return f"{len(ps)} paket &nbsp;·&nbsp; {dipakai} dipakai event &nbsp;·&nbsp; satu paket bisa dipakai banyak event"

    def reload(self, select=None):
        """Muat ulang daftar paket; pilih paket `select` (bila ada), atau tetap paket yang sedang dipilih."""
        keep = select if select is not None else self.paket_id
        keep_mapel = self.mapel_id if keep == self.paket_id else None
        pakets = list(self.db.pakets())
        self.stack.setCurrentIndex(1 if pakets else 0)
        self.t_paket.blockSignals(True)
        self.t_paket.setRowCount(0)
        row = 0
        for i, p in enumerate(pakets):
            self.t_paket.insertRow(i)
            evs = [e["nama"] for e in self.db.paket_events(p["id"])]
            it = _item(p["nama"])
            it.setData(Qt.UserRole, p["id"])
            self.t_paket.setItem(i, 0, it)
            self.t_paket.setItem(i, 1, _item(str(p["n_mapel"]), Qt.AlignCenter))
            self.t_paket.setItem(i, 2, _item(", ".join(evs) or "—", tip="\n".join(evs) or "Belum dipakai event"))
            if p["id"] == keep:
                row = i
        if pakets:
            self.t_paket.selectRow(row)
        self.t_paket.blockSignals(False)
        self._paket_selected(keep_mapel)

    def _paket_selected(self, keep_mapel=None):
        rows = self.t_paket.selectionModel().selectedRows()
        it = self.t_paket.item(rows[0].row(), 0) if rows else None
        pid = it.data(Qt.UserRole) if it is not None else None
        if pid != self.paket_id:
            keep_mapel = None
        self.paket_id = pid
        has = pid is not None
        for b in (self.b_paket_ren, self.b_paket_del, self.b_pdf, self.b_xls, self.b_mapel_add):
            b.setEnabled(has)
        self._load_mapel(keep_mapel if isinstance(keep_mapel, int) else None)

    def _load_mapel(self, select=None):
        self._mapel = self.db.mapel(self.paket_id) if self.paket_id is not None else []
        self.t_mapel.blockSignals(True)
        self.t_mapel.setRowCount(0)
        row = 0
        for i, m in enumerate(self._mapel):
            self.t_mapel.insertRow(i)
            self.t_mapel.setItem(i, 0, _item(m["nama"], tip=m["nama"]))
            self.t_mapel.setItem(i, 1, _item(str(len(m["kunci"])), Qt.AlignCenter))
            ki = _item(ringkas_kode(m["kode"]) or "—", tip=", ".join(m["kode"]) or "Belum ada kode naskah")
            ki.setFont(theme.mono())
            self.t_mapel.setItem(i, 2, ki)
            note, tone = self._mapel_note(m)
            ci = _item(note, tip=note)
            if tone:
                paint(ci, tone)
            self.t_mapel.setItem(i, 3, ci)
            if m["id"] == select:
                row = i
        if self._mapel:
            self.t_mapel.selectRow(row)
            self.t_mapel.scrollTo(self.t_mapel.model().index(row, 0))
        self.t_mapel.blockSignals(False)
        self._mapel_selected()

    @staticmethod
    def _mapel_note(m):
        bad = nomor_tanpa_kunci(m["kunci"])
        if not m["kunci"]:
            return "kunci kosong", "error"
        if bad:
            nomor = ", ".join(map(str, bad[:8])) + ("…" if len(bad) > 8 else "")
            return f"kunci belum lengkap (soal {nomor}): belum dipakai menilai", "error"
        if not m["kode"]:
            return "belum ada kode naskah", "warn"
        return m["catatan"], ("warn" if m["catatan"] else None)

    def _cur_mapel(self):
        return next((m for m in self._mapel if m["id"] == self.mapel_id), None)

    def _mapel_selected(self):
        rows = self.t_mapel.selectionModel().selectedRows()
        m = self._mapel[rows[0].row()] if rows and rows[0].row() < len(self._mapel) else None
        self.mapel_id = m["id"] if m else None
        for b in (self.b_mapel_edit, self.b_mapel_del, self.b_kode_add, self.b_k_edit):
            b.setEnabled(m is not None)
        self.l_kode.clear()
        if m is None:
            self.kode_title.setText("Kode naskah")
            self.k_stack.setCurrentWidget(self.k_empty)
            self.k_empty.setText("Pilih mata pelajaran untuk melihat urutan kuncinya." if self._mapel else
                                 "Paket ini belum berisi mata pelajaran. Impor dari PDF pembahasan atau Excel, "
                                 "atau tambah secara manual.")
            self.k_title.setText("")
            self.k_sub.setText("")
            self.b_k_pdf.setEnabled(False)
            self._kode_buttons()
            return
        self.kode_title.setText(f"Kode naskah · {m['nama']}")
        for k in m["kode"]:
            it = QListWidgetItem(k)
            it.setTextAlignment(Qt.AlignCenter)
            it.setSizeHint(QSize(max(64, 14 * len(k) + 28), 32))
            self.l_kode.addItem(it)
        if m["kode"]:
            self.l_kode.setCurrentRow(0)
        self._kode_buttons()
        self.k_title.setText(m["nama"])
        parts = [f"{len(m['kunci'])} soal",
                 ("kode naskah " + ringkas_kode(m["kode"])) if m["kode"] else "belum ada kode naskah"]
        if m["sumber"]:
            parts.append(f"dari {Path(m['sumber']).name}")
        sub = " &nbsp;·&nbsp; ".join(parts)
        bad = nomor_tanpa_kunci(m["kunci"])
        if bad:
            sub += (f"<br><span style='color:{theme.tone_hex('error')[1]}'>Soal "
                    f"{', '.join(map(str, bad[:12]))}{'…' if len(bad) > 12 else ''} belum berisi kunci A–E; "
                    "mata pelajaran ini belum dipakai menilai. Klik Edit.</span>")
        self.k_sub.setText(sub)
        self.b_k_pdf.setEnabled(bool(m["sumber"]) and Path(m["sumber"]).exists())
        self.b_k_pdf.setToolTip(m["sumber"] or "Kunci ini tidak diimpor dari PDF")
        self.kview.set_kunci(m["kunci"])
        self.k_stack.setCurrentWidget(self.k_scroll)
        self.k_scroll.verticalScrollBar().setValue(0)

    def _kode_buttons(self, *_):
        sel = self.l_kode.currentItem() is not None
        self.b_kode_ren.setEnabled(sel)
        self.b_kode_del.setEnabled(sel)

    # ---- bantu
    def _paket_nama(self):
        p = self.db.paket(self.paket_id) if self.paket_id is not None else None
        return p["nama"] if p else ""

    def _boleh_ubah(self, aksi):
        """Paket dipakai event: perubahan kunci/kode ikut mengubah nilai event itu. Minta persetujuan."""
        evs = [e["nama"] for e in self.db.paket_events(self.paket_id)]
        if not evs:
            return True
        daftar = ", ".join(evs[:8]) + (f" dan {len(evs) - 8} lainnya" if len(evs) > 8 else "")
        return QMessageBox.question(
            self, "Paket dipakai event",
            f"{aksi}\n\nPaket {self._paket_nama()} dipakai {len(evs)} event: {daftar}.\n"
            "Nilai lembar di event tersebut akan ikut berubah. Lanjutkan?") == QMessageBox.Yes

    def _ask_text(self, title, label, text="", placeholder=""):
        d = QInputDialog(self)
        d.setWindowTitle(title)
        d.setLabelText(label)
        d.setTextValue(text)
        d.setOkButtonText("Simpan")
        d.setCancelButtonText("Batal")
        le = d.findChild(QLineEdit)
        if le is not None and placeholder:
            le.setPlaceholderText(placeholder)
        d.resize(420, 0)
        return d.textValue().strip() if d.exec() else None

    def _done(self, select_mapel=None):
        """Setelah data paket berubah: muat ulang (mata pelajaran terpilih tetap) dan kabari event pemakai."""
        if select_mapel is not None:
            self.mapel_id = select_mapel
        self.reload()
        self.changed.emit()

    # ---- paket
    def _add_paket(self):
        nama = self._ask_text("Paket kunci baru", "Nama paket kunci jawaban:", placeholder="FSN PROVINSI PAKET 1")
        if not nama:
            return
        if self.db.paket_by_nama(nama) is not None:
            QMessageBox.warning(self, "Paket kunci", f"Paket bernama {nama} sudah ada.")
            return
        pid = self.db.add_paket(nama)
        self.reload(select=pid)
        self.changed.emit()

    def _rename_paket(self):
        if self.paket_id is None:
            return
        nama = self._ask_text("Ubah nama paket", "Nama paket kunci jawaban:", self._paket_nama())
        if not nama or nama == self._paket_nama():
            return
        other = self.db.paket_by_nama(nama)
        if other is not None and other["id"] != self.paket_id:
            QMessageBox.warning(self, "Paket kunci", f"Paket bernama {nama} sudah ada.")
            return
        self.db.rename_paket(self.paket_id, nama)
        self.reload()
        self.changed.emit()

    def _del_paket(self):
        if self.paket_id is None:
            return
        evs = [e["nama"] for e in self.db.paket_events(self.paket_id)]
        msg = f"Hapus paket {self._paket_nama()} beserta {len(self._mapel)} mata pelajaran dan kode naskahnya?"
        if evs:
            msg += (f"\n\nPaket ini dipakai {len(evs)} event: {', '.join(evs)}. Event tersebut akan kembali tanpa "
                    "kunci jawaban; lembarnya tidak dinilai sampai memilih paket lain.")
        if QMessageBox.question(self, "Hapus paket", msg) != QMessageBox.Yes:
            return
        self.db.delete_paket(self.paket_id)
        self.paket_id = None
        self.reload()
        self.changed.emit()

    # ---- mata pelajaran
    def _add_mapel(self):
        if self.paket_id is None:
            return
        d = KunciDialog(self, None, "", "", jumlah=30)
        if not d.exec():
            return
        _kode, nama, kunci = d.values()
        mid = self.db.add_mapel(self.paket_id, nama, kunci)
        self._done(mid)
        self._add_kode()                    # langsung tawarkan kode naskahnya (boleh dibatalkan)

    def _edit_mapel(self):
        m = self._cur_mapel()
        if m is None:
            return
        d = KunciDialog(self, None, m["nama"], m["kunci"], m["sumber"])
        if not d.exec():
            return
        _kode, nama, kunci = d.values()
        if nama == m["nama"] and kunci == m["kunci"]:
            return
        if kunci != m["kunci"] and m["kode"] and not self._boleh_ubah(f"Kunci {m['nama']} diubah."):
            return
        self.db.update_mapel(m["id"], nama, kunci, catatan="" if kunci != m["kunci"] else None)
        self._done(m["id"])

    def _del_mapel(self):
        m = self._cur_mapel()
        if m is None:
            return
        if QMessageBox.question(self, "Hapus mata pelajaran",
                                f"Hapus {m['nama']} beserta kode naskahnya ({ringkas_kode(m['kode']) or 'tanpa kode'}) "
                                f"dari paket {self._paket_nama()}?") != QMessageBox.Yes:
            return
        if m["kode"] and not self._boleh_ubah(f"Lembar berkode {ringkas_kode(m['kode'])} tidak akan dinilai lagi."):
            return
        self.db.delete_mapel(m["id"])
        self.mapel_id = None
        self._done()

    def _open_pdf(self):
        m = self._cur_mapel()
        if m and m["sumber"]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(m["sumber"]))

    # ---- kode naskah
    def _cek_kode(self, kode, kecuali=None):
        """Pesan kesalahan untuk kode naskah baru, atau "" bila boleh."""
        if not kode or len(kode) > MAKS_KODE or re.search(r"\s", kode):
            return f"Kode naskah harus 1–{MAKS_KODE} karakter tanpa spasi."
        owner = self.db.kode_owner(self.paket_id, kode)
        if owner is not None and kode != kecuali:
            return f"Kode naskah {kode} sudah dipakai {owner['nama']} di paket ini."
        return ""

    def _add_kode(self):
        m = self._cur_mapel()
        if m is None:
            return
        kode = self._ask_text("Tambah kode naskah", f"Kode naskah untuk {m['nama']}:", placeholder="299")
        if not kode:
            return
        err = self._cek_kode(kode)
        if err:
            QMessageBox.warning(self, "Kode naskah", err)
            return
        try:
            self.db.add_kode(self.paket_id, m["id"], kode)
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Kode naskah", f"Kode naskah {kode} sudah dipakai di paket ini.")
            return
        self._done(m["id"])

    def _rename_kode(self):
        m, it = self._cur_mapel(), self.l_kode.currentItem()
        if m is None or it is None:
            return
        old = it.text()
        kode = self._ask_text("Ubah kode naskah", f"Kode naskah {m['nama']}:", old)
        if not kode or kode == old:
            return
        err = self._cek_kode(kode, kecuali=old)
        if err:
            QMessageBox.warning(self, "Kode naskah", err)
            return
        if not self._boleh_ubah(f"Kode naskah {old} ({m['nama']}) diganti {kode}."):
            return
        self.db.rename_kode(self.paket_id, old, kode)
        self._done(m["id"])

    def _del_kode(self):
        m, it = self._cur_mapel(), self.l_kode.currentItem()
        if m is None or it is None:
            return
        kode = it.text()
        if QMessageBox.question(self, "Hapus kode naskah",
                                f"Hapus kode naskah {kode} dari {m['nama']}?") != QMessageBox.Yes:
            return
        if not self._boleh_ubah(f"Lembar berkode {kode} tidak akan dinilai lagi."):
            return
        self.db.delete_kode(self.paket_id, kode)
        self._done(m["id"])

    # ---- impor
    def _import_pdf(self):
        if self.paket_id is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder PDF pembahasan soal")
        if not folder:
            return
        pdfs = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() == ".pdf")
        if not pdfs:
            QMessageBox.information(self, "Impor PDF", "Tidak ada file PDF di folder itu.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        hasil, gagal, problems, cara = [], [], [], {KU.CARA_1: 0, KU.CARA_2: 0}
        try:
            for p in pdfs:
                QApplication.processEvents()
                k = KU.parse(p)
                if k.jumlah_soal == 0:
                    gagal.append(p.name)
                    continue
                cara[k.cara] = cara.get(k.cara, 0) + 1
                if k.masalah:
                    problems.append(f"&bull; <b>{p.name}</b>: {'; '.join(k.masalah)}")
                hasil.append((KU.suggest_name(p), k.kunci, str(p), "; ".join(k.masalah)))
        finally:
            QApplication.restoreOverrideCursor()
        ada = {m["nama"].casefold(): m for m in self._mapel}
        berubah = [ada[n.casefold()] for n, ku, _s, _c in hasil
                   if n.casefold() in ada and ada[n.casefold()]["kunci"] != ku]
        if any(m["kode"] for m in berubah) and not self._boleh_ubah(
                f"Impor PDF mengganti kunci {len(berubah)} mata pelajaran yang sudah ada."):
            return
        baru = diganti = 0
        for nama, kunci, sumber, catatan in hasil:
            m = ada.get(nama.casefold())
            if m is None:
                self.db.add_mapel(self.paket_id, nama, kunci, sumber, catatan)
                baru += 1
            elif m["kunci"] != kunci or m["sumber"] != sumber:
                self.db.update_mapel(m["id"], nama, kunci, sumber, catatan)
                diganti += 1
        self._done()
        msg = (f"{len(pdfs) - len(gagal)} dari {len(pdfs)} PDF terbaca: {cara[KU.CARA_1]} dengan cara 1 "
               f"(<i>Kunci Jawaban: X</i>), {cara[KU.CARA_2]} dengan cara 2 (<i>Jawaban: X</i> di awal baris).<br>"
               f"{baru} mata pelajaran baru, {diganti} diperbarui (nama sama).<br>"
               "Periksa nama mata pelajaran, lalu isi <b>Kode naskah</b> tiap mata pelajaran.")
        if gagal:
            msg += "<br><br>Kunci tidak ditemukan di: " + ", ".join(gagal)
        if problems:
            msg += "<br><br>Perlu diperhatikan (kolom Catatan berwarna):<br>" + "<br>".join(problems)
        QMessageBox.information(self, "Impor PDF", msg)

    def _import_excel(self):
        if self.paket_id is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "File kunci (Excel)", "", "Excel (*.xlsx)")
        if not path:
            return
        try:
            soal = NI.load_kunci(path)
        except Exception as e:  # noqa: BLE001  file bukan format kunci
            QMessageBox.warning(self, "Impor Excel", f"File tidak bisa dibaca sebagai file kunci:\n{e}")
            return
        if self.db.paket_events(self.paket_id) and self._mapel and not self._boleh_ubah(
                f"Impor Excel ({len(soal)} kode naskah) bisa mengganti kunci yang sudah ada."):
            return
        baru = diganti = kode_baru = 0
        bentrok = []
        for s in sorted(soal.values(), key=lambda s: kode_sort(s.kode)):
            kunci = re.sub(r"[\s,;|/]", "", s.kunci).upper()   # pemisah yang diketik di Excel bukan kunci
            mapel = self.db.mapel(self.paket_id)
            owner = self.db.kode_owner(self.paket_id, s.kode)
            if owner is not None:                               # kode sudah ada: kunci mata pelajarannya diperbarui
                if owner["kunci"] != kunci or owner["nama"] != s.bidang:
                    self.db.update_mapel(owner["id"], s.bidang or owner["nama"], kunci,
                                         s.sumber or None, "" if owner["kunci"] != kunci else None)
                    diganti += 1
                continue
            same = [m for m in mapel if m["nama"].casefold() == s.bidang.casefold()]
            m = (next((m for m in same if m["kunci"] == kunci), None)
                 or next((m for m in same if not m["kode"]), None))
            if m is None:
                mid = self.db.add_mapel(self.paket_id, s.bidang, kunci, s.sumber)
                baru += 1
            else:
                mid = m["id"]
                if m["kunci"] != kunci:
                    self.db.update_mapel(mid, m["nama"], kunci, s.sumber or None, "")
                    diganti += 1
            try:
                self.db.add_kode(self.paket_id, mid, s.kode)
                kode_baru += 1
            except sqlite3.IntegrityError:
                bentrok.append(s.kode)
        self._done()
        msg = (f"{len(soal)} kode naskah dibaca: {baru} mata pelajaran baru, {diganti} kunci diperbarui, "
               f"{kode_baru} kode naskah ditambahkan.")
        if bentrok:
            msg += f"\n\nKode berikut sudah dipakai mata pelajaran lain dan dilewati: {', '.join(bentrok)}"
        QMessageBox.information(self, "Impor Excel", msg)
