"""Jendela utama: bilah atas (tombol buka/tutup sidebar, merek, server), sidebar kiri (daftar event, lalu menu
Sinkron / Kunci jawaban / Nilai hasil), dan lembar putih di kanan berisi tab Kunci / Scan & Nilai (cari peserta,
antrean + cek manual) / Latih untuk event terpilih, atau halaman menu (pustaka paket kunci, Nilai hasil)."""
import html
import shutil

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QKeySequence, QPainter, QPainterPath, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QScrollArea,
                               QSizePolicy, QStackedWidget, QStyle, QStyledItemDelegate, QTabWidget, QVBoxLayout,
                               QWidget)

from app import icons, server_client as SC, server_link as SL, theme
from app.kunci_tab import KunciTab
from app.latih_tab import LatihTab
from app.nilai_page import NilaiPage
from app.paket_page import PaketPage
from app.scan_tab import ScanTab
from app.server_dialog import ServerDialog
from app.widgets import EmptyState, pasang_pengaman_roda

TABS = (("Kunci jawaban", "Kunci"), ("Scan && nilai", "Scan"), ("Latih model", "Latih"))     # nama, nama pendek
SIDEBAR_W = 228
TOPBAR_H = 48
COUNT = Qt.UserRole + 1         # jumlah lembar perlu cek pada baris event (hanya event yang dibuka)
# Jendela lebih sempit dari ini (mis. setengah layar laptop): sidebar disembunyikan dan dibuka sebagai panel
# melayang lewat tombol di kiri logo, nama tab dipendekkan, tombol kepala halaman jadi ikon.
SEMPIT = 1000
# Menu sidebar (di bawah daftar event): kunci, keterangan. Sinkron = tindakan untuk event yang sedang dibuka.
NAV = (("sinkron", "Laporkan lembar yang sudah dicek, lalu tarik LJK yang dikirim admin daerah lewat HP "
                   "untuk event yang sedang dibuka"),
       ("kunci", "Paket kunci jawaban: satu paket bisa dipakai banyak event"),
       ("nilai", "Nilai peserta per event dan mata pelajaran, cetak nilai, ekspor Excel"))
SIDEBAR_TUTUP = "tampilan/sidebar_tutup"        # pengaturan: sidebar ditutup (jendela lebar), diingat antar-sesi


class KompetisiLoader(QThread):
    """Ambil daftar kompetisi server di latar belakang supaya jendela tidak macet."""
    done = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            self.done.emit(SC.kompetisi())
        except SC.ServerError as e:
            self.failed.emit(str(e))


class PageStack(QStackedWidget):
    """Tumpukan halaman yang ukuran minimumnya mengikuti halaman yang tampil saja (bawaan Qt: terbesar dari semua
    halaman), supaya halaman tersembunyi yang lebar tidak memaksa halaman lain ikut bergulir."""

    def __init__(self):
        super().__init__()
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()

    def hasHeightForWidth(self):
        # Bawaan: tinggi-untuk-lebar = terbesar dari SEMUA halaman (label yang turun baris membuat semua halaman
        # "punya" tinggi-untuk-lebar), sehingga area gulir setinggi halaman tersembunyi yang tertinggi.
        # Cukup ukuran minimum halaman yang tampil; tata letak di dalam halaman tetap mengurus teks yang turun baris.
        return False


