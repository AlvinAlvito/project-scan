# Deploy produksi: scan.posi.my.id

Catatan pemasangan yang sedang berjalan di VPS (aaPanel, Ubuntu 22.04). Kata sandi tidak dicatat di sini.

| Bagian | Nilai |
|---|---|
| Alamat | https://scan.posi.my.id (`/scan/` admin daerah, `/admin/` superadmin) |
| Folder | `/www/wwwroot/scan.posi.my.id/` berisi `engine/`, `server/`, `web/` |
| Python | 3.12 milik sendiri di `.tools/python` (dipasang `uv` di `.tools/bin`), venv `server/.venv`; Python sistem tidak disentuh |
| Konfigurasi | `server/.env` (milik `www`, mode 600) |
| Data | `server/data/` (foto, gambar hasil baca, kunci token) |
| Database | MariaDB 10.11, database `scan`, user `scan` |
| Layanan | systemd `ljk-scan` -> uvicorn `127.0.0.1:8710`, 1 worker, user `www`, `MemoryMax=900M`, `Nice=5` |
| Nginx | blok `#LJK-SCAN-START ... #LJK-SCAN-END` di `/www/server/panel/vhost/nginx/scan.posi.my.id.conf` (`location ^~ /` -> proxy, `client_max_body_size 25m`); backup asli di `/root/ljk-backup/` |

Port 8710 hanya mendengarkan di localhost; tidak ada port baru yang dibuka ke internet.

## Perintah harian (sebagai root)

```
systemctl status ljk-scan           # status
systemctl restart ljk-scan          # mulai ulang setelah update kode
journalctl -u ljk-scan -n 100       # log aplikasi
tail -f /www/wwwlogs/scan.posi.my.id.error.log   # log nginx
```

## Memperbarui kode

1. Kemas `engine/`, `server/`, `web/` dari repository **tanpa** `server/.venv`, `server/data`, `server/.env`.
2. Ekstrak ke `/www/wwwroot/scan.posi.my.id/` (menimpa file lama), lalu:
   ```
   cd /www/wwwroot/scan.posi.my.id
   chown -R www:www engine server web
   find engine server web -path server/.venv -prune -o -type d -exec chmod 755 {} +
   find engine server web -path server/.venv -prune -o -type f -exec chmod 644 {} +
   chmod 600 server/.env
   ```
3. Bila `server/requirements.txt` berubah:
   `.tools/bin/uv pip install --python server/.venv/bin/python -r server/requirements.txt`
4. `systemctl restart ljk-scan`. Tabel baru dibuat otomatis saat aplikasi mulai.

## Mencopot (rollback penuh)

```
systemctl disable --now ljk-scan && rm /etc/systemd/system/ljk-scan.service && systemctl daemon-reload
cp /root/ljk-backup/scan.posi.my.id.conf.<tanggal> /www/server/panel/vhost/nginx/scan.posi.my.id.conf
nginx -t && /etc/init.d/nginx reload
```

## Kapasitas

- VPS dipakai bersama banyak aplikasi: pembacaan ±8-12 detik per foto saat CPU sibuk.
- Disk tersisa ±4 GB saat pemasangan. Per lembar tersimpan ±4-6 MB (foto asli + gambar hasil baca),
  jadi ±700-900 lembar sebelum disk penuh. Pantau `df -h /` dan bersihkan foto kompetisi yang sudah
  selesai & sudah ditarik ke desktop.
