# project-scan

Pembaca Lembar Jawaban Komputer (LJK) POSI dari foto HP dan rekap nilai event olimpiade.

```
project-scan/
├── engine/               mesin pembaca LJK (paket ljk/), dipakai desktop dan server
├── application-desktop/  aplikasi desktop Windows: cek manual, rekap nilai, latih model, sinkron server
├── server/               API LJK Reader Online (FastAPI + MySQL), juga menyajikan folder web/
├── web/                  tampilan web: halaman HP admin daerah (scan/) dan panel superadmin (admin/)
└── dokumentasi/          rancangan arsitektur sistem
```

| Bagian | Petunjuk |
|---|---|
| Aplikasi desktop | [`application-desktop/README.md`](application-desktop/README.md) |
| Server & web | [`server/README.md`](server/README.md) |
| Mesin pembaca | [`engine/README.md`](engine/README.md) |
| Arsitektur | [`dokumentasi/arsitektur-sistem.html`](dokumentasi/arsitektur-sistem.html) |

Deploy ke VPS cukup membawa `engine/`, `server/`, dan `web/`; `application-desktop/` hanya
dipasang di laptop panitia pusat.

Data peserta (database, foto LJK, hasil rekap) dan kunci jawaban **tidak** disimpan di repository ini.
