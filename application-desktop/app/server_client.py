"""Koneksi ke server LJK Reader Online (API superadmin). Tanpa paket tambahan: memakai urllib.

Alamat server, username, dan token login disimpan di QSettings; kata sandi tidak disimpan."""
import json
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QSettings

TIMEOUT = 30


class ServerError(Exception):
    pass


def _settings():
    return QSettings("POSI", "LJK Reader")


def config():
    s = _settings()
    return {"url": (s.value("server/url", "") or "").rstrip("/"), "username": s.value("server/username", ""),
            "token": s.value("server/token", ""), "nama": s.value("server/nama", "")}


def save_config(url=None, username=None, token=None, nama=None):
    s = _settings()
    for k, v in (("url", url), ("username", username), ("token", token), ("nama", nama)):
        if v is not None:
            s.setValue(f"server/{k}", v.rstrip("/") if k == "url" else v)


def logged_in():
    c = config()
    return bool(c["url"] and c["token"])


def _request(method, path, body=None, token=None, url=None, raw=False):
    c = config()
    base = (url or c["url"]).rstrip("/")
    if not base:
        raise ServerError("Alamat server belum diatur.")
    headers = {"Accept": "application/json"}
    tok = token if token is not None else c["token"]
    if tok:
        headers["Authorization"] = "Bearer " + tok
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            content = r.read()
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}").get("detail")
        except ValueError:
            detail = None
        if isinstance(detail, list):      # galat validasi FastAPI: daftar {loc, msg, ...}
            detail = "; ".join(d.get("msg", "") for d in detail if isinstance(d, dict)) or None
        if e.code == 401:
            save_config(token="")
            raise ServerError(detail or "Sesi server berakhir. Login lagi.")
        raise ServerError(detail or f"Server menjawab {e.code}.")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ServerError(f"Tidak bisa terhubung ke server: {getattr(e, 'reason', e)}")
    return content if raw else json.loads(content or b"{}")


def login(url, username, password):
    r = _request("POST", "/api/auth/login", {"username": username, "password": password}, token="", url=url)
    if r["user"]["peran"] != "superadmin":
        raise ServerError("Akun ini bukan superadmin. Aplikasi desktop hanya untuk panitia pusat.")
    save_config(url=url, username=username, token=r["token"], nama=r["user"]["nama"])
    return r["user"]


def logout():
    save_config(token="")


def kompetisi():
    return _request("GET", "/api/sync/kompetisi")


def get_kompetisi(kompetisi_id):
    return _request("GET", f"/api/admin/kompetisi/{kompetisi_id}")


def create_kompetisi(nama, tanggal):
    return _request("POST", "/api/admin/kompetisi", {"nama": nama, "tanggal": tanggal, "status": "aktif"})


def add_bidang(kompetisi_id, kode_naskah, nama, jumlah_soal):
    """Tambah satu bidang ke kompetisi server. Sengaja hanya kode, nama, dan jumlah soal:
    kunci jawaban tidak pernah dikirim ke server."""
    return _request("POST", f"/api/admin/kompetisi/{kompetisi_id}/bidang",
                    {"kode_naskah": kode_naskah, "nama": nama, "jumlah_soal": jumlah_soal})


def pending(kompetisi_id, semua=False):
    return _request("GET", f"/api/sync/kompetisi/{kompetisi_id}/lembar" + ("?semua=true" if semua else ""))


def mark_pulled(ids):
    return _request("POST", "/api/sync/ditarik", {"ids": list(ids)}) if ids else None


def mark_checked(ids):
    return _request("POST", "/api/sync/dicek", {"ids": list(ids)}) if ids else None


def download(url_path, dest):
    """Unduh satu file (mis. foto asli) ke dest. Dipanggil dari thread pekerja."""
    data = _request("GET", url_path, raw=True)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest


def meta(item):
    """Data server yang disimpan di lembar lokal (kolom 'server')."""
    hb = item.get("hasil_baca") or {}
    return {
        "id": item["id"], "kota": item.get("kota", ""), "uploader": item.get("uploader", ""),
        "status": item.get("status"), "skor_kualitas": item.get("skor_kualitas"), "keyakinan": item.get("keyakinan"),
        "catatan": item.get("catatan", []), "konfirmasi": item.get("konfirmasi") or {},
        "peserta_baru": item.get("peserta_baru"), "peserta_baru_status": item.get("peserta_baru_status"),
        "bidang": item.get("bidang"), "dibuat": item.get("dibuat"),
        "terbaca": {k: hb.get(k, "") for k in ("nama", "nomor", "kode")},
    }
