"""Pewarnaan sel tabel menurut "tone" tema (ok, warn, error, info, chosen), ikut berganti saat tema berganti."""
from PySide6.QtCore import Qt

from app import theme


def paint(item, tone):
    """Beri warna penanda pada sel; tone=None -> kembali ke warna tema."""
    item.setData(theme.TONE_ROLE, tone)
    repaint(item)


def repaint(item):
    """Warna teks dari tone; latarnya digambar oleh app.widgets.ToneDelegate."""
    tone = item.data(theme.TONE_ROLE)
    if not tone:
        item.setData(Qt.ForegroundRole, None)
        return
    item.setForeground(theme.tone(tone)[1])
