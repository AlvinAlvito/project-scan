"""Membaca kunci jawaban dari PDF "Pembahasan Soal" POSI.

Ada DUA cara, dipilih otomatis per PDF:

Cara 1 (utama) - tulisan "Kunci Jawaban: X" dicari DI MANA SAJA dalam baris.
    Teks yang diambil dari PDF kadang menyambung kunci ke ujung baris pilihan
    jawaban ("... D. Ampere, lumen, gram. Kunci Jawaban: A"), jadi kunci tidak
    selalu di awal baris. Kunci diambil berurutan: kunci ke-1 untuk soal 1, dst.
    Salah ketik ringan ("Kucni jawaban") tetap dikenali. Nomor soal ("12. ...")
    hanya dipakai sebagai PEMERIKSA: bila nomor soal berikutnya sudah muncul
    padahal soal sekarang belum punya kunci, diberi peringatan (urutan kunci
    tidak diubah). Nomor yang tak terbaca (mis. soal berhuruf Arab yang
    angkanya di ujung baris) tidak membuat proses macet.

Cara 2 (cadangan) - dipakai bila PDF sama sekali tidak memuat "Kunci Jawaban".
    Kunci dicari dari baris yang DIAWALI "Jawaban: X" (mis. Matematika SD 1-2),
    dipasangkan per nomor soal; "Jawaban: ..." lain di dalam pembahasan dengan
    huruf yang sama diabaikan.

Hasil kedua cara dicocokkan dengan "JUMLAH SOAL" di halaman 1.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium

KUNCI_ANY = re.compile(r"\bK[a-z]{3,4}\s+Jawaban\s*:\s*\(?\s*([A-E])\b", re.I)   # cara 1
JAWABAN_START = re.compile(r"^\s*Jawaban\s*:\s*\(?\s*([A-Ea-e])\b", re.I)          # cara 2
Q_LINE = re.compile(r"^\s*(\d{1,3})\s*\.(?!\d)")
DECLARED = re.compile(r"(\d{1,3})\s*(?:SOAL\s+)?PILIHAN\s+BERGANDA", re.I)

CARA_1 = "cara 1 (Kunci Jawaban: X)"
CARA_2 = "cara 2 (Jawaban: X di awal baris)"


@dataclass
class KunciPDF:
    path: Path
    kunci: str                      # satu huruf per soal, "?" bila tidak ditemukan
    jumlah_soal: int
    jumlah_tertulis: int = 0        # angka "JUMLAH SOAL" di halaman 1 (0 bila tak terbaca)
    masalah: list = field(default_factory=list)
    cara: str = ""

    @property
    def lengkap(self):
        return "?" not in self.kunci and not self.masalah


def pdf_lines(path):
    pdf = pdfium.PdfDocument(str(path))
    try:
        for page in pdf:
            text = page.get_textpage().get_text_range()
            for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                yield line
    finally:
        pdf.close()


def _cara_1(lines):
    """Kunci diambil berurutan dari setiap "Kunci Jawaban: X"; nomor soal sebagai pemeriksa."""
    keys, masalah = [], []
    cur = 0             # nomor soal yang sedang menunggu kunci (0 = belum ada)
    in_list = False     # sudah ada daftar bernomor ("1. ...") di dalam soal ini
    for line in lines:
        q = Q_LINE.match(line)
        if q:
            n = int(q.group(1))
            if n == len(keys) + 1:
                cur, in_list = n, False
            elif n == 1 and cur:
                in_list = True
            elif n == len(keys) + 2 and cur == len(keys) + 1 and not in_list and n > 5:
                # Nomor soal berikutnya muncul padahal soal 'cur' belum punya kunci: hanya
                # peringatan (urutan kunci TIDAK diubah, supaya tidak ada pergeseran).
                masalah.append(f"sekitar soal {cur}: nomor soal {n} muncul sebelum kunci soal {cur}; "
                               "periksa apakah ada kunci yang terlewat")
                cur, in_list = n, False
        for m in KUNCI_ANY.finditer(line):
            keys.append(m.group(1).upper())
    return "".join(keys), masalah


def _cara_2(lines):
    """Kunci dari baris yang diawali "Jawaban: X", dipasangkan per nomor soal."""
    cur, keys, beda = 0, {}, {}
    for line in lines:
        q = Q_LINE.match(line)
        if q and int(q.group(1)) == cur + 1 and (cur == 0 or cur in keys):
            cur += 1
            continue
        k = JAWABAN_START.match(line)
        if k and cur > 0:
            letter = k.group(1).upper()
            if cur in keys and keys[cur] != letter:
                beda.setdefault(cur, {keys[cur]}).add(letter)
            keys.setdefault(cur, letter)
    masalah = [f"soal {q}: ada lebih dari satu kunci ({'/'.join(sorted(v))}), dipakai {keys[q]}"
               for q, v in sorted(beda.items())]
    missing = [str(i) for i in range(1, cur + 1) if i not in keys]
    if missing:
        masalah.append(f"kunci tidak ditemukan untuk soal {', '.join(missing)} (ditandai ?)")
    return "".join(keys.get(i, "?") for i in range(1, cur + 1)), masalah


def parse(path):
    path = Path(path)
    lines = list(pdf_lines(path))
    m = DECLARED.search(" ".join(lines[:40]))
    declared = int(m.group(1)) if m else 0
    if any(KUNCI_ANY.search(l) for l in lines):
        kunci, masalah = _cara_1(lines)
        cara = CARA_1
    else:
        kunci, masalah = _cara_2(lines)
        cara = CARA_2
    n = len(kunci)
    if declared and declared != n:
        masalah.append(f"di halaman 1 tertulis 'JUMLAH SOAL: {declared}', tetapi ditemukan {n} kunci "
                       f"(dipakai {n}; periksa bila ada kunci yang terlewat)")
    if n == 0:
        masalah.append("tidak ada tulisan 'Kunci Jawaban: X' maupun 'Jawaban: X' di PDF ini")
    return KunciPDF(path, kunci, n, declared, masalah, cara)


def suggest_name(path):
    """Usulan nama bidang dari nama file, mis. 'Pembahasan Soal SMA Ekonomi - FSN 2026.pdf'
    -> 'EKONOMI SMA'. Hanya usulan; nama akhirnya diisi/diubah di aplikasi."""
    s = Path(path).name
    s = re.sub(r"\.(docx\.)?pdf$", "", s, flags=re.I)
    s = re.sub(r"^\s*pembahasan\s+soal\s*", "", s, flags=re.I)
    s = re.split(r"\s+-\s+", s)[0]
    s = re.sub(r"[()]", " ", s)
    words = s.split()
    lvl = [w for w in words if w.upper() in ("SD", "SMP", "SMA", "MI", "MTS", "MA")]
    rng = [w for w in words if re.fullmatch(r"\d+-\d+", w)]
    rest = [w for w in words if w not in lvl and w not in rng]
    return " ".join(w.upper() for w in rest + lvl + rng)
