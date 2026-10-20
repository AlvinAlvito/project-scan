"""Pembacaan LJK di server memakai mesin ljk/ yang sama persis dengan aplikasi desktop.

Selain hasil baca, modul ini menghitung:
- kualitas_server: cek ulang kualitas foto resolusi penuh (kecerahan, ketajaman, silau),
- keyakinan: seberapa yakin hasil baca (0-100), dari jumlah isian ragu dan catatan pelurusan.
"""
import shutil
import sys
import threading
from pathlib import Path

import cv2
import numpy as np

from .config import DATA_DIR, LJK_PATH, READ_WORKERS

if str(LJK_PATH) not in sys.path:
    sys.path.insert(0, str(LJK_PATH))

from ljk import belajar as BL  # noqa: E402
from ljk import service as SV  # noqa: E402

BL.set_model_dir(DATA_DIR / "model")     # model "juri kedua" bila disalin ke sini (opsional)
_slots = threading.BoundedSemaphore(READ_WORKERS)


def server_quality(path):
    """Metrik kualitas dari foto asli. Dihitung di gambar 1000 px agar cepat dan sebanding antar HP."""
    data = np.fromfile(str(path), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return {"bisa_dibuka": False}
    h, w = img.shape[:2]
    s = 1000 / max(h, w)
    small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return {
        "bisa_dibuka": True,
        "ukuran": f"{w}x{h}",
        "kecerahan": round(float(np.percentile(gray, 75)), 1),       # tingkat kertas
        "ketajaman": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 1),
        "silau": round(float((gray >= 250).mean() * 100), 2),         # % piksel jenuh
    }


def keyakinan(rec, jumlah_soal):
    """0-100. Turun untuk setiap kolom data peserta yang ragu/kosong, setiap jawaban ragu/ganda
    di dalam jumlah soal, dan setiap catatan pelurusan yang kritis."""
    if rec.get("error"):
        return 0
    baca = rec.get("baca", {})
    n = jumlah_soal or 180
    skor = 100
    for i in baca.get("issues", []):
        key = i.get("key", "")
        if key.startswith(("nama:", "nomor:", "kode:")):
            skor -= 15
        elif key.startswith("soal:") and int(key.split(":")[1]) <= n:
            skor -= 4
        elif key == "foto":
            skor -= 10
    return max(0, min(100, skor))


def read_sheet(foto_path, out_dir, jumlah_soal):
    """Baca satu foto. Mengembalikan (rec, kualitas_server, keyakinan). rec = rekaman process_photo."""
    with _slots:
        kualitas = server_quality(foto_path)
        try:
            rec = SV.process_photo(foto_path, out_dir)
        except Exception as e:  # noqa: BLE001 - foto rusak dsb.: dicatat sebagai gagal
            rec = {"file": str(foto_path), "error": f"Gagal diproses: {e}", "baca": {}}
    if rec.get("gambar"):
        # bahan latih model (baca.jpg/.npz) hanya dipakai desktop, yang membuatnya sendiri saat sinkron
        for name in ("baca.jpg", "baca.npz"):
            (Path(rec["gambar"]).parent / name).unlink(missing_ok=True)
    return rec, kualitas, keyakinan(rec, jumlah_soal)


def remove_files(lembar):
    """Hapus foto, gambar cek, dan potongan milik satu lembar."""
    if lembar.foto_path:
        Path(lembar.foto_path).unlink(missing_ok=True)
    if lembar.cek_path:
        shutil.rmtree(Path(lembar.cek_path).parent, ignore_errors=True)


def summary(rec, jumlah_soal):
    """Ringkasan hasil baca untuk disimpan di DB dan ditampilkan di HP admin."""
    if rec.get("error"):
        return {"error": rec["error"]}
    jaw = rec.get("jawaban", [])
    n = jumlah_soal or len(jaw)
    issues = [i["text"] for i in rec.get("baca", {}).get("issues", [])
              if not (i.get("key", "").startswith("soal:") and int(i["key"].split(":")[1]) > n)]
    return {
        "nama": rec.get("nama", ""), "nomor": rec.get("nomor", ""), "kode": rec.get("kode", ""),
        "tanggal": rec.get("tanggal", ""),
        "jawaban": jaw,
        "terisi": sum(1 for a in jaw[:n] if a),
        "lebih": sum(1 for a in jaw[n:] if a) if jumlah_soal else 0,
        "issues": issues,
    }
