"""Jendela utama: bilah atas (merek, cari, server), daftar event di sidebar kiri, dan lembar putih berisi
tab Kunci / Scan & Nilai (antrean + cek manual) / Latih di kanan."""
import html
import shutil

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QKeySequence, QPainter, QPainterPath, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QStackedWidget, QStyle,
                               QStyledItemDelegate, QTabWidget, QVBoxLayout, QWidget)

from app import icons, server_client as SC, server_link as SL, theme
from app.kunci_tab import KunciTab
from app.latih_tab import LatihTab
from app.scan_tab import ScanTab
from app.server_dialog import ServerDialog
from app.widgets import EmptyState

TABS = (("Kunci jawaban", "Kunci"), ("Scan && nilai", "Scan"), ("Latih model", "Latih"))     # nama, nama pendek
SIDEBAR_W = 228
TOPBAR_H = 48
COUNT = Qt.UserRole + 1         # jumlah lembar perlu cek pada baris event (hanya event yang dibuka)
# Jendela lebih sempit dari ini (mis. setengah layar laptop): sidebar disembunyikan dan dibuka sebagai panel
# melayang lewat tombol di kiri judul, nama tab dipendekkan, tombol kepala halaman jadi ikon.
SEMPIT = 1000


class KompetisiLoader(QThread):
    """Ambil daftar kompetisi server di latar belakang supaya jendela tidak macet."""
    done = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            self.done.emit(SC.kompetisi())
        except SC.ServerError as e:
            self.failed.emit(str(e))


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
    """Baris event di sidebar: nama + tanggal redup; terpilih = latar abu-abu membulat. Event yang dibuka
    menampilkan jumlah lembar yang masih perlu dicek di kanan."""

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 52)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(0, 1, 0, -1)
        selected = option.state & QStyle.State_Selected
        if selected or option.state & QStyle.State_MouseOver:
            path = QPainterPath()
            path.addRoundedRect(r, 8, 8)
            p.fillPath(path, QColor(theme.c("side_sel" if selected else "side_hover")))
        nama, tanggal = (index.data(Qt.DisplayRole) or "\n").split("\n", 1)
        n = index.data(COUNT)
        f = QFont(option.font)
        p.setFont(f)
        right = r.right() - 10
        if n:
            w = p.fontMetrics().horizontalAdvance(str(n))
            p.setPen(QColor(theme.c("side_text")))
            p.drawText(QRectF(right - w, r.top() + 7, w, 20), Qt.AlignRight | Qt.AlignVCenter, str(n))
            right -= w + 10
        p.setPen(QColor(theme.c("side_text")))
        text_r = QRectF(r.left() + 10, r.top() + 7, right - r.left() - 10, 20)
        p.drawText(text_r, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(nama, Qt.ElideRight, int(text_r.width())))
        f.setPointSizeF(f.pointSizeF() * 0.9)
        p.setFont(f)
        p.setPen(QColor(theme.c("side_muted")))
        p.drawText(QRectF(r.left() + 10, r.top() + 27, r.width() - 20, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(tanggal, Qt.ElideRight, int(r.width() - 20)))
        p.restore()


class MainWindow(QMainWindow):
    def __init__(self, db, data_dir):
        super().__init__()
        self.db, self.data_dir = db, data_dir
        self.event_id = None
        self._summary = None
        self.setWindowTitle("LJK Reader")
        self.resize(1440, 880)
        self.setMinimumSize(640, 560)

        self.kunci = KunciTab(db)
        self.scan = ScanTab(db, data_dir)
        self.latih = LatihTab(db, data_dir)

        # ---- bilah atas: merek, cari lembar, server
        top = QWidget()
        top.setObjectName("topbar")
        top.setAttribute(Qt.WA_StyledBackground, True)
        top.setFixedHeight(TOPBAR_H)
        th = QHBoxLayout(top)
        th.setContentsMargins(20, 0, 16, 0)
        th.setSpacing(10)
        brand = QWidget()
        brand.setFixedWidth(SIDEBAR_W - 20)
        bh = QHBoxLayout(brand)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(10)
        self.logo = QLabel()
        self.logo.setFixedSize(24, 24)
        self.logo.setAlignment(Qt.AlignCenter)
        name = QLabel("LJK Reader")
        name.setProperty("role", "brand")
        bh.addWidget(self.logo)
        bh.addWidget(name)
        bh.addStretch()
        th.addWidget(brand)
        th.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Cari peserta, nomor, atau kode naskah")
        self.search.setToolTip("Saring antrean Scan & nilai (Ctrl+K)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(160)
        self.search.setMaximumWidth(548)
        self._search_act = self.search.addAction(icons.icon("search", theme.c("muted")), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._search_changed)
        th.addWidget(self.search, 4)
        th.addStretch(1)
        self.btn_server = theme.button("", "cloud", "ghost", "Koneksi ke server LJK Reader Online", self._server)
        self.btn_sync = theme.button("Sinkron", "cloud-download", tip="Tarik LJK yang dikirim admin daerah lewat HP",
                                     slot=self.scan.sync)
        th.addWidget(self.btn_server)
        th.addWidget(self.btn_sync)
        for seq in ("Ctrl+K", "Ctrl+F"):
            QShortcut(QKeySequence(seq), self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))

        # ---- sidebar: daftar event di atas bingkai
        side = self.side = QWidget()
        side.setObjectName("sidebar")
        side.setAttribute(Qt.WA_StyledBackground, True)
        side.setFixedWidth(SIDEBAR_W)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 10, 12, 14)
        sv.setSpacing(4)
        sec = QHBoxLayout()
        sec.setContentsMargins(8, 0, 0, 0)
        sec.setSpacing(2)
        lb = QLabel("Event")
        lb.setProperty("role", "section")
        sec.addWidget(lb)
        sec.addStretch()
        new = theme.button("", "plus", "icon", "Event baru", self._new_event)
        self.btn_ev_more = theme.button("", "more", "icon", "Tindakan event")
        menu = QMenu(self.btn_ev_more)
        self.act_refresh = menu.addAction("Ambil kompetisi terbaru dari server",
                                          lambda: self._sync_server_events(manual=True))
        self.act_push = menu.addAction("Kirim event ke server", self._push_event)
        self.act_edit = menu.addAction("Ubah event…", self._edit_event)
        menu.addSeparator()
        self.act_delete = menu.addAction("Hapus event…", self._delete_event)
        self.btn_ev_more.setMenu(menu)
        self.btn_ev_more.setProperty("menu", False)
        self.btn_ev_more.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0; }")
        for b in (new, self.btn_ev_more):
            b.setFixedSize(28, 28)
            b.setIconSize(QSize(16, 16))
            sec.addWidget(b)
        sv.addLayout(sec)
        sv.addSpacing(4)

        self.events = QListWidget()
        self.events.setItemDelegate(EventDelegate(self.events))
        self.events.setMouseTracking(True)
        self.events.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.events.currentItemChanged.connect(self._event_selected)
        self.events.itemClicked.connect(lambda _it: self._close_side())
        sv.addWidget(self.events, 1)
        folder = theme.button("Folder data", "folder", tip=str(data_dir),
                              slot=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_dir))))
        sv.addWidget(folder)
        self.btn_theme = theme.button("", slot=theme.toggle)
        sv.addWidget(self.btn_theme)

        # ---- lembar putih: judul event + tab
        sheet = QWidget()
        sheet.setObjectName("sheet")
        sheet.setAttribute(Qt.WA_StyledBackground, True)
        cv = QVBoxLayout(sheet)
        cv.setContentsMargins(24, 18, 24, 20)
        cv.setSpacing(0)
        head = QVBoxLayout()
        head.setSpacing(2)
        self.title = QLabel("")
        self.title.setProperty("role", "title")
        self.subtitle = QLabel("")
        self.subtitle.setProperty("role", "subtitle")
        self.subtitle.setTextFormat(Qt.RichText)        # kalimat temuan memakai cetak tebal & pemisah
        for lbl in (self.title, self.subtitle):
            lbl.setWordWrap(True)                       # jendela sempit: turun baris, tidak memaksa lebar
        head.addWidget(self.title)
        head.addWidget(self.subtitle)
        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        self.btn_side = theme.button("", "panel-left", "icon", "Tampilkan daftar event", self._open_side)
        self.btn_side.setVisible(False)
        head_row.addWidget(self.btn_side, 0, Qt.AlignTop)
        head_row.addLayout(head, 1)
        for w in (self.scan.kontras, self.scan.btn_add, self.scan.btn_export):    # pengaturan & tindakan per event
            head_row.addWidget(w, 0, Qt.AlignTop)
        cv.addLayout(head_row)
        cv.addSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        for w, (text, _pendek) in zip((self.kunci, self.scan, self.latih), TABS):
            self.tabs.addTab(w, text)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.kunci.changed.connect(self.scan.refresh)
        self.scan.linked.connect(self._event_linked)
        self.scan.summary.connect(self._on_summary)
        self.scan.running.connect(lambda on: self.btn_sync.setEnabled(not on and self.event_id is not None))

        self.empty = EmptyState("calendar", "Belum ada event",
                                "Buat event untuk mulai memasukkan kunci jawaban dan memindai LJK.",
                                theme.button("Buat event", "plus", "primary", slot=self._new_event))
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.tabs)
        cv.addWidget(self.stack, 1)

        body = self._body = QWidget()
        bl = self._body_layout = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 8, 8)               # lembar menjorok 8 px dari tepi kanan & bawah jendela
        bl.setSpacing(0)
        bl.addWidget(side)
        bl.addWidget(sheet, 1)

        root = self._root = QWidget()
        root.setObjectName("frame")
        root.setAttribute(Qt.WA_StyledBackground, True)
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(top)
        rl.addWidget(body, 1)
        self.setCentralWidget(root)

        theme.bus.changed.connect(self._theme_changed)
        self._theme_changed()
        self._loader = None
        self._sempit = False
        self._load_events()
        self.events.setFocus()                          # bukan kolom cari: fokus awal tidak menyorot apa pun
        self._sync_server_events()

    def _theme_changed(self):
        dark = theme.name() == "gelap"
        theme.set_icon(self.btn_theme, "sun" if dark else "moon")
        self.btn_theme.setText("Tema terang" if dark else "Tema gelap")
        self._search_act.setIcon(icons.icon("search", theme.c("muted")))
        self._update_server_button()
        dpr = self.devicePixelRatioF() or 2.0
        logo = self._logo_pixmap(dpr)
        if logo is not None:
            self.logo.setPixmap(logo)
            self.logo.setStyleSheet("")
        else:                                           # tanpa ikon aplikasi: logo bawaan
            self.logo.setPixmap(icons.pixmap("scan", theme.c("on_accent"), 16, dpr))
            self.logo.setStyleSheet(f"background: {theme.c('accent')}; border-radius: 6px;")
        self.events.viewport().update()
        theme.refresh_all()

    def _logo_pixmap(self, dpr):
        """Logo bilah atas = ikon aplikasi (packaging/ljk_reader.ico, lihat tools/buat_ikon.py), jadi ikut berganti
        bila ikon diganti. Dipakai gambar ukuran kecil terbesar di ikon (<= 64 px: versi potongan untuk ukuran
        kecil, mis. wajah), bukan gambar utuh 128/256 px yang terlalu ramai untuk 24 px. None bila tidak ada ikon."""
        ikon = QApplication.windowIcon()
        kecil = [s for s in ikon.availableSizes() if s.width() <= 64]
        if not kecil:
            return None
        n = max(s.width() for s in kecil)
        px = round(self.logo.width() * dpr)
        pm = ikon.pixmap(QSize(n, n), 1.0).scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        return pm

    # ---- event
    @staticmethod
    def _event_text(ev):
        srv = " · server" if ev["server_kompetisi_id"] and ev["server_url"] else ""
        return f"{ev['nama']}\n{ev['tanggal']}{srv}"

    def _load_events(self, select=None):
        self.events.blockSignals(True)
        self.events.clear()
        for ev in self.db.events():
            it = QListWidgetItem(self._event_text(ev))
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
        self._summary = None
        has = event_id is not None
        self.stack.setCurrentWidget(self.tabs if has else self.empty)
        for a in (self.act_push, self.act_edit, self.act_delete):
            a.setEnabled(has)
        for w in (self.scan.kontras, self.scan.btn_add, self.scan.btn_export):
            w.setVisible(has)
        self.btn_sync.setEnabled(has and not self.scan.busy())
        self._update_header()
        self.latih.load(event_id)
        self.kunci.load(event_id)
        self.scan.load(event_id)

    def _on_summary(self, s):
        """Jumlah lembar per status dari tab Scan: kalimat temuan di bawah judul + angka di baris event."""
        self._summary = s
        self._update_header()
        it = self.events.currentItem()
        if it is not None:
            it.setData(COUNT, s.get("Perlu cek", 0))

    def _finding(self):
        s = self._summary
        if not s:
            return ""
        total, perlu, gagal = s["Semua"], s["Perlu cek"], s["Gagal"]
        siap = s["OK"] + s["Sudah dicek"]
        if not total:
            return "belum ada lembar"
        ink = theme.c("text")
        if siap == total:
            return f"<span style='color:{ink}; font-weight:600'>semua {total} lembar siap diekspor</span>"
        parts = [f"{perlu} perlu cek"] if perlu else []
        if gagal:
            parts.append(f"{gagal} gagal dibaca")
        if s.get("tanpa_nilai"):
            parts.append(f"{s['tanpa_nilai']} tanpa nilai (kode naskah belum terdaftar)")
        return (f"<span style='color:{ink}; font-weight:600'>{siap} dari {total} lembar siap diekspor</span>"
                + (f"; {', '.join(parts)}" if parts else ""))

    def _update_header(self):
        if self.event_id is None:
            self.title.setText("Selamat datang")
            self.subtitle.setText("Pembaca Lembar Jawaban Komputer POSI")
            return
        ev = self.db.event(self.event_id)
        self.title.setText(ev["nama"])
        linked = ev["server_kompetisi_id"] and ev["server_url"]
        parts = [html.escape(ev["tanggal"]), self._finding()]
        if linked:
            parts.append(f"terhubung ke server (kompetisi #{ev['server_kompetisi_id']})")
        self.subtitle.setText(" &nbsp;·&nbsp; ".join(p for p in parts if p))
        self.act_push.setText("Kirim bidang baru ke server" if linked else "Kirim event ke server")
        self.act_push.setToolTip("Kirim bidang baru dari Kunci Jawaban ke kompetisi server" if linked else
                                 "Kirim event ke server (menjadi kompetisi)")

    def _update_server_button(self):
        c = SC.config()
        self.btn_server.setText(f"Server · {c['nama']}" if SC.logged_in() else "Hubungkan server")

    def _server(self):
        ServerDialog(self).exec()
        self._update_server_button()
        self._sync_server_events()

    def _search_changed(self, text):
        if text and self.tabs.currentWidget() is not self.scan:
            self.tabs.setCurrentWidget(self.scan)
        self.scan.set_query(text)

    # ---- kompetisi server -> event desktop
    def _sync_server_events(self, manual=False):
        """Setiap kompetisi di server otomatis menjadi event di desktop (nama, tanggal, bidang ikut
        diperbarui). Event lokal biasa dan data yang sudah ada tidak diubah."""
        if not SC.logged_in():
            if manual:
                QMessageBox.information(self, "Server", "Hubungkan server dulu (tombol di kanan atas).")
            return
        if self._loader is not None and self._loader.isRunning():
            return
        self.act_refresh.setEnabled(False)
        self._loader = KompetisiLoader(self)
        self._loader.done.connect(lambda items: self._apply_server_events(items, manual))
        self._loader.failed.connect(lambda msg: self._server_sync_failed(msg, manual))
        self._loader.finished.connect(lambda: self.act_refresh.setEnabled(True))
        self._loader.start()

    def _apply_server_events(self, items, manual):
        url = SC.config()["url"]
        baru = 0
        for k in items:
            _eid, created = SL.apply_kompetisi(self.db, url, k)
            baru += created
        self._load_events(select=self.event_id)
        if manual:
            QMessageBox.information(self, "Server", f"{len(items)} kompetisi di server" +
                                    (f", {baru} event baru ditambahkan." if baru else ", semua sudah ada di desktop."))

    def _server_sync_failed(self, msg, manual):
        self._update_server_button()
        if manual:
            QMessageBox.warning(self, "Server", msg)

    # ---- event desktop -> kompetisi server
    def _push_event(self):
        if self.event_id is None:
            return
        if not self.kunci.confirm_leave():
            QMessageBox.information(self, "Kirim ke server", "Simpan dulu perubahan di Kunci Jawaban; "
                                                             "bidang yang dikirim diambil dari kunci yang tersimpan.")
            return
        kid = SL.kirim(self, self.db, self.data_dir, self.event_id)
        self._update_server_button()
        if kid is not None:
            self._event_linked()

    def _event_linked(self):
        """Event yang dibuka baru dihubungkan/dikirim ke server: perbarui daftar event tanpa berpindah event
        (event kosong yang digantikan hilang dari daftar), judul, dan bidang server di tab Kunci."""
        rows = {ev["id"]: ev for ev in self.db.events()}
        self.events.blockSignals(True)
        for i in reversed(range(self.events.count())):
            it = self.events.item(i)
            ev = rows.get(it.data(Qt.UserRole))
            if ev is None:
                self.events.takeItem(i)
            else:
                it.setText(self._event_text(ev))
        self.events.blockSignals(False)
        self._update_header()
        self.kunci.show_server_bidang()

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
            self.scan.activate()

    # ---- jendela sempit (mis. setengah layar)
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_width()

    def _apply_width(self):
        sempit = self.width() < SEMPIT
        if sempit != self._sempit:
            self._sempit = sempit
            QApplication.instance().removeEventFilter(self)
            if sempit:                                  # sidebar keluar dari susunan, jadi panel melayang
                self._body_layout.removeWidget(self.side)
                self.side.hide()
            else:
                self._body_layout.insertWidget(0, self.side)
                self.side.show()
            self.side.setProperty("floating", sempit)
            theme.repolish(self.side)
            self.btn_side.setVisible(sempit)
            for i, (text, pendek) in enumerate(TABS):
                self.tabs.setTabText(i, pendek if sempit else text)
            for b in (self.scan.btn_add, self.scan.btn_export, self.btn_server):
                b.set_compact(sempit)
        if sempit and self.side.isVisible():
            self.side.setGeometry(0, 0, SIDEBAR_W, self._body.height())

    def _open_side(self):
        """Panel daftar event melayang di atas isi (jendela sempit); tertutup saat event diklik atau klik di luar."""
        self.side.setGeometry(0, 0, SIDEBAR_W, self._body.height())
        self.side.raise_()
        self.side.show()
        QApplication.instance().installEventFilter(self)

    def _close_side(self):
        if self._sempit:
            self.side.hide()
            QApplication.instance().removeEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseButtonPress and self._sempit and self.side.isVisible():
            p = self.side.mapFromGlobal(ev.globalPosition().toPoint())
            if not self.side.rect().contains(p):
                self._close_side()
        return False

    def closeEvent(self, e):
        if self.scan.busy():
            QMessageBox.information(self, "LJK Reader", "Tunggu proses scan selesai dulu.")
            e.ignore()
            return
        if not self.scan.review.confirm_leave():
            e.ignore()
            return
        super().closeEvent(e)
