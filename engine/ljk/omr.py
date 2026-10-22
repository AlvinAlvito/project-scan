"""Membaca bulatan: ukur kegelapan, beri status, lalu terjemahkan per kolom/baris."""
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import template as T
from .align import redness

# Status per bulatan
TERISI, KOSONG, RAGU = "terisi", "kosong", "ragu"

# Ambang skor kegelapan RELATIF: skor bulatan dikurangi median skor bloknya
# (kebanyakan bulatan di satu blok kosong, jadi median = tingkat "kosong" blok
# itu pada foto itu). Ditentukan dari sebaran 21 foto sampel: kosong (termasuk
# yang kena bayangan) < +0,15; isian tipis mulai ~+0,20; > +0,25 jelas terisi.
T_KOSONG = 0.15     # skor relatif <= ini: kosong
T_TERISI = 0.24     # skor relatif >= ini: terisi; di antaranya: ragu
# Bila ada satu bulatan terisi dan bulatan lain di grup yang sama hanya samar
# (misalnya bekas hapusan), pilihan tetap diterima asal yang samar < RASIO_HAPUSAN x yang terisi.
RASIO_HAPUSAN = 0.5

# Aturan "tanda menonjol" (isian tipis tapi tunggal). Peserta sering menghitamkan
# tipis (coretan pensil, huruf masih tembus); menilai tiap bulatan sendiri-sendiri
# membuat isian itu "ragu" atau bahkan hilang jadi kosong. Bila SATU bulatan jauh
# lebih gelap dari semua pilihan lain di baris/kolomnya:
#   skor >= T_MENONJOL_TERISI           -> terisi (otomatis)
#   T_MENONJOL_RAGU <= skor < ...TERISI -> ragu dengan tebakan (bisa bekas hapusan, dicek manusia)
# Bayangan/cahaya menggelapkan satu baris secara merata, jadi tidak lolos syarat selisih.
SELISIH_MENONJOL = 0.10
T_MENONJOL_TERISI = 0.15
T_MENONJOL_RAGU = 0.10

# Isian pensil yang MENGILAP: bila lampu memantul di grafit, isian tampak abu-abu
# keperakan, bahkan lebih terang dari kertas, sehingga ukuran kegelapan menganggapnya
# kosong. Cirinya: ada titik lebih terang dari kertas di dalam bulatan ("kilap") dan
# huruf merah cetakannya tertutup. Tidak diterima otomatis: grup yang tadinya kosong
# atau ragu dijadikan "ragu" dengan tebakan huruf itu. Ambang dari 106 foto OSM SUMBAR:
# isian mengilap asli kilap 13-70; bulatan kosong 99% <= 4.
KILAP_YAKIN = 12        # p95 terang di dalam bulatan dikurangi terang kertas (skala 0-255)
KILAP_MIN = 8           # kilap 8-12 baru dihitung bila huruf merahnya juga tertutup
HILANG_MERAH = 0.4      # merah huruf berkurang >= 40% dibanding huruf sama di bulatan lain
R_DALAM = 7             # jari-jari bagian dalam bulatan yang diukur kilap & merahnya

# Khusus kolom NAMA: huruf yang hilang tidak menimbulkan tanda apa pun (kolom kosong =
# spasi), jadi isian yang sangat samar tetapi jelas paling gelap di kolomnya dijadikan
# ragu. 127 foto uji: 11 kolom kena, semuanya huruf asli dari tulisan tangan.
T_NAMA_SAMAR = 0.07
SELISIH_NAMA_SAMAR = 0.05

