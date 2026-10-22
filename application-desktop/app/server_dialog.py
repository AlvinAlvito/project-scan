"""Dialog koneksi ke server LJK Reader Online dan pengiriman event desktop ke kompetisi server."""
import re
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QVBoxLayout)

from app import server_client as SC
from app import theme
from app.widgets import badge, set_badge

BULAN = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
         "November", "Desember")


def fmt_date(s):
    """'2026-09-24' -> '24 September 2026'; teks lain apa adanya."""
    try:
        y, m, d = (int(x) for x in (s or "").split("-"))
        return f"{d} {BULAN[m - 1]} {y}"
    except (ValueError, IndexError):
        return s or ""


_BULAN3 = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "may": 5, "jun": 6, "jul": 7, "agu": 8, "agt": 8,
           "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "des": 12, "dec": 12}


def iso_date(s):
    """Kebalikan fmt_date: '20 OKTOBER 2026', '16/10/2026', '2026-10-16' -> '2026-10-16'.
    None bila teks tidak dikenali sebagai tanggal."""
    s = (s or "").strip()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
        y, mo, d = map(int, m.groups())
    elif m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", s):
        d, mo, y = map(int, m.groups())
    elif m := re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s):
        d, mo, y = int(m[1]), _BULAN3.get(m[2][:3].lower()), int(m[3])
        if mo is None:
            return None
    else:
        return None
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


