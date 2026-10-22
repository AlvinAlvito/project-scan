"""Belajar dari koreksi panitia: data latih bulatan dan model "juri kedua".

Alur
1. Tiap lembar yang diproses menyimpan gambar yang DIPAKAI MEMBACA (canon, bukan gambar
   tampilan yang dipertajam) + posisi, skor & keputusan aturan tiap bulatan:
   <folder lembar>/baca.jpg dan baca.npz.
2. Label hanya dari panitia: layar "Latih Model" (per bulatan: terisi/kosong/hapusan) dan
   lembar "Sudah dicek" (jawaban akhir per soal, digit nomor & kode).
3. tools/latih_bulatan.py (lingkungan PyTorch terpisah, .venv-latih) melatih CNN kecil,
   mengujinya pada label panitia yang disisihkan (tidak pernah dipakai melatih), lalu
   mengekspor ONNX. Model baru hanya AKTIF bila lulus ujian (gerbang A), dan hanya boleh
   memutus kasus ragu bila lulus gerbang B.
4. Saat membaca, model aktif menjadi juri kedua (omr.apply_model): bila tidak setuju dengan
   aturan, grup dijadikan "ragu" (perlu dicek). Tanpa model aktif pembacaan sama persis
   seperti sebelumnya.
"""
import json
import zlib
from pathlib import Path

import cv2
import numpy as np

from . import omr as OM
from . import template as T

KELAS = ("kosong", "terisi", "hapusan")
PATCH = 32                  # sisi potongan bulatan (px canon) masukan model
UJI_BAGI = 4                # 1 dari UJI_BAGI lembar disisihkan untuk ujian model (tidak dilatih)

IDX = {(g, i, v): k for k, (g, i, v, _, _) in enumerate(T.BUBBLES)}
GROUP = [(g, i) for (g, i, _, _, _) in T.BUBBLES]

_MODEL_DIR = None
_ACTIVE = {"stamp": None, "model": None}


# ---------------------------------------------------------------- potongan bulatan

def patches(canon, bubble_xy, size=PATCH):
    """Potongan size x size berpusat di tiap bulatan, dari gambar baca (canon). uint8 BGR."""
    h = size // 2
    m = h + 2
    pad = cv2.copyMakeBorder(canon, m, m, m, m, cv2.BORDER_REPLICATE)
    out = np.empty((len(bubble_xy), size, size, 3), np.uint8)
    for i, (x, y) in enumerate(bubble_xy):
        cx, cy = int(round(x)) + T.PAD + m, int(round(y)) + T.PAD + m
        out[i] = pad[cy - h: cy - h + size, cx - h: cx - h + size]
    return out


def normalize(p):
    """uint8 N x H x W x 3 -> float32 N x 3 x H x W. Tiap kanal dibagi terang kertas setempat
    (persentil 90 potongan), jadi bayangan & cahaya foto tidak berpengaruh; kilap jadi > 1."""
    f = p.astype(np.float32)
    paper = np.percentile(f.reshape(len(f), -1, 3), 90, axis=1)
    f = f / np.maximum(paper[:, None, None, :], 1.0)
    return np.ascontiguousarray(np.clip(f, 0.0, 1.5).transpose(0, 3, 1, 2))


def is_test_sheet(file):
    """Lembar ujian ditentukan dari nama fotonya (tetap sama setiap kali dilatih ulang)."""
    return zlib.crc32(Path(file).name.encode("utf-8")) % UJI_BAGI == 0


# ---------------------------------------------------------------- data per lembar

def rule_labels(read):
    """Per bulatan: pilih = aturan menghitungnya sebagai isian; ragu = grupnya ragu/ganda."""
    groups = dict(read.header_groups)
    for q, gr in enumerate(read.answer_groups):
        groups[("jawaban", q)] = gr
    pilih = np.zeros(len(T.BUBBLES), bool)
    ragu = np.zeros(len(T.BUBBLES), bool)
    for k, (g, i, v, _, _) in enumerate(T.BUBBLES):
        gr = groups[(g, i)]
        if gr.kind == "ok":
            pilih[k] = v == gr.value
        elif gr.kind == "ragu":
            pilih[k] = v == OM.guess_of(gr)
            ragu[k] = True
        elif gr.kind == "ganda":
            pilih[k] = OM.status_of(read.scores[k]) == OM.TERISI
            ragu[k] = True
    return pilih, ragu


