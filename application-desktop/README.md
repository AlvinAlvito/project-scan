# LJK Reader

Aplikasi desktop (offline) untuk membaca Lembar Jawaban Komputer POSI dari foto HP
dan merekap nilai event olimpiade. Tahap sekarang: **mesin pembaca (OMR)**.

## Cara kerja singkat

1. **Arah foto**: garis hitam tepi kiri menentukan foto tegak/terbalik. Kertas boleh miring
   di dalam foto sampai sekitar 45°.
2. **Garis tepi kiri** (1 + 26 + 30 garis) dicocokkan ke template lewat pola celahnya,
   memperhitungkan perspektif foto miring. Ini patokan baris yang tidak bisa "loncat".
   Bila beberapa garis tak terbaca sehingga urutannya seri, kandidat dipilih dengan pola blok.
3. **Pelurusan global** memakai ratusan lingkaran cetak merah + garis tepi.
4. **Per blok** (nama, nomor-kode, tanggal, 6 blok jawaban): posisi blok dicari dengan
   "sidik jari" pola merahnya (`engine/ljk/ref/*.png`), lalu dihaluskan per petak dan per bulatan
   (median tetangga) supaya kertas yang melengkung tetap pas. Bila pola merah blok tak
   dikenali (mis. tertutup bayangan), posisi baris diambil dari garis tepi kiri.
5. **Baca bulatan** dari kanal merah (cetakan merah tak terlihat), skor relatif terhadap
   median bloknya: `kosong` <= 0,15 < `ragu` < 0,24 <= `terisi`. Isian tipis tapi tunggal
   (jauh lebih gelap dari pilihan lain di baris/kolomnya): >= 0,15 diterima, 0,10-0,15 ragu
   (bisa bekas hapusan) dengan tebakan. Isian pensil yang **mengilap** (lampu memantul di
   grafit, tampak keperakan dan tidak gelap) dikenali dari titik lebih terang dari kertas di
   dalam bulatan + huruf merahnya tertutup -> ragu dengan tebakan. Kolom nama: isian sangat
   samar (>= 0,07, menonjol) juga ragu, karena huruf yang hilang di nama tidak memberi tanda lain.
   Pengaman pelurusan: bila garis tepi kiri tidak jatuh di barisnya (selisih > 0,4 baris),
   lembar ditandai "jawaban mungkin bergeser baris".
   **Normalisasi kontras**: ambang di atas disetel dari foto HP biasa (isian jelas ~0,6). Foto
   yang pudar, mis. frame video kamera dari web HP (~0,38), menekan isian dan bekas hapusan
   dengan rasio yang sama; skor lembar seperti itu dikalikan sampai tingkat isiannya setara
   acuan (paling besar 2x), lembar normal tidak diubah. Acuan per event di kanan atas, sejajar nama
   event (*Kontras baca*: mati / rendah 0,45 / **standar 0,50** / tinggi 0,55); server selalu standar.
   Uji 128 foto: tidak ada keputusan "ok" yang berubah; isian tipis yang dulu terbaca kosong
   atau ragu kini terbaca.
7. **Gambar untuk dilihat** (`ljk/tampilan.py`) dipisah dari gambar untuk dibaca. Pembacaan
   bulatan & nilai tetap dari gambar lurus 2000 px seperti sebelumnya. Gambar cek (1,5x) dan
   potongan tulisan tangan (2x) dibuat langsung dari foto asli resolusi penuh lalu dipertajam
   (unsharp mask yang dijepit, tanpa halo). Di dalam setiap bulatan (jari-jari 14 px bingkai baku)
   piksel foto asli disalin persis — isian pensil, hapusan, dan isian mengilap tampil apa adanya.
   Potongan tulisan tangan (tidak memuat bulatan) diratakan kertasnya dan goresan tipis dipertegas.
   Di panel cek, tombol **Hitam-putih** menampilkan gambar cek ala scanner: tinta & isian pensil
   hitam (rata-rata per bulatan, seperti mesin baca menilai), cetakan merah abu-abu muda, tanda
   hasil baca tetap berwarna; slider **Kontras** (standar 50) hanya mengubah tampilan, bukan hasil baca.
