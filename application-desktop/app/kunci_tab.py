"""Tab 1: kunci jawaban per kode naskah untuk event yang dipilih."""
import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ljk import kunci as KU
from app.colors import paint
from app.kunci_dialog import KunciDialog
from ljk import nilai as NI

COL_KODE, COL_BIDANG, COL_JUMLAH, COL_KUNCI, COL_CATATAN = range(5)
WARN = QColor(255, 216, 168)


class KunciTab(QWidget):
    changed = Signal()

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.event_id = None
        self._dirty = False

        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "Daftarkan setiap <b>kode naskah</b> yang dipakai di event ini beserta <b>nama bidang</b> "
            "(dipakai sebagai nama sheet di Excel, mis. <i>EKONOMI SMA</i>) dan <b>kuncinya</b> "
            "(satu huruf A-E per soal). Jumlah soal dihitung otomatis dari panjang kunci."))
        bar = QHBoxLayout()
        for text, slot in (("Impor dari PDF pembahasan...", self._import_pdf),
                           ("Impor dari Excel...", self._import_excel),
                           ("Edit kunci per nomor...", self._edit_current),
                           ("Tambah bidang", self._add_row), ("Hapus baris", self._del_rows)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch()
        self.state = QLabel("")
        bar.addWidget(self.state)
        self.save_btn = QPushButton("Simpan kunci")
        self.save_btn.setStyleSheet("font-weight: bold")
        self.save_btn.clicked.connect(self.save)
        bar.addWidget(self.save_btn)
        v.addLayout(bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Kode Naskah", "Nama Bidang", "Jumlah Soal", "Kunci", "Catatan"])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(COL_KODE, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_BIDANG, QHeaderView.Interactive)
        h.setSectionResizeMode(COL_JUMLAH, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_KUNCI, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_CATATAN, QHeaderView.Interactive)
        self.table.setColumnWidth(COL_CATATAN, 320)
        self.table.setColumnWidth(COL_BIDANG, 220)
        self.table.itemChanged.connect(self._item_changed)
        self.table.cellDoubleClicked.connect(self._double_click)
        v.addWidget(self.table)
        v.addWidget(QLabel("Klik dua kali kolom Jumlah Soal / Kunci / Catatan untuk mengedit kunci per nomor soal. "
                           "Kode Naskah dan Nama Bidang bisa diedit langsung di tabel."))

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
        ki.setFont(QFont("Consolas", 10))
        ki.setFlags(ki.flags() & ~Qt.ItemIsEditable)      # diedit lewat editor per nomor
        ki.setData(Qt.UserRole, sumber)
        self.table.setItem(r, COL_KUNCI, ki)
        ci = QTableWidgetItem(note)
        ci.setFlags(ci.flags() & ~Qt.ItemIsEditable)
        ci.setToolTip(note)
        self.table.setItem(r, COL_CATATAN, ci)
        if note and (warn is None or warn):
            paint(ci, WARN)

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
        self.state.setText("<span style='color:#c0392b'>Belum disimpan</span>" if dirty else "")

    def confirm_leave(self):
        return not self._dirty

    def _rows(self):
        out = []
        for r in range(self.table.rowCount()):
            get = lambda c: (self.table.item(r, c).text().strip() if self.table.item(r, c) else "")  # noqa: E731
            ki = self.table.item(r, COL_KUNCI)
            src = (ki.data(Qt.UserRole) if ki else "") or ""
            out.append((get(COL_KODE), get(COL_BIDANG), get(COL_KUNCI).upper(), src))
        return out

    def save(self):
        if self.event_id is None:
            return
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
            seen.add(kode)
            soal.append(NI.Soal(kode, bidang, kunci, sumber))
        if errors:
            QMessageBox.warning(self, "Kunci belum bisa disimpan", "\n".join(errors))
            return
        self.db.set_naskah(self.event_id, soal)
        self.load(self.event_id)          # muat ulang, urut menurut kode naskah
        self.changed.emit()
        QMessageBox.information(self, "Kunci", f"{len(soal)} kode naskah tersimpan.")

    # ---- editor per nomor
    def _double_click(self, r, c):
        if c in (COL_JUMLAH, COL_KUNCI, COL_CATATAN):
            self._edit_row(r)

    def _edit_current(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Kunci", "Pilih dulu baris bidang yang kuncinya akan diedit.")
            return
        self._edit_row(r)

    def _edit_row(self, r, new=False):
        kode, bidang, kunci, sumber = self._rows()[r]
        d = KunciDialog(self, kode, bidang, kunci, sumber)
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
            if s.kode in existing:
                r = existing[s.kode]
                self.table.item(r, COL_BIDANG).setText(s.bidang)
                self.table.item(r, COL_KUNCI).setText(s.kunci)
                self.table.item(r, COL_KUNCI).setData(Qt.UserRole, s.sumber)
                self.table.item(r, COL_JUMLAH).setText(str(len(s.kunci)))
            else:
                self._append(s.kode, s.bidang, s.kunci, sumber=s.sumber)
        self.table.blockSignals(False)
        self._set_dirty(True)
        QMessageBox.information(self, "Impor Excel", f"{len(soal)} kode naskah dimuat. Klik Simpan kunci.")
