"""Meluruskan foto LJK ke bingkai baku (lihat template.py).

Langkah:
1. Putar foto jadi tegak; garis tepi kiri menentukan apakah perlu diputar 180°.
2. Cocokkan garis-garis tepi kiri ke posisi bakunya -> transformasi awal.
3. Haluskan transformasi memakai ratusan bulatan cetak (lingkaran merah)
   yang posisinya diketahui -> homografi global, lalu per wilayah
   (kepala lembar dan area jawaban) supaya kertas yang melengkung tetap pas.
"""
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import template as T

WORK_H = 2000  # tinggi gambar kerja (piksel)


class AlignError(Exception):
    """Foto tidak bisa diluruskan (bukan LJK, terpotong parah, atau terlalu buram)."""


def load_image(path):
    data = np.fromfile(str(path), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise AlignError("File gambar tidak bisa dibuka")
    return img


def _to_work(img):
    s = WORK_H / img.shape[0]
    return cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)


def dark_mask(img, thr=0.5):
    """Piksel hitam/pensil. Kanal merah dipakai supaya cetakan merah LJK hilang.
    thr: batas kecerahan relatif terhadap kertas di sekitarnya."""
    R = img[:, :, 2].astype(np.float32)
    bg = cv2.GaussianBlur(cv2.dilate(R, np.ones((41, 41), np.uint8)), (0, 0), 15)
    return ((R / np.maximum(bg, 1)) < thr).astype(np.uint8)


MAX_TILT_DEG = 45     # kemiringan kertas di dalam foto yang masih didukung
LEFT_LIMIT = 300      # tahap awal pelurusan: bulatan dengan x < batas ini (dekat garis tepi)


