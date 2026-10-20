# Mesin pembaca LJK (`ljk/`)

Paket Python yang membaca foto LJK POSI: meluruskan foto, membaca bulatan (OMR), menilai, dan
membuat gambar cek. Dipakai bersama oleh:

- [`../application-desktop/`](../application-desktop/) - aplikasi desktop (lewat `sys.path` ke folder ini)
- [`../server/`](../server/) - server LJK Reader Online (pengaturan `LJK_ENGINE_PATH`, bawaan `../engine`)

Karena satu mesin dipakai di dua tempat, hasil baca di server dan di desktop selalu sama.
Cara kerja pembacaan dijelaskan di [`../application-desktop/README.md`](../application-desktop/README.md).

| Modul | Isi |
|---|---|
| `align.py` | meluruskan foto ke bingkai baku (garis tepi kiri, lingkaran merah, sidik jari blok `ref/`) |
| `omr.py` | membaca bulatan: terisi / kosong / ragu / ganda |
| `pipeline.py`, `tampilan.py` | satu foto -> hasil baca, gambar cek, potongan tulisan tangan |
| `service.py` | penghubung ke aplikasi: proses foto, status lembar, ekspor |
| `nilai.py`, `kunci.py`, `export.py` | penilaian, kunci dari PDF/Excel, Excel daftar nilai |
| `belajar.py` | model "juri kedua" (opsional) |
| `db.py` | database SQLite aplikasi desktop |
| `template.py` | geometri LJK POSI |

Kebutuhan: lihat `requirements.txt` (sudah tercakup di requirements desktop dan server).
