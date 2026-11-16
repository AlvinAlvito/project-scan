"""Komponen tampilan bersama: tampilan kosong, kartu hitung, lencana status, toolbar yang menyesuaikan lebar."""
from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStyle, QStyledItemDelegate,
                               QVBoxLayout, QWidget)

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


class CountCard(QPushButton):
    """Kartu hitung yang sekaligus penyaring daftar: keterangan kecil di atas angka. Terpilih = tepi warna merek."""

    def __init__(self, caption):
        super().__init__()
        self.setProperty("role", "count")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(56)
        self.setMinimumWidth(64)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(0)
        cap = QLabel(caption)
        cap.setProperty("role", "stat-caption")
        # kartu boleh menyempit di jendela sempit (keterangan terpotong, angka tetap terlihat)
        cap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.value = QLabel("0")
        self.value.setProperty("role", "stat-value")
        for lb in (cap, self.value):
            lb.setAttribute(Qt.WA_TransparentForMouseEvents)
            v.addWidget(lb)
        self.setToolTip(caption)

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


class ShortText:
    """Teks pendek untuk kotak centang/label saat toolbar sempit (dipakai ToolbarFit seperti tombol)."""

    def __init__(self, widget, pendek):
        self.w, self.pendek, self.panjang, self._compact = widget, pendek, widget.text(), False

    def set_compact(self, on):
        if on != self._compact:
            self._compact = on
            self.w.setText(self.pendek if on else self.panjang)
            self.w.setToolTip(self.panjang if on else "")


class ToolbarFit(QObject):
    """Bila toolbar tidak muat di lebar `host`, butir di `items` diringkas berurutan (tombol jadi ikon saja,
    teks jadi pendek) sampai muat; teks kembali saat ruang cukup. `items`: yang paling dulu diringkas
    di depan. Lebar yang tersedia = lebar host dikurangi margin kiri-kanan layout host."""

    def __init__(self, host, row, items, lebar=None):
        """lebar: fungsi opsional yang memberi lebar tersedia (dipakai bila host ada di area gulir, karena host
        tidak pernah lebih sempit dari toolbar-nya sendiri)."""
        super().__init__(host)
        self.host, self.row, self.items, self.lebar = host, row, list(items), lebar
        host.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Resize, QEvent.Show):
            self.fit()
        return False

    def _need(self):
        self.row.invalidate()           # ukuran toolbar tersimpan tidak ikut berubah saat teks tombol diganti
        return self.row.sizeHint().width()

    def fit(self):
        m = self.host.layout().contentsMargins() if self.host.layout() else None
        width = self.lebar() if self.lebar is not None else self.host.width()
        avail = width - (m.left() + m.right() if m else 0)
        for it in reversed(self.items):              # kembalikan teks (prioritas tertinggi dulu) selama muat
            if it._compact:
                it.set_compact(False)
                if self._need() > avail:
                    it.set_compact(True)
                    break
        for it in self.items:
            if self._need() <= avail:
                break
            it.set_compact(True)


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


class WheelGuard(QObject):
    """Roda mouse di atas kotak pilihan (combo) / isian angka / slider yang BELUM diklik tidak mengubah isinya,
    tetapi diteruskan ke tabel/area gulir di belakangnya. Tanpa ini, menggulir tabel jawaban yang tiap barisnya
    berisi combo diam-diam mengganti jawaban dan gulirannya 'nyangkut'. Dipasang sekali di QApplication."""

    TYPES = None

    def eventFilter(self, obj, ev):
        if WheelGuard.TYPES is None:
            from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QSlider
            WheelGuard.TYPES = (QComboBox, QAbstractSpinBox, QSlider)
        t = ev.type()
        if t == QEvent.Polish and isinstance(obj, WheelGuard.TYPES):
            if obj.focusPolicy() == Qt.WheelFocus:      # roda mouse tidak boleh memberi fokus
                obj.setFocusPolicy(Qt.StrongFocus)
        elif t == QEvent.Wheel and isinstance(obj, WheelGuard.TYPES) and not obj.hasFocus():
            self._gulir_induk(obj, ev)
            return True
        return False

    @staticmethod
    def _gulir_induk(obj, ev):
        """Gulirkan area gulir leluhur terdekat yang masih bisa bergerak ke arah roda (tabel, panel data, lalu
        halaman), seperti bila roda diputar di tempat kosong."""
        from PySide6.QtWidgets import QAbstractScrollArea, QApplication
        dy = ev.angleDelta().y()
        if not dy:
            return
        p = obj.parentWidget()
        while p is not None:
            if isinstance(p, QAbstractScrollArea):
                sb = p.verticalScrollBar()
                if (dy < 0 and sb.value() < sb.maximum()) or (dy > 0 and sb.value() > sb.minimum()):
                    step = max(1, sb.singleStep()) * QApplication.wheelScrollLines()
                    sb.setValue(sb.value() - round(dy / 120 * step))
                    return
            p = p.parentWidget()


def pasang_pengaman_roda(app):
    """Pasang WheelGuard di aplikasi (sekali saja)."""
    if getattr(app, "_wheel_guard", None) is None:
        app._wheel_guard = WheelGuard(app)
        app.installEventFilter(app._wheel_guard)
    return app._wheel_guard


def divider():
    f = QFrame()
    f.setProperty("role", "divider")
    f.setFixedHeight(24)
    return f
