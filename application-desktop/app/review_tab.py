"""Tab 3: cek manual satu lembar - gambar di kiri, data & jawaban yang bisa diubah di kanan."""
import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from app.colors import paint
from app.imageview import ImageView
from ljk import nilai as NI
from ljk import service as SV

CHOICES = [("", "-"), ("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"), ("E", "E"), ("*", "ganda")]
KIND_COLOR = {"ragu": QColor(255, 216, 168), "ganda": QColor(255, 179, 179)}
HW_ORDER = [("kotak_nama", "Nama (kotak)"), ("kotak_nomor", "Nomor"), ("kotak_kode", "Kode"),
            ("kotak_tanggal", "Tanggal"), ("bidang", "Bidang"), ("sekolah", "Sekolah"), ("kelas", "Kelas"),
            ("hp", "No. HP/WA")]
HW_MAKS = (460, 56)     # ukuran tampil maksimum potongan tulisan tangan (lebar, tinggi)


class ReviewTab(QWidget):
    changed = Signal()

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

        v = QVBoxLayout(self)
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("< Sebelumnya")
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.picker = QComboBox()
        self.picker.setMinimumWidth(420)
        self.picker.activated.connect(lambda i: self.show_lembar(self.ids[i]))
        self.btn_next = QPushButton("Berikutnya >")
        self.btn_next.clicked.connect(lambda: self._step(1))
        self.only_check = QCheckBox("Lompat hanya ke yang perlu cek")
        self.only_check.setChecked(True)
        for w in (self.btn_prev, self.picker, self.btn_next, self.only_check):
            nav.addWidget(w)
        nav.addStretch()
        self.status_label = QLabel("")
        nav.addWidget(self.status_label)
        v.addLayout(nav)

        split = QSplitter(Qt.Horizontal)
        # kiri: gambar
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.view = ImageView()
        zb = QHBoxLayout()
        for text, fn in (("Muat layar", lambda: self.view.fit()), ("Perbesar", lambda: self.view.zoom(1.25)),
                         ("Perkecil", lambda: self.view.zoom(0.8))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            zb.addWidget(b)
        zb.addStretch()
        lv.addLayout(zb)
        lv.addWidget(self.view)
        split.addWidget(left)

        # kanan: data
        right = QWidget()
        rv = QVBoxLayout(right)
        g_issue = QGroupBox("Hal yang perlu dicek (klik untuk melihat di gambar)")
        gl = QVBoxLayout(g_issue)
        self.issues = QListWidget()
        self.issues.setMaximumHeight(130)
        self.issues.itemClicked.connect(self._issue_clicked)
        gl.addWidget(self.issues)
        rv.addWidget(g_issue)

        g_data = QGroupBox("Data peserta")
        form = QFormLayout(g_data)
        self.f_nama, self.f_nomor, self.f_tanggal = QLineEdit(), QLineEdit(), QLineEdit()
        self.f_kode = QComboBox()
        self.f_kode.setEditable(True)
        self.f_bidang = QLabel("")
        self.read_lbl = {k: QLabel("") for k in ("nama", "nomor", "kode", "tanggal")}
        for lbl in self.read_lbl.values():
            lbl.setStyleSheet("color: gray")
        for key, label, w in (("nama", "Nama", self.f_nama), ("nomor", "Nomor peserta", self.f_nomor),
                              ("kode", "Kode naskah", self.f_kode), ("tanggal", "Tanggal", self.f_tanggal)):
            form.addRow(label, w)
            form.addRow("", self.read_lbl[key])
        form.addRow("Bidang", self.f_bidang)
        for w in (self.f_nama, self.f_nomor, self.f_tanggal):
            w.textEdited.connect(self._mark_dirty)
        self.f_kode.currentTextChanged.connect(self._kode_changed)
        rv.addWidget(g_data)

        g_hw = QGroupBox("Tulisan tangan (pembanding dan konfirmasi dengan peserta)")
        self.hw_layout = QFormLayout(g_hw)
        self.hw_labels = {}
        for key, label in HW_ORDER:
            lb = QLabel()
            lb.setMinimumHeight(28)
            self.hw_labels[key] = lb
            self.hw_layout.addRow(label, lb)
        rv.addWidget(g_hw)

        g_ans = QGroupBox("Jawaban")
        al = QVBoxLayout(g_ans)
        self.score_lbl = QLabel("")
        self.score_lbl.setStyleSheet("font-weight: bold; font-size: 11pt")
        al.addWidget(self.score_lbl)
        self.only_bad = QCheckBox("Hanya soal ragu/ganda")
        self.only_bad.toggled.connect(self._filter_answers)
        al.addWidget(self.only_bad)
        self.ans = QTableWidget(0, 5)
        self.ans.setHorizontalHeaderLabels(["Soal", "Terbaca", "Jawaban akhir", "Kunci", "Hasil"])
        self.ans.verticalHeader().setVisible(False)
        self.ans.setEditTriggers(QTableWidget.NoEditTriggers)
        self.ans.setSelectionBehavior(QTableWidget.SelectRows)
        self.ans.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.ans.setMinimumHeight(260)
        self.ans.cellClicked.connect(self._answer_clicked)
        al.addWidget(self.ans)
        rv.addWidget(g_ans, 1)

        btns = QHBoxLayout()
        self.btn_reset = QPushButton("Kembalikan ke hasil baca")
        self.btn_reset.clicked.connect(self._reset)
        self.btn_save = QPushButton("Simpan && tandai sudah dicek  (Ctrl+Enter)")
        self.btn_save.setStyleSheet("font-weight: bold; padding: 6px")
        self.btn_save.clicked.connect(self._save)
        btns.addWidget(self.btn_reset)
        btns.addStretch()
        btns.addWidget(self.btn_save)
        rv.addLayout(btns)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._save)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(right)
        split.addWidget(scroll)
        right.setMinimumWidth(560)
        split.setSizes([760, 740])
        v.addWidget(split, 1)
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
        self.picker.clear()
        self.ids, self.status = [], {}
        if self.event_id is None:
            return
        for v in SV.event_views(self.db, self.event_id):
            r = v.row
            self.ids.append(r["id"])
            self.status[r["id"]] = v.status
            self.picker.addItem(f"{r['urutan']}. {Path(r['file']).name}  -  {r['nama'] or '?'}  [{v.status}]")
        if self.cur is not None and self.cur["id"] in self.ids:
            self.picker.setCurrentIndex(self.ids.index(self.cur["id"]))
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

    def _step(self, d):
        if self.cur is None or not self.ids:
            return
        i = self.ids.index(self.cur["id"]) if self.cur["id"] in self.ids else 0
        j = i + d
        while 0 <= j < len(self.ids):
            if not self.only_check.isChecked() or self.status.get(self.ids[j]) in ("Perlu cek", "Gagal"):
                self.show_lembar(self.ids[j])
                return
            j += d
        QMessageBox.information(self, "Cek manual", "Tidak ada lagi lembar yang perlu dicek ke arah itu."
                                if self.only_check.isChecked() else "Sudah di ujung daftar.")

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
            if self.cur["id"] in self.ids:
                self.picker.setCurrentIndex(self.ids.index(self.cur["id"]))
            return
        row = self.db.lembar_by_id(lembar_id)
        if row is None:
            return
        self.cur = row
        self.baca = json.loads(row["baca"] or "{}")
        self.answers = json.loads(row["jawaban"] or "[]") or [""] * 180
        if lembar_id in self.ids:
            self.picker.setCurrentIndex(self.ids.index(lembar_id))
        self.view.set_image(row["gambar"])
        self._loading = True
        self.f_nama.setText(row["nama"])
        self.f_nomor.setText(row["nomor"])
        self.f_kode.setCurrentText(row["kode"])
        self.f_tanggal.setText(row["tanggal"])
        for k, lbl in self.read_lbl.items():
            # Tanggal tidak wajib terbaca: tidak perlu menarik perhatian pemeriksa.
            differs = k != "tanggal" and self.baca.get(k, "") != row[k]
            lbl.setText(f"terbaca dari bulatan: {self.baca.get(k, '')}" if differs else "")
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
        self._update_kode_label()
        self._fill_issues()
        self._fill_answers()
        self._enable(not row["error"])
        self.dirty = False
        self._update_status()

    def _clear(self):
        self.cur = None
        self.view.set_image(None)
        self.issues.clear()
        self.ans.setRowCount(0)
        self.status_label.setText("")
        self._enable(False)

    def _enable(self, on):
        for w in (self.f_nama, self.f_nomor, self.f_kode, self.f_tanggal, self.ans, self.btn_save, self.btn_reset):
            w.setEnabled(on)

    def _update_status(self):
        if self.cur is None:
            return
        st = self.status.get(self.cur["id"], "")
        self.status_label.setText(f"Status: <b>{st}</b>" + ("  <span style='color:#c0392b'>(belum disimpan)</span>"
                                                          if self.dirty else ""))

    def _soal(self):
        kode = self.f_kode.currentText().strip()
        for s in self.db.naskah(self.event_id):
            if s.kode == kode:
                return s
        return None

    def _update_kode_label(self):
        s = self._soal()
        self.f_bidang.setText(f"{s.bidang} ({s.jumlah} soal)" if s else
                              "<span style='color:#c0392b'>kode naskah belum terdaftar di kunci</span>")

    def _fill_issues(self):
        self.issues.clear()
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
            if kind in KIND_COLOR:
                for it in (num, ri):
                    paint(it, KIND_COLOR[kind])
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
            self.ans.setItem(q, 4, QTableWidgetItem(""))
        self._update_results()
        self._filter_answers()

    def _update_results(self):
        s = self._soal()
        for q in range(self.ans.rowCount()):
            a = self.answers[q]
            if s is None or q >= s.jumlah:
                txt, col = "", None
            elif a == "*":
                txt, col = "salah (ganda)", QColor(255, 179, 179)
            elif a == "":
                txt, col = "kosong", None
            elif a == s.kunci[q]:
                txt, col = "benar", QColor(212, 237, 218)
            else:
                txt, col = "salah", QColor(248, 215, 218)
            it = self.ans.item(q, 4)
            it.setText(txt)
            paint(it, col)
        if s:
            sk = NI.nilai(self.answers, s)
            self.score_lbl.setText(f"B {sk.benar}  |  S {sk.salah}  |  K {sk.kosong}  |  Nilai {sk.nilai}")
        else:
            self.score_lbl.setText("Nilai: kode naskah belum terdaftar")

    def _filter_answers(self):
        kinds = self.baca.get("jawaban_kind", [])
        only = self.only_bad.isChecked()
        for q in range(self.ans.rowCount()):
            bad = q < len(kinds) and kinds[q] in ("ragu", "ganda")
            self.ans.setRowHidden(q, only and not bad)

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

    def _answer_changed(self, q, combo):
        self.answers[q] = combo.currentData()
        self._mark_dirty()
        self._update_results()

    def _issue_clicked(self, item):
        it = item.data(Qt.UserRole)
        if not it:
            return
        self.view.focus(it.get("x"), it.get("y"))
        key = it.get("key", "")
        if key.startswith("soal:"):
            q = int(key.split(":")[1]) - 1
            if q < self.ans.rowCount():
                self.ans.selectRow(q)
                self.ans.scrollToItem(self.ans.item(q, 0))
                self.ans.cellWidget(q, 2).setFocus()
        elif key.startswith(("nama", "nomor", "kode", "tanggal")):
            {"nama": self.f_nama, "nomor": self.f_nomor, "kode": self.f_kode,
             "tanggal": self.f_tanggal}[key.split(":")[0]].setFocus()

    def _answer_clicked(self, r, _c):
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
        self.db.save_review(self.cur["id"], nama, nomor, kode, tanggal, self.answers, dicek=True)
        self.dirty = False
        cur_id = self.cur["id"]
        self.refresh_list()
        self.changed.emit()
        self.cur = self.db.lembar_by_id(cur_id)
        if go_next:
            nxt = None
            if cur_id in self.ids:
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
