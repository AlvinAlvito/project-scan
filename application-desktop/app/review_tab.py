"""Panel cek manual satu lembar (di kanan antrean Scan & Nilai): gambar di kiri, keputusan & data di kanan."""
import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from app import theme
from app.colors import paint
from app.imageview import ImageView
from app.widgets import EmptyState, ToolbarFit, badge, divider, set_badge, setup_table, toolbar
from ljk import nilai as NI
from ljk import service as SV
from ljk import tampilan as TP

CHOICES = [("", "-"), ("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"), ("E", "E"), ("*", "ganda")]
PILIHAN = [("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"), ("E", "E"), ("", "Kosong"), ("*", "Ganda")]  # tombol keputusan
KIND_TONE = {"ragu": "warn", "ganda": "error"}
STATUS_TONE = {"OK": "ok", "Perlu cek": "warn", "Sudah dicek": "info", "Gagal": "error"}
HW_ORDER = [("kotak_nama", "Nama"), ("kotak_nomor", "Nomor"), ("kotak_kode", "Kode"),
            ("kotak_tanggal", "Tanggal"), ("bidang", "Bidang"), ("sekolah", "Sekolah"), ("kelas", "Kelas"),
            ("hp", "HP/WA")]
HW_MAKS = (380, 52)     # ukuran tampil maksimum potongan tulisan tangan (lebar, tinggi)
TEGAK = 620             # lebar panel di bawah ini (jendela sempit): gambar di atas, data di bawah


class ChoiceRow(QWidget):
    """Tombol pilihan jawaban: satu baris bila muat; bila panel sempit, A-E di atas dan Kosong/Ganda di bawah."""

    def __init__(self, buttons):
        super().__init__()
        self.buttons = buttons
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        self._wide = None
        self._place(True)

    def _place(self, wide):
        if wide == self._wide:
            return
        self._wide = wide
        for b in self.buttons:
            self.grid.removeWidget(b)
        for c in range(12):
            self.grid.setColumnStretch(c, 0)
        if wide:                                   # A B C D E Kosong Ganda; kata lebih lebar dari huruf
            col = 0
            for b in self.buttons:
                span = 2 if len(b.text()) > 1 else 1
                self.grid.addWidget(b, 0, col, 1, span)
                col += span
            cols = col
        else:                                      # A-E satu baris, Kosong & Ganda berbagi baris kedua
            for i, b in enumerate(self.buttons[:5]):
                self.grid.addWidget(b, 0, i * 2, 1, 2)
            self.grid.addWidget(self.buttons[5], 1, 0, 1, 5)
            self.grid.addWidget(self.buttons[6], 1, 5, 1, 5)
            cols = 10
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place(self.width() >= 360)


