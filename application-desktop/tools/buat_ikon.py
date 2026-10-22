"""Buat ikon aplikasi packaging/ljk_reader.ico (16-256 px).

Ikon dipakai untuk file .exe (packaging/ljk_reader.spec) dan untuk jendela/taskbar (app/main.py). Setelah ikon
diganti, tutup aplikasi lalu jalankan "Buat EXE.bat".

    python tools/buat_ikon.py                                  # logo bawaan: kotak biru + simbol pindai
    python tools/buat_ikon.py GAMBAR.jpg                       # dari gambar (jpg/png), dipotong persegi di tengah
    python tools/buat_ikon.py GAMBAR.jpg --kecil X Y SISI      # ukuran <= 64 px memakai potongan persegi ini
                                                               # (px gambar asli), mis. wajah, supaya tetap jelas
"""
import argparse
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPainterPath  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

from app.icons import PATHS  # noqa: E402

LATAR = "#5b8cff"       # warna aksen tema gelap (sama dengan logo di sidebar)
SIMBOL = "#ffffff"
UKURAN = (16, 20, 24, 32, 40, 48, 64, 128, 256)
KECIL = 64              # ukuran sampai sini memakai potongan --kecil (bila ada)
OUT = ROOT / "packaging" / "ljk_reader.ico"


def _kanvas(n):
    img = QImage(n, n, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    return img, p


def logo(n):
    img, p = _kanvas(n)
    kotak = QPainterPath()
    kotak.addRoundedRect(QRectF(0, 0, n, n), n * 0.24, n * 0.24)
    p.fillPath(kotak, QColor(LATAR))
    tebal = 2.4 if n <= 24 else 2.0                 # garis sedikit lebih tebal di ukuran kecil supaya tetap terbaca
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{SIMBOL}" '
           f'stroke-width="{tebal}" stroke-linecap="round" stroke-linejoin="round">{PATHS["scan"]}</svg>')
    m = n * 0.2
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(m, m, n - 2 * m, n - 2 * m))
    p.end()
    return img


def dari_gambar(src, potong, n):
    """Potongan persegi `potong` dari gambar src, diperkecil halus ke n px, sudut sedikit membulat."""
    sq = src.copy(potong).scaled(n, n, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    img, p = _kanvas(n)
    bentuk = QPainterPath()
    bentuk.addRoundedRect(QRectF(0, 0, n, n), n * 0.12, n * 0.12)
    p.fillPath(bentuk, QBrush(sq))
    p.end()
    return img


def png(img):
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def tulis_ico(gambar):
    """gambar: [(n, QImage)] -> file ICO berisi PNG per ukuran."""
    data = [(n, png(img)) for n, img in gambar]
    out = struct.pack("<HHH", 0, 1, len(data))
    offset = 6 + 16 * len(data)
    for n, b in data:
        out += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(b), offset)
        offset += len(b)
    out += b"".join(b for _n, b in data)
    OUT.write_bytes(out)
    return len(out)


def main():
    ap = argparse.ArgumentParser(description="Buat packaging/ljk_reader.ico")
    ap.add_argument("gambar", nargs="?", help="gambar sumber (jpg/png); tanpa ini: logo bawaan")
    ap.add_argument("--kecil", nargs=3, type=int, metavar=("X", "Y", "SISI"),
                    help=f"potongan persegi untuk ukuran <= {KECIL} px (px gambar asli)")
    a = ap.parse_args()
    QGuiApplication(sys.argv)
    if a.gambar is None:
        gambar = [(n, logo(n)) for n in UKURAN]
    else:
        src = QImage(a.gambar)
        if src.isNull():
            raise SystemExit(f"Gambar tidak bisa dibuka: {a.gambar}")
        s = min(src.width(), src.height())
        tengah = QRect((src.width() - s) // 2, (src.height() - s) // 2, s, s)
        kecil = QRect(*a.kecil[:2], a.kecil[2], a.kecil[2]).intersected(src.rect()) if a.kecil else tengah
        gambar = [(n, dari_gambar(src, kecil if n <= KECIL else tengah, n)) for n in UKURAN]
    size = tulis_ico(gambar)
    print(f"{OUT} ({size // 1024} KB, {len(gambar)} ukuran)")


if __name__ == "__main__":
    main()
