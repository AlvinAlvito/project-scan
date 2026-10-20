"""Geometri LJK POSI dalam bingkai baku.

Bingkai baku ditentukan oleh pusat 4 kotak hitam di sudut kertas:
kiri-atas = (0, 0), kanan-atas = (1400, 0), kiri-bawah = (0, 2000),
kanan-bawah = (1400, 2000). Semua angka di sini diukur dari foto sampel
yang sudah diluruskan (rata-rata beberapa lembar).
"""

CANON_W = 1400
CANON_H = 2000
PAD = 60  # margin di sekeliling bingkai saat gambar diluruskan

BUBBLE_R = 10      # jari-jari lingkaran bulatan
FILL_R = 6         # jari-jari area yang diukur kegelapannya

CORNERS = [(0.0, 0.0), (CANON_W, 0.0), (0.0, CANON_H), (CANON_W, CANON_H)]

# Garis hitam tepi kiri: 1 garis atas, 26 garis baris nama (A-Z),
# 30 garis baris jawaban. Semuanya di x = TIMING_X.
TIMING_X = -8.0
TIMING_Y = [
    40.3, 131.5, 162.3, 192.9, 223.8, 254.7, 285.8, 317.2, 348.7, 380.1,
    411.6, 443.2, 474.8, 506.5, 538.5, 570.3, 602.2, 633.8, 665.6, 697.4,
    729.1, 761.2, 793.2, 825.2, 856.7, 888.5, 920.2, 1048.1, 1079.5, 1111.1,
    1143.0, 1175.1, 1207.0, 1239.0, 1270.8, 1302.7, 1334.5, 1366.2, 1398.3,
    1430.2, 1462.0, 1493.8, 1525.2, 1557.0, 1588.2, 1620.0, 1651.2, 1682.5,
    1713.6, 1744.5, 1775.3, 1806.0, 1836.5, 1867.4, 1897.9, 1928.6, 1959.5,
]
NAME_ROWS_Y = TIMING_Y[1:27]       # baris huruf A..Z
DIGIT_ROWS_Y = NAME_ROWS_Y[:10]    # baris angka 0..9 sejajar dengan A..J
ANSWER_ROWS_Y = TIMING_Y[27:57]    # baris soal ke-1..30 di setiap blok

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
OPTIONS = "ABCDE"

NAME_COLS_X = [
    75.7, 108.6, 140.1, 172.2, 204.0, 235.5, 267.3, 298.5, 330.6, 362.1,
    393.8, 425.4, 457.2, 488.7, 520.5, 552.3, 583.6, 615.1, 646.5,
]
NOMOR_COLS_X = [932.1, 964.0, 996.0, 1027.6, 1059.0]
KODE_COLS_X = [1123.3, 1154.2, 1185.3]
# Tanggal: (x, angka terbesar) — Tgl digit 1 hanya 0-3, Bln digit 1 hanya 0-1.
TANGGAL_COLS = [
    (1249.0, 3), (1281.0, 9),   # Tgl
    (1310.5, 1), (1344.2, 9),   # Bln
    (1377.2, 9), (1406.5, 9),   # Thn
]
# 6 blok x 5 pilihan (A-E); blok b berisi soal 30*b+1 .. 30*b+30.
ANSWER_COLS_X = [
    [138.5, 170.1, 201.8, 233.5, 265.3],
    [360.9, 392.8, 424.5, 456.4, 488.2],
    [583.5, 615.1, 646.9, 678.6, 710.2],
    [805.4, 837.1, 868.8, 900.6, 932.4],
    [1027.7, 1059.6, 1090.9, 1122.5, 1154.1],
    [1250.4, 1282.3, 1314.1, 1345.9, 1377.7],
]
N_QUESTIONS = 180

# Area tulisan tangan (x0, y0, x1, y1). Disimpan sebagai potongan gambar
# untuk dicek manual dan untuk ICR di tahap berikutnya.
HANDWRITING_BOXES = {
    "bidang": (695, 440, 1430, 494),
    "sekolah": (695, 501, 1430, 556),
    "kelas": (695, 562, 1430, 614),
    "hp": (695, 619, 1430, 672),
}
# Kotak huruf/angka tulisan tangan di atas bulatan (untuk ICR kotak nanti).
NAME_BOX_Y = (50, 84)
NOMOR_BOX_Y = (50, 82)
KODE_BOX_Y = (88, 117)
TANGGAL_BOX_Y = (88, 117)
CHAR_BOX_W = 31.7


def all_bubbles():
    """Daftar semua bulatan: (grup, indeks_grup, nilai, x, y).

    grup: 'nama', 'nomor', 'kode', 'tanggal', 'jawaban'.
    indeks_grup: kolom ke-berapa (nama/nomor/kode/tanggal) atau nomor soal-1.
    nilai: huruf/angka yang diwakili bulatan itu.
    """
    out = []
    for c, x in enumerate(NAME_COLS_X):
        for r, y in enumerate(NAME_ROWS_Y):
            out.append(("nama", c, LETTERS[r], x, y))
    for c, x in enumerate(NOMOR_COLS_X):
        for d, y in enumerate(DIGIT_ROWS_Y):
            out.append(("nomor", c, str(d), x, y))
    for c, x in enumerate(KODE_COLS_X):
        for d, y in enumerate(DIGIT_ROWS_Y):
            out.append(("kode", c, str(d), x, y))
    for c, (x, top) in enumerate(TANGGAL_COLS):
        for d in range(top + 1):
            out.append(("tanggal", c, str(d), x, DIGIT_ROWS_Y[d]))
    for b, xs in enumerate(ANSWER_COLS_X):
        for r, y in enumerate(ANSWER_ROWS_Y):
            for o, x in enumerate(xs):
                out.append(("jawaban", 30 * b + r, OPTIONS[o], x, y))
    return out


BUBBLES = all_bubbles()
HEADER_GROUPS = ("nama", "nomor", "kode", "tanggal")
# Data yang WAJIB terbaca (keputusan panitia). Tanggal tetap dibaca, tetapi
# kosong/ragu di tanggal tidak membuat lembar "perlu cek".
CRITICAL_GROUPS = ("nama", "nomor", "kode")
NONCRITICAL_BLOCKS = ("tanggal",)


def is_noncritical_note(note):
    """Catatan pelurusan/kualitas untuk blok yang tidak wajib (mis. 'tanggal: ...')."""
    return note.split(":", 1)[0].strip() in NONCRITICAL_BLOCKS
