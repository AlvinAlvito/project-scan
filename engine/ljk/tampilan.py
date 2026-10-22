"""Gambar untuk DILIHAT pemeriksa: gambar cek lembar dan potongan tulisan tangan.

Pembacaan bulatan & nilai TIDAK memakai gambar ini (tetap dari `canon` gambar kerja), jadi
peningkatan kualitas di sini tidak bisa mengubah hasil baca. Gambar dibuat langsung dari foto
asli resolusi penuh (sebelumnya dari gambar kerja yang sudah diperkecil 2x), lalu dipertajam
pada kecerahannya saja (warna tinta merah tidak diubah).

Di dalam setiap bulatan (lingkaran lindung LINDUNG_R) piksel foto asli disalin apa adanya:
isian pensil, bekas hapusan, dan isian mengilap tampil persis seperti difoto. Di luar lingkaran
itu ada transisi halus TEPI_LEMBUT supaya tidak tampak tambalan.
"""
import cv2
import numpy as np

from . import align as AL
from . import template as T

LINDUNG_R = 14.0            # px canon: bulatan (jari-jari 10) + isian yang meluber keluar garis: tidak diolah
TEPI_LEMBUT = 3.0           # px canon: lebar transisi dari piksel asli ke piksel olahan
# Penajaman gambar cek: unsharp mask yang hasilnya dijepit ke terang/gelap setempat foto
# (tepi lebih curam tanpa lingkar halo), derau sangat kecil tidak ikut diperkuat (coring).
TAJAM_LEMBAR = {"sigma": 2.0, "kekuatan": 1.5, "jepit_r": 1.0, "coring": 1.5}
# Potongan tulisan tangan (tidak memuat bulatan): kertas diratakan, derau diredam,
# goresan pensil tipis dipertegas (titik hitam), lalu dipertajam ringan.
TULISAN = {"titik_hitam": 0.5, "kertas": 245.0, "sigma": 1.0, "kekuatan": 0.8}


def bubble_mask(aligned, k):
    """1.0 persis di dalam lingkaran lindung tiap bulatan, turun ke 0 sejauh TEPI_LEMBUT di luarnya."""
    W, H = AL.frame_size(k)
    free = np.full((H, W), 255, np.uint8)
    r = int(np.ceil(LINDUNG_R * k))
    for x, y in aligned.bubble_xy:
        cv2.circle(free, (int(round((x + T.PAD) * k)), int(round((y + T.PAD) * k))), r, 0, -1)
    dist = cv2.distanceTransform(free, cv2.DIST_L2, 5)      # jarak ke lingkaran lindung terdekat
    return np.clip(1.0 - dist / (TEPI_LEMBUT * k), 0.0, 1.0).astype(np.float32)


def _luma(img):
    f = img.astype(np.float32)
    return 0.114 * f[:, :, 0] + 0.587 * f[:, :, 1] + 0.299 * f[:, :, 2]


def _add_luma(img, dy):
    """Tambahkan perubahan kecerahan yang sama ke B, G, R (warna tinta tetap)."""
    return np.clip(img.astype(np.float32) + dy[:, :, None] + 0.5, 0, 255).astype(np.uint8)


def sharpen(img, k, sigma, kekuatan, jepit_r, coring):
    """Unsharp mask pada kecerahan, dijepit ke rentang terang/gelap setempat (tanpa halo)."""
    y = _luma(img)
    hp = y - cv2.GaussianBlur(y, (0, 0), sigma * k)
    hp = np.sign(hp) * np.maximum(np.abs(hp) - coring, 0.0)
    y2 = y + kekuatan * hp
    d = max(1, int(round(jepit_r * k)))
    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * d + 1, 2 * d + 1))
    y2 = np.minimum(np.maximum(y2, cv2.erode(y, ker)), cv2.dilate(y, ker))
    return _add_luma(img, y2 - y)