def _find_dashes(img, thr=0.5):
    """Garis kecil hitam di tepi kiri. Diukur dengan kotak yang ikut miring
    (minAreaRect), jadi tetap dikenali walau kertas difoto miring.
    Mengembalikan (titik_pusat, arah_sumbu_panjang_radian)."""
    cnts, _ = cv2.findContours(dark_mask(img, thr), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    H, W = img.shape[:2]
    pts, angs = [], []
    for c in cnts:
        area = cv2.contourArea(c)
        if not (60 <= area <= 1500):
            continue
        bx, by, bw, bh = cv2.boundingRect(c)
        if bx <= 2 or by <= 2 or bx + bw >= W - 2 or by + bh >= H - 2:
            continue        # terpotong tepi foto (mis. kotak sudut yang tampak seperti garis)
        (cx, cy), (rw, rh), ang = cv2.minAreaRect(c)
        long_, short = max(rw, rh), min(rw, rh)
        if short < 1 or not (2.0 < long_ / short < 6.0) or area / (rw * rh) < 0.7:
            continue
        pts.append((cx, cy))
        angs.append(np.deg2rad(ang if rw >= rh else ang + 90))
    return np.array(pts, float).reshape(-1, 2), np.array(angs, float)


def _track_inliers(P, A, a, b, tol):
    """Titik yang dekat garis x = a*y + b DAN arah garis kecilnya tegak lurus garis itu."""
    dist = np.abs(P[:, 0] - (a * P[:, 1] + b)) / np.sqrt(1 + a * a)
    phi = np.arctan2(-a, 1.0)                        # arah tegak lurus garis tepi
    diff = np.abs(((A - phi + np.pi / 2) % np.pi) - np.pi / 2)
    return (dist < tol) & (diff < np.deg2rad(20))


def _fit_track(P, A, rng):
    """Cari garis lurus (boleh miring s.d. MAX_TILT_DEG) yang dilalui paling banyak garis kecil."""
    if len(P) < 8:
        return None
    max_a = np.tan(np.deg2rad(MAX_TILT_DEG))
    best = None
    for _ in range(3000):
        i, j = rng.choice(len(P), 2, replace=False)
        (x1, y1), (x2, y2) = P[i], P[j]
        if abs(y2 - y1) < 150:
            continue
        a = (x2 - x1) / (y2 - y1)
        if abs(a) > max_a:
            continue
        inl = _track_inliers(P, A, a, x1 - a * y1, 5)
        if best is None or inl.sum() > best.sum():
            best = inl
    if best is None or best.sum() < 8:
        return None
    a, b = np.polyfit(P[best, 1], P[best, 0], 1)
    return P[_track_inliers(P, A, a, b, 6)]


# Posisi garis tepi dalam "slot" (kelipatan jarak antarbaris): garis atas di
# slot 0, baris A..Z di slot 3..28, soal 1..30 di slot 32..61.
_TPITCH = float(np.median(np.diff(T.TIMING_Y[1:27])))
TIMING_SLOTS = [int(round((y - T.TIMING_Y[0]) / _TPITCH)) for y in T.TIMING_Y]


def _fit_projective_1d(Y, u):
    """u = (a*Y + b) / (g*Y + 1): pemetaan satu garis lurus di bawah perspektif."""
    A = np.c_[Y, np.ones_like(Y), -u * Y]
    (a, b, g), *_ = np.linalg.lstsq(A, u, rcond=None)
    return a, b, g


def _proj_1d(p, Y):
    a, b, g = p
    return (a * Y + b) / (g * Y + 1)


def _register_track(D):
    """Pasangkan garis tepi terdeteksi dengan indeks templatnya (0..56).

    Jarak antargaris bisa berubah sepanjang kertas (foto miring), jadi
    langkah antargaris dihitung terhadap jarak lokal, lalu urutan langkah itu
    dicocokkan dengan pola slot template (celah di atas baris A dan di antara
    baris Z dan soal 1 membuat posisinya unik).

    Mengembalikan ([(pasangan [(indeks_template, titik_gambar)], parameter_proyektif_1d)],
    titik_awal, arah_garis). Daftar kandidat berisi lebih dari satu bila urutannya seri.
    """
    d = D[np.argsort(D[:, 1])]
    direction = d[-1] - d[0]
    direction /= np.linalg.norm(direction)
    u = (d - d[0]) @ direction
    du = np.diff(u)
    mid = (u[1:] + u[:-1]) / 2

    # Jarak lokal sebagai fungsi linear posisi, dari langkah-langkah tunggal.
    p0 = np.median(du)
    single = (du > 0.6 * p0) & (du < 1.4 * p0)
    coef = np.array([0.0, np.median(du[single])])
    for _ in range(3):
        local = np.polyval(coef, mid)
        single = np.abs(du / local - 1) < 0.25
        if single.sum() >= 4:
            coef = np.polyfit(mid[single], du[single], 1)
    local = np.polyval(coef, mid)
    # Buang titik di UJUNG barisan yang jaraknya bukan kelipatan bulat jarak antargaris
    # (mis. kotak sudut yang terpotong di tepi foto sehingga tampak seperti garis).
    ratio = du / local
    lo, hi = 0, len(u) - 1
    while hi - lo > 8 and abs(ratio[lo] - round(ratio[lo])) > 0.2:
        lo += 1
    while hi - lo > 8 and abs(ratio[hi - 1] - round(ratio[hi - 1])) > 0.2:
        hi -= 1
    if lo > 0 or hi < len(u) - 1:
        return _register_track(d[lo:hi + 1])
    # Bercak tambahan DI TENGAH barisan (mis. garis tampak dobel karena buram atau
    # bayangan) membuat langkah setengah jarak yang tadinya dihitung satu slot,
    # sehingga urutan sesudahnya bergeser beberapa baris. Pertahankan rantai
    # terpanjang yang semua langkahnya kelipatan bulat jarak antargaris.
    keep = _regular_chain(u, coef)
    if len(keep) < len(u) and len(keep) >= 10:
        return _register_track(d[keep])
    steps = np.rint(du / local).astype(int)
    steps[steps < 1] = 1
    slots = np.r_[0, np.cumsum(steps)]

    tset = {s: j for j, s in enumerate(TIMING_SLOTS)}
    hits = {off: sum(1 for s in slots if s + off in tset)
            for off in range(-slots[-1] - 2, TIMING_SLOTS[-1] + 3)}
    top = max(hits.values())
    # Beberapa garis yang tak terbaca berurutan bisa meniru celah Z -> soal 1,
    # sehingga lebih dari satu geseran sama cocoknya. Semua dikembalikan;
    # align() memilih dengan pola blok.
    regs = [_refine_track(u, slots, off, tset) for off, h in sorted(hits.items()) if h == top]
    return [([(j, d[k]) for j, k in pairs], par) for pairs, par in regs], d[0], direction


CHAIN_TOL = 0.25    # langkah dianggap kelipatan bulat bila menyimpang < 0,25 jarak antargaris
CHAIN_MAX_GAP = 12  # celah terpanjang (dalam slot) antara dua garis yang terbaca


def _regular_chain(u, coef):
    """Indeks titik yang membentuk rantai terpanjang dengan setiap langkah
    = kelipatan bulat (>= 1) jarak antargaris lokal (polinom coef)."""
    n = len(u)
    best = np.ones(n, int)
    prev = np.full(n, -1)
    for i in range(1, n):
        for j in range(i - 1, -1, -1):
            r = (u[i] - u[j]) / np.polyval(coef, (u[i] + u[j]) / 2)
            if r > CHAIN_MAX_GAP + 0.5:
                break
            k = round(r)
            if k >= 1 and abs(r - k) < CHAIN_TOL and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    i = int(np.argmax(best))
    chain = []
    while i >= 0:
        chain.append(i)
        i = prev[i]
    return chain[::-1]


def _refine_track(u, slots, off, tset):
    """Pasangan (indeks_template, indeks_garis) untuk satu geseran slot, diperhalus."""
    TY = np.array(T.TIMING_Y)
    pairs = [(tset[s + off], k) for k, s in enumerate(slots) if s + off in tset]

    # Perhalus: pemetaan proyektif 1D, lalu cocokkan ulang dengan toleransi.
    js = np.array([j for j, _ in pairs]); ks = np.array([k for _, k in pairs])
    par = _fit_projective_1d(TY[js], u[ks])
    for _ in range(2):
        pred = _proj_1d(par, TY)
        lp = np.abs(np.gradient(pred)) / np.maximum(np.abs(np.gradient(TY)), 1e-6) * _TPITCH
        used = {}
        for k, uk in enumerate(u):
            j = int(np.argmin(np.abs(pred - uk)))
            if abs(pred[j] - uk) < 0.3 * lp[j]:
                if j not in used or abs(pred[j] - uk) < abs(pred[j] - u[used[j]]):
                    used[j] = k
        pairs = sorted(used.items())
        js = np.array([j for j, _ in pairs]); ks = np.array([k for _, k in pairs])
        if len(pairs) >= 6:
            par = _fit_projective_1d(TY[js], u[ks])
    return pairs, par


# Ambang garis tepi yang dicoba berurutan. Di sebagian foto HP garis tepi tampak abu-abu tua
# (mis. kecerahan 52% dari kertas), sehingga pada ambang 0,5 hanya serpihannya yang tertangkap.
# Foto yang sudah terbaca pada ambang pertama tidak terpengaruh.
DASH_THRESHOLDS = (0.5, 0.6, 0.7)
DASH_ENOUGH = 20      # garis tepi sebanyak ini dianggap cukup; ambang berikutnya tidak dicoba


def _detect_track(work, rng):
    best = None
    for thr in DASH_THRESHOLDS:
        P, A = _find_dashes(work, thr)
        D = _fit_track(P, A, rng)
        if D is not None and (best is None or len(D) > len(best)):
            best = D
        if best is not None and len(best) >= DASH_ENOUGH:
            break
    return best


def _orient(img, rng, with_rot=False):
    """Putar foto sampai garis tepi berada di kiri. Mengembalikan (gambar_kerja, diputar180, garis),
    ditambah kode putaran 90 derajat foto asli bila with_rot."""
    candidates = []
    if img.shape[1] > img.shape[0]:
        candidates = [cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE]
    else:
        candidates = [None]
    best = None
    for rot in candidates:
        base = img if rot is None else cv2.rotate(img, rot)
        work = _to_work(base)
        D = _detect_track(work, rng)
        if D is None:
            continue
        if best is None or len(D) > len(best[2]):
            best = (work, rot, D)
        if len(D) >= 20:
            break
    if best is None:
        raise AlignError("Garis tepi kiri tidak ditemukan")
    work, rot, D = best
    flipped = False
    if np.mean(D[:, 0]) > work.shape[1] / 2:
        work = cv2.rotate(work, cv2.ROTATE_180)
        D = _detect_track(work, rng)
        flipped = True
        if D is None:
            raise AlignError("Garis tepi kiri tidak ditemukan setelah diputar")
    return (work, flipped, D, rot) if with_rot else (work, flipped, D)


# ---------------------------------------------------------------- bulatan cetak

def _ring_kernel():
    yy, xx = np.mgrid[-15:16, -15:16]
    rr = np.hypot(xx, yy)
    ring = (rr >= T.BUBBLE_R - 2) & (rr <= T.BUBBLE_R + 2)
    k = np.zeros(rr.shape, np.float32)
    k[ring] = 1.0
    outer = rr > T.BUBBLE_R + 3
    k[outer] = -ring.sum() / outer.sum()
    return k


_RING_K = _ring_kernel()


def warp_to_canon(work, M):
    """Gambar kerja -> bingkai baku (dengan margin PAD)."""
    P = np.array([[1, 0, T.PAD], [0, 1, T.PAD], [0, 0, 1]], float)
    size = (T.CANON_W + 2 * T.PAD, T.CANON_H + 2 * T.PAD)
    return cv2.warpPerspective(work, P @ np.linalg.inv(M), size,
                               flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))


