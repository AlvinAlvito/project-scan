"""Penampil gambar lembar: zoom dengan roda mouse, geser dengan seret, tandai titik."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from app import theme

# Lebar gambar cek versi lama (0,75x bingkai baku). Zoom "lompat ke catatan" dan ukuran
# lingkaran penanda diskalakan terhadap ini, jadi gambar lama & baru tampil sama besar.
LEBAR_ACUAN = 1140.0


class ImageView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self._themed()
        theme.bus.changed.connect(self._themed)
        self._marker = None
        self._unit = 1.0
        self._item = None
        self._original = QPixmap()

    def _themed(self):
        self.setBackgroundBrush(QColor(theme.c("canvas")))

    def set_image(self, path):
        self.scene().clear()
        self._marker = self._item = None
        pm = QPixmap(str(path)) if path else QPixmap()
        self._original = pm
        if pm.isNull():
            self.scene().addText("Gambar tidak tersedia").setDefaultTextColor(QColor(theme.c("muted")))
            self._unit = 1.0
        else:
            self._item = self.scene().addPixmap(pm)
            # Bawaan Qt "Fast" (tetangga terdekat) membuat gambar bergerigi/kabur saat diperkecil/diperbesar.
            self._item.setTransformationMode(Qt.SmoothTransformation)
            self._unit = pm.width() / LEBAR_ACUAN
        self.setSceneRect(self.scene().itemsBoundingRect())
        self.fit()

    def show_pixmap(self, pm):
        """Ganti gambar yang tampil (ukuran sama, mis. versi hitam-putih) tanpa mengubah zoom & posisi."""
        if self._item is not None and not pm.isNull():
            self._item.setPixmap(pm)

    def show_original(self):
        self.show_pixmap(self._original)

    def fit(self):
        self.resetTransform()
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def zoom(self, factor):
        self.scale(factor, factor)

    def current_zoom(self):
        """Zoom sekarang dalam satuan focus(), supaya pindah titik tidak mengubah zoom pilihan pengguna."""
        return self.transform().m11() * self._unit

    def wheelEvent(self, event):
        self.zoom(1.25 if event.angleDelta().y() > 0 else 0.8)

    def focus(self, x, y, zoom=1.8):
        """Perbesar ke titik (x, y) dan beri lingkaran penanda."""
        if self._marker is not None:
            self.scene().removeItem(self._marker)
            self._marker = None
        if x is None or y is None:
            self.fit()
            return
        self.resetTransform()
        self.scale(zoom / self._unit, zoom / self._unit)
        self.centerOn(x, y)
        r = 34 * self._unit
        self._marker = self.scene().addEllipse(x - r, y - r, 2 * r, 2 * r, QPen(QColor(theme.c("accent")), 4 * self._unit))