6. Hal yang tidak pasti (ragu, lebih dari satu terisi, digit kosong, pelurusan meragukan)
   tidak ditebak diam-diam, tetapi dimasukkan ke daftar "perlu cek". Isian di soal setelah
   soal terakhir ujian tidak dinilai; baru diperingatkan bila ada >= 3 isian jelas dalam
   30 nomor sesudahnya (tanda kode naskah mungkin salah).

Mesin pembaca (paket `ljk/`) ada di folder [`../engine/`](../engine/) karena dipakai bersama
dengan server; aplikasi dan alat di `tools/` memuatnya dari sana secara otomatis.

## Pemasangan dari repository (Windows, Python 3.13)

```
cd application-desktop
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Lalu klik dua kali `Jalankan LJK Reader.bat`, atau `Buat EXE.bat` untuk membuat paket .exe.
Alat pelatihan model (opsional) memakai lingkungan terpisah: lihat `requirements-latih.txt`.

## Aplikasi desktop

Klik dua kali **`Jalankan LJK Reader.bat`** (memakai Python di `.venv`) atau buka versi .exe.
Data aplikasi (database `ljk.db`, gambar cek, potongan tulisan tangan) disimpan di
**`%LOCALAPPDATA%\LJK Reader`** (tombol "Buka folder data" di aplikasi), di luar folder program
sehingga aman saat aplikasi diperbarui. Documents tidak dipakai karena di laptop ini diblokir
"Controlled folder access" Windows. Data versi lama (folder `data/`) otomatis disalin saat pertama dibuka.
Tampilan bergaya "lembar di dalam bingkai": bilah atas (cari lembar dengan Ctrl+K, status server, **Sinkron**)
dan daftar event di kiri berwarna abu-abu muda; isi halaman di lembar putih. Huruf IBM Plex Sans/Mono ikut
dalam paket (`app/fonts`, lisensi OFL). Tema terang/gelap di kiri bawah.
Jendela bisa diperkecil sampai 640 px (mis. setengah layar dengan Win + panah). Di bawah 1000 px daftar event
dibuka lewat tombol panel di kiri judul dan tombol di kepala halaman menjadi ikon (namanya di tooltip); bila
tab Scan & nilai sempit, antrean pindah ke atas panel cek dan panel cek menampilkan gambar di atas data.

1. **Event** (panel kiri): **+** -> isi nama event & tanggal. Menu **⋯** di samping judul "Event" berisi
   ambil kompetisi dari server, kirim event ke server, ubah, dan hapus event.
2. **Kunci jawaban** (sidebar, kelompok *Menu* di bawah daftar event): kunci disimpan sebagai **paket** (mis.
   "FSN PROVINSI PAKET 1") yang bisa dipakai banyak event. Susunannya seperti aplikasi LJK lama: daftar
   **Paket kunci** (Tambah / Ubah nama / Hapus), **Mata pelajaran** paket terpilih (Impor PDF dari folder
   pembahasan, Impor Excel, Tambah, Edit kunci, Hapus), **Kode naskah** mata pelajaran terpilih (boleh lebih
   dari satu; satu kode hanya milik satu mata pelajaran di paket itu), dan di kanan urutan kunci 1..N
   (bulatan A-E). Edit kunci membuka editor per nomor (blok 30 nomor, tombol Buka PDF sumber). Semua
   perubahan langsung tersimpan. Mata pelajaran yang kuncinya belum lengkap (ada nomor tanpa A-E) belum
   dipakai menilai.
   **Nilai beku**: setiap lembar menyimpan kunci mata pelajarannya saat pertama kali di-scan, jadi mengedit
   kunci paket **tidak** mengubah nilai lembar yang sudah ada (hanya lembar yang di-scan sesudahnya). Proses
   ulang / ganti Kontras baca tetap memakai kunci scan pertama. Kunci lembar lama hanya diganti dengan sengaja:
   **Hitung ulang** di menu Nilai hasil, **Ganti paket** event, atau kode naskah dikoreksi di panel cek (kunci
   kode baru diambil saat disimpan). Lembar yang kodenya belum ada di kunci saat di-scan dibekukan begitu
   kodenya ditambahkan ke paket.
   Di tab **Kunci jawaban** event: paket yang dipakai, daftar kode naskahnya beserta jumlah lembar per kode,
   **Ganti paket**, dan kode naskah server/lembar yang belum ada di paket. Event yang dibuat sebelum ada paket
   tetap memakai kunci lamanya sampai memilih paket (kunci lama tidak dihapus).
3. **Scan & nilai** (cek manual ada di sini juga): **Tambah foto** (kanan atas; pilih foto atau satu
   folder) -> bila event belum memakai paket kunci, panitia diminta **memilih paket dulu** (kolom *Cocok*
   membandingkan kode naskah paket dengan kode di server/lembar event); setelah itu foto diproses otomatis. Kartu **Semua / Perlu cek / Gagal / Sudah dicek / OK** menghitung lembar
   sekaligus menyaring antrean di kiri (nama, nilai, catatan pertama; urut nomor, nilai, atau kode naskah).
   Kalimat di bawah nama event menyebut berapa lembar siap diekspor dan apa yang masih menahan.
   Pilih lembar di antrean -> gambar cek & data tampil di kanan. Soal yang ragu/ganda muncul di kotak
   **Soal N** dengan tombol A-E / Kosong / Ganda (atau tekan A-E di papan ketik); klik catatan untuk
   melompat ke lokasinya di gambar; data peserta, tulisan tangan, dan tabel semua jawaban ada di bawahnya.
   "Simpan dan tandai sudah dicek" (Ctrl+Enter) -> pindah ke lembar berikutnya di antrean
   (Ctrl+atas/bawah atau tombol ‹ › untuk berpindah tanpa menyimpan). Menu **⋯** antrean (atau klik kanan):
   proses ulang / hapus lembar terpilih. Tombol **Hitam-putih** (di samping zoom) memperjelas isian tipis;
   kontrasnya bisa digeser. Mengganti **Kontras baca** (kanan atas) menawarkan baca ulang lembar yang belum
   dicek. **Ekspor nilai** di kanan atas.
4. **Nilai hasil** (sidebar, kelompok *Menu*): kiri atas daftar event, kanan atas mata pelajaran event terpilih
   (semua mata pelajaran paketnya, dengan kode naskah, jumlah soal, peserta, rata-rata; plus *Belum dinilai*
   untuk lembar gagal / kode tak terdaftar), bawah tabel peserta: No, Tgl. periksa (waktu scan pertama; lembar
   dari sebelum fitur ini kosong), nomor, nama, nilai, B/S/K, kode naskah, status (*Perlu cek* = nilai sementara,
   *kunci lama* = kunci bekunya berbeda dari paket), jawaban, dan kunci. Kolom bisa diurutkan; klik dua kali
   peserta membuka lembarnya di panel cek. **Cetak nilai**: peserta terpilih (Ctrl/Shift+klik) dibandingkan
   dengan kunci, jawaban biru = benar, merah = salah, "-" = kosong, plus nilai (Benar/Salah/Kosong); muncul
   pratinjau (A4 mendatar) untuk printer atau **Simpan PDF**. **Ekspor Excel**: format Daftar Nilai untuk mata
   pelajaran terpilih, atau semua pelajaran dalam 1 file. **Hitung ulang**: ganti kunci beku lembar mata pelajaran
   ini / seluruh event dengan kunci paket terbaru.

## Menarik LJK dari server (LJK Reader Online)

LJK yang dipotret admin daerah lewat web HP (lihat [`../server/README.md`](../server/README.md))
ditarik ke event desktop:

1. **Hubungkan server** (bilah atas, kanan): alamat server + akun superadmin. Token login disimpan,
   kata sandi tidak.
2. Buka event -> **Sinkron** (bilah atas, kanan). Pertama kali, event dihubungkan ke
   kompetisi server (baru atau yang sudah ada; lihat bagian berikut).
3. Lembar yang sudah dikonfirmasi/ditandai admin daerah diunduh dan dibaca ulang di laptop
   (mesin yang sama). Data yang dikoreksi admin daerah dipakai, hasil baca asli tetap tampil
   sebagai "terbaca: …" di panel cek. Catatan server (nomor tidak terdaftar, duplikat, koreksi,
   peserta baru, kualitas foto < 85%) masuk ke daftar perlu cek. Lembar dari HP bertanda "HP" di antrean;
   lokasi, pengirim, dan skor kualitas foto tampil di baris **Dikirim** panel cek.
4. Lembar yang sudah dicek dilaporkan ke server pada sinkron berikutnya (terlihat di panel admin).
5. Lembar server yang pernah ditarik tetapi tidak ada lagi di event (mis. terhapus) ditawarkan untuk
   ditarik ulang saat sinkron; bila ditolak, lembar itu tidak muncul lagi sampai diminta.

Kunci jawaban tetap hanya di desktop; isi seperti biasa di tab Kunci Jawaban dengan kode naskah
yang sama dengan bidang di server.

### Mengirim event desktop ke server

Kompetisi yang dibuat di web otomatis menjadi event desktop (label "· server"). Arah sebaliknya
lewat menu **⋯** di samping judul "Event" (sidebar) -> **Kirim event ke server**:

- **Event belum terhubung**: pilih *Buat kompetisi baru* (nama & tanggal event ini), atau gabungkan
  dengan kompetisi yang sudah ada (kompetisi bernama sama dipilih otomatis). Bidang dari Kunci
  Jawaban ikut dikirim: kode naskah, nama bidang, jumlah soal. **Kunci jawaban tidak dikirim.**
- **Event sudah terhubung**: hanya menambah bidang yang kode naskahnya belum ada di server. Bidang
  server tidak pernah diubah atau dihapus dari desktop; perbedaan nama/jumlah soal hanya dilaporkan.

Setelah terhubung, nama, tanggal, dan daftar bidang mengikuti server; lokasi, peserta, dan akun admin
daerah diatur di panel admin web. Satu kompetisi hanya terhubung ke satu event desktop: menggabungkan
dengan kompetisi yang event desktopnya masih kosong menggantikan event kosong itu, sedangkan kompetisi
yang event desktopnya sudah berisi kunci/lembar tidak bisa dipilih (supaya lembar yang ditarik tidak
terbelah ke dua event). Menghapus event di desktop tidak menghapus kompetisi di server, begitu pula sebaliknya.

## Mengajari model membaca bulatan (tab "Latih model")

Pembacaan utama tetap memakai aturan. Model deep learning (CNN kecil) hanya **juri kedua**:
bila tidak setuju dengan aturan, lembar ditandai "Perlu cek"; model tidak pernah mengganti
hasil sendirian. Tanpa model yang lulus ujian, pembacaan sama persis seperti tanpa fitur ini.

1. **Ambil contoh sulit** -> muncul bulatan yang paling membingungkan (tipis, mengilap,
   setengah terisi, bekas hapusan). Tekan **1 = terisi**, **2 = kosong**, **3 = hapusan/bekas**,
   0 = lewati, Backspace = hapus label. Label disimpan di tabel `label_bulatan` (ljk.db).
   600 contoh paling berguna dikelompokkan **per LJK**: satu halaman = satu LJK (yang contohnya
   terbanyak dulu), urut posisi di lembar. **Klik dua kali** kotak (atau Enter) membuka LJK utuh
   (gambar cek) dengan bulatan yang ditanya dilingkari biru; label 1/2/3 bisa diberi di sana dan
   lingkaran pindah ke contoh berikutnya di LJK yang sama.
2. Lembar yang **Sudah dicek** (panel cek di Scan & nilai) ikut menjadi bahan latih (jawaban akhir soal
   1..jumlah soal, digit nomor & kode).
3. **Latih ulang model** menjalankan `tools/latih_bulatan.py` di lingkungan PyTorch terpisah
   (`.venv-latih`, CPU, ~1 menit). 1 dari 4 lembar (tetap, menurut nama foto) disisihkan
   sebagai lembar UJIAN dan tidak pernah dipakai melatih. Model baru aktif
   (`<data>/model/aktif.json`) hanya bila: >= 60 label Anda di lembar ujian, akurasinya >=
   aturan sekarang dan >= model sebelumnya, dan hampir tidak pernah berbeda pendapat pada
   bulatan yang jelas. Boleh memutus kasus ragu hanya bila lulus syarat lebih ketat (gerbang B).
4. Model aktif dipakai untuk foto yang diproses sesudahnya ("Proses ulang" untuk lembar lama).
   Aplikasi menjalankan model ONNX dengan OpenCV (tanpa PyTorch).

Bahan latih tiap lembar: `baca.jpg` (gambar yang dipakai membaca, bukan gambar tampilan)
dan `baca.npz` (posisi, skor, keputusan aturan tiap bulatan) di folder lembar.

## Versi .exe (tanpa Python)

Paket siap pakai ada di `dist\LJK Reader\` (buka `LJK Reader.exe`). Untuk laptop lain, salin
**seluruh folder** `LJK Reader`. Setelah kode diperbarui, klik dua kali `Buat EXE.bat` untuk
membuat ulang paketnya (data di %LOCALAPPDATA% tidak tersentuh). Tutup aplikasinya dulu: file yang
sedang dipakai tidak bisa diganti dan paketnya bisa rusak setengah jadi.

Ikon aplikasi (file .exe, jendela, taskbar) adalah `packaging\ljk_reader.ico`. Untuk menggantinya dari
gambar: `.venv\Scripts\python tools\buat_ikon.py GAMBAR.jpg` (opsional `--kecil X Y SISI`: potongan
persegi untuk ukuran kecil, mis. wajah), lalu `Buat EXE.bat`. Windows kadang masih menampilkan ikon lama
dari cache-nya sebentar.

Cek cepat hasil paket (tanpa membuka jendela):
`"LJK Reader.exe" --selftest FOTO.jpg KUNCI.pdf hasil.txt`

Data wajib terbaca: Nama, Nomor Peserta, Kode Naskah (bidang dari kode). Tanggal tetap dibaca
tetapi boleh kosong/ragu tanpa membuat lembar "perlu cek".

## Alat baris perintah

```
python tools/run_samples.py "FOLDER_FOTO" [FOLDER_HASIL]
```

Hasil di `output/sampel/`: `Hasil Baca LJK.xlsx`, `cek_visual/` (lembar yang sudah
diluruskan dengan tanda hasil baca), `potongan/` (area tulisan tangan).

### Kunci jawaban dan rekap nilai

```
python tools/import_kunci.py "D:\SCAN\FSN PROVINSI PAKET 1"
```
Membaca kunci dari PDF "Pembahasan Soal" ke `output/kunci/Kunci Jawaban - <folder>.xlsx`
(isi kolom Kode Naskah sebelum dipakai).

```
python tools/rekap.py "FOLDER_FOTO" "FILE_KUNCI.xlsx" --event "NAMA EVENT" --tanggal "6 September 2026"
```
Menghasilkan `<event> Daftar Nilai.xlsx` (satu sheet per bidang; benar +4, salah −1,
kosong 0, ganda = salah) dan `<event> Perlu Cek.xlsx`.

Sidik jari blok dibuat ulang (bila template berubah) dari foto acuan yang sudah dipastikan pas:

```
python tools/build_reference.py FOTO1.jpg FOTO2.jpg
```