def redness(img):
    """Kekuatan tinta merah (kanal a* Lab, sumbu merah-hijau).

    Teks hitam, pensil, dan kertas bernilai ~0 sehingga hanya cetakan merah
    yang muncul. Kanal a* tetap stabil walau cahaya foto kekuningan."""
    a = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)[:, :, 1].astype(np.float32)
    return np.clip(a - np.median(a), 0, None)


def ring_response(canon):
    """Peta kemiripan dengan lingkaran bulatan cetak (merah).

    Sengaja hanya tinta merah: nomor soal hitam di kiri pilihan A berjarak
    sama dengan jarak antarpilihan, sehingga kalau teks hitam ikut dihitung
    pelurusan bisa bergeser satu kolom."""
    red = cv2.GaussianBlur(redness(canon), (0, 0), 1.0)
    return cv2.filter2D(red, -1, _RING_K)


def _local_peaks(resp, pts, win):
    """Untuk tiap titik (bingkai baku), cari puncak respons di jendela +-win."""
    H, W = resp.shape
    found = np.array(pts, float).copy()
    val = np.zeros(len(pts))
    for i, (x, y) in enumerate(pts):
        cx, cy = int(round(x)) + T.PAD, int(round(y)) + T.PAD
        x0, x1 = max(cx - win, 0), min(cx + win + 1, W)
        y0, y1 = max(cy - win, 0), min(cy + win + 1, H)
        sub = resp[y0:y1, x0:x1]
        if sub.size == 0:
            continue
        k = int(np.argmax(sub))
        py, px = divmod(k, sub.shape[1])
        found[i] = (x0 + px - T.PAD, y0 + py - T.PAD)
        val[i] = sub[py, px]
    return found, val


def apply_h(H, pts):
    pts = np.asarray(pts, float).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, H).reshape(-1, 2)


def _translate(dx, dy):
    return np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], float)


def _initial_transform(p0, direction, par):
    """Homografi awal dari garis tepi saja.

    Sepanjang garis tepi dipakai pemetaan proyektif 1D hasil pencocokan.
    Ke arah kanan diasumsikan skala yang sama dengan skala tegak di tengah
    kertas, dengan perspektif yang sama (penyebut g*Y + 1).
    """
    a, b, g = par
    kappa = (a - b * g) / (g * (T.CANON_H / 2) + 1)
    nrm = np.array([direction[1], -direction[0]])
    F = np.array([[direction[0], nrm[0], p0[0]],
                  [direction[1], nrm[1], p0[1]],
                  [0, 0, 1]], float)
    K = np.array([[0, a, b], [kappa, 0, 0], [0, g, 1]], float)
    return F @ K @ _translate(-T.TIMING_X, 0)


def _global_fit(work, M, pts, win, dash_pairs):
    """Satu langkah penghalusan homografi global.

    Bulatan cetak dicari di sekitar posisi template; garis tepi kiri dipakai
    dengan pasangan indeks yang sudah pasti dari pencocokan awal, jadi
    pelurusan tidak bisa 'terkunci' bergeser satu-dua baris."""
    resp = ring_response(warp_to_canon(work, M))
    found, val = _local_peaks(resp, pts, win)
    ref = np.median(val[val > 0]) if np.any(val > 0) else 0
    ok = val > 0.35 * ref
    if ok.sum() < 12:
        return None
    tp = np.array([(T.TIMING_X, T.TIMING_Y[j]) for j, _ in dash_pairs], float)
    fp = apply_h(np.linalg.inv(M), [p for _, p in dash_pairs])
    src = np.vstack([pts[ok], tp]).astype(np.float32)
    dst = np.vstack([found[ok], fp]).astype(np.float32)
    Hc, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    return Hc


# Blok yang diluruskan sendiri-sendiri (kertas foto tidak benar-benar datar).
def _block_of(b):
    g, i = b[0], b[1]
    if g == "nama":
        return "nama"
    if g in ("nomor", "kode"):
        return "nomor-kode"
    if g == "tanggal":
        return "tanggal"
    return f"jawaban {30 * (i // 30) + 1}-{30 * (i // 30) + 30}"


BLOCK_NAMES = ["nama", "nomor-kode", "tanggal"] + [f"jawaban {30 * b + 1}-{30 * b + 30}" for b in range(6)]
# Jangkauan pencarian sidik jari (x, y). Baris nama & jawaban sejajar dengan
# garis tepi kiri yang sudah dipatok, jadi geser tegaknya dibatasi < setengah
# baris; blok angka (nomor, kode, tanggal) tidak menempel ke garis tepi, jadi
# boleh lebih jauh (pola kotaknya tidak berulang sehingga tetap unik).
REF_SEARCH_XY = {name: (28, 12) for name in BLOCK_NAMES}
REF_SEARCH_XY["nomor-kode"] = (28, 28)
REF_SEARCH_XY["tanggal"] = (28, 28)
BLOCK_INDEX = np.array([BLOCK_NAMES.index(_block_of(b)) for b in T.BUBBLES])


