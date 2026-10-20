"""Penghubung mesin pembaca dengan aplikasi: proses foto, status lembar, ekspor."""
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import belajar as BL
from . import export as EX
from . import nilai as NI
from . import omr as OM
from . import pipeline as PL
from . import template as T

# Gambar cek dibuat dari foto asli resolusi penuh pada 1,5x bingkai baku (dulu 0,75x dari
# gambar kerja yang sudah diperkecil), supaya tetap tajam saat diperbesar di layar cek.
OVERLAY_SCALE = 1.5
OVERLAY_BAR = 70            # tinggi bar judul di atas gambar cek (sebelum diskala)
MUTU_JPEG = {"lembar": 90, "potongan": 92}

_GROUP_IDX = {}
for _k, _b in enumerate(T.BUBBLES):
    _GROUP_IDX.setdefault((_b[0], _b[1]), []).append(_k)

LABEL = {"nama": "Nama kolom", "nomor": "Nomor peserta digit", "kode": "Kode naskah digit",
         "tanggal": "Tanggal digit"}


def _write_img(path, img, quality=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if quality and path.suffix.lower() == ".jpg" else []
    ok, buf = cv2.imencode(path.suffix, img, params)
    if ok:
        buf.tofile(str(path))


def _anchor(res, group, i, gr=None):
    """Posisi di gambar cek (piksel): bulatan yang dicurigai (paling gelap) bila
    grup ragu/ganda, selain itu tengah grup."""
    idx = _GROUP_IDX[(group, i)]
    if gr is not None and gr.kind in ("ragu", "ganda"):
        best = OM.guess_of(gr)
        idx = [k for k in idx if T.BUBBLES[k][2] == best] or idx
    xy = res.aligned.bubble_xy[idx].mean(axis=0)
    s = OVERLAY_SCALE
    return round(float((xy[0] + T.PAD) * s), 1), round(float((xy[1] + T.PAD + OVERLAY_BAR) * s), 1)


def _guess(gr, is_answer):
    """Tebakan untuk satu grup: nilai terbaca, atau pilihan paling gelap bila ragu."""
    if gr.kind == "ok":
        return gr.value
    if gr.kind == "kosong":
        return ""
    if gr.kind == "ganda" and is_answer:
        return "*"
    return OM.guess_of(gr)


def process_photo(path, out_dir):
    """Baca satu foto; simpan gambar cek & potongan tulisan tangan di out_dir/<nama foto>/.

    Mengembalikan rekaman untuk DB. Isian akhir awal = tebakan (bulatan ragu diisi
    pilihan paling gelap), sehingga di layar cek panitia cukup menyetujui atau mengubah."""
    path = Path(path)
    res = PL.process(path, keep_image=True)      # foto asli hanya untuk gambar tampilan
    rec = {"file": str(path), "error": res.error}
    if res.error:
        rec["baca"] = {"issues": [{"text": res.error, "key": "foto", "x": None, "y": None}]}
        return rec
    rd = res.read
    base = Path(out_dir) / path.stem
    gambar = base / "lembar.jpg"
    _write_img(gambar, PL.overlay(res, OVERLAY_SCALE), MUTU_JPEG["lembar"])
    potongan = {}
    for name, img in PL.handwriting_crops(res).items():
        p = base / f"{name}.jpg"
        _write_img(p, img, MUTU_JPEG["potongan"])
        (base / f"{name}.png").unlink(missing_ok=True)      # potongan versi lama
        potongan[name] = str(p)
    res.image = res._source = None
    BL.save_sheet(base, res.aligned, rd)                    # bahan latih model (gambar baca + skor)

    issues = [{"text": n, "key": "foto", "x": None, "y": None} for n in res.notes
              if not T.is_noncritical_note(n)]
    header, guess = {}, {}
    for g in ("nama", "nomor", "kode", "tanggal"):
        cols = sorted(i for (gg, i) in rd.header_groups if gg == g)
        header[g] = []
        chars = []
        for i in cols:
            gr = rd.header_groups[(g, i)]
            x, y = _anchor(res, g, i, gr)
            header[g].append({"col": i, "value": gr.value, "kind": gr.kind, "note": gr.note, "x": x, "y": y})
            gs = _guess(gr, False)
            chars.append(gs if gs else (" " if g == "nama" else "_"))
            if g in T.CRITICAL_GROUPS and (gr.kind in ("ragu", "ganda") or (gr.kind == "kosong" and g != "nama")):
                issues.append({"text": f"{LABEL[g]} {i + 1}: {gr.note or 'kosong'}", "key": f"{g}:{i}",
                               "x": x, "y": y})
        guess[g] = "".join(chars)
    guess["nama"] = " ".join(guess["nama"].split())
    t = guess["tanggal"]
    guess["tanggal"] = f"{t[0:2]}-{t[2:4]}-{t[4:6]}"

    kinds, notes, xy, jaw_guess = [], [], [], []
    for q, gr in enumerate(rd.answer_groups):
        kinds.append(gr.kind)
        notes.append(gr.note)
        x, y = _anchor(res, "jawaban", q, gr)
        xy.append((x, y))
        jaw_guess.append(_guess(gr, True))
        if gr.kind in ("ragu", "ganda"):
            issues.append({"text": f"Soal {q + 1}: {gr.note}", "key": f"soal:{q + 1}", "x": x, "y": y})

    rec.update(
        nama=guess["nama"], nomor=guess["nomor"], kode=guess["kode"], tanggal=guess["tanggal"],
        jawaban=jaw_guess, gambar=str(gambar), potongan=potongan,
        baca={"nama": rd.nama, "nomor": rd.nomor, "kode": rd.kode, "tanggal": rd.tanggal,
              "jawaban": rd.jawaban, "jawaban_kind": kinds, "jawaban_note": notes, "jawaban_xy": xy,
              "header": header, "issues": issues, "notes": res.notes, "model": res.model,
              "tebakan": {"nama": guess["nama"], "nomor": guess["nomor"], "kode": guess["kode"],
                          "tanggal": guess["tanggal"], "jawaban": jaw_guess}},
    )
    return rec


# ------------------------------------------------------------ status lembar

@dataclass
class SheetView:
    row: object
    status: str                 # "OK", "Perlu cek", "Sudah dicek", "Gagal"
    soal: object = None         # NI.Soal atau None
    skor: object = None         # NI.Skor atau None
    issues: list = field(default_factory=list)   # [{"text", "key", "x", "y"}]


def _blok_mulai(text):
    """Nomor soal pertama bila catatan dimulai dengan 'jawaban A-B:', selain itu 0."""
    m = re.match(r"jawaban (\d+)-\d+:", text)
    return int(m.group(1)) if m else 0


def duplicate_nomor(rows):
    c = Counter(r["nomor"] for r in rows if not r["error"] and r["nomor"])
    return {n for n, k in c.items() if k > 1}


def sheet_view(row, naskah, dup):
    """Status satu lembar. naskah: {kode: Soal}; dup: himpunan nomor peserta ganda."""
    if row["error"]:
        return SheetView(row, "Gagal", issues=[{"text": row["error"], "key": "foto", "x": None, "y": None}])
    baca = json.loads(row["baca"] or "{}")
    jawaban = json.loads(row["jawaban"] or "[]")
    issues = [] if row["dicek"] else list(baca.get("issues", []))
    soal = naskah.get(row["kode"])
    skor = None
    if soal is None:
        issues.insert(0, {"text": f"kode naskah '{row['kode']}' belum terdaftar di kunci event ini",
                          "key": "kode", "x": None, "y": None})
    else:
        # Catatan ragu/ganda di soal setelah soal terakhir ujian tidak dinilai, jadi tidak perlu dicek
        # (biasanya hanya bayangan di tepi bawah kertas).
        issues = [i for i in issues if not (i.get("key", "").startswith("soal:")
                                            and int(i["key"].split(":")[1]) > soal.jumlah)]
        # Catatan pelurusan untuk blok jawaban yang seluruhnya setelah soal terakhir juga tidak dinilai.
        issues = [i for i in issues if not (i.get("key") == "foto" and _blok_mulai(i["text"]) > soal.jumlah)]
        skor = NI.nilai(jawaban, soal)
        if skor.lebih:
            issues.append({"text": skor.catatan[-1], "key": f"soal:{skor.lebih[0]}", "x": None, "y": None})
    if row["dicek"] and any(ch in (row["nama"] + row["nomor"] + row["kode"]) for ch in "?_"):
        issues.append({"text": "masih ada tanda ? atau _ di data peserta", "key": "kepala", "x": None, "y": None})
    if row["nomor"] in dup:
        issues.append({"text": f"nomor peserta {row['nomor']} dipakai lebih dari satu lembar",
                       "key": "nomor", "x": None, "y": None})
    if issues:
        status = "Perlu cek"
    else:
        status = "Sudah dicek" if row["dicek"] else "OK"
    return SheetView(row, status, soal, skor, issues)


def event_views(db, event_id):
    rows = db.lembar(event_id)
    naskah = {s.kode: s for s in db.naskah(event_id)}
    dup = duplicate_nomor(rows)
    return [sheet_view(r, naskah, dup) for r in rows]


# ------------------------------------------------------------------- ekspor

def kode_sort(k):
    return (0, int(k)) if k.isdigit() else (1, k)


def export_event(db, event_id, path):
    """Tulis Daftar Nilai. Lembar gagal / kode tidak terdaftar dilewati.

    Kode naskah dengan nama bidang yang sama digabung dalam satu sheet; urutan
    sheet mengikuti kode naskah terkecil, urutan peserta = urutan scan."""
    ev = db.event(event_id)
    views = event_views(db, event_id)
    groups, first_kode, skipped = {}, {}, []
    for v in views:
        if v.skor is None:
            skipped.append(v)
            continue
        b = v.soal.bidang
        groups.setdefault(b, []).append((v.row["nomor"], v.row["nama"], v.skor))
        first_kode[b] = min(first_kode.get(b, v.soal.kode), v.soal.kode, key=kode_sort)
    ordered = [(b, groups[b]) for b in sorted(groups, key=lambda b: kode_sort(first_kode[b]))]
    EX.daftar_nilai(path, ev["nama"], ev["tanggal"], ordered)
    return len(views) - len(skipped), skipped