# Normalisasi kontras per lembar. Ambang di atas disetel dari foto HP biasa, yang isian jelasnya
# bertingkat kegelapan ~0,6. Foto yang pudar (mis. frame video kamera dari web HP) menekan
# kegelapan isian DAN bekas hapusan dengan rasio yang sama, sehingga isian asli jatuh ke "ragu"
# atau "kosong". Skor lembar yang tingkat isiannya (median isian jelas di blok jawaban) di bawah
# acuan dikalikan supaya setara dengan foto acuan; lembar normal tidak diubah (faktor >= 1).
# Data 128 lembar: foto HP isian median 0,59-0,64 (p10 >= 0,50); frame video web 0,33-0,42.
# Acuan "standar" 0,50: tidak satu pun keputusan "ok" di 126 foto HP lama berubah, dan lembar web
# OSM SULSEL 2 #26 terbaca nomor 10083 (sebelumnya 1???3). Acuan lebih tinggi = penguatan lebih kuat.
KONTRAS = {"mati": None, "rendah": 0.45, "standar": 0.50, "tinggi": 0.55}
KONTRAS_MAKS = 2.0          # penguatan paling besar
KONTRAS_SELISIH = 0.08      # isian jelas: bulatan tergelap di satu soal >= ini di atas pilihan kedua
KONTRAS_MIN_ISIAN = 5       # kurang dari ini isian jelas: tingkat isian tidak bisa diukur, faktor 1


SHIFT = 3           # pusat ukur boleh bergeser +-3 px ke bagian paling gelap
ANNULUS = (13, 17)  # cincin di sela bulatan untuk mengukur terang kertas setempat

_PR = ANNULUS[1] + 1
_yy, _xx = np.mgrid[-_PR: _PR + 1, -_PR: _PR + 1]
_RR = np.hypot(_xx, _yy)
_RING = (_RR >= ANNULUS[0]) & (_RR <= ANNULUS[1])
_dk = np.mgrid[-T.FILL_R: T.FILL_R + 1, -T.FILL_R: T.FILL_R + 1]
_DISK_K = (np.hypot(*_dk) <= T.FILL_R).astype(np.float32)
_DISK_K /= _DISK_K.sum()
_INNER = _RR <= R_DALAM


def _letter_keys(block_index):
    """Kunci 'huruf cetak yang sama': bulatan berhuruf sama mestinya semerah satu sama lain.
    Angka nomor/kode/tanggal satu keluarga; huruf jawaban per blok."""
    keys = []
    for i, (g, _, v, _, _) in enumerate(T.BUBBLES):
        if g == "jawaban":
            keys.append((g, int(block_index[i]), v))
        elif g == "nama":
            keys.append((g, v))
        else:
            keys.append(("angka", v))
    return keys


def measure_shine(canon, bubble_xy, block_index):
    """Kekuatan kilap tiap bulatan; 0 bila tidak dianggap isian mengilap."""
    gray = cv2.cvtColor(canon, cv2.COLOR_BGR2GRAY).astype(np.float32)
    red = redness(canon)
    kilap = np.zeros(len(bubble_xy))
    red_in = np.zeros(len(bubble_xy))
    for i, (x, y) in enumerate(bubble_xy):
        cx, cy = int(round(x)) + T.PAD, int(round(y)) + T.PAD
        g = gray[cy - _PR: cy + _PR + 1, cx - _PR: cx + _PR + 1]
        if g.shape != _RING.shape:
            continue
        r = red[cy - _PR: cy + _PR + 1, cx - _PR: cx + _PR + 1]
        kilap[i] = np.percentile(g[_INNER], 95) - np.percentile(g[_RING], 85)
        red_in[i] = r[_INNER].mean()
    groups = {}
    for i, k in enumerate(_letter_keys(block_index)):
        groups.setdefault(k, []).append(i)
    expected = np.zeros(len(bubble_xy))
    for idx in groups.values():
        expected[idx] = np.median(red_in[idx])
    hilang = (expected - red_in) / max(float(np.median(expected)), 1e-6)
    shiny = (kilap >= KILAP_YAKIN) | ((kilap >= KILAP_MIN) & (hilang >= HILANG_MERAH))
    return np.where(shiny, kilap, 0.0)


