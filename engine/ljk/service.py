"""Penghubung mesin pembaca dengan aplikasi: proses foto, status lembar, ekspor."""
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import belajar as BL
from . import db as DBM
from . import export as EX
from . import nilai as NI
from . import omr as OM
from . import pipeline as PL
from . import tampilan as TP
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


def process_photo(path, out_dir, kontras="standar"):
    """Baca satu foto; simpan gambar cek & potongan tulisan tangan di out_dir/<nama foto>/.

    Mengembalikan rekaman untuk DB. Isian akhir awal = tebakan (bulatan ragu diisi
    pilihan paling gelap), sehingga di layar cek panitia cukup menyetujui atau mengubah.
    kontras: normalisasi kontras lembar pudar (kunci omr.KONTRAS); server selalu "standar"."""
    path = Path(path)
    res = PL.process(path, keep_image=True, kontras=kontras)     # foto asli hanya untuk gambar tampilan
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
              "kontras": {"mode": kontras, "faktor": round(rd.kontras, 2)},
              "tebakan": {"nama": guess["nama"], "nomor": guess["nomor"], "kode": guess["kode"],
                          "tanggal": guess["tanggal"], "jawaban": jaw_guess}},
    )
    return rec


def cek_scale(width):
    """Skala gambar cek (lembar.jpg) dari lebarnya: 1,5 sekarang, 0,75 versi lama."""
    return width / (T.CANON_W + 2 * T.PAD)


def cek_xy(xy, s):
    """Posisi bulatan (px bingkai baku, seperti baca.npz 'xy') di gambar cek berskala s."""
    return (np.asarray(xy, float) + T.PAD) * s + np.array([0.0, OVERLAY_BAR * s])


def bw_source(gambar):
    """Bahan tampilan hitam-putih (tampilan.bw_prepare) untuk gambar cek satu lembar, atau None.
    Posisi bulatan & faktor kontras dari baca.npz di folder lembar; lembar lama yang dibaca tanpa
    normalisasi memakai faktor 'standar' dari skornya, supaya lembar pudar tetap jelas dilihat."""
    gambar = Path(gambar)
    img = cv2.imdecode(np.fromfile(str(gambar), np.uint8), cv2.IMREAD_COLOR) if gambar.is_file() else None
    if img is None:
        return None
    centers, faktor, radius, ukur = None, 1.0, 0.0, 0.0
    npz = gambar.parent / "baca.npz"
    if npz.is_file():
        z = np.load(npz)
        s = cek_scale(img.shape[1])
        centers = cek_xy(z["xy"], s)
        radius = (T.BUBBLE_R - 1.5) * s                     # bagian dalam bulatan, garis cetaknya tidak ikut
        ukur = T.FILL_R * s                                 # area ukur kegelapan mesin baca
        faktor = float(z["kontras"]) if "kontras" in z.files else OM.contrast_factor(z["skor"].astype(float))
    return TP.bw_prepare(img, faktor, centers, radius, ukur)


# ------------------------------------------------------------ status lembar

@dataclass
class SheetView:
    row: object
    status: str                 # "OK", "Perlu cek", "Sudah dicek", "Gagal"
    soal: object = None         # NI.Soal atau None
    skor: object = None         # NI.Skor atau None
    issues: list = field(default_factory=list)   # [{"text", "key", "x", "y"}]
    kunci_lama: bool = False    # kunci beku lembar berbeda dengan kunci yang berlaku sekarang (perlu hitung ulang?)


def soal_lembar(row, naskah):
    """Kunci untuk menilai lembar: kunci beku saat di-scan (bila kodenya sama dengan kode lembar), selain itu
    kunci yang berlaku sekarang untuk kode itu (lembar yang belum dibekukan). naskah: {kode: Soal}."""
    try:
        beku = row["soal_beku"]
    except (IndexError, KeyError):
        beku = None
    return DBM.soal_beku(beku, row["kode"]) or naskah.get(row["kode"])


def _blok_mulai(text):
    """Nomor soal pertama bila catatan dimulai dengan 'jawaban A-B:', selain itu 0."""
    m = re.match(r"jawaban (\d+)-\d+:", text)
    return int(m.group(1)) if m else 0


TANPA_CATATAN = ("nama", "tanggal")      # kolom yang salah isi bulatannya tidak dilaporkan (keputusan panitia)


def catatan_kepala_disembunyikan(i):
    """Catatan isi bulatan / pelurusan blok kolom nama & tanggal ujian: tidak ditampilkan dan tidak membuat
    lembar 'Perlu cek'. Nama yang ragu ditandai di kotak Nama panel cek (lihat nama_ragu)."""
    key = str(i.get("key", ""))
    if key.split(":", 1)[0] in TANPA_CATATAN:
        return True
    return key == "foto" and str(i.get("text", "")).split(":", 1)[0].strip() in TANPA_CATATAN


