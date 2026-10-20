"""Pewarnaan sel tabel yang tetap terbaca di tema terang maupun gelap Windows."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

DARK_TEXT = QColor(25, 25, 25)


def paint(item, color):
    """Beri latar warna (teks dibuat gelap); color=None -> kembali ke warna tema."""
    if color is None:
        item.setData(Qt.BackgroundRole, None)
        item.setData(Qt.ForegroundRole, None)
    else:
        item.setBackground(color)
        item.setForeground(DARK_TEXT)