# ------------------------------------------------- sidik jari blok (acuan)
# Bulatan tersusun berulang, jadi pencocokan bulatan saja tidak bisa membedakan
# blok yang bergeser tepat satu baris/kolom. "Sidik jari" = pola tinta merah
# satu blok (garis kotak, kolom Tgl yang hanya 0-3, kolom Bln yang hanya 0-1,
# dsb.) dari lembar acuan yang sudah dipastikan pas. Pola ini tidak berulang,
# sehingga posisinya unik.
REF_DIR = Path(__file__).with_name("ref")
REF_MARGIN = 22     # sisi tambahan di sekitar bulatan terluar (memuat garis kotak)


def block_bbox(k):
    pts = np.array([(b[3], b[4]) for b, bi in zip(T.BUBBLES, BLOCK_INDEX) if bi == k])
    m = T.BUBBLE_R + REF_MARGIN
    return (int(pts[:, 0].min() - m), int(pts[:, 1].min() - m),
            int(pts[:, 0].max() + m), int(pts[:, 1].max() + m))


def block_slug(name):
    return name.replace(" ", "_")


def ref_redness(canon):
    """Peta merah yang dipakai untuk sidik jari (dihaluskan, skala 0-255)."""
    red = cv2.GaussianBlur(redness(canon), (0, 0), 1.5)
    hi = np.percentile(red, 99.5)
    return np.clip(red * (255.0 / max(hi, 1e-6)), 0, 255).astype(np.uint8)


_REF_CACHE = {}


def _load_ref(name):
    if name not in _REF_CACHE:
        p = REF_DIR / f"{block_slug(name)}.png"
        _REF_CACHE[name] = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None
    return _REF_CACHE[name]


def _match_block(red, k, name, search=None, center=(0, 0)):
    """Cari pergeseran blok terhadap sidik jarinya.

    search: jangkauan (x, y) pencarian (bawaan REF_SEARCH_XY); center: pusat
    pencarian (dx, dy). Mengembalikan (dx, dy, skor, skor_kedua) atau None bila
    acuan belum ada. skor_kedua = kecocokan terbaik di posisi lain yang berjarak
    >= setengah jarak antarbaris; kalau hampir sama dengan skor, posisinya meragukan."""
    ref = _load_ref(name)
    if ref is None:
        return None
    x0, y0, x1, y1 = block_bbox(k)
    Sx, Sy = search or REF_SEARCH_XY[name]
    cx, cy = int(round(center[0])), int(round(center[1]))
    m = max(Sx, Sy) + 40
    padded = cv2.copyMakeBorder(red, m, m, m, m, cv2.BORDER_CONSTANT, value=0)
    ox, oy = x0 + T.PAD + m + cx - Sx, y0 + T.PAD + m + cy - Sy
    area = padded[oy: oy + (y1 - y0) + 2 * Sy, ox: ox + (x1 - x0) + 2 * Sx]
    res = cv2.matchTemplate(area, ref, cv2.TM_CCOEFF_NORMED)
    _, best, _, loc = cv2.minMaxLoc(res)
    dx, dy = loc[0] - Sx + cx, loc[1] - Sy + cy
    yy, xx = np.mgrid[: res.shape[0], : res.shape[1]]
    far = np.hypot(xx - loc[0], yy - loc[1]) >= 0.5 * _TPITCH
    second = float(res[far].max()) if far.any() else -1.0
    return dx, dy, float(best), second


# ------------------------------------------------ medan pergeseran per blok
# Kertas yang difoto bisa melengkung tidak lurus (misalnya hanya bagian atas
# yang terangkat), jadi satu transformasi afine per blok tidak cukup. Blok
# dibagi petak-petak; pergeseran tiap petak (dari sidik jari) dimodelkan
# sebagai fungsi halus posisi (polinom derajat 2), lalu dipakai untuk setiap
# bulatan di blok itu.

# Pembagian petak per blok (kolom x baris) dan model pergeseran.
TILES = {name: (2, 6) for name in BLOCK_NAMES}
TILES.update({"nama": (3, 6), "nomor-kode": (2, 3), "tanggal": (2, 3)})
MODEL = {name: "quad_y" for name in BLOCK_NAMES}   # jawaban: 2 kolom petak, lengkung arah tegak
MODEL.update({"nama": "quad", "nomor-kode": "affine", "tanggal": "affine"})
TILE_SEARCH = 12    # < setengah jarak antarbaris, jadi petak tak bisa loncat ke baris tetangga
TILE_MIN_SCORE = 0.3
_FALLBACK = {"quad": "quad_y", "quad_y": "affine", "affine": "translation"}


def _features(pts, model):
    pts = np.asarray(pts, float).reshape(-1, 2)
    x, y = pts[:, 0] / 1000.0, pts[:, 1] / 1000.0
    cols = [np.ones_like(x)]
    if model != "translation":
        cols += [x, y]
    if model in ("quad_y", "quad"):
        cols += [y * y]
    if model == "quad":
        cols += [x * x, x * y]
    return np.stack(cols, axis=1)


class BlockMap:
    """Pemetaan posisi template -> posisi di gambar yang sudah diluruskan, untuk satu blok."""

    def __init__(self, model="translation", cx=None, cy=None, H=None):
        self.model, self.cx, self.cy, self.H = model, cx, cy, H

    @classmethod
    def translation(cls, dx, dy):
        return cls("translation", np.array([dx]), np.array([dy]))

    @classmethod
    def from_h(cls, H):
        return cls(H=H)

    def __call__(self, pts):
        pts = np.asarray(pts, float).reshape(-1, 2)
        if self.H is not None:
            return apply_h(self.H, pts)
        F = _features(pts, self.model)
        return pts + np.c_[F @ self.cx, F @ self.cy]

    def remap(self, canon):
        """Lengkungkan gambar supaya posisi template blok ini tepat di posisinya
        (dipakai saat membuat sidik jari)."""
        h, w = canon.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        q = np.c_[xx.ravel() - T.PAD, yy.ravel() - T.PAD]
        src = self(q) + T.PAD
        mx = src[:, 0].reshape(h, w).astype(np.float32)
        my = src[:, 1].reshape(h, w).astype(np.float32)
        return cv2.remap(canon, mx, my, cv2.INTER_LINEAR, borderValue=(255, 255, 255))


