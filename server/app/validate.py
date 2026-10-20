"""Validasi hasil baca terhadap data server: daftar peserta, bidang yang dipilih, dan duplikat.

Hasilnya berupa catatan (teks) yang ditampilkan ke admin daerah di HP dan ikut ditarik ke
desktop sebagai hal yang perlu dicek."""
import difflib

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import models as M


def effective(lembar: M.Lembar) -> dict:
    """Nama/nomor/kode yang berlaku: hasil baca, ditimpa koreksi admin daerah bila ada."""
    hb = lembar.hasil_baca or {}
    kor = (lembar.konfirmasi or {}).get("koreksi") or {}
    return {k: (kor.get(k) or hb.get(k, "")).strip() for k in ("nama", "nomor", "kode")}


def _norm(s):
    return " ".join((s or "").upper().split())


def validate(db: Session, lembar: M.Lembar) -> list[str]:
    """Isi lembar.peserta_id dan kembalikan daftar catatan."""
    if lembar.error:
        return []
    v = effective(lembar)
    notes = []
    bidang = lembar.bidang
    if v["kode"] and bidang and v["kode"] != bidang.kode_naskah:
        notes.append(f"Kode naskah terbaca {v['kode']}, padahal bidang yang dipilih {bidang.nama} "
                     f"(kode {bidang.kode_naskah}).")
    if not v["nomor"] or any(ch in v["nomor"] for ch in "_?"):
        notes.append("Nomor peserta belum terbaca lengkap.")
        lembar.peserta_id = None
    else:
        p = db.scalar(select(M.Peserta).where(M.Peserta.kompetisi_id == lembar.kompetisi_id,
                                              M.Peserta.nomor == v["nomor"]))
        lembar.peserta_id = p.id if p else None
        if p is None:
            if lembar.peserta_baru_status != "disetujui":
                notes.append(f"Nomor peserta {v['nomor']} tidak ada di daftar peserta.")
        else:
            if v["nama"] and difflib.SequenceMatcher(None, _norm(v["nama"]), _norm(p.nama)).ratio() < 0.8:
                notes.append(f"Nama terbaca '{v['nama']}', di daftar peserta '{p.nama}'.")
            if p.lokasi_id and p.lokasi_id != lembar.lokasi_id:
                kota = db.get(M.Lokasi, p.lokasi_id)
                notes.append(f"Peserta ini terdaftar di lokasi {kota.kota if kota else 'lain'}.")
        dup = db.scalar(select(M.Lembar.id).where(
            M.Lembar.kompetisi_id == lembar.kompetisi_id, M.Lembar.bidang_id == lembar.bidang_id,
            M.Lembar.id != lembar.id, M.Lembar.status != M.GAGAL,
            or_(M.Lembar.hasil_baca["nomor"].as_string() == v["nomor"],
                M.Lembar.konfirmasi[("koreksi", "nomor")].as_string() == v["nomor"])))
        if dup:
            notes.append(f"Nomor peserta {v['nomor']} sudah pernah dikirim untuk bidang ini (lembar #{dup}).")
    lebih = (lembar.hasil_baca or {}).get("lebih", 0)
    if lebih >= 3:
        notes.append(f"Ada {lebih} isian setelah soal terakhir; pastikan bidang/kode naskah benar.")
    return notes
