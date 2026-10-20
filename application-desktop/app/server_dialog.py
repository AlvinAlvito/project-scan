"""Dialog koneksi ke server LJK Reader Online dan pemilihan kompetisi server untuk sebuah event."""
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


class KompetisiDialog(QDialog):
    """Pilih kompetisi di server yang dihubungkan dengan event desktop ini."""

    def __init__(self, parent, items, current=None):
        super().__init__(parent)
        self.setWindowTitle("Hubungkan ke kompetisi server")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(12)
        t = QLabel("Pilih kompetisi di server")
        t.setProperty("role", "title")
        v.addWidget(t)
        s = QLabel("LJK yang dikirim admin daerah untuk kompetisi ini akan ditarik ke event yang sedang dibuka.")
        s.setProperty("role", "muted")
        s.setWordWrap(True)
        v.addWidget(s)
        self.list = QListWidget()
        for k in items:
            bidang = ", ".join(f"{b['nama']} ({b['kode_naskah']})" for b in k["bidang"]) or "belum ada bidang"
            it = QListWidgetItem(f"{k['nama']}  ·  {fmt_date(k['tanggal']) or '-'}  ·  {len(k['lokasi'])} lokasi\n{bidang}")
            it.setData(Qt.UserRole, k)
            self.list.addItem(it)
            if k["id"] == current:
                self.list.setCurrentItem(it)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        v.addWidget(self.list, 1)
        bar = QHBoxLayout()
        bar.addStretch()
        bar.addWidget(theme.button("Batal", variant="ghost", slot=self.reject))
        ok = theme.button("Hubungkan", "check", "primary", slot=self.accept)
        ok.setDefault(True)
        bar.addWidget(ok)
        v.addLayout(bar)
        self.resize(560, 420)

    def selected(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None