def measure(canon, bubble_xy):
    """Skor kegelapan tiap bulatan (0 = seterang kertas sekitarnya, 1 = hitam).

    Kanal merah dipakai supaya cetakan merah (lingkaran & huruf) tak terhitung.
    Terang kertas diambil dari cincin tipis di sela bulatan, jadi bayangan yang
    menutupi bulatan dan sekitarnya saling meniadakan. Pusat ukur boleh
    bergeser sedikit ke bagian paling gelap supaya isian yang miring tetap
    terukur penuh. Juga mengembalikan pergeseran itu (untuk cek pelurusan).
    """
    R = canon[:, :, 2].astype(np.float32)
    scores = np.zeros(len(bubble_xy))
    offsets = np.zeros((len(bubble_xy), 2))
    for i, (x, y) in enumerate(bubble_xy):
        cx, cy = int(round(x)) + T.PAD, int(round(y)) + T.PAD
        patch = R[cy - _PR: cy + _PR + 1, cx - _PR: cx + _PR + 1]
        if patch.shape != _RING.shape:
            continue
        paper = max(float(np.percentile(patch[_RING], 85)), 1.0)
        dark = np.clip(1 - patch / paper, 0, 1)
        mean = cv2.filter2D(dark, -1, _DISK_K, borderType=cv2.BORDER_CONSTANT)
        c = _PR
        win = mean[c - SHIFT: c + SHIFT + 1, c - SHIFT: c + SHIFT + 1]
        k = int(np.argmax(win))
        dy, dx = divmod(k, win.shape[1])
        scores[i] = float(win[dy, dx])
        # Titik berat bagian gelap dalam radius 13 (untuk cek pelurusan).
        w = np.where(_RR <= 13, dark, 0)
        if w.sum() > 1e-6:
            offsets[i] = ((w * _xx).sum() / w.sum() + (cx - x - T.PAD),
                          (w * _yy).sum() / w.sum() + (cy - y - T.PAD))
    return scores, offsets


def status_of(score):
    if score >= T_TERISI:
        return TERISI
    if score <= T_KOSONG:
        return KOSONG
    return RAGU


@dataclass
class GroupRead:
    value: str          # huruf/angka terbaca; "" bila kosong; "?" ragu; "*" lebih dari satu terisi
    kind: str           # "ok", "kosong", "ragu", "ganda"
    scores: dict        # nilai -> skor
    note: str = ""
    guess: str = ""     # tebakan khusus untuk grup ragu (bila kosong: pilihan paling gelap)


def guess_of(gr):
    """Pilihan yang ditebak/dicurigai untuk grup ragu atau ganda."""
    return gr.guess or max(gr.scores, key=gr.scores.get)


def read_group(values, scores, shine=None, faint=False):
    """Terjemahkan satu kolom (nama/angka) atau satu baris soal.

    shine: kekuatan kilap tiap bulatan (measure_shine), untuk isian mengilap.
    faint: isian sangat samar yang menonjol dijadikan ragu (dipakai untuk kolom nama)."""
    base = _read_dark(values, scores)
    if base.kind in ("ok", "ganda"):
        return base
    if shine is None or not np.any(shine > 0):
        if faint and base.kind == "kosong":
            s = np.sort(scores)[::-1]
            if s[0] >= T_NAMA_SAMAR and s[0] - s[1] >= SELISIH_NAMA_SAMAR:
                v = values[int(np.argmax(scores))]
                return GroupRead("?", "ragu", base.scores,
                                 f"isian sangat samar di {v} (huruf terlewat atau bekas hapusan?)", guess=v)
        return base
    order = [k for k in np.argsort(shine)[::-1] if shine[k] > 0]
    v = values[order[0]]
    lain = f" (juga {', '.join(values[k] for k in order[1:])})" if len(order) > 1 else ""
    if base.kind == "ragu" and guess_of(base) == v:
        note = f"isian tipis dan mengilap (pantulan cahaya) di {v}{lain}"
    elif base.kind == "ragu":
        note = f"{base.note}; ada isian mengilap (pantulan cahaya) di {v}{lain}"
    else:
        note = f"isian mengilap (pantulan cahaya) di {v}{lain}, terbaca kosong"
    return GroupRead("?", "ragu", base.scores, note, guess=v)


# Model "juri kedua" (ljk/belajar.py): peluang tiap bulatan terisi menurut model hasil latih.
P_YAKIN = 0.90          # model yakin bulatan terisi
P_TIDAK = 0.10          # model yakin bulatan tidak terisi
P_PUTUS = 0.97          # memutus kasus ragu (hanya bila model lulus gerbang B)

