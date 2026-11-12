"""Penyimpanan data aplikasi (SQLite): event, paket kunci jawaban, dan lembar LJK.

Kunci jawaban disimpan di PAKET (mis. "FSN PROVINSI PAKET 1") yang dipakai bersama oleh banyak event:
paket -> mata pelajaran (nama + kunci) -> kode naskah (satu mata pelajaran boleh punya beberapa kode,
satu kode hanya milik satu mata pelajaran di paket itu). Event memilih satu paket (event.paket_id).

Nilai BEKU: setiap lembar menyimpan kunci mata pelajarannya saat pertama kali di-scan (lembar.soal_beku),
jadi mengedit kunci paket tidak mengubah nilai lembar yang sudah ada. Proses ulang tetap memakai kunci itu.
Kunci lembar hanya diganti dengan sengaja: hitung_ulang() (menu Nilai hasil), ganti paket event, atau kode
naskah lembar dikoreksi di panel cek (kunci kode baru diambil saat disimpan). Lembar yang kodenya belum ada
di kunci saat di-scan dibekukan begitu kuncinya tersedia (bekukan_belum).
Tabel `naskah` (kunci per event, versi sebelum ada paket) tetap dibaca untuk event lama yang belum
memilih paket, tetapi tidak diisi lagi oleh aplikasi."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .nilai import Soal

LETTERS = "ABCDE"


def kode_sort(k):
    """Urutan kode naskah: angka menurut nilainya ('9' sebelum '10'), lalu kode berhuruf."""
    return (0, int(k)) if k.isdigit() else (1, k)


def beku_json(soal):
    """Kunci satu kode naskah untuk disimpan di lembar.soal_beku (None bila kodenya tidak punya kunci)."""
    if soal is None:
        return None
    return json.dumps({"kode": soal.kode, "bidang": soal.bidang, "kunci": soal.kunci, "sumber": soal.sumber})


def soal_beku(beku, kode):
    """Soal dari lembar.soal_beku bila kodenya sama dengan kode lembar sekarang, selain itu None."""
    if not beku:
        return None
    try:
        d = json.loads(beku)
    except ValueError:
        return None
    if d.get("kode") != kode or not d.get("kunci"):
        return None
    return Soal(d["kode"], d.get("bidang", ""), d["kunci"], d.get("sumber", ""))


def sekarang():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def kunci_lengkap(kunci):
    """Kunci bisa dipakai menilai: tidak kosong dan semua isinya A-E (bukan '?' dari PDF yang tak terbaca)."""
    return bool(kunci) and all(ch in LETTERS for ch in kunci)


SCHEMA = """
CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY,
    nama TEXT NOT NULL,
    tanggal TEXT NOT NULL,
    dibuat TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS naskah (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES event(id) ON DELETE CASCADE,
    kode TEXT NOT NULL,
    bidang TEXT NOT NULL,
    kunci TEXT NOT NULL,
    sumber TEXT DEFAULT '',
    UNIQUE(event_id, kode)
);
CREATE TABLE IF NOT EXISTS lembar (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES event(id) ON DELETE CASCADE,
    urutan INTEGER NOT NULL,
    file TEXT NOT NULL,
    error TEXT DEFAULT '',
    nama TEXT DEFAULT '',          -- nilai akhir (hasil baca, lalu hasil cek manual)
    nomor TEXT DEFAULT '',
    kode TEXT DEFAULT '',
    tanggal TEXT DEFAULT '',
    jawaban TEXT DEFAULT '[]',     -- JSON 180 isian akhir
    baca TEXT DEFAULT '{}',        -- JSON hasil baca asli (untuk layar cek)
    dicek INTEGER DEFAULT 0,
    gambar TEXT DEFAULT '',
    potongan TEXT DEFAULT '{}',
    UNIQUE(event_id, file)
);
CREATE TABLE IF NOT EXISTS paket (            -- paket kunci jawaban, dipakai bersama oleh banyak event
    id INTEGER PRIMARY KEY,
    nama TEXT NOT NULL UNIQUE COLLATE NOCASE,
    dibuat TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mapel (            -- mata pelajaran di satu paket: nama + kunci
    id INTEGER PRIMARY KEY,
    paket_id INTEGER NOT NULL REFERENCES paket(id) ON DELETE CASCADE,
    nama TEXT NOT NULL,
    kunci TEXT NOT NULL DEFAULT '',
    sumber TEXT DEFAULT '',        -- path PDF pembahasan asal kunci (bila diimpor dari PDF)
    catatan TEXT DEFAULT ''        -- catatan impor PDF (mis. nomor yang kuncinya tidak ditemukan)
);
CREATE TABLE IF NOT EXISTS mapel_kode (       -- kode naskah milik mata pelajaran; unik di dalam satu paket
    paket_id INTEGER NOT NULL REFERENCES paket(id) ON DELETE CASCADE,
    mapel_id INTEGER NOT NULL REFERENCES mapel(id) ON DELETE CASCADE,
    kode TEXT NOT NULL,
    PRIMARY KEY (paket_id, kode)
);
CREATE TABLE IF NOT EXISTS label_bulatan (    -- label panitia per bulatan (layar Latih Model)
    file TEXT NOT NULL,            -- path foto (sama dengan lembar.file)
    idx INTEGER NOT NULL,          -- indeks bulatan (urutan template.BUBBLES)
    label TEXT NOT NULL,           -- 'terisi', 'kosong', 'hapusan'
    waktu TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (file, idx)
);
"""


class DB:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(path))
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(SCHEMA)
        cols = {r["name"] for r in self.con.execute("PRAGMA table_info(naskah)")}
        if "sumber" not in cols:   # database dari versi sebelumnya
            with self.con:
                self.con.execute("ALTER TABLE naskah ADD COLUMN sumber TEXT DEFAULT ''")
        # Kolom sinkron server (LJK Reader Online), ditambahkan ke database lama bila belum ada
        self._add_columns("event", {"server_kompetisi_id": "INTEGER", "server_url": "TEXT DEFAULT ''",
                                    "server_bidang": "TEXT DEFAULT '[]'",
                                    "kontras": "TEXT DEFAULT 'standar'",    # normalisasi kontras baca
                                    "paket_id": "INTEGER"})                 # paket kunci jawaban yang dipakai
        self._add_columns("lembar", {"server_id": "INTEGER", "server": "TEXT DEFAULT '{}'",
                                     "server_dicek": "INTEGER DEFAULT 0",
                                     "soal_beku": "TEXT",              # kunci saat di-scan (JSON), lihat docstring
                                     "dipindai": "TEXT DEFAULT ''"})   # waktu pertama kali di-scan (Tgl. Periksa)
        # lembar dari versi sebelum nilai beku: dibekukan dengan kunci yang berlaku sekarang
        self.bekukan_belum()

    def _add_columns(self, table, cols):
        have = {r["name"] for r in self.con.execute(f"PRAGMA table_info({table})")}
        with self.con:
            for name, decl in cols.items():
                if name not in have:
                    self.con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    # ---- event
    def events(self):
        return self.con.execute("SELECT * FROM event ORDER BY id DESC").fetchall()

    def event(self, event_id):
        return self.con.execute("SELECT * FROM event WHERE id=?", (event_id,)).fetchone()

    def add_event(self, nama, tanggal):
        with self.con:
            cur = self.con.execute("INSERT INTO event(nama, tanggal) VALUES (?, ?)", (nama, tanggal))
        return cur.lastrowid

    def update_event(self, event_id, nama, tanggal):
        with self.con:
            self.con.execute("UPDATE event SET nama=?, tanggal=? WHERE id=?", (nama, tanggal, event_id))

    def set_kontras(self, event_id, kontras):
        with self.con:
            self.con.execute("UPDATE event SET kontras=? WHERE id=?", (kontras, event_id))

    def link_server(self, event_id, kompetisi_id, url):
        with self.con:
            self.con.execute("UPDATE event SET server_kompetisi_id=?, server_url=? WHERE id=?",
                             (kompetisi_id, url, event_id))

    def event_for_kompetisi(self, url, kompetisi_id):
        """Event desktop yang terhubung ke kompetisi server ini, atau None."""
        return self.con.execute("SELECT * FROM event WHERE server_kompetisi_id=? AND server_url=?",
                                (kompetisi_id, url)).fetchone()

    def upsert_server_event(self, url, kompetisi_id, nama, tanggal, bidang):
        """Event lokal untuk satu kompetisi server: dibuat bila belum ada, nama/tanggal/bidang diperbarui
        bila sudah ada. Mengembalikan (event_id, dibuat_baru)."""
        row = self.event_for_kompetisi(url, kompetisi_id)
        bj = json.dumps(bidang)
        with self.con:
            if row:
                self.con.execute("UPDATE event SET nama=?, tanggal=?, server_bidang=? WHERE id=?",
                                 (nama, tanggal, bj, row["id"]))
                return row["id"], False
            cur = self.con.execute("INSERT INTO event(nama, tanggal, server_kompetisi_id, server_url, server_bidang) "
                                   "VALUES (?, ?, ?, ?, ?)", (nama, tanggal, kompetisi_id, url, bj))
            return cur.lastrowid, True

    def server_bidang(self, event_id):
        """Bidang kompetisi server yang terhubung: [{kode_naskah, nama, jumlah_soal}]."""
        r = self.con.execute("SELECT server_bidang FROM event WHERE id=?", (event_id,)).fetchone()
        try:
            return json.loads(r["server_bidang"] or "[]") if r else []
        except ValueError:
            return []

    def delete_event(self, event_id):
        with self.con:
            self.con.execute("DELETE FROM event WHERE id=?", (event_id,))

    # ---- kunci yang dipakai event
    def naskah(self, event_id):
        """Kunci per kode naskah yang dipakai menilai lembar event ini: dari paket yang dipilih event; event lama
        yang belum memilih paket memakai kunci per event versi sebelumnya. Kode yang kuncinya belum lengkap
        (masih ada nomor tanpa kunci A-E) tidak ikut, jadi lembarnya belum dinilai."""
        ev = self.event(event_id)
        if ev is not None and ev["paket_id"] is not None and self.paket(ev["paket_id"]) is not None:
            return [s for s in self.paket_naskah(ev["paket_id"]) if kunci_lengkap(s.kunci)]
        return self.naskah_lama(event_id)

    def naskah_lama(self, event_id):
        """Kunci yang tersimpan langsung di event (sebelum ada paket kunci)."""
        rows = self.con.execute("SELECT kode, bidang, kunci, sumber FROM naskah WHERE event_id=? ORDER BY kode",
                                (event_id,)).fetchall()
        return [Soal(r["kode"], r["bidang"], r["kunci"], r["sumber"] or "") for r in rows]

    def set_event_paket(self, event_id, paket_id):
        with self.con:
            self.con.execute("UPDATE event SET paket_id=? WHERE id=?", (paket_id, event_id))

    def event_paket(self, event_id):
        """Paket kunci yang dipakai event, atau None."""
        ev = self.event(event_id)
        return self.paket(ev["paket_id"]) if ev is not None and ev["paket_id"] is not None else None

    # ---- paket kunci jawaban
    def pakets(self):
        """Semua paket + jumlah mata pelajaran & event pemakai, urut nama."""
        return self.con.execute(
            """SELECT p.id, p.nama, p.dibuat,
                      (SELECT COUNT(*) FROM mapel m WHERE m.paket_id = p.id) AS n_mapel,
                      (SELECT COUNT(*) FROM mapel_kode k WHERE k.paket_id = p.id) AS n_kode,
                      (SELECT COUNT(*) FROM event e WHERE e.paket_id = p.id) AS n_event
               FROM paket p ORDER BY p.nama COLLATE NOCASE""").fetchall()

    def paket(self, paket_id):
        return self.con.execute("SELECT * FROM paket WHERE id=?", (paket_id,)).fetchone()

    def paket_by_nama(self, nama):
        return self.con.execute("SELECT * FROM paket WHERE nama=? COLLATE NOCASE", (nama.strip(),)).fetchone()

    def add_paket(self, nama):
        """Paket baru; sqlite3.IntegrityError bila namanya sudah dipakai."""
        with self.con:
            return self.con.execute("INSERT INTO paket(nama) VALUES (?)", (nama.strip(),)).lastrowid

    def rename_paket(self, paket_id, nama):
        with self.con:
            self.con.execute("UPDATE paket SET nama=? WHERE id=?", (nama.strip(), paket_id))

    def delete_paket(self, paket_id):
        """Hapus paket beserta mata pelajaran & kode naskahnya; event pemakainya kembali tanpa paket."""
        with self.con:
            self.con.execute("UPDATE event SET paket_id=NULL WHERE paket_id=?", (paket_id,))
            self.con.execute("DELETE FROM paket WHERE id=?", (paket_id,))

    def paket_events(self, paket_id):
        """Event yang memakai paket ini (urut nama)."""
        return self.con.execute("SELECT id, nama, tanggal FROM event WHERE paket_id=? ORDER BY nama COLLATE NOCASE",
                                (paket_id,)).fetchall()

    def mapel(self, paket_id):
        """Mata pelajaran di paket: [{id, nama, kunci, sumber, catatan, kode: [..]}], urut kode naskah terkecil
        (mata pelajaran tanpa kode di akhir, urut nama)."""
        kode = {}
        for r in self.con.execute("SELECT mapel_id, kode FROM mapel_kode WHERE paket_id=?", (paket_id,)):
            kode.setdefault(r["mapel_id"], []).append(r["kode"])
        out = []
        for r in self.con.execute("SELECT * FROM mapel WHERE paket_id=?", (paket_id,)):
            ks = sorted(kode.get(r["id"], []), key=kode_sort)
            out.append({"id": r["id"], "nama": r["nama"], "kunci": r["kunci"], "sumber": r["sumber"] or "",
                        "catatan": r["catatan"] or "", "kode": ks})
        out.sort(key=lambda m: (not m["kode"], kode_sort(m["kode"][0]) if m["kode"] else (0, 0), m["nama"].casefold()))
        return out

    def mapel_by_id(self, mapel_id):
        return self.con.execute("SELECT * FROM mapel WHERE id=?", (mapel_id,)).fetchone()

    def add_mapel(self, paket_id, nama, kunci, sumber="", catatan=""):
        with self.con:
            return self.con.execute("INSERT INTO mapel(paket_id, nama, kunci, sumber, catatan) VALUES (?, ?, ?, ?, ?)",
                                    (paket_id, nama.strip(), kunci, sumber, catatan)).lastrowid

    def update_mapel(self, mapel_id, nama, kunci, sumber=None, catatan=None):
        """Ubah nama & kunci (sumber/catatan hanya bila diberikan; catatan impor dihapus saat kunci diedit manual)."""
        sets, args = ["nama=?", "kunci=?"], [nama.strip(), kunci]
        if sumber is not None:
            sets.append("sumber=?")
            args.append(sumber)
        if catatan is not None:
            sets.append("catatan=?")
            args.append(catatan)
        with self.con:
            self.con.execute(f"UPDATE mapel SET {', '.join(sets)} WHERE id=?", (*args, mapel_id))

    def delete_mapel(self, mapel_id):
        with self.con:
            self.con.execute("DELETE FROM mapel WHERE id=?", (mapel_id,))

    def kode_owner(self, paket_id, kode):
        """Mata pelajaran pemilik kode naskah ini di paket, atau None."""
        return self.con.execute("SELECT m.* FROM mapel_kode k JOIN mapel m ON m.id = k.mapel_id "
                                "WHERE k.paket_id=? AND k.kode=?", (paket_id, kode.strip())).fetchone()

    def add_kode(self, paket_id, mapel_id, kode):
        """Tambah kode naskah ke mata pelajaran; sqlite3.IntegrityError bila kode sudah dipakai di paket ini."""
        with self.con:
            self.con.execute("INSERT INTO mapel_kode(paket_id, mapel_id, kode) VALUES (?, ?, ?)",
                             (paket_id, mapel_id, kode.strip()))

    def rename_kode(self, paket_id, old, new):
        with self.con:
            self.con.execute("UPDATE mapel_kode SET kode=? WHERE paket_id=? AND kode=?", (new.strip(), paket_id, old))

    def delete_kode(self, paket_id, kode):
        with self.con:
            self.con.execute("DELETE FROM mapel_kode WHERE paket_id=? AND kode=?", (paket_id, kode))

    def paket_naskah(self, paket_id):
        """Semua kode naskah paket sebagai Soal(kode, nama mata pelajaran, kunci, sumber), urut kode."""
        rows = self.con.execute("SELECT k.kode, m.nama, m.kunci, m.sumber FROM mapel_kode k "
                                "JOIN mapel m ON m.id = k.mapel_id WHERE k.paket_id=?", (paket_id,)).fetchall()
        out = [Soal(r["kode"], r["nama"], r["kunci"], r["sumber"] or "") for r in rows]
        return sorted(out, key=lambda s: kode_sort(s.kode))

    def set_naskah(self, event_id, soal_list):
        with self.con:
            self.con.execute("DELETE FROM naskah WHERE event_id=?", (event_id,))
            self.con.executemany(
                "INSERT INTO naskah(event_id, kode, bidang, kunci, sumber) VALUES (?, ?, ?, ?, ?)",
                [(event_id, s.kode, s.bidang, s.kunci, s.sumber) for s in soal_list])

    # ---- lembar
    def lembar(self, event_id):
        return self.con.execute("SELECT * FROM lembar WHERE event_id=? ORDER BY urutan", (event_id,)).fetchall()

    def lembar_by_id(self, lembar_id):
        return self.con.execute("SELECT * FROM lembar WHERE id=?", (lembar_id,)).fetchone()

    def files(self, event_id):
        return {r["file"] for r in self.con.execute("SELECT file FROM lembar WHERE event_id=?", (event_id,))}

    def next_urutan(self, event_id):
        r = self.con.execute("SELECT COALESCE(MAX(urutan), 0) FROM lembar WHERE event_id=?", (event_id,)).fetchone()
        return r[0] + 1

    def _beku_baru(self, event_id, kode):
        """Kunci yang berlaku sekarang untuk kode ini di event (JSON untuk soal_beku), atau None."""
        return beku_json({s.kode: s for s in self.naskah(event_id)}.get(kode))

    def add_lembar(self, event_id, urutan, rec):
        """Simpan hasil baca. Lembar yang dibaca ulang (file sama) tetap memakai kunci & waktu scan pertamanya
        selama kode naskahnya sama; lembar baru dibekukan dengan kunci yang berlaku sekarang."""
        old = self.con.execute("SELECT soal_beku, dipindai FROM lembar WHERE event_id=? AND file=?",
                               (event_id, rec["file"])).fetchone()
        kode = rec.get("kode", "")
        beku = old["soal_beku"] if old is not None else None
        if not rec.get("error") and soal_beku(beku, kode) is None:
            beku = self._beku_baru(event_id, kode)
        # waktu scan pertama tidak berubah saat dibaca ulang (lembar dari versi lama tetap kosong)
        dipindai = (old["dipindai"] or "") if old is not None else sekarang()
        with self.con:
            self.con.execute(
                """INSERT OR REPLACE INTO lembar(event_id, urutan, file, error, nama, nomor, kode, tanggal,
                   jawaban, baca, dicek, gambar, potongan, server_id, server, server_dicek, soal_beku, dipindai)
                   VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,0,?,?)""",
                (event_id, urutan, rec["file"], rec.get("error", ""), rec.get("nama", ""), rec.get("nomor", ""),
                 kode, rec.get("tanggal", ""), json.dumps(rec.get("jawaban", [])),
                 json.dumps(rec.get("baca", {})), rec.get("gambar", ""), json.dumps(rec.get("potongan", {})),
                 rec.get("server_id"), json.dumps(rec.get("server") or {}), beku, dipindai))

    # ---- nilai beku
    def bekukan_belum(self, event_id=None):
        """Bekukan lembar yang belum punya kunci beku (kodenya belum ada di kunci saat di-scan, atau lembar dari
        versi sebelum nilai beku) dengan kunci yang berlaku sekarang. Mengembalikan jumlah lembar."""
        ids = [event_id] if event_id is not None else [e["id"] for e in self.events()]
        n = 0
        for eid in ids:
            rows = self.con.execute("SELECT id, kode FROM lembar WHERE event_id=? AND soal_beku IS NULL "
                                    "AND COALESCE(error, '') = ''", (eid,)).fetchall()
            if not rows:
                continue
            naskah = {s.kode: s for s in self.naskah(eid)}
            upd = [(beku_json(naskah[r["kode"]]), r["id"]) for r in rows if r["kode"] in naskah]
            if upd:
                with self.con:
                    self.con.executemany("UPDATE lembar SET soal_beku=? WHERE id=?", upd)
                n += len(upd)
        return n

    def hitung_ulang(self, event_id, kodes=None):
        """Ganti kunci beku lembar event (semua, atau hanya kode naskah di `kodes`) dengan kunci yang berlaku
        sekarang. Mengembalikan jumlah lembar yang kuncinya berubah."""
        naskah = {s.kode: s for s in self.naskah(event_id)}
        rows = self.con.execute("SELECT id, kode, soal_beku FROM lembar WHERE event_id=?", (event_id,)).fetchall()
        upd = []
        for r in rows:
            if kodes is not None and r["kode"] not in kodes:
                continue
            baru = beku_json(naskah.get(r["kode"]))
            lama = soal_beku(r["soal_beku"], r["kode"])
            now = naskah.get(r["kode"])
            beda = (lama is None) != (now is None) or (lama is not None and (lama.kunci, lama.bidang) != (now.kunci, now.bidang))
            if beda or (r["soal_beku"] is not None and baru is None):
                upd.append((baru, r["id"]))
        if upd:
            with self.con:
                self.con.executemany("UPDATE lembar SET soal_beku=? WHERE id=?", upd)
        return len(upd)

    # ---- sinkron server
    def server_ids(self, event_id):
        return {r[0] for r in self.con.execute("SELECT server_id FROM lembar WHERE event_id=? AND server_id IS NOT NULL",
                                               (event_id,))}

    def dicek_unsynced(self, event_id):
        """server_id lembar yang sudah dicek di desktop tapi belum dilaporkan ke server."""
        return [r[0] for r in self.con.execute(
            "SELECT server_id FROM lembar WHERE event_id=? AND server_id IS NOT NULL AND dicek=1 AND server_dicek=0",
            (event_id,))]

    def mark_server_dicek(self, event_id, server_ids):
        with self.con:
            self.con.executemany("UPDATE lembar SET server_dicek=1 WHERE event_id=? AND server_id=?",
                                 [(event_id, i) for i in server_ids])

    def save_review(self, lembar_id, nama, nomor, kode, tanggal, jawaban, dicek=True):
        """Simpan hasil cek manual. Kode naskah dikoreksi (atau lembar belum punya kunci beku): kunci kode itu
        yang berlaku sekarang dibekukan; kode sama: kunci beku lembar tidak berubah."""
        row = self.lembar_by_id(lembar_id)
        beku = row["soal_beku"] if row is not None else None
        if row is not None and soal_beku(beku, kode) is None:
            beku = self._beku_baru(row["event_id"], kode)
        with self.con:
            self.con.execute("UPDATE lembar SET nama=?, nomor=?, kode=?, tanggal=?, jawaban=?, dicek=?, server_dicek=0, "
                             "soal_beku=? WHERE id=?",
                             (nama, nomor, kode, tanggal, json.dumps(jawaban), int(dicek), beku, lembar_id))

    def rebase_paths(self, old, new):
        """Ganti awalan path gambar & potongan (dipakai saat folder data dipindah)."""
        old_j, new_j = json.dumps(old)[1:-1], json.dumps(new)[1:-1]
        rows = self.con.execute("SELECT id, gambar, potongan FROM lembar").fetchall()
        with self.con:
            for r in rows:
                g = r["gambar"] or ""
                if g.startswith(old):
                    g = new + g[len(old):]
                p = (r["potongan"] or "{}").replace(old_j, new_j)
                self.con.execute("UPDATE lembar SET gambar=?, potongan=? WHERE id=?", (g, p, r["id"]))

    def delete_lembar(self, lembar_ids):
        with self.con:
            self.con.executemany("DELETE FROM lembar WHERE id=?", [(i,) for i in lembar_ids])

    # ---- label bulatan (untuk melatih model)
    def set_label(self, file, idx, label):
        with self.con:
            if label is None:
                self.con.execute("DELETE FROM label_bulatan WHERE file=? AND idx=?", (file, idx))
            else:
                self.con.execute("INSERT OR REPLACE INTO label_bulatan(file, idx, label, waktu) "
                                 "VALUES (?, ?, ?, CURRENT_TIMESTAMP)", (file, idx, label))

    def labels(self):
        """{(file, idx): label} semua label panitia."""
        return {(r["file"], r["idx"]): r["label"] for r in self.con.execute("SELECT file, idx, label FROM label_bulatan")}

    def all_lembar(self):
        return self.con.execute("SELECT * FROM lembar ORDER BY event_id, urutan").fetchall()
