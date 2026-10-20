"""Editor kunci jawaban satu bidang, per nomor soal (tampilan mirip LJK: blok 30 nomor, pilihan A-E)."""
import re
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from app import theme
from app.colors import paint
from app.widgets import ToneDelegate

LETTERS = "ABCDE"
BLOCK = 30
ROW_H, NO_W, OPT_W = 28, 46, 36


class KeyBlock(QTableWidget):
    """Satu blok nomor soal [start, end). Klik pilihan atau ketik A-E untuk mengisi kunci."""
    picked = Signal(int, str)   # indeks soal, huruf

    def __init__(self, start, end):
        super().__init__(end - start, 6)
        self.start = start
        self.setHorizontalHeaderLabels(["No", *LETTERS])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setShowGrid(False)
        self.setItemDelegate(ToneDelegate(self, pill=True))
        self.setFrameShape(QFrame.NoFrame)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.horizontalHeader().setHighlightSections(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setColumnWidth(0, NO_W)
        for c in range(1, 6):
            self.setColumnWidth(c, OPT_W)
        for r in range(end - start):
            self.setRowHeight(r, ROW_H)
            num = QTableWidgetItem(str(start + r + 1))
            num.setTextAlignment(Qt.AlignCenter)
            f = num.font()
            f.setBold(True)
            num.setFont(f)
            self.setItem(r, 0, num)
            for c, ch in enumerate(LETTERS, 1):
                it = QTableWidgetItem(ch)
                it.setTextAlignment(Qt.AlignCenter)
                self.setItem(r, c, it)
        self.setFixedWidth(NO_W + 5 * OPT_W + 8)
        self.setFixedHeight(ROW_H * (end - start) + 40)
        self.cellClicked.connect(self._click)

    def show_value(self, q, letter, changed):
        r = q - self.start
        for c, ch in enumerate(LETTERS, 1):
            it = self.item(r, c)
            paint(it, "chosen" if ch == letter else None)
            f = it.font()
            f.setBold(ch == letter)
            it.setFont(f)
        paint(self.item(r, 0), "warn" if changed else None)

    def _click(self, r, c):
        if c >= 1:
            self.picked.emit(self.start + r, LETTERS[c - 1])

    def keyPressEvent(self, e):
        ch = e.text().upper()
        r = self.currentRow()
        if ch and ch in LETTERS and r >= 0:
            self.picked.emit(self.start + r, ch)
            if r + 1 < self.rowCount():
                self.setCurrentCell(r + 1, self.currentColumn())
            return
        super().keyPressEvent(e)


class KunciDialog(QDialog):
    def __init__(self, parent, kode, bidang, kunci, sumber=""):
        super().__init__(parent)
        self.setWindowTitle(f"Kunci Jawaban - {bidang or 'bidang baru'}")
        self.original = kunci
        self.kunci = list(kunci)
        self.sumber = sumber
        self.blocks = []

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(14)
        title = QLabel(f"Kunci jawaban · {bidang}" if bidang else "Bidang baru")
        title.setProperty("role", "title")
        v.addWidget(title)
        form = QFormLayout()
        form.setSpacing(10)
        self.f_kode = QLineEdit(kode)
        self.f_bidang = QLineEdit(bidang)
        self.f_jumlah = QSpinBox()
        self.f_jumlah.setRange(1, 180)
        self.f_jumlah.setValue(max(len(kunci), 1))
        self.f_jumlah.valueChanged.connect(self._resize)
        form.addRow("Kode naskah", self.f_kode)
        form.addRow("Nama bidang", self.f_bidang)
        form.addRow("Jumlah soal", self.f_jumlah)
        self.f_text = QLineEdit(kunci)
        self.f_text.setFont(theme.mono())
        self.f_text.setToolTip("Kunci lengkap sebagai teks; bisa ditempel (paste). Hanya huruf A-E yang dipakai.")
        self.f_text.textEdited.connect(self._text_edited)
        form.addRow("Kunci (teks)", self.f_text)
        v.addLayout(form)
        hint = QLabel("Klik huruf, atau pilih nomor lalu ketik A–E. Nomor yang diubah ditandai oranye.")
        hint.setProperty("role", "muted")
        v.addWidget(hint)

        self.grid_host = QWidget()
        self.grid = QHBoxLayout(self.grid_host)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_host)
        v.addWidget(scroll, 1)

        self.info = QLabel("")
        self.info.setProperty("role", "muted")
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_pdf = theme.button("Buka PDF sumber", "file-text",
                                    tip=sumber or "Kunci ini tidak diimpor dari PDF",
                                    slot=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(sumber)))
        self.btn_pdf.setEnabled(bool(sumber) and Path(sumber).exists())
        bar.addWidget(self.btn_pdf)
        bar.addStretch()
        bar.addWidget(theme.button("Batal", variant="ghost", slot=self.reject))
        ok = theme.button("Simpan", "save", "primary", slot=self._ok)
        ok.setDefault(True)
        bar.addWidget(ok)
        v.addLayout(bar)
        self._build()
        self.resize(980, 860)

    # ---- grid
    def _build(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.blocks = []
        n = len(self.kunci)
        for s in range(0, n, BLOCK):
            b = KeyBlock(s, min(s + BLOCK, n))
            b.picked.connect(self._pick)
            self.grid.addWidget(b, 0, Qt.AlignTop)
            self.blocks.append(b)
        for q in range(n):
            self._show(q)
        self._update_info()

    def _show(self, q):
        changed = q >= len(self.original) or self.kunci[q] != self.original[q]
        self.blocks[q // BLOCK].show_value(q, self.kunci[q], changed)

    def _pick(self, q, letter):
        self.kunci[q] = letter
        self._show(q)
        self.f_text.setText("".join(ch or "?" for ch in self.kunci))
        self._update_info()

    def _resize(self, n):
        if n == len(self.kunci):
            return
        self.kunci = (self.kunci + [""] * n)[:n]
        self.f_text.setText("".join(ch or "?" for ch in self.kunci))
        self._build()

    def _text_edited(self, text):
        clean = re.sub(r"[^A-Ea-e?]", "", text).upper()
        new = [("" if ch == "?" else ch) for ch in clean][:180]
        if not new:
            return
        self.kunci = new
        self.f_jumlah.blockSignals(True)
        self.f_jumlah.setValue(len(new))
        self.f_jumlah.blockSignals(False)
        self._build()

    def _update_info(self):
        n = len(self.kunci)
        empty = [str(q + 1) for q, ch in enumerate(self.kunci) if not ch]
        diff = [str(q + 1) for q in range(min(n, len(self.original))) if self.kunci[q] != self.original[q]]
        parts = [f"{n} soal"]
        if diff:
            parts.append(f"diubah: soal {', '.join(diff)}")
        if len(self.original) and n != len(self.original):
            parts.append(f"jumlah soal berubah dari {len(self.original)}")
        if empty:
            parts.append(f"<span style='color:{theme.tone_hex('error')[1]}'>belum diisi: soal {', '.join(empty)}</span>")
        self.info.setText("  |  ".join(parts))

    def _ok(self):
        if not self.f_kode.text().strip() or not self.f_bidang.text().strip():
            QMessageBox.warning(self, "Kunci", "Kode naskah dan nama bidang wajib diisi.")
            return
        empty = [str(q + 1) for q, ch in enumerate(self.kunci) if not ch]
        if empty:
            QMessageBox.warning(self, "Kunci", f"Kunci soal berikut belum diisi: {', '.join(empty)}")
            return
        self.accept()

    def values(self):
        return self.f_kode.text().strip(), self.f_bidang.text().strip(), "".join(self.kunci)