def save_sheet(base, aligned, read, model=None):
    """Simpan bahan latih satu lembar di folder lembarnya: baca.jpg + baca.npz."""
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".jpg", aligned.canon, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if ok:
        buf.tofile(str(base / "baca.jpg"))
    pilih, ragu = rule_labels(read)
    extra = {"model": read.model_prob.astype(np.float32)} if getattr(read, "model_prob", None) is not None else {}
    np.savez_compressed(base / "baca.npz", xy=aligned.bubble_xy.astype(np.float32),
                        skor=np.asarray(read.scores, np.float32), kilap=np.asarray(read.shine, np.float32),
                        pilih=pilih, ragu=ragu, kontras=np.float32(getattr(read, "kontras", 1.0)), **extra)


def sheet_dir(row):
    """Folder lembar (tempat lembar.jpg, baca.jpg, baca.npz) dari baris DB."""
    return Path(row["gambar"]).parent if row["gambar"] else None


def load_sheet(row):
    d = sheet_dir(row)
    if d is None or not (d / "baca.npz").exists() or not (d / "baca.jpg").exists():
        return None
    z = np.load(d / "baca.npz")
    return {k: z[k] for k in z.files} | {"dir": d}


def read_image(d):
    return cv2.imdecode(np.fromfile(str(Path(d) / "baca.jpg"), np.uint8), cv2.IMREAD_COLOR)


def review_labels(row, data, jumlah):
    """Label 'perak' dari lembar Sudah dicek: jawaban akhir soal 1..jumlah, digit nomor & kode.
    Bulatan yang dipilih panitia = terisi; bulatan lain di grup itu = kosong, atau hapusan bila
    tampak ada bekas (skor >= 0,10 atau kilap)."""
    out = []
    skor, kilap = data["skor"], data["kilap"]

    def group(g, i, final, values):
        if final in ("?", "*"):
            return
        for v in values:
            k = IDX[(g, i, v)]
            if v == final:
                out.append((k, "terisi"))
            else:
                out.append((k, "hapusan" if (skor[k] >= 0.10 or kilap[k] > 0) else "kosong"))

    jawaban = json.loads(row["jawaban"] or "[]")
    for q in range(min(jumlah, len(jawaban))):
        group("jawaban", q, jawaban[q], T.OPTIONS)
    for g, s in (("nomor", row["nomor"]), ("kode", row["kode"])):
        for i, ch in enumerate(s):
            if ch.isdigit() and (g, i, ch) in IDX:
                group(g, i, ch, [b[2] for b in T.BUBBLES if b[0] == g and b[1] == i])
    return out


# ---------------------------------------------------------------- contoh untuk dilabeli