_GROUP_IDX = {}
for _k, _b in enumerate(T.BUBBLES):
    _GROUP_IDX.setdefault((_b[0], _b[1]), []).append(_k)


def apply_model(reads, prob_filled, putus_ragu=False):
    """Juri kedua: model tidak pernah mengganti hasil sendirian. Bila tidak setuju dengan
    aturan, grup dijadikan ragu (perlu dicek) dengan tebakan aturan. Hanya bila putus_ragu
    (model lulus ujian kasus ragu), grup ragu yang sangat jelas menurut model diputuskan."""
    out = {}
    for key, gr in reads.items():
        idx = _GROUP_IDX[key]
        vals = [T.BUBBLES[i][2] for i in idx]
        p = prob_filled[idx]
        top = int(np.argmax(p))
        if gr.kind == "ok":
            yakin_lain = [v for v, q in zip(vals, p) if v != gr.value and q >= P_YAKIN]
            if p[vals.index(gr.value)] < P_TIDAK or yakin_lain:
                gr = GroupRead("?", "ragu", gr.scores, f"model tidak setuju: aturan {gr.value}, model "
                               f"{', '.join(yakin_lain) or 'kosong'}", guess=gr.value)
        elif gr.kind == "kosong":
            if p[top] >= P_YAKIN:
                gr = GroupRead("?", "ragu", gr.scores, f"model melihat isian di {vals[top]}, aturan kosong",
                               guess=vals[top])
        elif gr.kind == "ragu" and putus_ragu:
            hi = [v for v, q in zip(vals, p) if q >= P_PUTUS]
            if len(hi) == 1 and all(q <= 1 - P_PUTUS for v, q in zip(vals, p) if v != hi[0]):
                gr = GroupRead(hi[0], "ok", gr.scores, f"diputus model (yakin terisi {hi[0]})")
            elif not hi and p.max() <= 1 - P_PUTUS:
                gr = GroupRead("", "kosong", gr.scores, "diputus model (yakin kosong)")
        out[key] = gr
    return out


def _read_dark(values, scores):
    """Keputusan dari kegelapan bulatan saja."""
    sc = dict(zip(values, scores))
    order = np.argsort(scores)[::-1]
    s1 = scores[order[0]]
    s2 = scores[order[1]] if len(order) > 1 else 0.0
    st = [status_of(s) for s in scores]
    n_fill = st.count(TERISI)
    n_doubt = st.count(RAGU)
    best = values[order[0]]
    menonjol = s1 - s2 >= SELISIH_MENONJOL and s2 <= T_KOSONG
    if menonjol and n_fill <= 1:
        if s1 >= T_MENONJOL_TERISI:
            return GroupRead(best, "ok", sc, "" if s1 >= T_TERISI else f"isian tipis di {best}")
        if s1 >= T_MENONJOL_RAGU:
            return GroupRead("?", "ragu", sc, f"isian sangat tipis, mungkin bekas hapusan (paling gelap {best})")
    if n_fill == 0 and n_doubt == 0:
        return GroupRead("", "kosong", sc)
    if n_fill >= 2:
        picked = "".join(values[i] for i in order[:n_fill])
        return GroupRead("*", "ganda", sc, f"lebih dari satu terisi ({picked})")
    if n_fill == 1:
        if n_doubt == 0 or s2 < RASIO_HAPUSAN * s1:
            note = f"ada bekas samar di {values[order[1]]}" if n_doubt else ""
            return GroupRead(best, "ok", sc, note)
        return GroupRead("?", "ragu", sc, f"{best} terisi tapi {values[order[1]]} juga cukup gelap")
    return GroupRead("?", "ragu", sc, f"hanya samar (paling gelap {values[order[0]]})")


@dataclass
class SheetRead:
    nama: str
    nomor: str
    kode: str
    tanggal: str
    jawaban: list                  # 180 item: "A".."E", "", "?", "*"
    header_groups: dict            # ("nama", i) -> GroupRead, dst.
    answer_groups: list            # 180 GroupRead
    issues: list = field(default_factory=list)   # daftar teks hal yang perlu dicek


