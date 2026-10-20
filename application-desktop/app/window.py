"""Jendela utama: daftar event di sidebar kiri, tab Kunci / Scan & Nilai / Cek Manual / Latih di kanan."""
import shutil

from PySide6.QtCore import QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QStackedWidget, QStyle, QStyledItemDelegate, QTabWidget,
                               QVBoxLayout, QWidget)

from app import icons, server_client as SC, theme
from app.kunci_tab import KunciTab
from app.latih_tab import LatihTab
from app.review_tab import ReviewTab
from app.scan_tab import ScanTab
from app.server_dialog import ServerDialog
from app.widgets import EmptyState

TABS = (("key", "Kunci Jawaban"), ("scan", "Scan && Nilai"), ("clipboard-check", "Cek Manual"),
        ("cpu", "Latih Model"))


class EventDialog(QDialog):
    def __init__(self, parent=None, nama="", tanggal=""):
        super().__init__(parent)
        self.setWindowTitle("Ubah Event" if nama else "Event Baru")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(16)
        title = QLabel(self.windowTitle())
        title.setProperty("role", "title")
        v.addWidget(title)
        self.nama = QLineEdit(nama)
        self.nama.setPlaceholderText("FSN PROVINSI PAKET 1")
        self.tanggal = QLineEdit(tanggal)
        self.tanggal.setPlaceholderText("24 September 2026")
        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.addRow("Nama event", self.nama)
        form.addRow("Tanggal", self.tanggal)
        v.addLayout(form)
        bar = QHBoxLayout()
        bar.addStretch()
        bar.addWidget(theme.button("Batal", variant="ghost", slot=self.reject))
        ok = theme.button("Simpan", "check", "primary", slot=self._ok)
        ok.setDefault(True)
        bar.addWidget(ok)
        v.addLayout(bar)
        self.resize(460, 0)

    def _ok(self):
        if not self.nama.text().strip() or not self.tanggal.text().strip():
            QMessageBox.warning(self, "Event", "Nama event dan tanggal wajib diisi.")
            return
        self.accept()

    def values(self):
        return self.nama.text().strip(), self.tanggal.text().strip()


class EventDelegate(QStyledItemDelegate):
    """Baris event di sidebar: nama tebal + tanggal redup, latar membulat saat dipilih/disorot."""

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 58)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(0, 2, 0, -2)
        selected = option.state & QStyle.State_Selected
        if selected or option.state & QStyle.State_MouseOver:
            path = QPainterPath()
            path.addRoundedRect(r, 8, 8)
            p.fillPath(path, QColor(theme.c("side_sel" if selected else "side_hover")))
        if selected:
            p.fillRect(QRectF(r.left(), r.top() + 12, 3, r.height() - 24), QColor(theme.c("accent")))
        nama, tanggal = (index.data(Qt.DisplayRole) or "\n").split("\n", 1)
        f = QFont(option.font)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(theme.c("side_text")))
        text_r = r.adjusted(14, 9, -10, 0)
        p.drawText(text_r, Qt.AlignLeft | Qt.AlignTop,
                   p.fontMetrics().elidedText(nama, Qt.ElideRight, int(text_r.width())))
        f.setWeight(QFont.Normal)
        f.setPointSizeF(f.pointSizeF() * 0.9)
        p.setFont(f)
        p.setPen(QColor(theme.c("side_muted")))
        p.drawText(r.adjusted(14, 0, -10, -9), Qt.AlignLeft | Qt.AlignBottom, tanggal)
        p.restore()


