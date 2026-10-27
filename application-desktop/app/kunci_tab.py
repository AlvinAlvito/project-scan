"""Tab 1: kunci jawaban per kode naskah untuk event yang dipilih."""
import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ljk import kunci as KU
from app import icons, theme
from app.colors import paint
from app.kunci_dialog import KunciDialog
from app.widgets import EmptyState, ToolbarFit, badge, divider, setup_table, toolbar
from ljk import nilai as NI

COL_KODE, COL_BIDANG, COL_JUMLAH, COL_KUNCI, COL_CATATAN = range(5)
LIHAT, ISI, KURANG = "Lihat kunci jawaban", "Isi kunci jawaban", "Kunci belum lengkap"


def bukan_kunci(kunci):
    """Nomor soal (mulai 1) yang isinya bukan A-E, mis. "?" dari PDF yang kuncinya tidak ditemukan."""
    return [q + 1 for q, ch in enumerate(kunci) if ch not in "ABCDE"]


class KunciLinkDelegate(QStyledItemDelegate):
    """Kolom Kunci tidak memperlihatkan isi kunci, hanya tautan "Lihat kunci jawaban" yang membuka editor
    per nomor. Isi kunci tetap disimpan sebagai teks sel (dipakai simpan, impor, dan editor)."""
    PAD, ICON, GAP = 10, 16, 8

    def _font(self, option, hover=False):
        f = QFont(option.widget.font() if option.widget else option.font)
        f.setWeight(QFont.Medium)
        f.setUnderline(hover)
        return f

    def paint(self, p, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""                                   # latar, pilihan, dan garis baris tetap dari gaya tabel
        w = opt.widget
        (w.style() if w else QApplication.style()).drawControl(QStyle.CE_ItemViewItem, opt, p, w)
        kunci = (index.data() or "").strip()
        if not kunci:
            ikon, warna, teks = "pencil", theme.c("muted"), ISI
        elif bukan_kunci(kunci):        # isi kunci tersembunyi: soal tanpa kunci harus tetap kelihatan
            ikon, warna, teks = "alert", theme.tone_hex("warn")[1], KURANG
        else:
            ikon, warna, teks = "eye", None, LIHAT
        r = option.rect.adjusted(self.PAD, 0, -self.PAD, 0)
        pm = icons.pixmap(ikon, warna or theme.c("icon"), self.ICON, w.devicePixelRatioF() if w else 2.0)
        p.save()
        p.drawPixmap(r.left(), r.center().y() - self.ICON // 2 + 1, pm)
        p.setFont(self._font(option, bool(option.state & QStyle.State_MouseOver)))
        p.setPen(QColor(warna or theme.c("text")))
        tr = r.adjusted(self.ICON + self.GAP, 0, 0, 0)
        p.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter, QFontMetrics(p.font()).elidedText(teks, Qt.ElideRight, tr.width()))
        p.restore()

    def sizeHint(self, option, index):
        fm = QFontMetrics(self._font(option))
        lebar = max(fm.horizontalAdvance(t) for t in (LIHAT, ISI, KURANG))
        return QSize(2 * self.PAD + self.ICON + self.GAP + lebar + 4, super().sizeHint(option, index).height())


class KunciTab(QWidget):
    changed = Signal()

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.event_id = None
        self._dirty = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 18, 0, 0)
        v.setSpacing(14)
        bar = toolbar()
        b_pdf = theme.button("Impor PDF", "file-text", tip="Baca kunci dari folder PDF pembahasan soal",
                             slot=self._import_pdf)
        b_xls = theme.button("Impor Excel", "sheet", tip="Muat kunci dari file Excel", slot=self._import_excel)
        b_add = theme.button("Tambah bidang", "plus", tip="Tambah kode naskah baru", slot=self._add_row)
        b_edit = theme.button("Edit kunci", "grid", tip="Edit kunci per nomor soal untuk baris yang dipilih",
                              slot=self._edit_current)
        b_del = theme.button("Hapus", "trash", "danger", "Hapus baris yang dipilih", self._del_rows)
        for w in (b_pdf, b_xls, divider(), b_add, b_edit, b_del):
            bar.addWidget(w)
        bar.addStretch()
        self.state = badge("Belum disimpan", "warn")
        self.state.setVisible(False)
        bar.addWidget(self.state)
        self.save_btn = theme.button("Simpan kunci", "save", "primary", slot=self.save)
        bar.addWidget(self.save_btn)
        v.addLayout(bar)
        ToolbarFit(self, bar, (b_del, b_edit, b_add, b_xls, b_pdf, self.save_btn))

        # bidang yang terdaftar di server tetapi belum punya kunci di laptop ini
        self.srv_box = QFrame()
        self.srv_box.setProperty("role", "card")
        sb = QHBoxLayout(self.srv_box)
        sb.setContentsMargins(16, 10, 12, 10)
        sb.setSpacing(10)
        self.srv_text = QLabel("")
        self.srv_text.setWordWrap(True)
        sb.addWidget(self.srv_text, 1)
        self.srv_buttons = QHBoxLayout()
        self.srv_buttons.setSpacing(8)
        sb.addLayout(self.srv_buttons)
        self.srv_box.setVisible(False)
        v.addWidget(self.srv_box)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Kode naskah", "Bidang", "Soal", "Kunci", "Catatan"])
        setup_table(self.table)
        self.table.setSelectionBehavior(QTableWidget.SelectItems)
        self.table.setToolTip("Klik \"Lihat kunci jawaban\" untuk melihat atau mengedit kunci per nomor.\n"
                              "Kode naskah dan bidang bisa diketik langsung.")
        self.table.setItemDelegateForColumn(COL_KUNCI, KunciLinkDelegate(self.table))
        self.table.setMouseTracking(True)
        self.table.viewport().setAttribute(Qt.WA_Hover, True)
        self.table.entered.connect(lambda i: self.table.viewport().setCursor(
            Qt.PointingHandCursor if i.column() == COL_KUNCI else Qt.ArrowCursor))
        self.table.viewportEntered.connect(lambda: self.table.viewport().setCursor(Qt.ArrowCursor))
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(COL_KODE, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_BIDANG, QHeaderView.Interactive)
        h.setSectionResizeMode(COL_JUMLAH, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_KUNCI, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_CATATAN, QHeaderView.Stretch)
        self.table.setColumnWidth(COL_BIDANG, 220)
        self.table.itemChanged.connect(self._item_changed)
        self.table.cellClicked.connect(self._cell_clicked)
        self.table.cellDoubleClicked.connect(self._double_click)
        self.empty = EmptyState("key", "Belum ada kunci jawaban",
                                "Impor dari PDF pembahasan atau Excel, atau tambah bidang secara manual.")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.table)
        v.addWidget(self.stack, 1)
        self.table.model().rowsInserted.connect(self._update_empty)
        self.table.model().rowsRemoved.connect(self._update_empty)

    def _update_empty(self, *_):
        self.stack.setCurrentWidget(self.table if self.table.rowCount() else self.empty)

    # ---- data
    def load(self, event_id):
        self.event_id = event_id
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        if event_id is not None:
            for s in self.db.naskah(event_id):
                self._append(s.kode, s.bidang, s.kunci, sumber=s.sumber)
        self.table.blockSignals(False)
        self._set_dirty(False)
        self.show_server_bidang()

    def show_server_bidang(self):
        """Tampilkan bidang server yang kode naskahnya belum ada di tabel kunci."""
        while self.srv_buttons.count():
            w = self.srv_buttons.takeAt(0).widget()
            if w:
                w.deleteLater()
        if self.event_id is None:
            self.srv_box.setVisible(False)
            return
        have = {r[0] for r in self._rows()}
        missing = [b for b in self.db.server_bidang(self.event_id) if b["kode_naskah"] not in have]
        self.srv_box.setVisible(bool(missing))
        if not missing:
            return
        daftar = ", ".join(f"<b>{b['nama']}</b> ({b['kode_naskah']} · {b['jumlah_soal']} soal)" for b in missing)
        self.srv_text.setText(f"Bidang dari server yang belum ada kuncinya: {daftar}")
        for b in missing[:3]:           # sisanya muncul setelah yang ini diisi (tetap tertulis di teks)
            btn = theme.button(f"Isi kunci {b['kode_naskah']}", "key", "primary" if b is missing[0] else None,
                               f"Isi kunci {b['nama']}", lambda _=False, b=b: self.add_from_server(b))
            self.srv_buttons.addWidget(btn)
        theme.refresh_all()

    def add_from_server(self, b):
        """Tambah baris bidang dari server (kode, nama, jumlah soal sudah terisi) lalu buka editor kunci."""
        self.table.blockSignals(True)
        self._append(b["kode_naskah"], b["nama"], "")
        self.table.blockSignals(False)
        r = self.table.rowCount() - 1
        self.table.setCurrentCell(r, COL_KODE)
        self._edit_row(r, new=True, jumlah=int(b.get("jumlah_soal") or 0))
        self.show_server_bidang()

    def _append(self, kode, bidang, kunci, note="", sumber="", warn=None):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, COL_KODE, QTableWidgetItem(kode))
        self.table.setItem(r, COL_BIDANG, QTableWidgetItem(bidang))
        jml = QTableWidgetItem(str(len(kunci)))
        jml.setFlags(jml.flags() & ~Qt.ItemIsEditable)
        jml.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(r, COL_JUMLAH, jml)
        ki = QTableWidgetItem(kunci)
        ki.setFont(theme.mono())
        ki.setFlags(ki.flags() & ~Qt.ItemIsEditable)      # diedit lewat editor per nomor
        ki.setData(Qt.UserRole, sumber)
        self.table.setItem(r, COL_KUNCI, ki)
        ci = QTableWidgetItem(note)
        ci.setFlags(ci.flags() & ~Qt.ItemIsEditable)
        ci.setToolTip(note)
        self.table.setItem(r, COL_CATATAN, ci)
        if note and (warn is None or warn):
            paint(ci, "warn")

    def _item_changed(self, item):
        if item.column() == COL_KUNCI:
            self.table.blockSignals(True)
            clean = re.sub(r"[^A-Ea-e]", "", item.text()).upper()
            if clean != item.text():
                item.setText(clean)
            self.table.item(item.row(), COL_JUMLAH).setText(str(len(clean)))
            self.table.blockSignals(False)
        self._set_dirty(True)

    def _set_dirty(self, dirty):
        self._dirty = dirty
        self.state.setVisible(dirty)

    def confirm_leave(self):
        return not self._dirty

    def ask_save(self):
        """Kunci belum disimpan saat event ditinggalkan / aplikasi ditutup: Simpan / Buang / Batal.
        True = boleh lanjut."""
        if not self._dirty or self.event_id is None:
            return True
        r = QMessageBox.question(self, "Kunci jawaban", "Kunci jawaban event ini belum disimpan. Simpan sekarang?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def _rows(self):
        out = []
        for r in range(self.table.rowCount()):
            get = lambda c: (self.table.item(r, c).text().strip() if self.table.item(r, c) else "")  # noqa: E731
            ki = self.table.item(r, COL_KUNCI)
            src = (ki.data(Qt.UserRole) if ki else "") or ""
            out.append((get(COL_KODE), get(COL_BIDANG), get(COL_KUNCI).upper(), src))
        return out

    def save(self):
        """Simpan kunci; False bila belum bisa disimpan (pesan kesalahan sudah ditampilkan)."""
        if self.event_id is None:
            return False
        errors, seen, soal = [], set(), []
        for i, (kode, bidang, kunci, sumber) in enumerate(self._rows(), 1):
            if not (kode or bidang or kunci):
                continue
            if not kode:
                errors.append(f"Baris {i}: kode naskah kosong")
            elif kode in seen:
                errors.append(f"Baris {i}: kode naskah {kode} dipakai dua kali")
            if not bidang:
                errors.append(f"Baris {i}: nama bidang kosong")
            if not kunci:
                errors.append(f"Baris {i}: kunci kosong")
            elif len(kunci) > 180:
                errors.append(f"Baris {i}: kunci lebih dari 180 soal")
            elif bad := bukan_kunci(kunci):
                nomor = ", ".join(map(str, bad[:10])) + (f" (dan {len(bad) - 10} lainnya)" if len(bad) > 10 else "")
                errors.append(f"Baris {i} ({kode or bidang}): soal {nomor} belum berisi kunci A–E. "
                              "Buka \"Kunci belum lengkap\" lalu pilih kuncinya.")
            seen.add(kode)
            soal.append(NI.Soal(kode, bidang, kunci, sumber))
        if errors:
            QMessageBox.warning(self, "Kunci belum bisa disimpan", "\n".join(errors))
            return False
        self.db.set_naskah(self.event_id, soal)
        self.load(self.event_id)          # muat ulang, urut menurut kode naskah
        self.changed.emit()
        QMessageBox.information(self, "Kunci", f"{len(soal)} kode naskah tersimpan.")
        return True

    # ---- editor per nomor
    def _cell_clicked(self, r, c):
        if c == COL_KUNCI:              # tautan "Lihat kunci jawaban": cukup sekali klik
            self._edit_row(r)

    def _double_click(self, r, c):
        if c in (COL_JUMLAH, COL_CATATAN):
            self._edit_row(r)

    def _edit_current(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Kunci", "Pilih dulu baris bidang yang kuncinya akan diedit.")
            return
        self._edit_row(r)

    def _edit_row(self, r, new=False, jumlah=0):
        kode, bidang, kunci, sumber = self._rows()[r]
        d = KunciDialog(self, kode, bidang, kunci, sumber, jumlah=jumlah)
        if not d.exec():
            if new:
                self.table.removeRow(r)
            return
        kode, bidang, kunci = d.values()
        self.table.blockSignals(True)
        self.table.item(r, COL_KODE).setText(kode)
        self.table.item(r, COL_BIDANG).setText(bidang)
        self.table.item(r, COL_KUNCI).setText(kunci)
        self.table.item(r, COL_JUMLAH).setText(str(len(kunci)))
        self.table.blockSignals(False)
        self._set_dirty(True)
        self.save()

    # ---- tombol
    def _add_row(self):
        self.table.blockSignals(True)
        self._append("", "", "")
        self.table.blockSignals(False)
        r = self.table.rowCount() - 1
        self.table.setCurrentCell(r, COL_KODE)
        self._edit_row(r, new=True)

    def _del_rows(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        if rows:
            self._set_dirty(True)

    def _import_pdf(self):
        if self.event_id is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder PDF pembahasan soal")
        if not folder:
            return
        pdfs = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() == ".pdf")
        if not pdfs:
            QMessageBox.information(self, "Impor PDF", "Tidak ada file PDF di folder itu.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        problems, gagal, cara = [], [], {KU.CARA_1: 0, KU.CARA_2: 0}
        try:
            self.table.blockSignals(True)
            for p in pdfs:
                QApplication.processEvents()
                k = KU.parse(p)
                if k.jumlah_soal == 0:
                    gagal.append(p.name)
                    continue
                cara[k.cara] = cara.get(k.cara, 0) + 1
                notes = list(k.masalah)
                if notes:
                    problems.append(f"&bull; <b>{p.name}</b>: {'; '.join(notes)}")
                if k.cara == KU.CARA_2:
                    notes.append("dibaca dengan cara 2 ('Jawaban: X' di awal baris)")
                self._append("", KU.suggest_name(p), k.kunci, "; ".join(notes), sumber=str(p),
                             warn=bool(k.masalah))
        finally:
            self.table.blockSignals(False)
            QApplication.restoreOverrideCursor()
        self._set_dirty(True)
        n_ok = len(pdfs) - len(gagal)
        msg = (f"{n_ok} dari {len(pdfs)} PDF terbaca: {cara[KU.CARA_1]} dengan cara 1 (<i>Kunci Jawaban: X</i>), "
               f"{cara[KU.CARA_2]} dengan cara 2 (<i>Jawaban: X</i> di awal baris).<br>"
               "Isi kolom <b>Kode Naskah</b>, periksa <b>Nama Bidang</b>, lalu klik <b>Simpan kunci</b>.")
        if gagal:
            msg += "<br><br>Kunci tidak ditemukan di: " + ", ".join(gagal)
        if problems:
            msg += ("<br><br>Perlu diperhatikan (kunci tetap terbaca; baris Catatan berwarna):<br>"
                    + "<br>".join(problems))
        QMessageBox.information(self, "Impor PDF", msg)

    def _import_excel(self):
        if self.event_id is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "File kunci (Excel)", "", "Excel (*.xlsx)")
        if not path:
            return
        try:
            soal = NI.load_kunci(path)
        except Exception as e:  # file bukan format kunci
            QMessageBox.warning(self, "Impor Excel", f"File tidak bisa dibaca sebagai file kunci:\n{e}")
            return
        existing = {r[0]: i for i, r in enumerate(self._rows())}
        self.table.blockSignals(True)
        for s in soal.values():
            kunci = re.sub(r"[\s,;|/]", "", s.kunci)     # pemisah yang diketik di Excel ("A, B, C") bukan kunci
            if s.kode in existing:
                r = existing[s.kode]
                self.table.item(r, COL_BIDANG).setText(s.bidang)
                self.table.item(r, COL_KUNCI).setText(kunci)
                self.table.item(r, COL_KUNCI).setData(Qt.UserRole, s.sumber)
                self.table.item(r, COL_JUMLAH).setText(str(len(kunci)))
            else:
                self._append(s.kode, s.bidang, kunci, sumber=s.sumber)
        self.table.blockSignals(False)
        self._set_dirty(True)
        QMessageBox.information(self, "Impor Excel", f"{len(soal)} kode naskah dimuat. Klik Simpan kunci.")