def saring_catatan(issues, soal):
    """Catatan baca yang perlu dicek: tanpa catatan kolom nama & tanggal ujian, dan (bila kunci `soal` diketahui)
    hanya sampai soal terakhir kunci. Catatan soal sesudahnya dan catatan pelurusan blok jawaban yang seluruhnya
    sesudah soal terakhir dibuang (tidak dinilai; biasanya hanya bayangan di bagian kertas yang tidak dipakai).
    Catatan nomor peserta, kode naskah, dan lembar jawaban tetap ada."""
    out = []
    for i in issues:
        if catatan_kepala_disembunyikan(i):
            continue
        key = str(i.get("key", ""))
        if soal is not None and key.startswith("soal:") and int(key.split(":")[1]) > soal.jumlah:
            continue
        if soal is not None and key == "foto" and _blok_mulai(i["text"]) > soal.jumlah:
            continue
        out.append(i)
    return out


def nama_ragu(baca):
    """Kolom nama yang isian bulatannya ragu/ganda menurut hasil baca: [(nomor kolom mulai 1, catatan)]."""
    out = []
    for h in (baca.get("header") or {}).get("nama", []):
        if h.get("kind") in ("ragu", "ganda"):
            out.append((h.get("col", 0) + 1, h.get("note") or h.get("kind")))
    return out


def info_lebih(skor, soal):
    """Info (bukan catatan perlu cek): ada beberapa isian tepat setelah soal terakhir kunci. Tidak dinilai, tetapi
    bila banyak bisa tanda kode naskah salah. None bila tidak ada."""
    if skor is None or not skor.lebih:
        return None
    return (f"Info: ada isian di soal {skor.lebih[0]}-{skor.lebih[-1]}, setelah soal terakhir kunci ({soal.jumlah}). "
            "Tidak dinilai; bila peserta memang menjawab sebanyak itu, periksa kode naskahnya.")


def duplicate_nomor(rows):
    c = Counter(r["nomor"] for r in rows if not r["error"] and r["nomor"])
    return {n for n, k in c.items() if k > 1}


KUALITAS_MIN = 85      # skor kualitas foto dari HP di bawah ini ikut dilaporkan


def server_info(row):
    """Data dari server LJK Reader Online untuk lembar yang ditarik (kosong untuk foto lokal)."""
    try:
        return json.loads(row["server"] or "{}")
    except (IndexError, KeyError, ValueError):
        return {}


def server_issues(row):
    """Catatan dari server & admin daerah yang perlu dicek panitia pusat."""
    srv = server_info(row)
    if not srv:
        return []
    out = [{"text": f"Server: {c}", "key": "server", "x": None, "y": None} for c in srv.get("catatan", [])]
    kon = srv.get("konfirmasi") or {}
    oleh = kon.get("oleh") or "admin daerah"
    label = {"nama": "nama", "nomor": "nomor peserta", "kode": "kode naskah"}
    for k, v in (kon.get("koreksi") or {}).items():
        out.append({"text": f"Dikoreksi {oleh}: {label.get(k, k)} terbaca '{srv.get('terbaca', {}).get(k, '')}' "
                            f"diganti '{v}'", "key": k, "x": None, "y": None})
    if kon.get("catatan"):
        out.append({"text": f"Catatan {oleh}: {kon['catatan']}", "key": "server", "x": None, "y": None})
    pb = srv.get("peserta_baru")
    if pb:
        st = "sudah disetujui" if srv.get("peserta_baru_status") == "disetujui" else "belum disetujui"
        out.append({"text": f"Peserta baru daftar di tempat ({st}): {pb.get('nama', '')} {pb.get('nomor', '')}",
                    "key": "nomor", "x": None, "y": None})
    if srv.get("skor_kualitas") is not None and srv["skor_kualitas"] < KUALITAS_MIN:
        out.append({"text": f"Kualitas foto dari HP rendah ({srv['skor_kualitas']}%)", "key": "foto",
                    "x": None, "y": None})
    return out


