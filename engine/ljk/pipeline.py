"""Satu foto LJK -> hasil baca + gambar cek visual + potongan tulisan tangan."""
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import align as AL
from . import belajar as BL
from . import omr as OM
from . import tampilan as TP
from . import template as T

CROP_SCALE = 2.0      # skala potongan tulisan tangan (2 = ~resolusi foto asli)


@dataclass
class SheetResult:
    path: Path
    error: str = ""                      # diisi bila foto gagal diluruskan
    read: OM.SheetRead = None
    aligned: AL.Aligned = None
    notes: list = field(default_factory=list)   # catatan pelurusan/kualitas foto
    model: str = None                    # versi model juri kedua yang dipakai, None bila tanpa model
    image: object = field(default=None, repr=False)     # foto asli (hanya untuk membuat gambar tampilan)
    _source: object = field(default=None, repr=False)

    def source(self):
        """Foto asli resolusi penuh yang sudah diputar searah gambar kerja (dibuat sekali)."""
        if self._source is None:
            self._source = AL.source_image(self.image, self.aligned)
        return self._source

    @property
    def issues(self):
        out = [n for n in self.notes if not T.is_noncritical_note(n)]
        if self.read is not None:
            out += self.read.issues
        return out

    @property
    def status(self):
        if self.error:
            return "Gagal"
        return "Perlu cek" if self.issues else "OK"


def _center_check(read, block_index):
    """Isian pensil seharusnya di tengah bulatan. Kalau di satu blok semua
    isian bergeser ke arah yang sama, kemungkinan pelurusan meleset."""
    notes = []
    filled = read.scores >= OM.T_TERISI
    for k, name in enumerate(AL.BLOCK_NAMES):
        sel = filled & (block_index == k)
        if sel.sum() >= 3:
            dx, dy = np.median(read.offsets[sel], axis=0)
            if np.hypot(dx, dy) > 4:
                notes.append(f"{name}: isian rata-rata bergeser ({dx:+.0f},{dy:+.0f}) px dari tengah bulatan, "
                             "pelurusan mungkin meleset")
    return notes


def process(path, keep_image=False):
    """Baca satu foto. keep_image: simpan foto asli di hasil supaya gambar cek & potongan
    tulisan tangan bisa dibuat dari resolusi penuh (pembacaan sendiri tidak memakainya)."""
    path = Path(path)
    res = SheetResult(path=path)
    try:
        img = AL.load_image(path)
        a = AL.align(img)
    except AL.AlignError as e:
        res.error = str(e)
        return res
    res.aligned = a
    res.notes = list(a.notes)
    # Model juri kedua (hanya bila ada model yang lulus ujian; tanpa itu pembacaan tetap sama).
    model = BL.active_model()
    prob = model.prob(a.canon, a.bubble_xy) if model is not None else None
    res.read = OM.read_sheet(a.canon, a.bubble_xy, AL.BLOCK_INDEX, prob,
                             putus_ragu=model is not None and model.putus_ragu)
    res.model = model.versi if model is not None else None
    res.notes += _center_check(res.read, AL.BLOCK_INDEX)
    if keep_image:
        res.image = img
    return res


# ------------------------------------------------------------- cek visual

GREEN, ORANGE, RED, GRAY = (40, 170, 40), (0, 140, 255), (0, 0, 230), (170, 170, 170)


