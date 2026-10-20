"""Pengaturan server, dibaca dari variabel lingkungan atau berkas server/.env."""
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # folder server/


def _load_env():
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

DB_URL = os.environ.get("LJK_DB_URL", "mysql+pymysql://root:root@localhost:3306/ljk_online?charset=utf8mb4")
DATA_DIR = Path(os.environ.get("LJK_DATA_DIR", str(ROOT / "data")))
# Mesin pembaca LJK yang sama dengan aplikasi desktop (folder berisi paket ljk/)
LJK_PATH = Path(os.environ.get("LJK_ENGINE_PATH", str(ROOT.parent / "engine")))
# Tampilan web (halaman HP admin daerah, panel superadmin) yang disajikan server
WEB_DIR = Path(os.environ.get("LJK_WEB_DIR", str(ROOT.parent / "web")))
SECRET = os.environ.get("LJK_SECRET") or ""
TOKEN_HOURS = int(os.environ.get("LJK_TOKEN_HOURS", "72"))
MAX_UPLOAD_MB = int(os.environ.get("LJK_MAX_UPLOAD_MB", "25"))
READ_WORKERS = int(os.environ.get("LJK_READ_WORKERS", "2"))   # foto yang dibaca bersamaan

if not SECRET:
    # Kunci tanda tangan token disimpan di data/, supaya login tidak putus tiap server dimulai ulang.
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    kf = DATA_DIR / ".secret"
    if not kf.exists():
        kf.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    SECRET = kf.read_text(encoding="utf-8").strip()