def sheet_view(row, naskah, dup):
    """Status satu lembar. naskah: {kode: Soal}; dup: himpunan nomor peserta ganda."""
    if row["error"]:
        return SheetView(row, "Gagal", issues=[{"text": row["error"], "key": "foto", "x": None, "y": None}])
    baca = json.loads(row["baca"] or "{}")
    jawaban = json.loads(row["jawaban"] or "[]")
    issues = [] if row["dicek"] else list(baca.get("issues", []))
    soal = soal_lembar(row, naskah)
    now = naskah.get(row["kode"])
    kunci_lama = soal is not None and now is not None and soal.kunci != now.kunci
    skor = None
    # tanpa catatan kolom nama & tanggal; bila kunci diketahui, hanya sampai soal terakhir kunci
    issues = saring_catatan(issues, soal)
    if soal is None:
        issues.insert(0, {"text": f"kode naskah '{row['kode']}' tidak ada di paket kunci (salah isi?): "
                                  "pilih kode naskah yang benar",
                          "key": "kode", "x": None, "y": None})
    else:
        # Yang dicek hanya sampai soal terakhir kunci: isian setelah soal terakhir (skor.lebih) tidak membuat
        # lembar "Perlu cek"; panel cek tetap menampilkannya sebagai info (lihat info_lebih).
        skor = NI.nilai(jawaban, soal)
    if not row["dicek"]:
        issues += server_issues(row)
    if row["dicek"] and any(ch in (row["nomor"] + row["kode"]) for ch in "?_"):
        issues.append({"text": "masih ada tanda ? atau _ di nomor peserta / kode naskah", "key": "kepala",
                       "x": None, "y": None})
    if row["nomor"] in dup:
        issues.append({"text": f"nomor peserta {row['nomor']} dipakai lebih dari satu lembar",
                       "key": "nomor", "x": None, "y": None})
    if issues:
        status = "Perlu cek"
    else:
        status = "Sudah dicek" if row["dicek"] else "OK"
    return SheetView(row, status, soal, skor, issues, kunci_lama)


BELUM = "belum"         # kunci kelompok lembar tanpa nilai (gagal dibaca / kode naskah tak terdaftar)


def kelompok_bidang(db, event_id, views=None):
    """Bidang (mata pelajaran) event menurut paket kuncinya, SEMUA bidang (termasuk yang belum ada lembarnya),
    urut kode naskah, masing-masing dengan lembarnya: [{key, nama, kode, jumlah, views}]. Lembar tanpa nilai
    (gagal dibaca / kode naskah tak terdaftar) dikumpulkan di kelompok BELUM paling akhir (hanya bila ada).
    Event lama tanpa paket memakai kunci per event, dikelompokkan per nama bidang. Dipakai tab Scan & nilai
    (dropdown Bidang) dan menu Nilai hasil, supaya pembagiannya selalu sama."""
    views = event_views(db, event_id) if views is None else views
    paket = db.event_paket(event_id)
    groups, kode2g = [], {}
    if paket is not None:
        for m in db.mapel(paket["id"]):
            g = {"key": ("m", m["id"]), "nama": m["nama"], "kode": list(m["kode"]), "jumlah": len(m["kunci"]),
                 "views": []}
            groups.append(g)
            for k in m["kode"]:
                kode2g[k] = g
    else:
        by = {}
        for s in db.naskah_lama(event_id):
            g = by.get(s.bidang.casefold())
            if g is None:
                g = by[s.bidang.casefold()] = {"key": ("b", s.bidang.casefold()), "nama": s.bidang, "kode": [],
                                               "jumlah": s.jumlah, "views": []}
                groups.append(g)
            g["kode"].append(s.kode)
            kode2g[s.kode] = g
    belum = {"key": BELUM, "nama": "Tanpa bidang (gagal dibaca / kode tak terdaftar)", "kode": [], "jumlah": 0,
             "views": []}
    for v in views:
        if v.skor is None:
            belum["views"].append(v)
            continue
        g = kode2g.get(v.row["kode"])
        if g is None:                       # kode sudah tidak ada di paket, tetapi lembarnya punya kunci beku
            nama = v.soal.bidang
            g = next((x for x in groups if x["nama"].casefold() == nama.casefold()), None)
            if g is None:
                g = {"key": ("x", nama.casefold()), "nama": nama, "kode": [], "jumlah": v.soal.jumlah, "views": []}
                groups.append(g)
            if v.row["kode"] not in g["kode"]:
                g["kode"].append(v.row["kode"])
        g["views"].append(v)
    if belum["views"]:
        groups.append(belum)
    return groups


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
    naskah = {s.kode: s for s in db.naskah(event_id)}
    groups, first_kode, skipped = {}, {}, []
    for v in views:
        if v.skor is None:
            skipped.append(v)
            continue
        # nama sheet = nama mata pelajaran sekarang (bisa sudah diganti di paket); nilai tetap dari kunci beku
        b = naskah[v.soal.kode].bidang if v.soal.kode in naskah else v.soal.bidang
        groups.setdefault(b, []).append((v.row["nomor"], v.row["nama"], v.skor))
        first_kode[b] = min(first_kode.get(b, v.soal.kode), v.soal.kode, key=kode_sort)
    ordered = [(b, groups[b]) for b in sorted(groups, key=lambda b: kode_sort(first_kode[b]))]
    EX.daftar_nilai(path, ev["nama"], ev["tanggal"], ordered)
    return len(views) - len(skipped), skipped