class PageScroll(QScrollArea):
    """Wadah halaman: bila jendela terlalu kecil untuk ukuran minimum isi halaman, muncul bilah gulir alih-alih
    widget dipaksa menyempit sampai saling menimpa. Memberi tahu lebar yang tersedia (halaman responsif)."""
    lebar = Signal(int)

    def __init__(self, widget):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        # pembungkus polos: QScrollArea memeriksa tinggi-untuk-lebar lewat tata letak isinya, jadi PageStack
        # (yang menolak tinggi-untuk-lebar) dibungkus satu tata letak biasa
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widget)
        self.setWidget(box)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.lebar.emit(self.viewport().width())


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
        self.nama.setPlaceholderText("FSN NIAS 2026")
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
        aktif = bool(option.state & QStyle.State_Enabled)       # menu Sinkron tanpa event / saat proses baca: redup
        if aktif and (selected or option.state & QStyle.State_MouseOver):
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
        p.setPen(QColor(theme.c("side_text" if aktif else "side_muted")))
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
        # roda mouse tidak mengubah combo/isian angka yang belum diklik (mis. combo jawaban di tabel panel cek,
        # Kontras baca di kepala halaman saat halaman digulir); gulirannya diteruskan ke tabel/halaman
        pasang_pengaman_roda(QApplication.instance())
        self.db, self.data_dir = db, data_dir
        self.event_id = None
        self._summary = None
        self._page = "event"            # "event": tab event terpilih; "kunci": pustaka paket; "nilai": Nilai hasil
        self.setWindowTitle("LJK Reader")
        self.resize(1440, 880)
        self.setMinimumSize(640, 560)

        self.kunci = KunciTab(db)
        self.scan = ScanTab(db, data_dir)
        self.latih = LatihTab(db, data_dir)
        self.library = PaketPage(db)
        self.nilai = NilaiPage(db)

        # ---- bilah atas: tombol buka/tutup sidebar, merek, server
        top = QWidget()
        top.setObjectName("topbar")
        top.setAttribute(Qt.WA_StyledBackground, True)
        top.setFixedHeight(TOPBAR_H)
        th = QHBoxLayout(top)
        th.setContentsMargins(12, 0, 16, 0)
        th.setSpacing(10)
        self.btn_side = theme.button("", "panel-left", "ghost", slot=self._toggle_side)
        self.btn_side.setFixedSize(34, 32)
        self.btn_side.setIconSize(QSize(18, 18))
        th.addWidget(self.btn_side)
        brand = QWidget()
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
        self.btn_server = theme.button("", "cloud", "ghost", "Koneksi ke server LJK Reader Online", self._server)
        th.addWidget(self.btn_server)
        # cari peserta ada di atas antrean Scan & nilai; pintasannya tetap berlaku dari mana saja
        for seq in ("Ctrl+K", "Ctrl+F"):
            QShortcut(QKeySequence(seq), self, activated=self._fokus_cari)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self._toggle_side)

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
        self.events.itemClicked.connect(lambda _it: (self._show_event_page(), self._close_side()))
        sv.addWidget(self.events, 1)

        # ---- Menu: Sinkron (event yang dibuka), pustaka paket kunci (dipakai bersama banyak event), Nilai hasil
        sv.addSpacing(10)
        sec2 = QHBoxLayout()
        sec2.setContentsMargins(8, 0, 0, 0)
        lb2 = QLabel("Menu")
        lb2.setProperty("role", "section")
        sec2.addWidget(lb2)
        sec2.addStretch()
        sv.addLayout(sec2)
        sv.addSpacing(4)
        self.nav = QListWidget()
        self.nav.setItemDelegate(EventDelegate(self.nav))
        self.nav.setMouseTracking(True)
        self.nav.setFixedHeight(len(NAV) * 52 + 6)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for key, tip in NAV:
            it = QListWidgetItem("\n")
            it.setData(Qt.UserRole, key)
            it.setToolTip(tip)
            self.nav.addItem(it)
        self.nav.itemClicked.connect(self._nav_clicked)
        sv.addWidget(self.nav)
        sv.addSpacing(6)
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
        self.kunci.changed.connect(self._update_header)
        self.kunci.buka_paket.connect(self._open_library)
        self.kunci.cek_tanpa_bidang.connect(self._cek_tanpa_bidang)
        self.scan.linked.connect(self._event_linked)
        self.scan.summary.connect(self._on_summary)
        self.scan.running.connect(self._running_changed)
        self.scan.paket_dipilih.connect(self._paket_event_berubah)
        self.scan.buka_kunci.connect(lambda: self._open_library(None))
        self.library.changed.connect(self._paket_berubah)
        self.nilai.buka_lembar.connect(self._buka_lembar)
        self.nilai.changed.connect(self._nilai_berubah)

        self.empty = EmptyState("calendar", "Belum ada event",
                                "Buat event untuk mulai memindai LJK. Kunci jawaban disimpan sebagai paket di menu "
                                "Kunci jawaban (kiri) dan bisa dipakai banyak event.",
                                theme.button("Buat event", "plus", "primary", slot=self._new_event))
        self.stack = PageStack()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.tabs)
        self.stack.addWidget(self.library)
        self.stack.addWidget(self.nilai)
        self.page_scroll = PageScroll(self.stack)
        # halaman menu menyusun panelnya atas-bawah bila lebar yang tersedia sempit
        self.page_scroll.lebar.connect(lambda wd: (self.library.set_lebar(wd), self.nilai.set_lebar(wd),
                                                   self.scan.set_lebar(wd)))
        self._tab_policy()
        cv.addWidget(self.page_scroll, 1)

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
        # sidebar ditutup lewat tombol di kiri logo (jendela lebar): diingat saat aplikasi dibuka lagi
        self._side_tutup = theme.setelan().value(SIDEBAR_TUTUP, False, type=bool)
        self.side.setVisible(not self._side_tutup)
        self._atur_tepi()
        self._update_nav()
        self._load_events()
        self.events.setFocus()                          # bukan kolom cari: fokus awal tidak menyorot apa pun
        self._sync_server_events()

    def _theme_changed(self):
        dark = theme.name() == "gelap"
        theme.set_icon(self.btn_theme, "sun" if dark else "moon")
        self.btn_theme.setText("Tema terang" if dark else "Tema gelap")
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
        self.nav.viewport().update()
        self._update_header()                           # warna teks tebal di subjudul ikut tema baru
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
        self._update_nav()                              # jumlah event di menu Nilai hasil
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
        if self._page != "event":
            self.events.clearSelection()                # menu (Kunci jawaban / Nilai hasil) yang terbuka tetap disorot

    def _event_selected(self, cur, _prev):
        eid = cur.data(Qt.UserRole) if cur else None
        if eid is not None and eid == self.event_id:
            # daftar dimuat ulang dengan event yang sama (sinkron server, ubah event): jangan muat ulang tab,
            # supaya cek manual yang belum disimpan tidak hilang
            self._update_header()
            self.kunci.show_server_bidang()
            return
        if self.event_id is not None and not self._boleh_tinggalkan():
            # batal pindah: sorotan kembali ke event ini (setelah klik selesai diproses daftar)
            QTimer.singleShot(0, lambda keep=self.event_id: self._sorot_event(keep))
            return
        self._set_event(eid)

    def _boleh_tinggalkan(self):
        """Sebelum meninggalkan event: tawarkan simpan kunci jawaban & cek manual yang belum disimpan."""
        return self.kunci.ask_save() and self.scan.review.confirm_leave()

    def _sorot_event(self, event_id):
        self.events.blockSignals(True)
        for i in range(self.events.count()):
            if self.events.item(i).data(Qt.UserRole) == event_id:
                self.events.setCurrentRow(i)
        self.events.blockSignals(False)

    def _running_changed(self, on):
        has = self.event_id is not None
        self._update_sinkron()
        self.act_delete.setEnabled(not on and has)      # hapus event saat scan berjalan: hasil scan kehilangan tempat

    def _set_event(self, event_id):
        self.event_id = event_id
        self._summary = None
        has = event_id is not None
        self._page = "event"
        self.nav.clearSelection()
        self.stack.setCurrentWidget(self.tabs if has else self.empty)
        for a in (self.act_push, self.act_edit):
            a.setEnabled(has)
        self.act_delete.setEnabled(has and not self.scan.busy())
        for w in (self.scan.kontras, self.scan.btn_add, self.scan.btn_export):
            w.setVisible(has)
        self._update_sinkron()
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
            parts.append(f"{s['tanpa_nilai']} tanpa bidang (kode naskah salah isi / tak terdaftar)")
        return (f"<span style='color:{ink}; font-weight:600'>{siap} dari {total} lembar siap diekspor</span>"
                + (f"; {', '.join(parts)}" if parts else ""))

    def _update_header(self):
        if self._page == "kunci":
            self.title.setText("Kunci jawaban")
            self.subtitle.setText(self.library.summary())
            return
        if self._page == "nilai":
            self.title.setText("Nilai hasil")
            self.subtitle.setText(self.nilai.summary())
            return
        if self.event_id is None:
            self.title.setText("Selamat datang")
            self.subtitle.setText("Pembaca Lembar Jawaban Komputer POSI")
            return
        ev = self.db.event(self.event_id)
        self.title.setText(ev["nama"])
        linked = ev["server_kompetisi_id"] and ev["server_url"]
        paket = self.db.event_paket(self.event_id)
        if paket is not None:
            kunci = f"paket {html.escape(paket['nama'])}"
        elif self.db.naskah_lama(self.event_id):
            kunci = "kunci lama (belum memilih paket)"
        else:
            kunci = f"<span style='color:{theme.tone_hex('warn')[1]}'>belum memilih paket kunci</span>"
        parts = [html.escape(ev["tanggal"]), self._finding(), kunci]
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

    # ---- menu sidebar: Sinkron, Kunci jawaban (pustaka paket), Nilai hasil <-> halaman event
    def _nav_item(self, key):
        return self.nav.item(next(i for i, (k, _tip) in enumerate(NAV) if k == key))

    def _update_nav(self):
        ps = list(self.db.pakets())
        self._nav_item("kunci").setText(f"Kunci jawaban\n{len(ps)} paket" if ps else "Kunci jawaban\nbelum ada paket")
        n = len(self.db.events())
        self._nav_item("nilai").setText(f"Nilai hasil\n{n} event")
        self._update_sinkron()

    def _update_sinkron(self):
        """Menu Sinkron: keterangannya nama event yang akan disinkron; redup bila belum ada event yang dibuka atau
        proses baca sedang berjalan (sama seperti tombol Sinkron dulu). Tidak pernah tersorot: ini tindakan, bukan
        halaman."""
        it = self._nav_item("sinkron")
        ev = self.db.event(self.event_id) if self.event_id is not None else None
        sibuk = self.scan.busy()
        if ev is None:
            ket = "pilih event dulu"
        elif sibuk:
            ket = "menunggu proses baca selesai"
        else:
            ket = ev["nama"]
        it.setText(f"Sinkron\n{ket}")
        it.setFlags(Qt.ItemIsEnabled if ev is not None and not sibuk else Qt.NoItemFlags)
        it.setToolTip(NAV[0][1] + (f": {ev['nama']}" if ev is not None else ""))

    def _nav_clicked(self, it):
        if not it.flags() & Qt.ItemIsEnabled:
            return
        key = it.data(Qt.UserRole)
        if key == "sinkron":
            self._sinkron()
        elif key == "kunci":
            self._open_library()
        else:
            self._open_nilai()

    def _sinkron(self):
        """Menu Sinkron (fungsinya sama dengan tombol Sinkron dulu): laporkan lembar yang sudah dicek, lalu tarik
        LJK kiriman HP untuk event yang sedang dibuka. Halaman Scan & nilai event itu ditampilkan supaya proses
        bacanya terlihat."""
        if self.event_id is None or self.scan.busy():
            return
        self._close_side()
        self._show_event_page()
        self.tabs.setCurrentWidget(self.scan)
        self.scan.sync()

    def _open_page(self, page, widget):
        """Buka halaman menu (pustaka kunci / Nilai hasil). Event yang sedang dibuka tetap terbuka di belakang;
        klik event di sidebar untuk kembali."""
        self._page = page
        self.stack.setCurrentWidget(widget)
        self.events.clearSelection()
        self.nav.setCurrentItem(self._nav_item(page))
        for w in (self.scan.kontras, self.scan.btn_add, self.scan.btn_export):
            w.setVisible(False)
        self._update_header()
        self._close_side()

    def _open_library(self, paket_id=None):
        self.library.reload(select=paket_id)
        self._open_page("kunci", self.library)

    def _open_nilai(self):
        self.nilai.reload(select=self.event_id)
        self._update_nav()
        self._open_page("nilai", self.nilai)

    def _buka_lembar(self, event_id, lembar_id):
        """Dari Nilai hasil (klik dua kali peserta): buka event itu di tab Scan & nilai pada lembar tersebut."""
        if event_id != self.event_id:
            if self.event_id is not None and not self._boleh_tinggalkan():
                return
            self._sorot_event(event_id)
            self._set_event(event_id)
        else:
            self._show_event_page()
        self.tabs.setCurrentWidget(self.scan)
        self.scan.set_bidang(None)                      # lembarnya pasti tampil di antrean
        self.scan.set_filter("Semua")
        self.scan.review.show_lembar(lembar_id)

    def _cek_tanpa_bidang(self):
        """Dari tab Kunci jawaban: buka Scan & nilai pada bidang 'Tanpa bidang' (kode salah isi / gagal dibaca)."""
        from ljk import service as SV
        self.tabs.setCurrentWidget(self.scan)
        self.scan.set_bidang(SV.BELUM)
        self.scan.set_filter("Semua")

    def _nilai_berubah(self):
        """Hitung ulang di Nilai hasil: nilai di tab event yang terbuka ikut diperbarui."""
        if self.event_id is not None:
            self.kunci.load(self.event_id)
            self.scan.refresh()
        self._update_header()

    def _show_event_page(self):
        if self._page == "event":
            return
        self._page = "event"
        self.nav.clearSelection()
        self._sorot_event(self.event_id)
        has = self.event_id is not None
        self.stack.setCurrentWidget(self.tabs if has else self.empty)
        for w in (self.scan.kontras, self.scan.btn_add, self.scan.btn_export):
            w.setVisible(has)
        self._update_header()
        if has and self.tabs.currentWidget() is self.scan:
            self.scan.activate()                        # nilai mungkin berubah karena kunci paket diubah
        elif has and self.tabs.currentWidget() is self.kunci:
            self.kunci.load(self.event_id)

    def _paket_event_berubah(self):
        """Event memilih paket (sebelum scan): tab Kunci, judul, dan menu ikut diperbarui."""
        self.kunci.load(self.event_id)
        self._update_nav()
        self._update_header()

    def _paket_berubah(self):
        """Isi pustaka paket berubah (kunci, kode naskah, nama). Lembar yang sudah dibekukan tidak berubah; lembar
        yang kodenya baru saja punya kunci dibekukan sekarang. Tampilan event yang terbuka diperbarui."""
        self.db.bekukan_belum()
        self._update_nav()
        self._update_header()
        if self.event_id is not None:
            self.kunci.load(self.event_id)
            self.scan.refresh()

    def _fokus_cari(self):
        """Ctrl+K / Ctrl+F: kotak cari peserta di atas antrean Scan & nilai event yang sedang dibuka."""
        if self.event_id is None:
            return
        self._close_side()
        self._show_event_page()
        self.tabs.setCurrentWidget(self.scan)
        self.scan.fokus_cari()

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
        if self.event_id is None or self.scan.busy():
            return
        ev = self.db.event(self.event_id)
        n = len(self.db.lembar(self.event_id))
        if QMessageBox.question(self, "Hapus event",
                                f"Hapus event '{ev['nama']}' beserta {n} lembar hasil scan?\n"
                                "Paket kunci jawaban dan foto asli tidak ikut terhapus.") != QMessageBox.Yes:
            return
        shutil.rmtree(self.data_dir / "event" / str(self.event_id), ignore_errors=True)
        self.db.delete_event(self.event_id)
        self.kunci._set_dirty(False)        # isian event yang dihapus memang ikut dibuang: jangan tawarkan simpan
        self.scan.review.dirty = False
        self._load_events()

    # ---- tab
    def _tab_changed(self, idx):
        self._tab_policy()
        if self.tabs.widget(idx) is self.scan:
            self.scan.activate()
        elif self.tabs.widget(idx) is self.kunci and self.event_id is not None:
            # jumlah lembar per kode & kode yang tidak ada di paket ikut berubah saat lembar dicek / ditambah /
            # dihapus di Scan & nilai: muat ulang setiap kali tab ini dibuka (dulu bisa menampilkan angka lama)
            self.kunci.load(self.event_id)

    def _tab_policy(self):
        """Ukuran minimum tab mengikuti tab yang tampil saja. Bawaan Qt memakai yang terbesar dari semua tab, termasuk
        tab tersembunyi yang masih bersusunan lama (mis. atas-bawah dari jendela sempit tadi), sehingga bilah gulir
        bisa muncul padahal tab yang tampil muat."""
        cur = self.tabs.currentWidget()
        for i in range(self.tabs.count()):
            pg = self.tabs.widget(i)
            pol = QSizePolicy.Preferred if pg is cur else QSizePolicy.Ignored
            pg.setSizePolicy(pol, pol)
        self.tabs.updateGeometry()

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
            else:                                       # kembali ke susunan, kecuali sedang ditutup lewat tombol
                self._body_layout.insertWidget(0, self.side)
                self.side.setVisible(not self._side_tutup)
            self.side.setProperty("floating", sempit)
            theme.repolish(self.side)
            self._atur_tepi()
            for i, (text, pendek) in enumerate(TABS):
                self.tabs.setTabText(i, pendek if sempit else text)
            for b in (self.scan.btn_add, self.scan.btn_export, self.btn_server):
                b.set_compact(sempit)
        if sempit and self.side.isVisible():
            self.side.setGeometry(0, 0, SIDEBAR_W, self._body.height())

    def _toggle_side(self):
        """Tombol di kiri logo / Ctrl+B. Jendela lebar: sidebar ditutup (lembar melebar penuh) atau dibuka lagi,
        diingat saat aplikasi dibuka lagi. Jendela sempit: panel melayang dibuka / ditutup."""
        if self._sempit:
            if self.side.isVisible():
                self._close_side()
            else:
                self._open_side()
            return
        self._side_tutup = not self._side_tutup
        self.side.setVisible(not self._side_tutup)
        theme.setelan().setValue(SIDEBAR_TUTUP, self._side_tutup)
        self._atur_tepi()

    def _atur_tepi(self):
        """Tanpa sidebar di kiri (ditutup / jendela sempit) lembar putih diberi jarak 8 px dari tepi kiri jendela,
        sama seperti tepi kanan & bawah. Tooltip tombol sidebar ikut keadaannya."""
        ada = not self._sempit and not self._side_tutup
        self._body_layout.setContentsMargins(0 if ada else 8, 0, 8, 8)
        if self._sempit:
            tip = "Tampilkan daftar event & menu"
        else:
            tip = "Tampilkan sidebar" if self._side_tutup else "Sembunyikan sidebar (halaman jadi penuh)"
        self.btn_side.setToolTip(f"{tip} (Ctrl+B)")

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
            g = ev.globalPosition().toPoint()
            luar = not self.side.rect().contains(self.side.mapFromGlobal(g))
            # klik tombol sidebar: biar tombolnya yang menutup (kalau ditutup di sini, klik itu membukanya lagi)
            tombol = self.btn_side.rect().contains(self.btn_side.mapFromGlobal(g))
            if luar and not tombol:
                self._close_side()
        return False

    def closeEvent(self, e):
        if self.scan.busy():
            QMessageBox.information(self, "LJK Reader", "Tunggu proses scan selesai dulu.")
            e.ignore()
            return
        if not self._boleh_tinggalkan():
            e.ignore()
            return
        super().closeEvent(e)