class ServerDialog(QDialog):
    """Atur alamat server dan login superadmin. Token disimpan; kata sandi tidak."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Server")
        c = SC.config()
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(14)
        head = QHBoxLayout()
        title = QLabel("Koneksi server")
        title.setProperty("role", "title")
        head.addWidget(title)
        head.addStretch()
        self.state = badge("", "neutral")
        head.addWidget(self.state)
        v.addLayout(head)
        sub = QLabel("Untuk menarik LJK yang dikirim admin daerah lewat HP. Gunakan akun superadmin.")
        sub.setProperty("role", "muted")
        sub.setWordWrap(True)
        v.addWidget(sub)
        form = QFormLayout()
        form.setSpacing(10)
        self.url = QLineEdit(c["url"] or "http://localhost:8000")
        self.url.setPlaceholderText("https://ljk.posi.id")
        self.user = QLineEdit(c["username"])
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("tidak disimpan")
        form.addRow("Alamat server", self.url)
        form.addRow("Username", self.user)
        form.addRow("Kata sandi", self.pw)
        v.addLayout(form)
        bar = QHBoxLayout()
        self.btn_out = theme.button("Keluar", "x", "ghost", slot=self._logout)
        bar.addWidget(self.btn_out)
        bar.addStretch()
        bar.addWidget(theme.button("Tutup", variant="ghost", slot=self.reject))
        login = theme.button("Masuk", "check", "primary", slot=self._login)
        login.setDefault(True)
        bar.addWidget(login)
        v.addLayout(bar)
        self.resize(480, 0)
        self._update()

    def _update(self):
        c = SC.config()
        on = SC.logged_in()
        set_badge(self.state, f"Terhubung · {c['nama']}" if on else "Belum terhubung", "ok" if on else "neutral")
        self.btn_out.setVisible(on)

    def _login(self):
        url, user, pw = self.url.text().strip().rstrip("/"), self.user.text().strip(), self.pw.text()
        if not url or not user or not pw:
            QMessageBox.warning(self, "Server", "Isi alamat server, username, dan kata sandi.")
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            u = SC.login(url, user, pw)
        except SC.ServerError as e:
            QMessageBox.warning(self, "Server", str(e))
            return
        self.pw.clear()
        self._update()
        QMessageBox.information(self, "Server", f"Terhubung sebagai {u['nama']}.")
        self.accept()

    def _logout(self):
        SC.logout()
        self._update()


def same_name(a, b):
    return " ".join((a or "").split()).casefold() == " ".join((b or "").split()).casefold()


class KirimDialog(QDialog):
    """Event desktop yang belum terhubung -> kompetisi server: buat kompetisi baru, atau gabungkan dengan
    kompetisi yang sudah ada. Kompetisi yang sudah dipakai event desktop lain berisi data tidak bisa dipilih
    (satu kompetisi hanya boleh terhubung ke satu event, supaya lembar yang ditarik tidak terbelah)."""

    NEW = "baru"

    def __init__(self, parent, ev, n_bidang, items, taken):
        """items: kompetisi di server. taken: {kompetisi_id: (event desktop lain yang terhubung, berisi data?)}."""
        super().__init__(parent)
        self.setWindowTitle("Kirim event ke server")
        self.ev, self.taken = ev, taken
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(12)
        t = QLabel("Kirim event ke server")
        t.setProperty("role", "title")
        v.addWidget(t)
        what = (f"{n_bidang} bidang (kode naskah, nama bidang, jumlah soal)" if n_bidang else
                "belum ada bidang: isi Kunci Jawaban dulu bila bidangnya ingin ikut terkirim")
        s = QLabel(f"Yang dikirim: nama event, tanggal, dan {what}. Kunci jawaban tidak dikirim.")
        s.setProperty("role", "muted")
        s.setWordWrap(True)
        v.addWidget(s)

        self.list = QListWidget()
        new = QListWidgetItem(f"Buat kompetisi baru\n{ev['nama']}  ·  {ev['tanggal'] or '-'}")
        new.setData(Qt.UserRole, self.NEW)
        self.list.addItem(new)
        match = None
        if items:
            head = QListWidgetItem("Atau gabungkan dengan kompetisi yang sudah ada:")
            head.setFlags(Qt.NoItemFlags)
            self.list.addItem(head)
        for k in items:
            bidang = ", ".join(f"{b['nama']} ({b['kode_naskah']})" for b in k["bidang"]) or "belum ada bidang"
            line2 = bidang
            it = QListWidgetItem()
            it.setData(Qt.UserRole, k)
            other, has_data = taken.get(k["id"], (None, False))
            if other is not None and has_data:
                line2 = f"sudah dipakai event '{other['nama']}' di desktop"
                it.setFlags(Qt.NoItemFlags)
                it.setToolTip("Satu kompetisi hanya boleh terhubung ke satu event desktop.")
            it.setText(f"{k['nama']}  ·  {fmt_date(k['tanggal']) or '-'}  ·  {len(k['lokasi'])} lokasi\n{line2}")
            self.list.addItem(it)
            if match is None and it.flags() & Qt.ItemIsEnabled and same_name(k["nama"], ev["nama"]):
                match = it
        self.list.setCurrentItem(match or new)
        self.list.currentItemChanged.connect(lambda *_: self._hint())
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        v.addWidget(self.list, 1)
        self.hint = QLabel("")
        self.hint.setTextFormat(Qt.PlainText)
        self.hint.setProperty("role", "muted")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)
        self._same = any(same_name(k["nama"], ev["nama"]) for k in items)

        bar = QHBoxLayout()
        bar.addStretch()
        bar.addWidget(theme.button("Batal", variant="ghost", slot=self.reject))
        ok = theme.button("Kirim", "cloud-upload", "primary", slot=self.accept)
        ok.setDefault(True)
        bar.addWidget(ok)
        v.addLayout(bar)
        self.resize(600, 460)
        self._hint()

    def _hint(self):
        k = self.selected()
        if k is None:
            text = ""
        elif k == self.NEW:
            text = ("Kompetisi baru dibuat dengan nama dan tanggal event ini. Lokasi, peserta, dan akun admin "
                    "daerah dilengkapi di panel admin web.")
            if self._same:
                text = "Sudah ada kompetisi bernama sama di server. " + text
        else:
            text = ("Event ini dihubungkan ke kompetisi itu; nama dan tanggalnya mengikuti server. Bidang dari Kunci "
                    "Jawaban yang kode naskahnya belum ada di server ditambahkan; bidang server tidak diubah.")
            other, _has = self.taken.get(k["id"], (None, False))
            if other is not None:
                text += f" Event kosong '{other['nama']}' di desktop yang dibuat otomatis untuk kompetisi ini diganti."
        self.hint.setText(text)

    def accept(self):
        if self.selected() is not None:
            super().accept()

    def selected(self):
        """KirimDialog.NEW, data kompetisi yang dipilih, atau None."""
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it and it.flags() & Qt.ItemIsEnabled else None