def _fit_field(src, dst, model):
    """Pasang model pergeseran halus ke pergeseran petak, buang petak menyimpang.

    Mengembalikan (BlockMap, porsi_petak_dipakai, selisih_rata2_px)."""
    d = dst - src
    keep = np.ones(len(src), bool)
    while True:
        F = _features(src, model)
        if keep.sum() >= F.shape[1] + 2 or model == "translation":
            break
        model = _FALLBACK[model]
    if len(src) == 0:
        return None, 0.0, 99.0
    for _ in range(4):
        F = _features(src, model)
        if keep.sum() < F.shape[1]:
            break
        cx, *_ = np.linalg.lstsq(F[keep], d[keep, 0], rcond=None)
        cy, *_ = np.linalg.lstsq(F[keep], d[keep, 1], rcond=None)
        r = np.hypot(F @ cx - d[:, 0], F @ cy - d[:, 1])
        new_keep = r < max(2.5, 2.5 * np.median(r[keep]))
        if (new_keep == keep).all() or new_keep.sum() < F.shape[1] + 1:
            break
        keep = new_keep
    bm = BlockMap(model, cx, cy)
    resid = float(r[keep].mean()) if keep.any() else 99.0
    return bm, float(keep.mean()), resid


def _subpixel(res, loc):
    """Perhalus puncak hasil matchTemplate dengan parabola (sumbu x dan y terpisah)."""
    x, y = loc
    out = [float(x), float(y)]
    for axis, (a, b, c) in enumerate((
            (res[y, x - 1], res[y, x], res[y, x + 1]) if 0 < x < res.shape[1] - 1 else (0, 0, 0),
            (res[y - 1, x], res[y, x], res[y + 1, x]) if 0 < y < res.shape[0] - 1 else (0, 0, 0))):
        den = a - 2 * b + c
        if den < 0:
            out[axis] += 0.5 * (a - c) / den
    return out


def _tile_fit(red, k, name, dx, dy, shape=None):
    """Penghalusan blok dengan sidik jari per petak.

    Tiap petak dicocokkan ke sidik jarinya di sekitar posisi blok
    (+-TILE_SEARCH); pergeseran petak-petak itu menjadi medan pergeseran blok.
    shape(y): tambahan pusat pencarian tegak menurut y template (pola lengkung kertas
    dari garis tepi kiri), supaya petak di ujung blok yang melengkung jauh tetap dicari
    di sekitar barisnya sendiri, bukan baris tetangga.
    Mengembalikan (BlockMap, porsi_petak_jelas, selisih_rata2_petak_px)."""
    ref = _load_ref(name)
    x0, y0, _, _ = block_bbox(k)
    h, w = ref.shape
    nx, ny = TILES[name]
    S = TILE_SEARCH
    m = S + 32
    padded = cv2.copyMakeBorder(red, m, m, m, m, cv2.BORDER_CONSTANT, value=0)
    src, dst = [], []
    total = 0
    for ix in range(nx):
        for iy in range(ny):
            tx0, tx1 = ix * w // nx, (ix + 1) * w // nx
            ty0, ty1 = iy * h // ny, (iy + 1) * h // ny
            tpl = ref[ty0:ty1, tx0:tx1]
            if tpl.std() < 4:
                continue
            total += 1
            c = np.array([x0 + (tx0 + tx1) / 2, y0 + (ty0 + ty1) / 2])
            dyt = dy + (int(round(float(shape(c[1])))) if shape is not None else 0)
            ax = x0 + T.PAD + tx0 + dx - S + m
            ay = y0 + T.PAD + ty0 + dyt - S + m
            if ay < 0 or ay + (ty1 - ty0) + 2 * S > padded.shape[0]:
                continue
            area = padded[ay: ay + (ty1 - ty0) + 2 * S, ax: ax + (tx1 - tx0) + 2 * S]
            res = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
            _, sc, _, loc = cv2.minMaxLoc(res)
            if sc < TILE_MIN_SCORE:
                continue
            fx, fy = _subpixel(res, loc)
            src.append(c)
            dst.append(c + (fx - S + dx, fy - S + dyt))
    src, dst = np.array(src, float).reshape(-1, 2), np.array(dst, float).reshape(-1, 2)
    bm, used, resid = _fit_field(src, dst, MODEL[name])
    if bm is None:
        return BlockMap.translation(dx, dy), 0.0, 99.0
    ratio = used * len(src) / max(total, 1)
    return bm, ratio, resid


def _fit_block(resp, pts, H0=None, wins=(10, 6, 4)):
    """Koreksi afine dari lingkaran merah (hanya dipakai saat membuat sidik jari).

    Mengembalikan (H 3x3, porsi bulatan cocok, selisih rata-rata piksel)."""
    H = np.eye(3) if H0 is None else H0
    ratio, res = 0.0, 99.0
    for win in wins:
        pred = apply_h(H, pts)
        found, val = _local_peaks(resp, pred, win)
        ref = np.median(val[val > 0]) if np.any(val > 0) else 0
        ok = val > 0.35 * ref
        if ok.sum() < 8:
            break
        A, inl = cv2.estimateAffine2D(pts[ok].astype(np.float32), found[ok].astype(np.float32),
                                      method=cv2.RANSAC, ransacReprojThreshold=2.0)
        if A is None:
            break
        H = np.vstack([A, [0, 0, 1]])
        inl = inl.ravel() > 0
        ratio = float(inl.sum() / len(pts))
        d = apply_h(H, pts[ok][inl]) - found[ok][inl]
        res = float(np.mean(np.hypot(d[:, 0], d[:, 1]))) if len(d) else 99.0
    return H, ratio, res


def _grid_index():
    """Posisi baris/kolom tiap bulatan di dalam bloknya (untuk mencari tetangga)."""
    rc = np.zeros((len(T.BUBBLES), 2), int)
    for idx, (g, i, v, _, _) in enumerate(T.BUBBLES):
        if g == "nama":
            rc[idx] = (T.LETTERS.index(v), i)
        elif g == "nomor":
            rc[idx] = (int(v), i)
        elif g == "kode":
            rc[idx] = (int(v), 6 + i)           # celah 1 kolom antara nomor dan kode
        elif g == "tanggal":
            rc[idx] = (int(v), i)
        else:
            rc[idx] = (i % 30, T.OPTIONS.index(v))
    return rc