def overlay(res, scale=0.75):
    """Gambar lembar yang sudah diluruskan dengan tanda hasil baca:
    hijau = terisi & dipakai, oranye = ragu, merah = lebih dari satu terisi,
    abu-abu tipis = posisi bulatan kosong.

    Bila foto asli tersedia (process(..., keep_image=True)), latar dibuat dari foto asli
    resolusi penuh dan dipertajam di luar bulatan (tampilan.sheet_view); isi bulatan tetap
    piksel foto asli. Tanda dilingkari di sekeliling bulatan, tidak menutupi isiannya."""
    a, r = res.aligned, res.read
    if res.image is not None:
        vis = TP.sheet_view(res.image, a, scale, res.source())
    elif scale != 1:
        vis = cv2.resize(a.canon, AL.frame_size(scale), interpolation=cv2.INTER_AREA)
    else:
        vis = a.canon.copy()

    def rad(extra):
        return max(1, int(round((T.BUBBLE_R + extra) * scale)))

    def thick(t):
        return max(1, int(round(t * scale)))

    groups = dict(r.header_groups)
    for q, g in enumerate(r.answer_groups):
        groups[("jawaban", q)] = g
    for idx, (g, i, v, _, _) in enumerate(T.BUBBLES):
        x, y = a.bubble_xy[idx]
        c = (int(round((x + T.PAD) * scale)), int(round((y + T.PAD) * scale)))
        st = OM.status_of(r.scores[idx])
        gr = groups[(g, i)]
        guess = OM.guess_of(gr)
        if gr.kind == "ok" and v == gr.value:
            cv2.circle(vis, c, rad(2), GREEN, thick(2), cv2.LINE_AA)          # pilihan yang dipakai
        elif gr.kind == "ragu" and v == guess:
            cv2.circle(vis, c, rad(2), ORANGE, thick(2), cv2.LINE_AA)         # tebakan untuk dicek
        elif st == OM.TERISI:
            cv2.circle(vis, c, rad(2), RED if gr.kind == "ganda" else ORANGE, thick(2), cv2.LINE_AA)
        elif st == OM.RAGU:
            cv2.circle(vis, c, rad(1), ORANGE, thick(1), cv2.LINE_AA)         # bekas samar
        else:
            cv2.circle(vis, c, rad(0), GRAY, thick(1), cv2.LINE_AA)
    head = [
        f"{res.path.name}  [{res.status}]",
        f"Nama: {r.nama}   No: {r.nomor}   Kode: {r.kode}   Tgl: {r.tanggal}",
    ]
    bar = np.full((int(round(70 * scale)), vis.shape[1], 3), 255, np.uint8)
    for j, t in enumerate(head):
        cv2.putText(bar, t, (int(10 * scale), int((28 + 30 * j) * scale)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.75 * scale, (0, 0, 0), thick(2), cv2.LINE_AA)
    return np.vstack([bar, vis])


# ------------------------------------------------- potongan tulisan tangan

def _crop(img, aligned, bmap, box, k=1.0, margin=6):
    """Potong kotak template `box` (dikoreksi peta blok) dari bingkai skala k. Sisi bawah
    dijauhkan dari lingkaran lindung bulatan supaya potongan boleh diolah tanpa menyentuh bulatan."""
    x0, y0, x1, y1 = box
    corners = bmap([(x0, y0), (x1, y0), (x0, y1), (x1, y1)])
    xa, ya = corners.min(axis=0) - margin
    xb, yb = corners.max(axis=0) + margin
    xa, ya, xb, yb = TP.clear_of_bubbles(aligned, (xa, ya, xb, yb))
    xa, ya = int(max((xa + T.PAD) * k, 0)), int(max((ya + T.PAD) * k, 0))
    xb, yb = int(min((xb + T.PAD) * k, img.shape[1])), int(min((yb + T.PAD) * k, img.shape[0]))
    return img[ya:yb, xa:xb].copy()


def handwriting_crops(res, k=CROP_SCALE):
    """Potongan gambar area tulisan tangan (untuk konfirmasi & ICR nanti).

    Bila foto asli tersedia: dipotong dari foto asli resolusi penuh (skala k) lalu diperjelas
    (kertas diratakan, kontras & ketajaman dinaikkan). Potongan tidak memuat bulatan."""
    a = res.aligned
    if res.image is not None:
        img = TP.text_view(res.image, a, k, res.source())
    else:
        img, k = a.canon, 1.0
    Ha, Hn, Ht = a.block_map["nomor-kode"], a.block_map["nama"], a.block_map["tanggal"]
    out = {name: _crop(img, a, Ha, box, k) for name, box in T.HANDWRITING_BOXES.items()}
    w = T.CHAR_BOX_W / 2
    out["kotak_nama"] = _crop(img, a, Hn, (T.NAME_COLS_X[0] - w, T.NAME_BOX_Y[0],
                                           T.NAME_COLS_X[-1] + w, T.NAME_BOX_Y[1]), k)
    out["kotak_nomor"] = _crop(img, a, Ha, (T.NOMOR_COLS_X[0] - w, T.NOMOR_BOX_Y[0],
                                            T.NOMOR_COLS_X[-1] + w, T.NOMOR_BOX_Y[1]), k)
    out["kotak_kode"] = _crop(img, a, Ha, (T.KODE_COLS_X[0] - w, T.KODE_BOX_Y[0],
                                           T.KODE_COLS_X[-1] + w, T.KODE_BOX_Y[1]), k)
    out["kotak_tanggal"] = _crop(img, a, Ht, (T.TANGGAL_COLS[0][0] - w, T.TANGGAL_BOX_Y[0],
                                              T.TANGGAL_COLS[-1][0] + w, T.TANGGAL_BOX_Y[1]), k)
    # Potongan bisa kosong bila areanya jatuh di luar foto (mis. block_map dari pola blok yang lemah);
    # potongan seperti itu dilewati, jangan sampai membuat seluruh lembar gagal diproses.
    out = {name: c for name, c in out.items() if c is not None and c.size and min(c.shape[:2]) >= 4}
    if res.image is not None:
        out = {name: TP.enhance_text(c, k) for name, c in out.items()}
    return out
