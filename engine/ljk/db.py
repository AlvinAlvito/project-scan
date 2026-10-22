"""Penyimpanan data aplikasi (SQLite): event, kunci per kode naskah, dan lembar LJK."""
import json
import sqlite3
from pathlib import Path

from .nilai import Soal

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
                                    "server_bidang": "TEXT DEFAULT '[]'"})
        self._add_columns("lembar", {"server_id": "INTEGER", "server": "TEXT DEFAULT '{}'",
                                     "server_dicek": "INTEGER DEFAULT 0"})

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

    # ---- kunci
    def naskah(self, event_id):
        rows = self.con.execute("SELECT kode, bidang, kunci, sumber FROM naskah WHERE event_id=? ORDER BY kode",
                                (event_id,)).fetchall()
        return [Soal(r["kode"], r["bidang"], r["kunci"], r["sumber"] or "") for r in rows]

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

    def add_lembar(self, event_id, urutan, rec):
        with self.con:
            self.con.execute(
                """INSERT OR REPLACE INTO lembar(event_id, urutan, file, error, nama, nomor, kode, tanggal,
                   jawaban, baca, dicek, gambar, potongan, server_id, server, server_dicek)
                   VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,0)""",
                (event_id, urutan, rec["file"], rec.get("error", ""), rec.get("nama", ""), rec.get("nomor", ""),
                 rec.get("kode", ""), rec.get("tanggal", ""), json.dumps(rec.get("jawaban", [])),
                 json.dumps(rec.get("baca", {})), rec.get("gambar", ""), json.dumps(rec.get("potongan", {})),
                 rec.get("server_id"), json.dumps(rec.get("server") or {})))

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
        with self.con:
            self.con.execute("UPDATE lembar SET nama=?, nomor=?, kode=?, tanggal=?, jawaban=?, dicek=?, server_dicek=0 "
                             "WHERE id=?", (nama, nomor, kode, tanggal, json.dumps(jawaban), int(dicek), lembar_id))

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