def candidates(rows, labels, jumlah_of=None, model=None, limit=200, seed=0):
    """Bulatan yang paling berguna untuk dilabeli panitia, prioritas tertinggi dulu.
    rows: baris DB lembar; labels: {(file, idx): label}; jumlah_of(row) -> jumlah soal ujian."""
    rng = np.random.default_rng(seed)
    out = []
    for row in rows:
        if row["error"]:
            continue
        data = load_sheet(row)
        if data is None:
            continue
        skor, kilap, ragu, pilih = data["skor"], data["kilap"], data["ragu"], data["pilih"]
        n = len(skor)
        pri = np.zeros(n)
        samar = (skor >= 0.06) & (skor <= 0.30)
        pri[samar] = 2 + (0.3 - np.abs(skor[samar] - 0.15))
        pri[kilap > 0] = 3.5
        pri[ragu & (skor >= 0.05) & (skor < 0.35)] = 4          # bulatan meragukan di grup ragu/ganda
        pri[ragu & (skor >= 0.35)] = 1.5                        # isian tebal di grup ganda: kurang informatif
        prob = None
        if model is not None:
            prob = model.prob(read_image(data["dir"]), data["xy"])[:, 1]
            beda = (prob >= 0.5) != pilih
            pri[beda] = np.maximum(pri[beda], 5)
            bimbang = (prob > 0.2) & (prob < 0.8)
            pri[bimbang] = np.maximum(pri[bimbang], 3)
        easy = (pri == 0) & (rng.random(n) < 0.01)            # sedikit contoh mudah untuk kalibrasi
        pri[easy] = 1
        jumlah = jumlah_of(row) if jumlah_of else T.N_QUESTIONS
        for k in np.flatnonzero(pri > 0):
            g, i, v, _, _ = T.BUBBLES[k]
            if (row["file"], int(k)) in labels or g == "tanggal":
                continue
            p = pri[k] - (2 if g == "jawaban" and i >= jumlah else 0)
            out.append({"file": row["file"], "dir": data["dir"], "idx": int(k), "xy": data["xy"][k],
                        "grup": g, "kolom": i, "nilai": v, "skor": float(skor[k]), "kilap": float(kilap[k]),
                        "aturan": "terisi" if pilih[k] else "kosong", "ragu": bool(ragu[k]),
                        "model": None if prob is None else float(prob[k]), "prioritas": float(p)})
    out.sort(key=lambda c: -c["prioritas"])
    return out[:limit]


def describe(c):
    g, i, v = c["grup"], c["kolom"], c["nilai"]
    if g == "jawaban":
        return f"Soal {i + 1} - {v}"
    if g == "nama":
        return f"Nama kolom {i + 1} - {v}"
    return f"{'Nomor' if g == 'nomor' else 'Kode'} digit {i + 1} - {v}"


def context_image(d, xy, scale=3.0, r=40):
    """Potongan gambar baca di sekitar bulatan (tetangganya ikut terlihat), diperbesar,
    dengan lingkaran tipis biru di bulatan yang ditanya."""
    img = read_image(d)
    cx, cy = int(round(xy[0])) + T.PAD, int(round(xy[1])) + T.PAD
    pad = cv2.copyMakeBorder(img, r, r, r, r, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    crop = pad[cy: cy + 2 * r, cx: cx + 2 * r]
    big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    c = int(round(r * scale))
    cv2.circle(big, (c, c), int(round((T.BUBBLE_R + 4) * scale)), (255, 120, 0), 2, cv2.LINE_AA)
    return big


# ---------------------------------------------------------------- model aktif

class Model:
    """Model ONNX hasil tools/latih_bulatan.py, dijalankan dengan OpenCV (tanpa PyTorch)."""

    def __init__(self, path, info):
        self.net = cv2.dnn.readNetFromONNX(str(path))
        self.info = info
        self.versi = info.get("versi", Path(path).stem)
        self.putus_ragu = bool(info.get("gerbang_b", False))

    def prob(self, canon, bubble_xy):
        """Peluang tiap kelas (kosong, terisi, hapusan) untuk tiap bulatan: N x 3."""
        self.net.setInput(normalize(patches(canon, bubble_xy)))
        return np.asarray(self.net.forward(), np.float32)


def set_model_dir(path):
    """Dipanggil aplikasi saat mulai: folder model (<data>/model)."""
    global _MODEL_DIR
    _MODEL_DIR = Path(path) if path else None
    _ACTIVE["stamp"] = None


def active_model():
    """Model yang lulus ujian dan sedang aktif, atau None. Dimuat ulang bila aktif.json berubah."""
    if _MODEL_DIR is None:
        return None
    f = _MODEL_DIR / "aktif.json"
    if not f.exists():
        _ACTIVE.update(stamp=None, model=None)
        return None
    stamp = f.stat().st_mtime
    if stamp != _ACTIVE["stamp"]:
        model = None
        try:
            info = json.loads(f.read_text(encoding="utf-8"))
            if info.get("aktif"):
                model = Model(_MODEL_DIR / info["file"], info)
        except Exception:      # noqa: BLE001 - model rusak: baca tanpa model, jangan berhenti
            model = None
        _ACTIVE.update(stamp=stamp, model=model)
    return _ACTIVE["model"]