def protect(enhanced, raw, mask):
    """Piksel asli di dalam masker (bulatan) -- disalin persis --, hasil olahan di luar."""
    m = mask[:, :, None]
    out = (raw.astype(np.float32) * m + enhanced.astype(np.float32) * (1.0 - m) + 0.5).astype(np.uint8)
    inner = mask >= 1.0
    out[inner] = raw[inner]
    return out


def sheet_view(img, aligned, k, src=None):
    """Gambar cek lembar pada skala k: dari foto asli, dipertajam di luar bulatan."""
    raw = AL.render_view(img, aligned, k, src)
    return protect(sharpen(raw, k, **TAJAM_LEMBAR), raw, bubble_mask(aligned, k))


def text_view(img, aligned, k, src=None):
    """Bingkai skala k dari foto asli untuk dipotong-potong (tulisan tangan). Belum diolah."""
    return AL.render_view(img, aligned, k, src)


def clear_of_bubbles(aligned, rect):
    """Kecilkan sisi bawah kotak (px canon, tanpa PAD) supaya tidak menyentuh lingkaran lindung
    bulatan mana pun. Potongan tulisan tangan lalu boleh diolah bebas."""
    x0, y0, x1, y1 = rect
    for x, y in aligned.bubble_xy:
        if x + LINDUNG_R > x0 and x - LINDUNG_R < x1:
            top = y - LINDUNG_R
            if y0 < top < y1:
                y1 = top
    return x0, y0, x1, y1


# Tampilan hitam-putih ala scanner OMR (layar Cek Manual), dibuat dari gambar cek (lembar.jpg):
# - tinta (pensil, pulpen, cetakan hitam: abu-abu netral) diukur di kanal merah relatif terhadap terang
#   kertas setempat, dikali faktor kontras lembar (normalisasi yang sama dengan pembacaan); di atas
#   ambang -> hitam,
# - cetakan merah LJK (lingkaran, huruf; merah muda: R jauh di atas G) -> abu-abu muda, supaya letak
#   bulatan tetap terlihat tanpa menyerupai isian,
# - tanda hasil baca berwarna (hijau/oranye/merah) dipertahankan.
# Kontras 0-100: makin tinggi, makin banyak goresan tipis yang menjadi hitam. HANYA tampilan.
BW_STANDAR = 50
BW_AMBANG = (0.40, 0.10)        # ambang kegelapan tinta pada kontras 0 dan 100 (standar 50: 0,25)
BW_LEMBUT = 0.06                # lebar transisi tepi (anti-gerigi; goresan sangat samar tampak abu-abu)
BW_CETAK = (0.10, 0.25, 200)    # kegelapan cetakan merah (kanal hijau): mulai, penuh, abu-abu tujuan
BW_MERAH = (12.0, 32.0)         # R - G: di bawah ini tinta netral, di atas ini cetakan merah murni
# Di dalam bulatan, kegelapan tiap piksel paling sedikit rata-rata kegelapan bulatan itu (seperti mesin
# baca menilai satu bulatan), jadi isian bertekstur/mengilap tampil padat, sedangkan bulatan kosong (huruf
# cetak tipis) dan bekas hapusan tetap terang. Menutup lubang secara morfologi justru menggumpalkan huruf.


def _paper(ch, abaikan):
    """Terang kertas setempat: maksimum lokal (goresan, isian, bar hitam hilang), dihaluskan. Piksel
    `abaikan` (tanda berwarna yang lebih terang dari kertas di kanal merah) dan titik silau (median)
    tidak ikut. Di 1/4 resolusi; jendela ~124 px lebih lebar dari bulatan dan bar hitam di gambar cek."""
    ch = np.where(abaikan, 0.0, ch).astype(np.float32)
    small = cv2.resize(ch, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    small = cv2.medianBlur(small, 5)
    small = cv2.GaussianBlur(cv2.dilate(small, cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31))), (0, 0), 8)
    return np.maximum(cv2.resize(small, (ch.shape[1], ch.shape[0]), interpolation=cv2.INTER_LINEAR), 1.0)