class ReviewTab(QWidget):
    changed = Signal()
    shown = Signal(int)             # id lembar yang sedang tampil (antrean ikut memilihnya)
    step_requested = Signal(int)    # tombol sebelumnya/berikutnya: -1 / +1 di urutan antrean

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.event_id = None
        self.ids = []           # urutan id lembar
        self.status = {}        # id -> status
        self.cur = None         # baris DB lembar aktif
        self.baca = {}
        self.answers = []
        self.dirty = False
        self._loading = False
        self._dec_q = None      # nomor soal (0-based) di kotak keputusan
        self._first_soal = None
        # lembar berikutnya sesudah simpan, menurut urutan antrean: fungsi(id) -> id | None (diisi ScanTab)
        self.next_id = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.page = QWidget()
        v = QVBoxLayout(self.page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        # ---- kepala: nama peserta, nomor & kode, posisi di antrean
        head = toolbar(10)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.h_name = QLabel("")
        self.h_name.setProperty("role", "h2")
        self.h_sub = QLabel("")
        self.h_sub.setProperty("role", "muted")
        for lb in (self.h_name, self.h_sub):
            lb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)     # nama panjang terpotong, tidak memaksa lebar
            names.addWidget(lb)
        head.addLayout(names, 1)
        self.dirty_badge = badge("Belum disimpan", "warn")
        self.dirty_badge.setVisible(False)
        self.status_label = badge("", "neutral")
        self.status_label.setVisible(False)
        head.addWidget(self.dirty_badge, 0, Qt.AlignVCenter)
        head.addWidget(self.status_label, 0, Qt.AlignVCenter)
        head.addSpacing(6)
        self.btn_prev = theme.button("", "chevron-left", "ghost", "Lembar sebelumnya di antrean (Ctrl+↑)",
                                     lambda: self.step_requested.emit(-1))
        self.pos_lbl = QLabel("")
        self.pos_lbl.setProperty("role", "muted")
        self.btn_next = theme.button("", "chevron-right", "ghost", "Lembar berikutnya di antrean (Ctrl+↓)",
                                     lambda: self.step_requested.emit(1))
        for w in (self.btn_prev, self.pos_lbl, self.btn_next):
            head.addWidget(w, 0, Qt.AlignVCenter)
        v.addLayout(head)
        QShortcut(QKeySequence("Ctrl+Up"), self, activated=lambda: self.step_requested.emit(-1))
        QShortcut(QKeySequence("Ctrl+Down"), self, activated=lambda: self.step_requested.emit(1))

        split = self.split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        # kiri: gambar di sumur abu-abu, alat zoom & hitam-putih di atasnya
        left = QFrame()
        left.setProperty("role", "well")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)
        self.view = ImageView()
        zb = toolbar(4)
        for ic, tip, fn in (("maximize", "Muat layar", lambda: self.view.fit()),
                            ("zoom-in", "Perbesar (roda mouse)", lambda: self.view.zoom(1.25)),
                            ("zoom-out", "Perkecil (roda mouse)", lambda: self.view.zoom(0.8))):
            zb.addWidget(theme.button("", ic, "ghost", tip, fn))
        zb.addWidget(divider())
        # tampilan hitam-putih ala scanner (hanya tampilan; hasil baca tidak berubah)
        self.btn_bw = theme.button("Hitam-putih", "contrast", "ghost", (
            "Tampilan hitam-putih ala scanner: isian pensil tampak hitam pekat, cetakan merah memudar,\n"
            "bekas hapusan tetap terang. Hanya tampilan; hasil baca tidak berubah."))
        self.btn_bw.setCheckable(True)
        self.bw_slider = QSlider(Qt.Horizontal)
        self.bw_slider.setRange(0, 100)
        self.bw_slider.setFixedWidth(130)
        self.bw_slider.setToolTip("Kontras tampilan: makin ke kanan, goresan tipis makin hitam")
        self.bw_label = QLabel("")
        self.bw_label.setProperty("role", "muted")
        self.btn_bw_std = theme.button("Standar", "undo", "ghost", "Kembalikan kontras tampilan ke standar",
                                       lambda: self.bw_slider.setValue(TP.BW_STANDAR))
        for w in (self.btn_bw, self.bw_slider, self.bw_label, self.btn_bw_std):
            zb.addWidget(w)
        zb.addStretch()
        self.zoom_hint = QLabel("Seret untuk menggeser · roda mouse untuk zoom")
        self.zoom_hint.setProperty("role", "muted")
        self.zoom_hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.zoom_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)    # sempit: terpotong, tidak memaksa lebar
        zb.addWidget(self.zoom_hint)
        lv.addLayout(zb)
        self._zb_fit = ToolbarFit(left, zb, (self.btn_bw_std, self.btn_bw))
        self._bw_prep = None
        self._bw_timer = QTimer(self)
        self._bw_timer.setSingleShot(True)
        self._bw_timer.setInterval(90)             # geser slider: gambar dibuat ulang setelah berhenti sejenak
        self._bw_timer.timeout.connect(self._bw_show)
        st = QSettings("POSI", "LJK Reader")
        self.bw_slider.setValue(st.value("cek/kontras", TP.BW_STANDAR, type=int))
        self.btn_bw.setChecked(st.value("cek/hitam_putih", False, type=bool))
        self.bw_slider.valueChanged.connect(self._bw_kontras)
        self.btn_bw.toggled.connect(self._bw_toggled)
        self._bw_controls()
        lv.addWidget(self.view, 1)
        split.addWidget(left)

        # kanan: keputusan soal yang ditandai, catatan, data, jawaban; tombol simpan selalu terlihat di bawah
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 10, 0)
        rv.setSpacing(0)

        self.decide = QWidget()
        dv = QVBoxLayout(self.decide)
        dv.setContentsMargins(0, 0, 0, 16)
        dv.setSpacing(4)
        self.dec_title = QLabel("")
        self.dec_title.setProperty("role", "h3")
        self.dec_text = QLabel("")
        self.dec_text.setProperty("role", "muted")
        self.dec_text.setWordWrap(True)
        dv.addWidget(self.dec_title)
        dv.addWidget(self.dec_text)
        dv.addSpacing(8)
        self.dec_group = QButtonGroup(self)
        self.dec_group.setExclusive(True)
        self.dec_btns = {}
        for val, text in PILIHAN:
            b = QPushButton(text)
            b.setProperty("role", "choice")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            b.setMinimumWidth(30)
            b.setToolTip("Tekan A–E di papan ketik" if val in "ABCDE" and val else "")
            b.clicked.connect(lambda _c=False, vv=val: self._choose(vv))
            self.dec_group.addButton(b)
            self.dec_btns[val] = b
        dv.addWidget(ChoiceRow(list(self.dec_btns.values())))
        self.decide.setVisible(False)
        rv.addWidget(self.decide)
        for letter in "ABCDE":
            sc = QShortcut(QKeySequence(letter), self, activated=lambda vv=letter: self._choose(vv, key=True))
            sc.setContext(Qt.WindowShortcut)       # juga saat fokus di antrean; kolom teks tetap menerima ketikan

        g_issue = QGroupBox("Catatan")
        g_issue.setToolTip("Klik catatan untuk melihat lokasinya di gambar")
        gl = QVBoxLayout(g_issue)
        gl.setContentsMargins(0, 0, 0, 0)
        self.issues = QListWidget()
        self.issues.setMaximumHeight(140)
        self.issues.setWordWrap(True)
        self.issues.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.issues.itemClicked.connect(self._issue_clicked)
        gl.addWidget(self.issues)
        rv.addWidget(g_issue)

        g_data = QGroupBox("Data peserta")
        form = QFormLayout(g_data)
        form.setContentsMargins(0, 0, 0, 0)
        self.f_nama, self.f_nomor, self.f_tanggal = QLineEdit(), QLineEdit(), QLineEdit()
        self.f_kode = QComboBox()
        self.f_kode.setEditable(True)
        self.f_bidang = QLabel("")
        self.read_lbl = {k: QLabel("") for k in ("nama", "nomor", "kode", "tanggal")}
        form.setSpacing(8)
        for lbl in self.read_lbl.values():
            lbl.setProperty("role", "muted")
        for key, label, w in (("nama", "Nama", self.f_nama), ("nomor", "Nomor peserta", self.f_nomor),
                              ("kode", "Kode naskah", self.f_kode), ("tanggal", "Tanggal", self.f_tanggal)):
            form.addRow(label, w)
            form.addRow("", self.read_lbl[key])
        form.addRow("Bidang", self.f_bidang)
        self.f_server = QLabel("")
        self.f_server.setWordWrap(True)
        self.f_server.setProperty("role", "muted")
        form.addRow("Dikirim", self.f_server)
        self._form = form
        for w in (self.f_nama, self.f_nomor, self.f_tanggal):
            w.textEdited.connect(self._mark_dirty)
        self.f_kode.currentTextChanged.connect(self._kode_changed)
        rv.addWidget(g_data)

        g_hw = QGroupBox("Tulisan tangan")
        g_hw.setToolTip("Pembanding dan konfirmasi dengan peserta")
        self.hw_layout = QFormLayout(g_hw)
        self.hw_layout.setContentsMargins(0, 0, 0, 0)
        self.hw_layout.setSpacing(8)
        self.hw_labels = {}
        for key, label in HW_ORDER:
            lb = QLabel()
            lb.setMinimumHeight(28)
            self.hw_labels[key] = lb
            self.hw_layout.addRow(label, lb)
        rv.addWidget(g_hw)

        g_ans = QGroupBox("Jawaban")
        al = QVBoxLayout(g_ans)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(10)
        top = toolbar()
        self.score_lbl = QLabel("")
        top.addWidget(self.score_lbl)
        top.addStretch()
        self.only_bad = QCheckBox("Ragu/ganda saja")
        self.only_bad.toggled.connect(self._filter_answers)
        top.addWidget(self.only_bad)
        al.addLayout(top)
        self.ans = QTableWidget(0, 5)
        self.ans.setHorizontalHeaderLabels(["No", "Terbaca", "Jawaban", "Kunci", "Hasil"])
        setup_table(self.ans, 36)
        self.ans.setEditTriggers(QTableWidget.NoEditTriggers)
        self.ans.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.ans.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.ans.setMinimumHeight(260)
        self.ans.cellClicked.connect(self._answer_clicked)
        al.addWidget(self.ans)
        rv.addWidget(g_ans, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(right)
        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(8)
        sv.addWidget(scroll, 1)
        self.btn_save = theme.button("Simpan dan tandai sudah dicek", "check", "primary",
                                     "Ctrl+Enter, lalu lanjut ke lembar berikutnya", lambda: self._save())
        sv.addWidget(self.btn_save)
        btns = toolbar()
        self.btn_reset = theme.button("Kembalikan", "undo", "ghost", "Kembalikan ke hasil baca awal", self._reset)
        hint = QLabel("Ctrl+Enter: simpan, lalu lanjut")
        hint.setProperty("role", "muted")
        hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        btns.addWidget(self.btn_reset)
        btns.addWidget(hint, 1)
        sv.addLayout(btns)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._save)
        split.addWidget(side)
        right.setMinimumWidth(300)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([460, 420])
        v.addWidget(split, 1)

        self.empty = EmptyState("clipboard-check", "Pilih lembar di antrean",
                                "Gambar dan hasil baca lembar yang dipilih tampil di sini.")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.page)
        outer.addWidget(self.stack)
        self._enable(False)

    # ---------------------------------------------------------------- daftar
    def load(self, event_id):
        self.event_id = event_id
        self.cur = None
        self.dirty = False
        self.refresh_list()
        if self.ids:
            self.show_lembar(self._first_to_check() or self.ids[0])
        else:
            self._clear()

    def refresh_list(self):
        self.ids, self.status = [], {}
        if self.event_id is None:
            return
        for v in SV.event_views(self.db, self.event_id):
            self.ids.append(v.row["id"])
            self.status[v.row["id"]] = v.status
        names = [f"{s.kode}" for s in self.db.naskah(self.event_id)]
        self._loading = True
        cur = self.f_kode.currentText()
        self.f_kode.clear()
        self.f_kode.addItems(names)
        self.f_kode.setCurrentText(cur)
        self._loading = False

    def activate(self):
        """Dipanggil saat tab dibuka: segarkan daftar; bila belum ada lembar aktif,
        tampilkan lembar pertama yang perlu dicek."""
        self.refresh_list()
        if self.cur is None or self.cur["id"] not in self.ids:
            self.cur = None
            if self.ids:
                self.show_lembar(self._first_to_check() or self.ids[0])
            else:
                self._clear()
        else:
            self.show_lembar(self.cur["id"])

    def _first_to_check(self):
        for i in self.ids:
            if self.status.get(i) in ("Perlu cek", "Gagal"):
                return i
        return None

    def set_position(self, i, n):
        """Posisi lembar ini di antrean yang sedang tampil (i mulai 1); i=0 bila tidak ada di antrean."""
        self.pos_lbl.setText(f"{i} dari {n}" if i else "")
        self.btn_prev.setEnabled(i > 1)
        self.btn_next.setEnabled(0 < i < n)

    # ---------------------------------------------------------------- tampil
    def confirm_leave(self):
        if not self.dirty or self.cur is None:
            return True
        r = QMessageBox.question(self, "Cek manual", "Perubahan di lembar ini belum disimpan. Simpan sekarang?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self._save(go_next=False)
        return r == QMessageBox.Discard

    def show_lembar(self, lembar_id):
        if self.cur is not None and lembar_id != self.cur["id"] and not self.confirm_leave():
            self.shown.emit(self.cur["id"])        # batal pindah: antrean kembali ke lembar ini
            return
        row = self.db.lembar_by_id(lembar_id)
        if row is None:
            return
        self.cur = row
        self.stack.setCurrentWidget(self.page)
        self.baca = json.loads(row["baca"] or "{}")
        self.answers = json.loads(row["jawaban"] or "[]") or [""] * 180
        self.view.set_image(row["gambar"])
        self._bw_prep = None
        self._bw_show()
        self._loading = True
        self.f_nama.setText(row["nama"])
        self.f_nomor.setText(row["nomor"])
        self.f_kode.setCurrentText(row["kode"])
        self.f_tanggal.setText(row["tanggal"])
        for k, lbl in self.read_lbl.items():
            # Tanggal tidak wajib terbaca: tidak perlu menarik perhatian pemeriksa.
            differs = k != "tanggal" and self.baca.get(k, "") != row[k]
            lbl.setText(f"terbaca: {self.baca.get(k, '')}" if differs else "")
            lbl.setVisible(differs)
        self._loading = False
        pot = json.loads(row["potongan"] or "{}")
        for key, lb in self.hw_labels.items():
            pm = QPixmap(pot.get(key, ""))
            if pm.isNull():
                lb.setPixmap(QPixmap())
                continue
            # Ukuran tampil tetap (muat di HW_MAKS, rasio dijaga) apa pun resolusi berkasnya;
            # diskalakan ke piksel layar sebenarnya (layar DPI tinggi) dan ditandai rasio
            # pikselnya, supaya Qt tidak memperbesarnya lagi (penyebab potongan tampak kabur).
            dpr = lb.devicePixelRatioF()
            s = min(HW_MAKS[0] / pm.width(), HW_MAKS[1] / pm.height())
            w, h = max(1, round(pm.width() * s)), max(1, round(pm.height() * s))
            spm = pm.scaled(round(w * dpr), round(h * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            spm.setDevicePixelRatio(dpr)
            lb.setPixmap(spm)
            lb.setMinimumSize(w, h)
        srv = SV.server_info(row)
        if srv:
            self.f_server.setText(f"{srv.get('kota', '')} · {srv.get('uploader', '')} · {srv.get('dibuat', '')}\n"
                                  f"kualitas foto {srv.get('skor_kualitas', '?')}% · keyakinan baca server "
                                  f"{srv.get('keyakinan', '?')}% · lembar server #{srv.get('id')}")
        self._form.setRowVisible(self.f_server, bool(srv))
        self._update_head(srv)
        self._update_kode_label()
        self._fill_issues()
        self._fill_answers()
        self._set_decision(self._first_soal)
        self._enable(not row["error"])
        self.dirty = False
        self._update_status()
        self.shown.emit(lembar_id)

    def _update_head(self, srv):
        r = self.cur
        s = self._soal()
        sumber = f"HP · {srv.get('kota', '')}" if srv else Path(r["file"]).name
        self.h_name.setText(r["nama"] or "Nama tidak terbaca")
        self.h_sub.setText(" · ".join([r["nomor"] or "—", f"kode {r['kode'] or '—'}" + (f" {s.bidang}" if s else ""),
                                       f"lembar #{r['urutan']}", sumber]))
        self.h_sub.setToolTip(r["file"])

    def resizeEvent(self, e):
        super().resizeEvent(e)
        tegak = self.width() < TEGAK
        if tegak != (self.split.orientation() == Qt.Vertical):
            self.split.setOrientation(Qt.Vertical if tegak else Qt.Horizontal)
            total = self.split.height() if tegak else self.split.width()
            self.split.setSizes([int(total * 0.5), int(total * 0.5)])

    # ---- tampilan hitam-putih
    def _bw_controls(self):
        on = self.btn_bw.isChecked()
        for w in (self.bw_slider, self.bw_label, self.btn_bw_std):
            w.setVisible(on)
        self.zoom_hint.setVisible(not on)
        v = self.bw_slider.value()
        text = f"{v}" + (" · standar" if v == TP.BW_STANDAR else "")
        faktor = self._bw_prep["faktor"] if self._bw_prep else 1.0
        if faktor > 1.01:
            text += f" · ×{faktor:.1f}"
        self.bw_label.setText(text)
        self.bw_label.setToolTip(f"Lembar pudar: kegelapan dikuatkan {faktor:.1f}x, sama seperti saat dibaca"
                                 if faktor > 1.01 else "")
        self._zb_fit.fit()                         # slider muncul/hilang: lebar toolbar berubah

    def _bw_toggled(self, on):
        QSettings("POSI", "LJK Reader").setValue("cek/hitam_putih", on)
        self._bw_controls()
        self._bw_show()

    def _bw_kontras(self, v):
        QSettings("POSI", "LJK Reader").setValue("cek/kontras", v)
        self._bw_controls()
        self._bw_timer.start()

    def _bw_show(self):
        """Gambar cek berwarna atau hitam-putih sesuai tombol; zoom & posisi gambar tetap."""
        if self.cur is None or not self.cur["gambar"]:
            return
        if not self.btn_bw.isChecked():
            self.view.show_original()
            return
        if self._bw_prep is None:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._bw_prep = SV.bw_source(self.cur["gambar"])
            except Exception:  # gambar / baca.npz rusak: tampilan berwarna tetap bisa dipakai
                self._bw_prep = None
            finally:
                QApplication.restoreOverrideCursor()
            self._bw_controls()
        if self._bw_prep is None:
            self.view.show_original()
            return
        out = TP.bw_render(self._bw_prep, self.bw_slider.value())
        h, w = out.shape[:2]
        self.view.show_pixmap(QPixmap.fromImage(QImage(out.data, w, h, out.strides[0], QImage.Format_BGR888)))

    def _clear(self):
        self.cur = None
        self._bw_prep = None
        self.view.set_image(None)
        self.issues.clear()
        self.ans.setRowCount(0)
        self.status_label.setVisible(False)
        self.dirty_badge.setVisible(False)
        self.stack.setCurrentWidget(self.empty)
        self._enable(False)

    def _enable(self, on):
        for w in (self.f_nama, self.f_nomor, self.f_kode, self.f_tanggal, self.ans, self.btn_save, self.btn_reset,
                  self.decide):
            w.setEnabled(on)

    def _update_status(self):
        if self.cur is None:
            return
        st = self.status.get(self.cur["id"], "")
        set_badge(self.status_label, st, STATUS_TONE.get(st, "neutral"))
        self.dirty_badge.setVisible(self.dirty)

    def _soal(self):
        kode = self.f_kode.currentText().strip()
        for s in self.db.naskah(self.event_id):
            if s.kode == kode:
                return s
        return None

    def _update_kode_label(self):
        s = self._soal()
        self.f_bidang.setText(f"{s.bidang} · {s.jumlah} soal" if s else
                              f"<span style='color:{theme.tone_hex('error')[1]}'>kode naskah belum terdaftar</span>")

    def _fill_issues(self):
        self.issues.clear()
        self._first_soal = None
        view = SV.sheet_view(self.cur, {s.kode: s for s in self.db.naskah(self.event_id)},
                             SV.duplicate_nomor(self.db.lembar(self.event_id)))
        items = list(self.baca.get("issues", []))
        texts = {i["text"] for i in items}
        items += [i for i in view.issues if i["text"] not in texts]
        if self.cur["dicek"]:
            items.insert(0, {"text": "Lembar ini sudah dicek. Hasil baca awal di bawah hanya sebagai catatan.",
                             "key": "info", "x": None, "y": None})
        for it in items:
            li = QListWidgetItem(it["text"])
            li.setData(Qt.UserRole, it)
            self.issues.addItem(li)
            if self._first_soal is None and str(it.get("key", "")).startswith("soal:"):
                self._first_soal = int(it["key"].split(":")[1]) - 1
        if not items:
            self.issues.addItem("Tidak ada catatan.")

    def _n_rows(self):
        s = self._soal()
        if s:
            return s.jumlah
        filled = [q for q, a in enumerate(self.baca.get("jawaban", [])) if a]
        return max(30, (filled[-1] + 1) if filled else 0)

    def _fill_answers(self):
        self.ans.setRowCount(0)
        s = self._soal()
        kinds = self.baca.get("jawaban_kind", [])
        read = self.baca.get("jawaban", [])
        n = self._n_rows()
        self.ans.setRowCount(n)
        for q in range(n):
            kind = kinds[q] if q < len(kinds) else ""
            raw = read[q] if q < len(read) else ""
            num = QTableWidgetItem(str(q + 1))
            num.setTextAlignment(Qt.AlignCenter)
            num.setData(Qt.UserRole, q)
            shown = {"": "-", "?": "ragu", "*": "ganda"}.get(raw, raw)
            ri = QTableWidgetItem(shown)
            ri.setTextAlignment(Qt.AlignCenter)
            if kind in KIND_TONE:
                for it in (num, ri):
                    paint(it, KIND_TONE[kind])
            self.ans.setItem(q, 0, num)
            self.ans.setItem(q, 1, ri)
            combo = QComboBox()
            for val, text in CHOICES:
                combo.addItem(text, val)
            vals = [c[0] for c in CHOICES]
            combo.setCurrentIndex(vals.index(self.answers[q]) if self.answers[q] in vals else 0)
            combo.currentIndexChanged.connect(lambda _i, qq=q, cb=combo: self._answer_changed(qq, cb))
            self.ans.setCellWidget(q, 2, combo)
            ki = QTableWidgetItem(s.kunci[q] if s and q < s.jumlah else "")
            ki.setTextAlignment(Qt.AlignCenter)
            self.ans.setItem(q, 3, ki)
            res = QTableWidgetItem("")
            res.setTextAlignment(Qt.AlignCenter)
            self.ans.setItem(q, 4, res)
        self._update_results()
        self._filter_answers()

    def _update_results(self):
        s = self._soal()
        for q in range(self.ans.rowCount()):
            a = self.answers[q]
            if s is None or q >= s.jumlah:
                txt, col = "", None
            elif a == "*":
                txt, col = "salah (ganda)", "error"
            elif a == "":
                txt, col = "kosong", None
            elif a == s.kunci[q]:
                txt, col = "benar", "ok"
            else:
                txt, col = "salah", "error"
            it = self.ans.item(q, 4)
            it.setText(txt)
            paint(it, col)
        if s:
            sk = NI.nilai(self.answers, s)
            mut = theme.c("muted")
            self.score_lbl.setText(
                f"<span style='font-size:14pt; font-weight:600'>{sk.nilai}</span>"
                f"<span style='color:{mut}'> /{4 * s.jumlah} &nbsp;·&nbsp; {sk.benar} benar &nbsp;·&nbsp; "
                f"{sk.salah} salah &nbsp;·&nbsp; {sk.kosong} kosong</span>")
        else:
            self.score_lbl.setText(f"<span style='color:{theme.c('muted')}'>Nilai belum bisa dihitung: "
                                   "kode naskah belum terdaftar</span>")

    def _filter_answers(self):
        kinds = self.baca.get("jawaban_kind", [])
        only = self.only_bad.isChecked()
        for q in range(self.ans.rowCount()):
            bad = q < len(kinds) and kinds[q] in ("ragu", "ganda")
            self.ans.setRowHidden(q, only and not bad)

    # ---------------------------------------------------------------- keputusan satu soal
    def _set_decision(self, q):
        """Kotak keputusan untuk soal q (0-based): apa yang terbaca dan tombol pilihan jawabannya."""
        if q is None or q >= self.ans.rowCount():
            self._dec_q = None
            self.decide.setVisible(False)
            return
        self._dec_q = q
        kinds = self.baca.get("jawaban_kind", [])
        read = self.baca.get("jawaban", [])
        tebak = (self.baca.get("tebakan") or {}).get("jawaban", [])
        kind = kinds[q] if q < len(kinds) else ""
        raw = read[q] if q < len(read) else ""
        guess = tebak[q] if q < len(tebak) and tebak[q] in "ABCDE" else ""
        if kind == "ragu" or raw == "?":
            text = "Isian tipis atau bekas hapusan" + (f"; mesin menebak {guess}." if guess else ".")
        elif kind == "ganda" or raw == "*":
            text = "Lebih dari satu pilihan terisi; dihitung salah kecuali dipilih salah satu."
        else:
            text = f"Terbaca {raw}." if raw else "Terbaca kosong."
        self.dec_title.setText(f"Soal {q + 1}")
        self.dec_text.setText(text + " Pastikan pilihannya.")
        self.decide.setVisible(True)
        self._sync_decision()

    def _sync_decision(self):
        if self._dec_q is None:
            return
        b = self.dec_btns.get(self.answers[self._dec_q])
        if b is not None:
            b.setChecked(True)

    def _choose(self, val, key=False):
        q = self._dec_q
        if q is None or not self.decide.isVisible() or not self.decide.isEnabled() or q >= self.ans.rowCount():
            return
        combo = self.ans.cellWidget(q, 2)
        vals = [c[0] for c in CHOICES]
        combo.setCurrentIndex(vals.index(val))     # memicu _answer_changed: tandai belum disimpan, hitung ulang nilai
        self._sync_decision()
        if key:
            self.dec_btns[val].setFocus()

    # ---------------------------------------------------------------- aksi
    def _mark_dirty(self, *_):
        if not self._loading:
            self.dirty = True
            self._update_status()

    def _kode_changed(self, _text):
        if self._loading or self.cur is None:
            return
        self._mark_dirty()
        self._update_kode_label()
        self._fill_answers()
        self._set_decision(self._dec_q)

    def _answer_changed(self, q, combo):
        self.answers[q] = combo.currentData()
        self._mark_dirty()
        self._update_results()
        if q == self._dec_q:
            self._sync_decision()

    def _issue_clicked(self, item):
        it = item.data(Qt.UserRole)
        if not it:
            return
        self.view.focus(it.get("x"), it.get("y"))
        key = it.get("key", "")
        if key.startswith("soal:"):
            q = int(key.split(":")[1]) - 1
            if q < self.ans.rowCount():
                self._set_decision(q)
                self.ans.selectRow(q)
                self.ans.scrollToItem(self.ans.item(q, 0))
        elif key.startswith(("nama", "nomor", "kode", "tanggal")):
            {"nama": self.f_nama, "nomor": self.f_nomor, "kode": self.f_kode,
             "tanggal": self.f_tanggal}[key.split(":")[0]].setFocus()

    def _answer_clicked(self, r, _c):
        self._set_decision(r)
        xy = self.baca.get("jawaban_xy", [])
        if r < len(xy):
            self.view.focus(*xy[r])

    def _reset(self):
        """Pulihkan isian ke hasil baca awal (bulatan ragu diisi tebakan terkuatnya)."""
        if self.cur is None:
            return
        b = self.baca
        t = b.get("tebakan") or b
        self._loading = True
        self.f_nama.setText(t.get("nama", ""))
        self.f_nomor.setText(t.get("nomor", ""))
        self.f_kode.setCurrentText(t.get("kode", ""))
        self.f_tanggal.setText(t.get("tanggal", ""))
        self._loading = False
        valid = {c[0] for c in CHOICES}
        self.answers = [a if a in valid else "" for a in t.get("jawaban", [""] * 180)]
        self._update_kode_label()
        self._fill_answers()
        self._set_decision(self._dec_q)
        self.dirty = True
        self._update_status()

    def _save(self, go_next=True):
        if self.cur is None or self.cur["error"]:
            return False
        nama = " ".join(self.f_nama.text().upper().split())
        nomor = self.f_nomor.text().strip()
        kode = self.f_kode.currentText().strip()
        tanggal = self.f_tanggal.text().strip()
        warn = []
        if any(ch in nama + nomor + kode for ch in "?_"):
            warn.append("Masih ada tanda ? atau _ di nama, nomor peserta, atau kode naskah.")
        if not nomor.isdigit():
            warn.append("Nomor peserta belum berupa angka lengkap.")
        if self._soal() is None:
            warn.append(f"Kode naskah '{kode}' belum terdaftar di kunci; lembar ini tidak akan ikut diekspor.")
        if warn and QMessageBox.question(self, "Simpan", "\n".join(warn) + "\n\nTetap simpan?") != QMessageBox.Yes:
            return False
        cur_id = self.cur["id"]
        # lembar berikutnya menurut antrean ditentukan sebelum status lembar ini berubah
        nxt = self.next_id(cur_id) if go_next and self.next_id is not None else None
        self.db.save_review(cur_id, nama, nomor, kode, tanggal, self.answers, dicek=True)
        self.dirty = False
        self.refresh_list()
        self.changed.emit()
        self.cur = self.db.lembar_by_id(cur_id)
        if go_next:
            if nxt is None and self.next_id is None and cur_id in self.ids:
                i = self.ids.index(cur_id)
                for j in range(i + 1, len(self.ids)):
                    if self.status.get(self.ids[j]) in ("Perlu cek", "Gagal"):
                        nxt = self.ids[j]
                        break
                if nxt is None:
                    nxt = self._first_to_check()
            if nxt is not None and nxt != cur_id:
                self.show_lembar(nxt)
                return True
            QMessageBox.information(self, "Cek manual", "Tidak ada lagi lembar yang perlu dicek.")
        self.show_lembar(cur_id)
        return True