GRID_RC = _grid_index()


def _row_dash_index():
    """Indeks garis tepi kiri yang sejajar dengan baris tiap bulatan."""
    out = np.zeros(len(T.BUBBLES), int)
    for idx, (g, i, v, _, _) in enumerate(T.BUBBLES):
        if g == "nama":
            out[idx] = 1 + T.LETTERS.index(v)
        elif g in ("nomor", "kode", "tanggal"):
            out[idx] = 1 + int(v)
        else:
            out[idx] = 27 + i % 30
    return out


ROW_DASH = _row_dash_index()
FINGERPRINT_MIN = {name: 0.35 for name in BLOCK_NAMES}   # di bawah ini pola blok dianggap tidak dikenali
FINGERPRINT_MIN.update({"nama": 0.45, "nomor-kode": 0.45, "tanggal": 0.45})
LOCAL_WIN = 8       # jendela pencarian lingkaran per bulatan (< setengah jarak antarbaris)
LOCAL_MAX = 12      # total geseran maksimum penyetelan lokal


def _local_refine(resp, bubble_xy):
    """Setel posisi tiap bulatan ke lingkaran merah cetaknya.

    Puncak lingkaran per bulatan dicari di +-LOCAL_WIN, lalu koreksinya
    diratakan dengan median koreksi bulatan tetangga (+-2 baris/kolom di blok
    yang sama) supaya bulatan yang samar/dihitamkan ikut terkoreksi dan derau
    tidak berpengaruh. Mengikuti lengkungan kertas apa pun bentuknya.
    Mengembalikan (posisi_baru, porsi_bulatan_terlihat, rata2_koreksi_px)."""
    found, val = _local_peaks(resp, bubble_xy, LOCAL_WIN)
    corr = found - bubble_xy
    good = np.zeros(len(bubble_xy), bool)
    for k in range(len(BLOCK_NAMES)):
        sel = BLOCK_INDEX == k
        ref = np.median(val[sel])
        good[sel] = val[sel] > 0.5 * ref
    out = bubble_xy.copy()
    applied = np.zeros(len(bubble_xy))
    for idx in range(len(bubble_xy)):
        k = BLOCK_INDEX[idx]
        r, c = GRID_RC[idx]
        for reach in (2, 4):
            nb = ((BLOCK_INDEX == k) & good
                  & (np.abs(GRID_RC[:, 0] - r) <= reach) & (np.abs(GRID_RC[:, 1] - c) <= reach))
            if nb.sum() >= 5:
                d = np.median(corr[nb], axis=0)
                out[idx] = bubble_xy[idx] + d
                applied[idx] = np.hypot(*d)
                break
    return out, float(good.mean()), applied


SHAPE_MIN = 4.0     # px: lengkung garis tepi sekecil ini tidak perlu dipakai untuk memusatkan petak
ROW_LOCK_MAX = 0.5  # x jarak baris: simpangan baris blok dari lengkung acuannya yang dianggap salah kunci
# Acuan lengkung tegak tiap blok jawaban = blok di sebelah kirinya (yang tidak tercantum: garis
# tepi kiri). Blok kepala tetap memakai garis tepi: blok nama yang salah pas (foto buram, 142834)
# justru menular ke nomor-kode bila dirantai.
REF_NEIGHBOR = {f"jawaban {30 * b + 1}-{30 * b + 30}": f"jawaban {30 * b - 29}-{30 * b}" for b in range(1, 6)}


def _track_deviation(bm, pts, ry):
    """Simpangan terbesar posisi tegak baris hasil pas terhadap pola garis tepi kiri
    (setelah selisih tetapnya dibuang). Baris yang 'terkunci' ke baris tetangga ~ 1 jarak baris."""
    d = (bm(pts) - pts)[:, 1] - ry
    return float(np.max(np.abs(d - np.median(d))))


def _fit_with_track(red, k, name, dx, dy, pts, ry):
    """Pas petak blok dua cara: pusat pencarian tetap (seluruh blok) dan pusat yang mengikuti
    lengkung garis tepi kiri. Kertas yang melengkung bisa menggeser ujung blok hampir satu
    baris; dengan pusat tetap petak di ujung itu terkunci ke baris tetangga. Dipilih hasil
    yang paling sejalan dengan pola garis tepi."""
    fit0 = _tile_fit(red, k, name, dx, dy)
    ys, inv = np.unique(pts[:, 1], return_inverse=True)
    ry_row = np.bincount(inv, weights=ry) / np.bincount(inv)
    shape_v = ry_row - np.median(ry)
    if np.max(np.abs(shape_v)) < SHAPE_MIN:
        return fit0
    fit1 = _tile_fit(red, k, name, dx, dy, shape=lambda y: np.interp(y, ys, shape_v))
    if fit1[1] < 0.5 * fit0[1]:
        return fit0
    dev0, dev1 = _track_deviation(fit0[0], pts, ry), _track_deviation(fit1[0], pts, ry)
    return fit1 if dev1 < dev0 else fit0


PICK_MARGIN = 0.15  # selisih minimal kecocokan pola blok supaya pilihan urutan garis tepi dianggap pasti
TRACK_ERR_MAX = 0.4   # batas median selisih garis tepi terhadap barisnya (x jarak antarbaris);
                      # 127 foto uji: lembar normal <= 6 px (0,2), urutan keliru ~70 px


def _pick_registration(work, regs, p0, direction, left):
    """Pilih urutan garis tepi yang seri dengan pola blok (sidik jari).

    Tiap kandidat diluruskan kasar (tahap awal pelurusan global), lalu
    dinilai dengan median kecocokan sidik jari semua blok. Urutan yang salah
    menggeser seluruh lembar beberapa baris, jadi polanya jelas tidak cocok.
    Mengembalikan (kandidat terurut terbaik dulu, pasti?)."""
    if not all(_load_ref(n) is not None for n in BLOCK_NAMES):
        return regs, False
    scored = []
    for pairs, par in regs:
        if len(pairs) < 10:
            scored.append(-1.0)
            continue
        M = _initial_transform(p0, direction, par)
        Hc = _global_fit(work, M, left, 12, pairs)
        if Hc is not None:
            M = M @ Hc
        red = ref_redness(warp_to_canon(work, M))
        scored.append(float(np.median([_match_block(red, k, n)[2] for k, n in enumerate(BLOCK_NAMES)])))
    order = np.argsort(scored)[::-1]
    best, second = scored[order[0]], scored[order[1]]
    sure = best >= min(FINGERPRINT_MIN.values()) and best - second >= PICK_MARGIN
    return [regs[i] for i in order], sure


