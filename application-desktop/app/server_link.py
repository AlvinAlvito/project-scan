"""Event desktop -> server LJK Reader Online.

Event lokal dikirim menjadi kompetisi baru, atau digabung dengan kompetisi yang sudah ada. Yang dikirim hanya
nama, tanggal, dan bidang (kode naskah, nama bidang, jumlah soal); kunci jawaban tidak pernah keluar dari laptop.
Setelah terhubung, nama/tanggal/daftar bidang mengikuti server (MainWindow._sync_server_events). Bidang server
tidak pernah diubah atau dihapus dari sini, hanya ditambah. Satu kompetisi terhubung ke tepat satu event desktop.
"""
import shutil
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from app import server_client as SC
from app.server_dialog import KirimDialog, ServerDialog, fmt_date, iso_date


def apply_kompetisi(db, url, k):
    """Simpan nama/tanggal/bidang kompetisi server ke event desktop yang terhubung (dibuat bila belum ada)."""
    bidang = [{"kode_naskah": b["kode_naskah"], "nama": b["nama"], "jumlah_soal": b["jumlah_soal"]}
              for b in k.get("bidang", [])]
    return db.upsert_server_event(url, k["id"], k["nama"], fmt_date(k["tanggal"]), bidang)


def push_bidang(db, event_id, k):
    """Tambahkan ke kompetisi k bidang dari Kunci Jawaban yang kode naskahnya belum ada di server.
    Mengembalikan (terkirim, berbeda, gagal): daftar teks untuk laporan."""
    server = {b["kode_naskah"]: b for b in k.get("bidang", [])}
    sent, differ, failed = [], [], []
    for s in db.naskah(event_id):
        n = len(s.kunci)
        b = server.get(s.kode)
        if b is not None:
            if b["jumlah_soal"] != n or " ".join(b["nama"].split()).casefold() != " ".join(s.bidang.split()).casefold():
                differ.append(f"{s.kode}: server '{b['nama']}' {b['jumlah_soal']} soal, "
                              f"laptop '{s.bidang}' {n} soal")
            continue
        if not 1 <= len(s.kode) <= 10 or not s.bidang.strip() or not 1 <= n <= 180:
            failed.append(f"{s.kode or '(tanpa kode)'}: perlu kode naskah 1-10 karakter, nama bidang, dan 1-180 soal")
            continue
        try:
            SC.add_bidang(k["id"], s.kode, s.bidang.strip()[:120], n)
            sent.append(f"{s.bidang} ({s.kode}, {n} soal)")
        except SC.ServerError as e:
            failed.append(f"{s.kode}: {e}")
    return sent, differ, failed


def kirim(parent, db, data_dir, event_id):
    """Kirim event ke server. Belum terhubung: pilih kompetisi baru atau gabung. Sudah terhubung: hanya
    menambah bidang yang belum ada di server. Mengembalikan id kompetisi yang terhubung, atau None."""
    if not SC.logged_in() and not ServerDialog(parent).exec():
        return None
    url = SC.config()["url"]
    ev = db.event(event_id)
    kid = ev["server_kompetisi_id"] if ev["server_url"] == url else None
    try:
        return _kirim_bidang(parent, db, event_id, url, kid) if kid else _hubungkan(parent, db, data_dir, ev, url)
    except SC.ServerError as e:
        QMessageBox.warning(parent, "Kirim ke server", str(e))
        return None


def _has_data(db, event_id):
    return bool(db.naskah(event_id) or db.lembar(event_id))


def _hubungkan(parent, db, data_dir, ev, url):
    items = SC.kompetisi()
    taken = {}
    for k in items:
        other = db.event_for_kompetisi(url, k["id"])
        if other is not None and other["id"] != ev["id"]:
            taken[k["id"]] = (other, _has_data(db, other["id"]))
    d = KirimDialog(parent, ev, len(db.naskah(ev["id"])), items, taken)
    if not d.exec():
        return None
    k = d.selected()
    replaced = None
    if k != KirimDialog.NEW:
        # periksa ulang: sinkron otomatis bisa membuat event untuk kompetisi ini selama dialog terbuka
        other = db.event_for_kompetisi(url, k["id"])
        if other is not None and other["id"] != ev["id"]:
            if _has_data(db, other["id"]):
                QMessageBox.warning(parent, "Kirim ke server",
                                    f"Kompetisi '{k['nama']}' sudah terhubung ke event '{other['nama']}' "
                                    "yang berisi data. Pakai event itu, atau buat kompetisi baru.")
                return None
            replaced = other
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        if k == KirimDialog.NEW:
            k = SC.create_kompetisi(ev["nama"], iso_date(ev["tanggal"]) or ev["tanggal"])
        elif replaced is not None:      # event kosong buatan sinkron otomatis: digantikan event ini
            shutil.rmtree(data_dir / "event" / str(replaced["id"]), ignore_errors=True)
            db.delete_event(replaced["id"])
        # langsung ditautkan (tanpa jeda event loop), supaya sinkron otomatis tidak membuat event kedua
        db.link_server(ev["id"], k["id"], url)
        sent, differ, failed = push_bidang(db, ev["id"], k)
        try:
            apply_kompetisi(db, url, SC.get_kompetisi(k["id"]))
        except SC.ServerError:
            pass                          # nama/tanggal/bidang diperbarui pada sinkron berikutnya
    finally:
        QApplication.restoreOverrideCursor()
    lines = [f"Event <b>{escape(ev['nama'])}</b> sekarang terhubung ke kompetisi server "
             f"<b>{escape(k['nama'])}</b>."]
    if replaced is not None:
        lines.append(f"Event kosong '{escape(replaced['nama'])}' yang dibuat otomatis untuk kompetisi ini sudah "
                     "diganti dengan event ini.")
    lines += _report(db, ev["id"], sent, differ, failed)
    lines.append("Lengkapi lokasi, peserta, dan akun admin daerah di panel admin web.")
    QMessageBox.information(parent, "Kirim ke server", "<br><br>".join(lines))
    return k["id"]


def _kirim_bidang(parent, db, event_id, url, kid):
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        k = SC.get_kompetisi(kid)
        sent, differ, failed = push_bidang(db, event_id, k)
        apply_kompetisi(db, url, SC.get_kompetisi(kid) if sent else k)
    finally:
        QApplication.restoreOverrideCursor()
    lines = _report(db, event_id, sent, differ, failed)
    if not sent and not differ and not failed and db.naskah(event_id):
        lines = ["Semua bidang di Kunci Jawaban sudah ada di server."]
    QMessageBox.information(parent, "Kirim ke server", "<br><br>".join(lines))
    return kid


def _report(db, event_id, sent, differ, failed):
    out = []
    if sent:
        out.append(f"{len(sent)} bidang dikirim: " + escape(", ".join(sent)))
    elif not db.naskah(event_id):
        out.append("Belum ada bidang yang dikirim karena Kunci Jawaban masih kosong. Setelah kunci diisi dan "
                   "disimpan, klik tombol kirim lagi (atau tambah bidang di panel admin web).")
    if differ:
        out.append("Sudah ada di server dengan data berbeda (server tidak diubah):<br>&bull; "
                   + "<br>&bull; ".join(escape(x) for x in differ))
    if failed:
        out.append("Gagal dikirim:<br>&bull; " + "<br>&bull; ".join(escape(x) for x in failed))
    return out
