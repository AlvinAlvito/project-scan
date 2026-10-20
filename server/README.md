# LJK Reader Online (server)

Server untuk memindai LJK lewat HP. Admin daerah memotret LJK di web HP dengan pemandu
kualitas realtime; server membaca foto dengan mesin [`../engine/`](../engine/) yang sama persis
dengan aplikasi desktop; panitia pusat memantau lewat panel admin dan menarik data ke aplikasi
desktop. Tampilan web ada di [`../web/`](../web/) dan disajikan oleh server ini.
Rancangan lengkap: [`../dokumentasi/arsitektur-sistem.html`](../dokumentasi/arsitektur-sistem.html).

| Alamat | Untuk |
|---|---|
| `/` | Login (diarahkan sesuai peran) |
| `/scan/` | Web HP admin daerah: pilih kompetisi & bidang, kamera, konfirmasi hasil, riwayat |
| `/admin/` | Panel superadmin: dashboard per lokasi, kompetisi/lokasi/bidang/peserta, akun & akses, lembar, peserta baru |
| `/docs` | Dokumentasi API (otomatis dari FastAPI) |

## Pemasangan lokal (Windows, Python 3.12+, MySQL 8)

```
cd server
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env                       (sesuaikan LJK_DB_URL bila perlu)
.venv\Scripts\python init_db.py --superadmin admin
```

`init_db.py` membuat database `ljk_online`, semua tabel, dan akun superadmin (kata sandi ditanya).
Lalu klik dua kali **`Jalankan Server.bat`** dan buka http://localhost:8000.

### Mencoba kamera dari HP (satu WiFi dengan laptop)

Browser HP hanya mengizinkan kamera lewat HTTPS. Untuk uji coba:

```
.venv\Scripts\python make_cert.py
```

Jalankan ulang `Jalankan Server.bat` (sekarang juga membuka port 8443), lalu buka alamat yang
dicetak, mis. `https://10.127.144.89:8443/scan/`. Browser akan memperingatkan sertifikat tidak
dikenal: pilih *Lanjutan → Lanjutkan*. Bila HP tidak bisa terhubung, izinkan Python di Windows Firewall.

## Alur data

1. Superadmin mengisi **Master bidang** (nama + kode naskah & jumlah soal bawaan) sekali, lalu
   membuat kompetisi, lokasi (kota), dan memilih bidang dari master (pencarian; kode & jumlah soal
   terisi otomatis). Daftar peserta diimpor dari Excel/CSV; tombol **Unduh template** memberi file
   yang pasti terbaca (kolom `nomor, nama, sekolah, lokasi`, daftar lokasi valid, petunjuk).
   Terakhir, buat akun admin daerah dengan akses per lokasi.
2. Admin daerah memilih kompetisi/lokasi dan bidang, lalu memotret. Skor kualitas dihitung di HP
   (`web/scan/quality.js`); tombol ambil baru aktif bila skor ≥ 90% (foto diambil otomatis saat
   stabil). Tanpa sinyal, foto disimpan di HP dan dikirim otomatis nanti.
3. Server menyimpan foto, membaca (±2-5 detik), memvalidasi (nomor di daftar peserta, nama cocok,
   kode naskah sesuai bidang, duplikat), lalu mengembalikan hasilnya ke HP.
4. Admin daerah mengonfirmasi: **Benar**, **Perbaiki data**, **Peserta baru** (daftar di tempat,
   disetujui superadmin), atau **Hapus & foto ulang**.
5. Aplikasi desktop: tombol **Sinkron server** menarik lembar yang sudah dikonfirmasi/ditandai,
   membacanya ulang secara lokal, dan memasukkan catatan server ke daftar Cek Manual. Lembar yang
   sudah dicek dilaporkan kembali ke server pada sinkron berikutnya.

Kunci jawaban **tidak** disimpan di server; nilai hanya dihitung di aplikasi desktop.

## Struktur

Folder ini hanya berisi API. Tampilan web ada di `../web/` (`index.html` login, `scan/` web HP
dengan `quality.js` penilai kualitas foto & `queue.js` antrean offline, `admin/` panel superadmin,
`static/` CSS & JS bersama); mesin pembaca di `../engine/`. Lokasi keduanya bisa diubah lewat
`LJK_WEB_DIR` dan `LJK_ENGINE_PATH` di `.env`.

```
app/
  config.py      pengaturan (.env)            models.py   tabel database
  security.py    login JWT & hak akses         reading.py  pembungkus mesin ljk/ + kualitas server
  validate.py    validasi terhadap daftar peserta, bidang, duplikat
  routers/       auth, admin (superadmin), scan (admin daerah), sync (desktop), files (gambar)
init_db.py       buat database, tabel, superadmin
make_cert.py     sertifikat HTTPS uji coba lokal
```

Data (foto, gambar hasil baca, kunci token) disimpan di `server/data/` dan tidak masuk git.

## Deploy ke VPS (aaPanel) - ringkas

1. Salin folder `engine/`, `server/`, dan `web/` ke VPS dalam satu folder induk (susunannya
   sama seperti di repository). Folder `application-desktop/` tidak perlu dibawa.
2. Buat database MySQL di aaPanel, isi `LJK_DB_URL`, jalankan `init_db.py --superadmin <nama>`.
3. Jalankan `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2` lewat Python Manager
   / Supervisor aaPanel, lalu reverse proxy domain ke port itu dan aktifkan SSL Let's Encrypt.
4. Batas ukuran unggah di Nginx minimal 25 MB (`client_max_body_size 25m`).