def relative_scores(scores, block_index):
    """Skor dikurangi median bloknya masing-masing."""
    rel = np.array(scores, float).copy()
    for k in np.unique(block_index):
        sel = block_index == k
        rel[sel] -= np.median(scores[sel])
    return rel


def fill_level(scores):
    """Tingkat kegelapan isian jelas di blok jawaban (median), None bila isian jelas terlalu sedikit."""
    fills = []
    for q in range(T.N_QUESTIONS):
        row = np.sort(scores[_GROUP_IDX[("jawaban", q)]])[::-1]
        if row[0] - row[1] >= KONTRAS_SELISIH:
            fills.append(row[0])
    return float(np.median(fills)) if len(fills) >= KONTRAS_MIN_ISIAN else None


def contrast_factor(scores, kontras="standar"):
    """Pengali skor relatif untuk lembar pudar (lihat KONTRAS). 1.0 untuk lembar normal atau 'mati'."""
    ref = KONTRAS.get(kontras, KONTRAS["standar"])
    level = fill_level(scores) if ref is not None else None
    return float(np.clip(ref / level, 1.0, KONTRAS_MAKS)) if level else 1.0


def read_sheet(canon, bubble_xy, block_index, model_prob=None, putus_ragu=False, kontras="standar"):
    """model_prob: N x 3 peluang (kosong, terisi, hapusan) dari model aktif, atau None.
    kontras: kunci KONTRAS untuk normalisasi kontras lembar pudar."""
    raw, offsets = measure(canon, bubble_xy)
    rel = relative_scores(raw, block_index)
    factor = contrast_factor(rel, kontras)
    scores = rel * factor
    shine = measure_shine(canon, bubble_xy, block_index)
    groups = {}
    for idx, (g, i, v, _, _) in enumerate(T.BUBBLES):
        groups.setdefault((g, i), ([], [], []))
        groups[(g, i)][0].append(v)
        groups[(g, i)][1].append(scores[idx])
        groups[(g, i)][2].append(shine[idx])
    reads = {k: read_group(vs, np.array(ss), np.array(sh), faint=k[0] == "nama")
             for k, (vs, ss, sh) in groups.items()}
    if model_prob is not None:
        reads = apply_model(reads, model_prob[:, 1], putus_ragu)
    issues = []

    # Nama: kolom kosong = spasi.
    letters = []
    for c in range(len(T.NAME_COLS_X)):
        r = reads[("nama", c)]
        if r.kind == "kosong":
            letters.append(" ")
        elif r.kind == "ok":
            letters.append(r.value)
        else:
            letters.append("?")
            issues.append(f"Nama kolom {c + 1}: {r.note}")
    nama = " ".join("".join(letters).split())

    def digits(group, n, label, critical=True):
        out = []
        for c in range(n):
            r = reads[(group, c)]
            if r.kind == "ok":
                out.append(r.value)
            elif r.kind == "kosong":
                out.append("_")
                if critical:
                    issues.append(f"{label} digit {c + 1}: kosong")
            else:
                out.append("?")
                if critical:
                    issues.append(f"{label} digit {c + 1}: {r.note}")
        return "".join(out)

    nomor = digits("nomor", len(T.NOMOR_COLS_X), "Nomor peserta")
    kode = digits("kode", len(T.KODE_COLS_X), "Kode naskah")
    tg = digits("tanggal", len(T.TANGGAL_COLS), "Tanggal", critical=False)
    tanggal = f"{tg[0:2]}-{tg[2:4]}-{tg[4:6]}"

    jawaban, answer_groups = [], []
    for q in range(T.N_QUESTIONS):
        r = reads[("jawaban", q)]
        answer_groups.append(r)
        jawaban.append(r.value)
        if r.kind in ("ragu", "ganda"):
            issues.append(f"Soal {q + 1}: {r.note}")

    header_groups = {k: v for k, v in reads.items() if k[0] != "jawaban"}
    sr = SheetRead(nama, nomor, kode, tanggal, jawaban, header_groups, answer_groups, issues)
    sr.raw_scores = raw
    sr.scores = scores
    sr.kontras = factor
    sr.offsets = offsets
    sr.shine = shine
    sr.model_prob = model_prob
    return sr
