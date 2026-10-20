"""Komponen tampilan bersama: tampilan kosong, kartu angka, lencana status."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget

from app import icons, theme


class EmptyState(QWidget):
    """Ikon besar + judul + keterangan + (opsional) tombol, di tengah area."""

    def __init__(self, icon_name, title, text="", action=None):
        super().__init__()
        self.icon_name = icon_name
        v = QVBoxLayout(self)
        v.addStretch()
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignCenter)
        v.addWidget(self.icon)
        v.addSpacing(8)
        self.title = QLabel(title)
        self.title.setProperty("role", "empty-title")
        self.title.setAlignment(Qt.AlignCenter)
        v.addWidget(self.title)
        self.text = QLabel(text)
        self.text.setProperty("role", "muted")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setWordWrap(True)
        self.text.setVisible(bool(text))
        v.addWidget(self.text)
        if action is not None:
            v.addSpacing(10)
            row = QHBoxLayout()
            row.addStretch()
            row.addWidget(action)
            row.addStretch()
            v.addLayout(row)
        v.addStretch()
        theme.bus.changed.connect(self._paint)
        self._paint()

    def set_text(self, title, text=""):
        self.title.setText(title)
        self.text.setText(text)
        self.text.setVisible(bool(text))

    def _paint(self):
        self.icon.setPixmap(icons.pixmap(self.icon_name, theme.c("faint"), 52, self.devicePixelRatioF() or 2.0))


class StatCard(QFrame):
    """Kartu kecil: angka besar + keterangan."""

    def __init__(self, caption, tone=None):
        super().__init__()
        self.setProperty("role", "stat")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 10, 16, 10)
        v.setSpacing(0)
        self.value = QLabel("0")
        self.value.setProperty("role", "stat-value")
        if tone:
            self.value.setProperty("tone", tone)
        cap = QLabel(caption)
        cap.setProperty("role", "stat-caption")
        v.addWidget(self.value)
        v.addWidget(cap)

    def set(self, n):
        self.value.setText(str(n))


class ToneDelegate(QStyledItemDelegate):
    """Menggambar latar penanda (tone) sel sebagai blok membulat. Stylesheet tabel mengabaikan
    BackgroundRole biasa, jadi latar tone digambar di sini sebelum teks."""

    def __init__(self, parent=None, pill=False):
        super().__init__(parent)
        self.pill = pill

    def paint(self, p, option, index):
        tone = index.data(theme.TONE_ROLE)
        if tone and not option.state & QStyle.State_Selected:
            bg, _fg = theme.tone(tone)
            p.save()
            p.setRenderHint(QPainter.Antialiasing)
            r = QRectF(option.rect).adjusted(4, 5, -4, -5) if self.pill else QRectF(option.rect).adjusted(1, 1, -1, -1)
            path = QPainterPath()
            rad = min(r.height() / 2, 10) if self.pill else 4
            path.addRoundedRect(r, rad, rad)
            p.fillPath(path, bg)
            p.restore()
        super().paint(p, option, index)


def setup_table(table, row_height=40, pill=False):
    """Gaya tabel seragam: tanpa garis kisi, baris lega, pilih per baris."""
    table.setItemDelegate(ToneDelegate(table, pill))
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    table.horizontalHeader().setMinimumHeight(38)
    table.setFrameShape(QFrame.NoFrame)


def toolbar(spacing=8):
    h = QHBoxLayout()
    h.setSpacing(spacing)
    h.setContentsMargins(0, 0, 0, 0)
    return h


def badge(text="", tone="neutral"):
    lb = QLabel(text)
    lb.setProperty("role", "badge")
    lb.setProperty("tone", tone)
    return lb


def set_badge(lb, text, tone):
    lb.setText(text)
    lb.setVisible(bool(text))
    if lb.property("tone") != tone:
        lb.setProperty("tone", tone)
        theme.repolish(lb)


def divider():
    f = QFrame()
    f.setProperty("role", "divider")
    f.setFixedHeight(24)
    return f
