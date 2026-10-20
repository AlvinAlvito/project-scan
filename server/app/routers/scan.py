"""Web HP admin daerah: daftar akses, unggah foto LJK (langsung dibaca), konfirmasi hasil baca."""
import hashlib
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as M
from .. import reading
from ..config import DATA_DIR, MAX_UPLOAD_MB
from ..db import get_db
from ..security import current_user, lokasi_ids, require_lokasi
from ..serial import bidang_out, kompetisi_out, lembar_out, lokasi_out
from ..validate import validate

router = APIRouter(prefix="/api/scan", tags=["admin daerah"])


@router.get("/akses")
def my_akses(user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    """Lokasi yang boleh diisi user ini (superadmin: semua lokasi kompetisi aktif)."""
    if user.peran == M.SUPERADMIN:
        lokasi = db.scalars(select(M.Lokasi).join(M.Kompetisi).where(M.Kompetisi.status == "aktif")).all()
    else:
        lokasi = [db.get(M.Lokasi, i) for i in lokasi_ids(user)]
        lokasi = [lo for lo in lokasi if lo and lo.kompetisi.status == "aktif"]
    out = []
    for lo in sorted(lokasi, key=lambda lo: (lo.kompetisi.nama, lo.kota)):
        out.append({"lokasi": lokasi_out(lo), "kompetisi": kompetisi_out(lo.kompetisi),
                    "bidang": [bidang_out(b) for b in lo.kompetisi.bidang]})
    return out


def _lembar_for(db, user, lid) -> M.Lembar:
    lb = db.get(M.Lembar, lid)
    if lb is None:
        raise HTTPException(404, "Lembar tidak ditemukan.")
    require_lokasi(user, lb.lokasi_id)
    return lb


@router.post("/lembar")
def upload(lokasi_id: int = Form(...), bidang_id: int = Form(...), skor_kualitas: int = Form(0),
           metrik: str = Form("{}"), foto: UploadFile = File(...),
           user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    """Simpan foto, baca dengan mesin ljk/, validasi, dan kembalikan hasilnya (±2-3 detik).

    Foto yang sama persis (hash sama) tidak disimpan dua kali: bila HP mengirim ulang dari
    antrean offline, lembar yang sudah ada dikembalikan."""
    require_lokasi(user, lokasi_id)
    lokasi = db.get(M.Lokasi, lokasi_id)
    bidang = db.get(M.Bidang, bidang_id)
    if lokasi is None or bidang is None or bidang.kompetisi_id != lokasi.kompetisi_id:
        raise HTTPException(400, "Lokasi atau bidang tidak cocok.")
    if lokasi.kompetisi.status != "aktif":
        raise HTTPException(400, "Kompetisi ini sudah ditutup.")
    data = foto.file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Foto lebih dari {MAX_UPLOAD_MB} MB.")
    if len(data) < 10_000:
        raise HTTPException(400, "File foto rusak atau terlalu kecil.")
    digest = hashlib.sha256(data).hexdigest()
    old = db.scalar(select(M.Lembar).where(M.Lembar.kompetisi_id == lokasi.kompetisi_id,
                                           M.Lembar.foto_hash == digest))
    if old is not None:
        require_lokasi(user, old.lokasi_id)
        return {**lembar_out(old, detail=True), "sudah_ada": True}
    try:
        metrik_d = json.loads(metrik) if metrik else {}
    except ValueError:
        metrik_d = {}

    kid = lokasi.kompetisi_id
    name = uuid.uuid4().hex
    foto_path = DATA_DIR / "foto" / f"k{kid}" / f"{name}.jpg"
    foto_path.parent.mkdir(parents=True, exist_ok=True)
    foto_path.write_bytes(data)

    rec, kualitas, yakin = reading.read_sheet(foto_path, DATA_DIR / "hasil" / f"k{kid}", bidang.jumlah_soal)
    lb = M.Lembar(kompetisi_id=kid, lokasi_id=lokasi_id, bidang_id=bidang_id, uploader_id=user.id,
                  foto_path=str(foto_path), foto_hash=digest, foto_ukuran=kualitas.get("ukuran", ""),
                  skor_kualitas=max(0, min(100, skor_kualitas)), metrik=metrik_d, kualitas_server=kualitas,
                  hasil_baca=reading.summary(rec, bidang.jumlah_soal), keyakinan=yakin,
                  error=rec.get("error", ""), cek_path=rec.get("gambar", ""), potongan=rec.get("potongan", {}),
                  status=M.GAGAL if rec.get("error") else M.MENUNGGU, konfirmasi={})
    lb.bidang, lb.lokasi = bidang, lokasi
    db.add(lb)
    db.flush()
    lb.catatan = validate(db, lb)
    db.commit()
    return lembar_out(lb, detail=True)


@router.get("/lembar")
def my_lembar(lokasi_id: int, bidang_id: int | None = None, limit: int = 50,
              user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    require_lokasi(user, lokasi_id)
    cond = [M.Lembar.lokasi_id == lokasi_id]
    if bidang_id:
        cond.append(M.Lembar.bidang_id == bidang_id)
    rows = db.scalars(select(M.Lembar).where(*cond).order_by(M.Lembar.id.desc()).limit(min(limit, 200))).all()
    return [lembar_out(lb) for lb in rows]


@router.get("/lembar/{lid}")
def get_lembar(lid: int, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    return lembar_out(_lembar_for(db, user, lid), detail=True)


class PesertaBaruIn(BaseModel):
    nomor: str = Field(min_length=1, max_length=30)
    nama: str = Field(min_length=1, max_length=160)
    sekolah: str = ""


class KonfirmasiIn(BaseModel):
    aksi: str                                  # benar | perbaiki | peserta_baru
    koreksi: dict[str, str] = {}               # {nama, nomor, kode} yang diperbaiki admin
    catatan: str = ""
    peserta_baru: PesertaBaruIn | None = None


@router.post("/lembar/{lid}/konfirmasi")
def konfirmasi(lid: int, body: KonfirmasiIn, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    lb = _lembar_for(db, user, lid)
    if lb.status == M.GAGAL:
        raise HTTPException(400, "Lembar ini gagal dibaca. Hapus lalu foto ulang.")
    if lb.ditarik_at:
        raise HTTPException(409, "Lembar sudah ditarik pusat dan tidak bisa diubah lagi.")
    hb = lb.hasil_baca or {}
    koreksi = {k: " ".join(v.upper().split()) if k == "nama" else v.strip()
               for k, v in body.koreksi.items() if k in ("nama", "nomor", "kode") and v.strip()
               and v.strip() != hb.get(k, "")}
    lb.konfirmasi = {"aksi": body.aksi, "koreksi": koreksi, "catatan": body.catatan.strip(), "oleh": user.nama,
                     "waktu": datetime.now().isoformat(timespec="seconds")}
    lb.peserta_baru, lb.peserta_baru_status = None, None
    if body.aksi == "benar" and not koreksi and not body.catatan.strip():
        lb.status = M.DIKONFIRMASI
    elif body.aksi in ("benar", "perbaiki"):
        lb.status = M.DITANDAI
    elif body.aksi == "peserta_baru":
        if body.peserta_baru is None:
            raise HTTPException(400, "Isi data peserta baru.")
        pb = body.peserta_baru
        lb.peserta_baru = {"nomor": pb.nomor.strip(), "nama": " ".join(pb.nama.upper().split()),
                           "sekolah": pb.sekolah.strip()}
        lb.peserta_baru_status = "diajukan"
        lb.status = M.DITANDAI
    else:
        raise HTTPException(400, "Aksi tidak dikenal.")
    lb.dikonfirmasi_at = datetime.now()
    lb.catatan = validate(db, lb)
    db.commit()
    return lembar_out(lb, detail=True)


@router.delete("/lembar/{lid}")
def delete(lid: int, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    """Hapus untuk foto ulang. Tidak bisa setelah lembar ditarik pusat."""
    lb = _lembar_for(db, user, lid)
    if lb.ditarik_at:
        raise HTTPException(409, "Lembar sudah ditarik pusat dan tidak bisa dihapus.")
    reading.remove_files(lb)
    db.delete(lb)
    db.commit()
    return {"ok": True}
