"""Tab Kunci jawaban event: paket kunci yang dipakai event ini dan kode naskah di dalamnya.

Kunci jawaban tidak lagi diisi per event, tetapi di pustaka paket kunci (menu Kunci jawaban di sidebar,
app/paket_page.py) supaya satu paket bisa dipakai banyak event. Di sini panitia memilih/mengganti paket dan
melihat kode naskah mana yang sudah dinilai. Event lama yang belum memilih paket masih memakai kunci yang
tersimpan langsung di event (ditampilkan apa adanya sampai paket dipilih)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QHeaderView, QLabel, QStackedWidget, QTableWidget, QVBoxLayout,
                               QWidget)

from app import theme
from app.colors import paint
from app.paket_page import _item, kode_lembar, nomor_tanpa_kunci, pilih_paket, ringkas_kode
from app.widgets import EmptyState, setup_table
from ljk.db import kode_sort, kunci_lengkap


class KunciTab(QWidget):
    changed = Signal()              # paket event diganti: nilai lembar dihitung ulang
    buka_paket = Signal(object)     # minta jendela membuka menu Kunci jawaban (id paket, atau None)

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.event_id = None
        self.paket_id = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 18, 0, 0)
        v.setSpacing(14)

        # ---- kartu paket yang dipakai
        self.card = QFrame()
        self.card.setProperty("role", "card")
        ch = QHBoxLayout(self.card)
        ch.setContentsMargins(18, 12, 12, 12)
        ch.setSpacing(8)
        col = QVBoxLayout()
        col.setSpacing(2)
        cap = QLabel("Paket kunci jawaban")
        cap.setProperty("role", "section")
        self.p_name = QLabel("")
        self.p_name.setProperty("role", "h2")
        self.p_name.setWordWrap(True)
        self.p_sub = QLabel("")
        self.p_sub.setProperty("role", "muted")
        self.p_sub.setWordWrap(True)
        self.p_sub.setTextFormat(Qt.RichText)
        for w in (cap, self.p_name, self.p_sub):
            col.addWidget(w)
        ch.addLayout(col, 1)
        self.btn_ganti = theme.button("Ganti paket", "refresh", tip="Pilih paket kunci lain untuk event ini",
                                      slot=self._pilih)
        self.btn_buka = theme.button("Buka paket", "key", tip="Lihat atau ubah isi paket di menu Kunci jawaban",
                                     slot=lambda: self.buka_paket.emit(self.paket_id))
        ch.addWidget(self.btn_ganti, 0, Qt.AlignVCenter)
        ch.addWidget(self.btn_buka, 0, Qt.AlignVCenter)

        # ---- catatan: kode server yang belum ada di paket / kunci lama
        self.note = QFrame()
        self.note.setProperty("role", "card")
        nh = QHBoxLayout(self.note)
        nh.setContentsMargins(16, 10, 12, 10)
        nh.setSpacing(10)
        self.note_text = QLabel("")
        self.note_text.setWordWrap(True)
        self.note_text.setTextFormat(Qt.RichText)
        nh.addWidget(self.note_text, 1)
        self.note_btn = theme.button("", "key", "primary")
        self.note_btn.clicked.connect(self._note_action)
        nh.addWidget(self.note_btn, 0, Qt.AlignVCenter)
        self._note_do = None

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Kode naskah", "Mata pelajaran", "Soal", "Lembar di event ini", "Catatan"])
        setup_table(self.table)
        self.table.setToolTip("Isi paket diubah di menu Kunci jawaban (sidebar kiri).")
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 260)
        self.table.cellDoubleClicked.connect(lambda *_: self.paket_id is not None and self.buka_paket.emit(self.paket_id))

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(14)
        cv.addWidget(self.card)
        cv.addWidget(self.note)
        cv.addWidget(self.table, 1)

        self.empty = EmptyState("key", "Event ini belum memakai paket kunci jawaban",
                                "Pilih paket kunci (mis. FSN PROVINSI PAKET 1) yang dipakai menilai lembar event ini. "
                                "Paket dibuat dan diisi di menu Kunci jawaban (sidebar kiri).",
                                theme.button("Pilih paket kunci", "key", "primary", slot=self._pilih))
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(content)
        v.addWidget(self.stack, 1)

    # ---- dipanggil jendela utama (antarmuka lama tab Kunci tetap ada: kunci tidak lagi diedit di sini)
    def confirm_leave(self):
        return True

    def ask_save(self):
        return True

    def _set_dirty(self, _dirty):
        pass

    def show_server_bidang(self):
        """Daftar bidang server event berubah (sinkron): muat ulang tampilan."""
        self.load(self.event_id)

    # ---- data
    def load(self, event_id):
        self.event_id = event_id
        self.table.setRowCount(0)
        self.note.setVisible(False)
        if event_id is None:
            self.paket_id = None
            self.stack.setCurrentWidget(self.empty)
            return
        paket = self.db.event_paket(event_id)
        self.paket_id = paket["id"] if paket else None
        lembar = kode_lembar(self.db, event_id)
        if paket is None:
            lama = self.db.naskah_lama(event_id)
            if not lama:
                self.stack.setCurrentWidget(self.empty)
                return
            self._show_lama(lama, lembar)
        else:
            self._show_paket(paket, lembar)
        self.stack.setCurrentIndex(1)

    def _row(self, kode, nama, jumlah, n_lembar, note="", tone=None):
        r = self.table.rowCount()
        self.table.insertRow(r)
        ki = _item(kode)
        ki.setFont(theme.mono())
        self.table.setItem(r, 0, ki)
        self.table.setItem(r, 1, _item(nama, tip=nama))
        self.table.setItem(r, 2, _item(str(jumlah) if jumlah != "" else "", Qt.AlignCenter))
        self.table.setItem(r, 3, _item(str(n_lembar) if n_lembar else "—", Qt.AlignCenter))
        ci = _item(note, tip=note)
        if tone:
            paint(ci, tone)
        self.table.setItem(r, 4, ci)

    def _show_paket(self, paket, lembar):
        mapel = self.db.mapel(paket["id"])
        evs = [e["nama"] for e in self.db.paket_events(paket["id"])]
        lain = [n for n in evs if n != self.db.event(self.event_id)["nama"]]
        self.p_name.setText(paket["nama"])
        kode_all = [k for m in mapel for k in m["kode"]]
        sub = [f"{len(mapel)} mata pelajaran", f"kode naskah {ringkas_kode(kode_all)}" if kode_all else "belum ada kode naskah"]
        sub.append(f"juga dipakai {', '.join(lain[:4])}{'…' if len(lain) > 4 else ''}" if lain else "hanya dipakai event ini")
        self.p_sub.setText(" &nbsp;·&nbsp; ".join(sub))
        self.btn_buka.setVisible(True)
        self.btn_ganti.setVisible(True)

        rows = []
        for m in mapel:
            bad = nomor_tanpa_kunci(m["kunci"])
            for k in m["kode"]:
                if not kunci_lengkap(m["kunci"]):
                    note, tone = (f"kunci belum lengkap (soal {', '.join(map(str, bad[:6]))}"
                                  f"{'…' if len(bad) > 6 else ''}): lembar belum dinilai", "error")
                else:
                    note, tone = "", None
                rows.append((k, m["nama"], len(m["kunci"]), lembar.get(k, 0), note, tone))
            if not m["kode"]:
                rows.append(("—", m["nama"], len(m["kunci"]), 0, "belum ada kode naskah (isi di menu Kunci jawaban)",
                             "warn"))
        punya = set(kode_all)
        for k, n in lembar.items():
            if k not in punya:
                rows.append((k, "—", "", n, "kode naskah ini tidak ada di paket: lembarnya belum dinilai", "error"))
        rows.sort(key=lambda r: (r[0] == "—", kode_sort(r[0]) if r[0] != "—" else (0, 0)))
        for r in rows:
            self._row(*r)

        missing = [b for b in self.db.server_bidang(self.event_id) if b["kode_naskah"] not in punya]
        if missing:
            daftar = ", ".join(f"<b>{b['nama']}</b> ({b['kode_naskah']} · {b['jumlah_soal']} soal)" for b in missing)
            self._set_note(f"Kode naskah dari server yang belum ada di paket {paket['nama']}: {daftar}. "
                           "Tambahkan kodenya ke mata pelajaran yang sesuai di paket.",
                           "Buka paket", lambda: self.buka_paket.emit(self.paket_id))

    def _show_lama(self, lama, lembar):
        self.p_name.setText("Kunci lama (tersimpan langsung di event ini)")
        self.p_sub.setText(f"{len(lama)} kode naskah &nbsp;·&nbsp; dibuat sebelum ada paket kunci")
        self.btn_buka.setVisible(False)
        self.btn_ganti.setVisible(False)            # tombol "Pilih paket kunci" ada di catatan di bawahnya
        for s in lama:
            self._row(s.kode, s.bidang, s.jumlah, lembar.get(s.kode, 0))
        punya = {s.kode for s in lama}
        for k, n in sorted(lembar.items(), key=lambda kv: kode_sort(kv[0])):
            if k not in punya:
                self._row(k, "—", "", n, "kode naskah ini tidak ada di kunci: lembarnya belum dinilai", "error")
        self._set_note("Event ini dibuat sebelum ada paket kunci, jadi masih memakai kunci yang tersimpan di event. "
                       "Pilih paket kunci untuk menggantinya (kunci lama tidak dihapus).",
                       "Pilih paket kunci", self._pilih)

    def _set_note(self, text, button, action):
        self.note_text.setText(text)
        self.note_btn.setText(button)
        self._note_do = action
        self.note.setVisible(True)

    def _note_action(self):
        if self._note_do:
            self._note_do()

    # ---- pilih / ganti paket
    def _pilih(self):
        if self.event_id is None:
            return
        r = pilih_paket(self, self.db, self.event_id)
        if r == "buka":
            self.buka_paket.emit(None)
        elif r:
            self.load(self.event_id)
            self.changed.emit()
