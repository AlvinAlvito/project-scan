"""Bentuk JSON yang dikirim ke klien (web HP, panel admin, desktop)."""
from . import models as M


def _ts(d):
    return d.isoformat(sep=" ", timespec="seconds") if d else None


def user_out(u: M.User, with_akses=False):
    out = {"id": u.id, "nama": u.nama, "username": u.username, "peran": u.peran, "aktif": u.aktif}
    if with_akses:
        out["lokasi_ids"] = sorted(a.lokasi_id for a in u.akses)
    return out


def lokasi_out(lo: M.Lokasi):
    return {"id": lo.id, "kompetisi_id": lo.kompetisi_id, "kota": lo.kota, "target_lembar": lo.target_lembar}


def bidang_out(b: M.Bidang):
    return {"id": b.id, "kompetisi_id": b.kompetisi_id, "kode_naskah": b.kode_naskah, "nama": b.nama,
            "jumlah_soal": b.jumlah_soal}


def kompetisi_out(k: M.Kompetisi, detail=False):
    out = {"id": k.id, "nama": k.nama, "tanggal": k.tanggal, "status": k.status}
    if detail:
        out["lokasi"] = [lokasi_out(lo) for lo in k.lokasi]
        out["bidang"] = [bidang_out(b) for b in k.bidang]
    return out


def peserta_out(p: M.Peserta):
    return {"id": p.id, "kompetisi_id": p.kompetisi_id, "lokasi_id": p.lokasi_id, "nomor": p.nomor,
            "nama": p.nama, "sekolah": p.sekolah, "daftar_di_tempat": p.daftar_di_tempat}


def file_urls(lb: M.Lembar):
    base = f"/api/files/lembar/{lb.id}"
    urls = {"foto": f"{base}/foto"}
    if lb.cek_path:
        urls["cek"] = f"{base}/cek"
    for k in ("kotak_nama", "kotak_nomor", "kotak_kode"):
        if k in (lb.potongan or {}):
            urls[k] = f"{base}/{k}"
    return urls


def lembar_out(lb: M.Lembar, detail=False):
    hb = lb.hasil_baca or {}
    kor = (lb.konfirmasi or {}).get("koreksi") or {}
    out = {
        "id": lb.id, "kompetisi_id": lb.kompetisi_id, "lokasi_id": lb.lokasi_id,
        "kota": lb.lokasi.kota if lb.lokasi else "",
        "bidang_id": lb.bidang_id,
        "bidang": {"kode_naskah": lb.bidang.kode_naskah, "nama": lb.bidang.nama,
                   "jumlah_soal": lb.bidang.jumlah_soal} if lb.bidang else None,
        "uploader": lb.uploader.nama if lb.uploader else "",
        "status": lb.status, "error": lb.error,
        "nama": kor.get("nama") or hb.get("nama", ""), "nomor": kor.get("nomor") or hb.get("nomor", ""),
        "kode": kor.get("kode") or hb.get("kode", ""),
        "terisi": hb.get("terisi", 0),
        "skor_kualitas": lb.skor_kualitas, "keyakinan": lb.keyakinan,
        "catatan": lb.catatan or [], "konfirmasi": lb.konfirmasi or {},
        "peserta_baru": lb.peserta_baru, "peserta_baru_status": lb.peserta_baru_status,
        "peserta_id": lb.peserta_id,
        "dibuat": _ts(lb.dibuat), "dikonfirmasi_at": _ts(lb.dikonfirmasi_at),
        "ditarik_at": _ts(lb.ditarik_at), "dicek_at": _ts(lb.dicek_at),
        "urls": file_urls(lb),
    }
    if detail:
        out.update(hasil_baca=hb, metrik=lb.metrik or {}, kualitas_server=lb.kualitas_server or {},
                   foto_ukuran=lb.foto_ukuran)
    return out
