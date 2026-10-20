"""Editor kunci jawaban satu bidang, per nomor soal (tampilan mirip LJK: blok 30 nomor, pilihan A-E)."""
import re
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from app.colors import paint

LETTERS = "ABCDE"
BLOCK = 30
CHOSEN = QColor(52, 120, 220)
CHANGED = QColor(255, 216, 168)


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
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.setColumnWidth(0, 44)
        for c in range(1, 6):
            self.setColumnWidth(c, 34)
        for r in range(end - start):
            self.setRowHeight(r, 24)
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
        w = 44 + 5 * 34 + 4
        self.setFixedWidth(w)
        self.setFixedHeight(min(24 * (end - start) + self.horizontalHeader().height() + 4, 24 * BLOCK + 30))
        self.cellClicked.connect(self._click)

    def show_value(self, q, letter, changed):
        r = q - self.start
        for c, ch in enumerate(LETTERS, 1):
            it = self.item(r, c)
            if ch == letter:
                it.setBackground(CHOSEN)
                it.setForeground(QColor("white"))
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            else:
                paint(it, None)
                f = it.font()
                f.setBold(False)
                it.setFont(f)
        paint(self.item(r, 0), CHANGED if changed else None)

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
        form = QFormLayout()
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
        self.f_text.setFont(QFont("Consolas", 10))
        self.f_text.setToolTip("Kunci lengkap sebagai teks; bisa ditempel (paste). Hanya huruf A-E yang dipakai.")
        self.f_text.textEdited.connect(self._text_edited)
        form.addRow("Kunci (teks)", self.f_text)
        v.addLayout(form)
        v.addWidget(QLabel("Klik huruf untuk mengganti kunci, atau pilih nomor lalu ketik A-E (kursor turun "
                           "otomatis). Nomor yang diubah berwarna oranye sampai disimpan."))

        self.grid_host = QWidget()
        self.grid = QHBoxLayout(self.grid_host)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_host)
        v.addWidget(scroll, 1)

        self.info = QLabel("")
        v.addWidget(self.info)
        bar = QHBoxLayout()
        self.btn_pdf = QPushButton("Buka PDF sumber")
        self.btn_pdf.setEnabled(bool(sumber) and Path(sumber).exists())
        self.btn_pdf.setToolTip(sumber or "Sumber PDF tidak diketahui (kunci tidak diimpor dari PDF)")
        self.btn_pdf.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(sumber)))
        bar.addWidget(self.btn_pdf)
        bar.addStretch()
        cancel = QPushButton("Batal")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Simpan")
        ok.setDefault(True)
        ok.setStyleSheet("font-weight: bold")
        ok.clicked.connect(self._ok)
        bar.addWidget(cancel)
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
            parts.append(f"<span style='color:#c0392b'>belum diisi: soal {', '.join(empty)}</span>")
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