class MainWindow(QMainWindow):
    def __init__(self, db, data_dir):
        super().__init__()
        self.db, self.data_dir = db, data_dir
        self.event_id = None
        self.setWindowTitle("LJK Reader")
        self.resize(1440, 880)
        self.setMinimumSize(1100, 680)

        # ---- sidebar
        side = QWidget()
        side.setObjectName("sidebar")
        side.setAttribute(Qt.WA_StyledBackground, True)
        side.setFixedWidth(264)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(16, 20, 16, 16)
        sv.setSpacing(8)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        self.logo = QLabel()
        self.logo.setFixedSize(38, 38)
        self.logo.setAlignment(Qt.AlignCenter)
        brand.addWidget(self.logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        t = QLabel("LJK Reader")
        t.setProperty("role", "brand")
        s = QLabel("POSI · pembaca LJK")
        s.setProperty("role", "muted")
        names.addWidget(t)
        names.addWidget(s)
        brand.addLayout(names)
        brand.addStretch()
        sv.addLayout(brand)
        sv.addSpacing(18)

        sec = QHBoxLayout()
        lb = QLabel("EVENT")
        lb.setProperty("role", "section")
        sec.addWidget(lb)
        sec.addStretch()
        self.btn_edit = theme.button("", "pencil", "icon", "Ubah event", self._edit_event)
        self.btn_delete = theme.button("", "trash", "icon", "Hapus event", self._delete_event)
        for b in (self.btn_edit, self.btn_delete):
            b.setFixedSize(32, 32)
            b.setIconSize(QSize(16, 16))
            sec.addWidget(b)
        sv.addLayout(sec)

        self.events = QListWidget()
        self.events.setItemDelegate(EventDelegate(self.events))
        self.events.setMouseTracking(True)
        self.events.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.events.currentItemChanged.connect(self._event_selected)
        sv.addWidget(self.events, 1)
        new = theme.button("Event Baru", "plus", "primary", slot=self._new_event)
        sv.addWidget(new)
        sv.addSpacing(10)
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {theme.c('side_hover')}")
        self._side_line = line
        sv.addWidget(line)
        sv.addSpacing(4)
        self.btn_server = theme.button("", "cloud", tip="Koneksi ke server LJK Reader Online", slot=self._server)
        sv.addWidget(self.btn_server)
        folder = theme.button("Folder data", "folder", tip=str(data_dir),
                              slot=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_dir))))
        sv.addWidget(folder)
        self.btn_theme = theme.button("", slot=theme.toggle)
        sv.addWidget(self.btn_theme)

        # ---- isi
        content = QWidget()
        content.setObjectName("content")
        content.setAttribute(Qt.WA_StyledBackground, True)
        cv = QVBoxLayout(content)
        cv.setContentsMargins(28, 22, 28, 18)
        cv.setSpacing(6)
        head = QVBoxLayout()
        head.setSpacing(2)
        self.title = QLabel("")
        self.title.setProperty("role", "title")
        self.subtitle = QLabel("")
        self.subtitle.setProperty("role", "subtitle")
        head.addWidget(self.title)
        head.addWidget(self.subtitle)
        cv.addLayout(head)
        cv.addSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setIconSize(QSize(18, 18))
        self.kunci = KunciTab(db)
        self.scan = ScanTab(db, data_dir)
        self.review = ReviewTab(db)
        self.latih = LatihTab(db, data_dir)
        for w, (_ic, text) in zip((self.kunci, self.scan, self.review, self.latih), TABS):
            self.tabs.addTab(w, text)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.kunci.changed.connect(self.scan.refresh)
        self.scan.open_review.connect(self._open_review)
        self.scan.linked.connect(self._update_header)
        self.review.changed.connect(self.scan.refresh)

        self.empty = EmptyState("calendar", "Belum ada event",
                                "Buat event untuk mulai memasukkan kunci jawaban dan memindai LJK.",
                                theme.button("Buat Event", "plus", "primary", slot=self._new_event))
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.tabs)
        cv.addWidget(self.stack, 1)

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(side)
        h.addWidget(content, 1)
        self.setCentralWidget(root)

        theme.bus.changed.connect(self._theme_changed)
        self._theme_changed()
        self._load_events()

    def _theme_changed(self):
        dark = theme.name() == "gelap"
        theme.set_icon(self.btn_theme, "sun" if dark else "moon")
        self.btn_theme.setText("Tema terang" if dark else "Tema gelap")
        self._update_server_button()
        dpr = self.devicePixelRatioF() or 2.0
        self.logo.setPixmap(icons.pixmap("scan", theme.c("on_accent"), 22, dpr))
        self.logo.setStyleSheet(f"background: {theme.c('accent')}; border-radius: 10px;")
        self._side_line.setStyleSheet(f"background: {theme.c('side_hover')}")
        for i, (ic, _t) in enumerate(TABS):
            self.tabs.setTabIcon(i, icons.icon(ic, theme.c("icon"), theme.c("faint")))
        self.events.viewport().update()
        theme.refresh_all()

    # ---- event
    def _load_events(self, select=None):
        self.events.blockSignals(True)
        self.events.clear()
        for ev in self.db.events():
            it = QListWidgetItem(f"{ev['nama']}\n{ev['tanggal']}")
            it.setData(Qt.UserRole, ev["id"])
            it.setToolTip(ev["nama"])
            self.events.addItem(it)
        self.events.blockSignals(False)
        if self.events.count():
            idx = 0
            for i in range(self.events.count()):
                if self.events.item(i).data(Qt.UserRole) == select:
                    idx = i
            self.events.setCurrentRow(idx)
        else:
            self._set_event(None)

    def _event_selected(self, cur, _prev):
        self._set_event(cur.data(Qt.UserRole) if cur else None)

    def _set_event(self, event_id):
        self.event_id = event_id
        has = event_id is not None
        self.stack.setCurrentWidget(self.tabs if has else self.empty)
        self.btn_edit.setEnabled(has)
        self.btn_delete.setEnabled(has)
        self._update_header()
        self.latih.load(event_id)
        self.kunci.load(event_id)
        self.scan.load(event_id)
        self.review.load(event_id)

    def _update_header(self):
        if self.event_id is None:
            self.title.setText("Selamat datang")
            self.subtitle.setText("Pembaca Lembar Jawaban Komputer POSI")
            return
        ev = self.db.event(self.event_id)
        self.title.setText(ev["nama"])
        linked = ev["server_kompetisi_id"] and ev["server_url"]
        self.subtitle.setText(ev["tanggal"] + (f"  ·  terhubung ke server (kompetisi #{ev['server_kompetisi_id']})"
                                               if linked else ""))

    def _update_server_button(self):
        c = SC.config()
        self.btn_server.setText(f"Server · {c['nama']}" if SC.logged_in() else "Hubungkan server")

    def _server(self):
        ServerDialog(self).exec()
        self._update_server_button()

    def _new_event(self):
        d = EventDialog(self)
        if d.exec():
            eid = self.db.add_event(*d.values())
            self._load_events(select=eid)
            self.tabs.setCurrentIndex(0)

    def _edit_event(self):
        if self.event_id is None:
            return
        ev = self.db.event(self.event_id)
        d = EventDialog(self, ev["nama"], ev["tanggal"])
        if d.exec():
            self.db.update_event(self.event_id, *d.values())
            self._load_events(select=self.event_id)

    def _delete_event(self):
        if self.event_id is None:
            return
        ev = self.db.event(self.event_id)
        n = len(self.db.lembar(self.event_id))
        if QMessageBox.question(self, "Hapus event",
                                f"Hapus event '{ev['nama']}' beserta kunci dan {n} lembar hasil scan?\n"
                                "Foto asli tidak ikut terhapus.") != QMessageBox.Yes:
            return
        shutil.rmtree(self.data_dir / "event" / str(self.event_id), ignore_errors=True)
        self.db.delete_event(self.event_id)
        self._load_events()

    # ---- tab
    def _tab_changed(self, idx):
        if self.tabs.widget(idx) is self.scan:
            self.scan.refresh()
        elif self.tabs.widget(idx) is self.review:
            self.review.activate()

    def _open_review(self, lembar_id):
        self.tabs.setCurrentWidget(self.review)
        self.review.show_lembar(lembar_id)

    def closeEvent(self, e):
        if self.scan.busy():
            QMessageBox.information(self, "LJK Reader", "Tunggu proses scan selesai dulu.")
            e.ignore()
            return
        if not self.review.confirm_leave():
            e.ignore()
            return
        super().closeEvent(e)