@dataclass
class Aligned:
    work: np.ndarray            # gambar kerja tegak
    canon: np.ndarray           # gambar yang sudah diluruskan ke bingkai baku (dengan PAD)
    M: np.ndarray               # homografi bingkai baku -> gambar kerja
    bubble_xy: np.ndarray       # posisi tiap bulatan (urutan T.BUBBLES) di bingkai baku
    block_map: dict             # nama_blok -> BlockMap (template -> posisi sebenarnya)
    rotated_180: bool
    track_found: int
    track_matched: int
    block_quality: dict         # nama_blok -> (porsi_petak/bulatan, selisih_px, skor_sidik_jari)
    notes: list
    src_rot: object = None      # putaran 90 derajat foto asli -> gambar kerja (kode cv2.rotate)


def source_image(img, aligned):
    """Foto ASLI resolusi penuh, diputar searah gambar kerja."""
    src = img if aligned.src_rot is None else cv2.rotate(img, aligned.src_rot)
    return cv2.rotate(src, cv2.ROTATE_180) if aligned.rotated_180 else src


def render_view(img, aligned, k, src=None):
    """Bingkai lurus skala k (k=1 sama dengan canon) langsung dari foto ASLI resolusi penuh.

    Hanya untuk TAMPILAN (gambar cek, potongan tulisan tangan). Pembacaan bulatan tetap
    memakai `canon` dari gambar kerja. Foto diambil sampelnya ~1:1 lalu dikecilkan dengan
    INTER_AREA supaya tajam tanpa gerigi."""
    src = source_image(img, aligned) if src is None else src
    s = WORK_H / src.shape[0]                       # px gambar kerja per px foto asli
    A = np.array([[s, 0, 0.5 * s - 0.5], [0, s, 0.5 * s - 0.5], [0, 0, 1]])   # foto asli -> gambar kerja
    P = np.array([[1, 0, T.PAD], [0, 1, T.PAD], [0, 0, 1]], float)
    kw = max(k, 1.0 / s)
    big = cv2.warpPerspective(src, np.diag([kw, kw, 1.0]) @ P @ np.linalg.inv(aligned.M) @ A, frame_size(kw),
                              flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
    return big if kw == k else cv2.resize(big, frame_size(k), interpolation=cv2.INTER_AREA)


def frame_size(k):
    """(lebar, tinggi) bingkai lurus (dengan PAD) pada skala k."""
    return int(round((T.CANON_W + 2 * T.PAD) * k)), int(round((T.CANON_H + 2 * T.PAD) * k))


def align(img, seed=0):
    rng = np.random.default_rng(seed)
    work, flipped, D, src_rot = _orient(img, rng, with_rot=True)
    regs, p0, direction = _register_track(D)
    notes = []
    allp = np.array([(b[3], b[4]) for b in T.BUBBLES])
    left = allp[allp[:, 0] < LEFT_LIMIT]      # tahap awal: hanya bulatan dekat garis tepi
    if len(regs) > 1:
        regs, sure = _pick_registration(work, regs, p0, direction, left)
        if not sure:
            notes.append("urutan garis tepi kiri ambigu")
    pairs, par = regs[0]
    if len(pairs) < 10:
        raise AlignError(f"Garis tepi kiri terlalu sedikit yang terbaca ({len(pairs)} dari 57)")
    M = _initial_transform(p0, direction, par)

    # Penghalusan global bertahap: mulai dari bulatan dekat garis tepi, lalu seluruh lembar.
    for pts, win in ((left, 12), (allp, 12), (allp, 7)):
        Hc = _global_fit(work, M, pts, win, pairs)
        if Hc is None:
            raise AlignError("Bulatan cetak tidak cukup terlihat untuk meluruskan foto")
        M = M @ Hc

    canon = warp_to_canon(work, M)
    resp = ring_response(canon)
    red = ref_redness(canon)
    bubble_xy = allp.copy()
    block_map, quality = {}, {}
    # Selisih tegak tiap baris menurut garis tepi kiri (urutannya sudah pasti),
    # dipakai bila pola blok tidak dikenali (mis. tinta merah pudar karena bayangan).
    dj = np.array([j for j, _ in pairs])
    dpts = apply_h(np.linalg.inv(M), [p for _, p in pairs])
    dres = dpts[:, 1] - np.array(T.TIMING_Y)[dj]
    row_dy = np.interp(np.arange(len(T.TIMING_Y)), dj, dres)
    # Pengaman: garis tepi yang sudah dipasangkan harus jatuh di barisnya setelah
    # pelurusan. Selisih besar = urutan garis tepi atau pelurusan keliru, sehingga
    # bulatan bisa terbaca bergeser baris walau tampak pas di lingkaran cetak.
    track_err = float(np.median(np.abs(dres)))
    if track_err > TRACK_ERR_MAX * _TPITCH:
        notes.append(f"garis tepi kiri tidak cocok dengan posisi baris (selisih {track_err:.0f} px); "
                     "jawaban mungkin bergeser baris, perlu dicek")
    fixed = np.zeros(len(allp), bool)      # bulatan yang posisinya diambil dari garis tepi
    shapes, refs = {}, {}                  # pola tegak per baris tiap blok; acuan tiap blok
    for k, name in enumerate(BLOCK_NAMES):
        sel = BLOCK_INDEX == k
        # Acuan posisi tegak tiap baris: blok paling kiri memakai garis tepi kiri, blok lain
        # memakai blok di sebelah kirinya (lengkung kertas berubah perlahan dari kiri ke kanan).
        prev = REF_NEIGHBOR.get(name)
        if prev in shapes:
            ry = np.interp(allp[sel][:, 1], *shapes[prev])
        else:
            ry = row_dy[ROW_DASH[sel]]
        refs[name] = ry
        m = _match_block(red, k, name)
        if m is None:
            # Belum ada sidik jari (hanya saat membuat acuan): pakai lingkaran merah.
            H, ratio, res = _fit_block(resp, allp[sel])
            bm, score = BlockMap.from_h(H), None
            bubble_xy[sel] = bm(allp[sel])
        else:
            dx, dy, score, second = m
            if score < FINGERPRINT_MIN[name]:
                hx = _match_block(red, k, name, search=(28, 2), center=(0, float(np.median(ry))))
                gx = hx[0] if hx is not None and hx[2] >= 0.2 else 0.0
                # 1) Petak-petak kecil dengan pusat dari garis tepi (menangkap skala/lengkung).
                bm_t, ratio_t, res_t = _fit_with_track(red, k, name, int(round(gx)), int(round(float(np.median(ry)))),
                                                       allp[sel], ry)
                pos_t = bm_t(allp[sel])
                drift = np.abs((pos_t - allp[sel])[:, 1] - ry)       # beda dengan baris garis tepi
                # Semua baris (bukan hanya rata-ratanya) harus dekat barisnya menurut garis tepi:
                # satu ujung blok yang terkunci ke baris tetangga sudah cukup untuk salah baca.
                if ratio_t >= 0.5 and res_t <= 3.0 and np.max(drift) < 0.4 * _TPITCH:
                    notes.append(f"{name}: pola blok lemah (kecocokan {score:.2f}); posisi dari petak + garis tepi")
                    bm, ratio, res = bm_t, ratio_t, res_t
                    bubble_xy[sel] = pos_t
                else:
                    # 2) Posisi tegak tiap baris dari acuannya (garis tepi kiri / blok sebelah kiri),
                    #    mendatar dari geser samping.
                    notes.append(f"{name}: pola blok sulit dikenali (kecocokan {score:.2f}); "
                                 "posisi baris diambil dari garis tepi kiri")
                    shift = np.c_[np.full(sel.sum(), float(gx)), ry]
                    bubble_xy[sel] = allp[sel] + shift
                    bm, ratio, res = BlockMap.translation(float(gx), float(np.median(ry))), 0.0, 99.0
                    fixed |= sel
            else:
                bm, ratio, res = _fit_with_track(red, k, name, dx, dy, allp[sel], ry)
                bubble_xy[sel] = bm(allp[sel])
        ys_t, inv = np.unique(allp[sel][:, 1], return_inverse=True)
        dyb = (bubble_xy[sel] - allp[sel])[:, 1]
        shapes[name] = (ys_t, np.bincount(inv, weights=dyb) / np.bincount(inv))
        block_map[name] = bm
        quality[name] = (ratio, res, score)
    quality["garis tepi"] = (len(pairs) / len(T.TIMING_Y), track_err, None)

    if all(_load_ref(n) is not None for n in BLOCK_NAMES):
        # Diulang: tiap putaran bulatan bergerak (maks. LOCAL_WIN) ke lingkaran
        # terdekat, jadi lengkungan yang lebih besar dari jendela tetap terkejar.
        start = bubble_xy.copy()
        bubble_xy, seen, applied = _local_refine(resp, bubble_xy)
        # Bulatan yang koreksinya mentok di batas jendela masih perlu bergeser
        # lebih jauh (kertas sangat melengkung): ulangi hanya untuk bulatan itu.
        # Yang lain tidak diulang supaya tidak terseret garis kotak di dekatnya.
        moving = applied >= 0.75 * LOCAL_WIN
        for _ in range(3):
            if not moving.any():
                break
            nxt, _, applied2 = _local_refine(resp, bubble_xy)
            bubble_xy[moving] = nxt[moving]
            moving = moving & (applied2 >= 0.75 * LOCAL_WIN)
        # Batasi total geseran supaya tidak bisa merambat ke baris tetangga.
        d = bubble_xy - start
        n = np.hypot(*d.T)
        over = n > LOCAL_MAX
        bubble_xy[over] = start[over] + d[over] * (LOCAL_MAX / n[over])[:, None]
        # Blok yang polanya tidak dikenali: sinyal lingkaran terlalu lemah, jangan disetel.
        bubble_xy[fixed] = start[fixed]
        total = float(np.mean(np.hypot(*(bubble_xy - start).T)))
        quality["setel lokal"] = (seen, total, None)
        if seen < 0.3:
            notes.append(f"lingkaran cetak hanya terlihat di {seen:.0%} bulatan, foto mungkin terlalu buram")
        # Pemeriksaan akhir: pergeseran sistematis posisi bulatan terhadap
        # lingkaran cetak, per paruh atas/bawah tiap blok (getaran acak tiap
        # titik +-2 px tidak dihitung, hanya median pergeseran berarahnya).
        found, val = _local_peaks(resp, bubble_xy, 5)
        d = found - bubble_xy
        for k, name in enumerate(BLOCK_NAMES):
            sel = BLOCK_INDEX == k
            good = sel & (val > 0.5 * np.median(val[sel]))
            ys = bubble_xy[:, 1]
            mid = np.median(ys[sel])
            worst = 0.0
            for half in (good & (ys <= mid), good & (ys > mid)):
                if half.sum() >= 5:
                    worst = max(worst, float(np.hypot(*np.median(d[half], axis=0))))
            # Baris yang terkunci ke baris tetangga tampak pas di lingkaran cetak (polanya
            # berulang), tetapi tidak sejalan dengan lengkung garis tepi kiri.
            dv = (bubble_xy[sel] - allp[sel])[:, 1] - refs[name]
            ys_t, inv = np.unique(allp[sel][:, 1], return_inverse=True)
            per_row = np.bincount(inv, weights=dv) / np.bincount(inv)
            lock = float(np.max(np.abs(per_row - np.median(per_row))))
            quality[name] = quality[name] + (worst, lock)
            if worst > 2.5:
                notes.append(f"{name}: posisi bulatan belum pas (bergeser {worst:.1f} px), perlu dicek")
            if lock > ROW_LOCK_MAX * _TPITCH:
                notes.append(f"{name}: posisi baris tidak sejalan dengan garis tepi kiri (selisih {lock:.0f} px); "
                             "jawaban mungkin terbaca dari baris tetangga, perlu dicek")

    return Aligned(
        work=work, canon=canon, M=M, bubble_xy=bubble_xy, block_map=block_map,
        rotated_180=flipped, track_found=len(D), track_matched=len(pairs),
        block_quality=quality, notes=notes, src_rot=src_rot,
    )