def bw_prepare(img, faktor=1.0, centers=None, radius=0.0, ukur=0.0):
    """Bahan tampilan hitam-putih (sekali per gambar; bw_render cepat diulang saat kontras digeser).
    centers: pusat bulatan (px gambar); radius: bagian dalam bulatan yang diratakan; ukur: radius
    tempat rata-rata kegelapan diukur (sama dengan area ukur mesin baca)."""
    f = img.astype(np.float32)
    b, g, r = f[:, :, 0], f[:, :, 1], f[:, :, 2]
    # tanda hasil baca: hijau, atau oranye/merah murni (biru rendah; cetakan merah LJK berbiru tinggi)
    tanda = (g - np.maximum(r, b) > 50) | ((r > 170) & (b < 90) & (r - b > 120))
    tanda = cv2.dilate(tanda.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0     # tepi halus tanda ikut
    netral = np.clip((BW_MERAH[1] - (r - g)) / (BW_MERAH[1] - BW_MERAH[0]), 0.0, 1.0)   # 1 = bukan merah muda
    tinta = np.clip(1.0 - r / _paper(r, tanda), 0.0, 1.0) * netral * np.float32(faktor)
    if centers is not None and len(centers):
        u = max(1, int(round(ukur or radius)))
        disk = (np.hypot(*np.mgrid[-u:u + 1, -u:u + 1]) <= u).astype(np.float32)
        rata = cv2.filter2D(tinta, -1, disk / disk.sum(), borderType=cv2.BORDER_CONSTANT)
        isi = np.zeros_like(tinta)
        h, w = tinta.shape
        for x, y in centers:
            cx, cy = int(round(x)), int(round(y))
            if 0 <= cx < w and 0 <= cy < h:
                cv2.circle(isi, (cx, cy), max(1, int(round(radius))), float(rata[cy, cx]), -1)
        tinta = np.maximum(tinta, isi)
    tinta = cv2.GaussianBlur(tinta, (0, 0), 0.8)                                  # derau piksel
    cetak = np.clip(1.0 - g / _paper(g, tanda), 0.0, 1.0)
    return {"img": img, "tinta": tinta, "cetak": cetak, "tanda": tanda, "faktor": float(faktor)}


def bw_render(prep, kontras=BW_STANDAR):
    """Gambar BGR hitam-putih dari bw_prepare pada kontras 0-100."""
    t = BW_AMBANG[0] + (BW_AMBANG[1] - BW_AMBANG[0]) * float(np.clip(kontras, 0, 100)) / 100.0
    putih = np.clip((t - prep["tinta"]) / BW_LEMBUT + 0.5, 0.0, 1.0)           # 1 putih .. 0 hitam
    c0, c1, abu = BW_CETAK
    putih = np.minimum(putih, 1.0 - (1.0 - abu / 255.0) * np.clip((prep["cetak"] - c0) / (c1 - c0), 0.0, 1.0))
    out = cv2.cvtColor((putih * 255.0 + 0.5).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    out[prep["tanda"]] = prep["img"][prep["tanda"]]
    return out


def enhance_text(crop, k):
    """Potongan tulisan tangan: kertas diratakan (bayangan hilang), derau diredam, goresan
    pensil tipis dipertegas, lalu dipertajam ringan. Dipakai hanya pada potongan tanpa bulatan."""
    p = TULISAN
    y = _luma(crop)
    size = max(3, int(round(7 * k)) | 1)
    paper = cv2.dilate(y, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))   # coretan hilang
    paper = cv2.GaussianBlur(paper, (0, 0), 6 * k)
    t = (y / np.maximum(paper, 1.0)).astype(np.float32)                 # 1 = kertas
    t = cv2.bilateralFilter(t, d=int(2 * round(1.5 * k) + 1), sigmaColor=0.05, sigmaSpace=0.75 * k)
    t = np.clip((np.minimum(t, 1.0) - p["titik_hitam"]) / (1.0 - p["titik_hitam"]), 0.0, 1.0)
    y2 = p["kertas"] * t
    y2 = y2 + p["kekuatan"] * (y2 - cv2.GaussianBlur(y2, (0, 0), p["sigma"] * k))
    return _add_luma(crop, y2 - y)
