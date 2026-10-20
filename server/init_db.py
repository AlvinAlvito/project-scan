"""Siapkan database: buat database MySQL (bila belum ada), tabel, dan akun superadmin.

Pakai:
    .venv\\Scripts\\python init_db.py                       # buat DB + tabel
    .venv\\Scripts\\python init_db.py --superadmin admin     # + akun superadmin (kata sandi ditanya)
    .venv\\Scripts\\python init_db.py --superadmin admin --password <kata-sandi>
"""
import argparse
import getpass

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from app.config import DB_URL


def ensure_database():
    url = make_url(DB_URL)
    name = url.database
    server = create_engine(url.set(database=""), future=True)
    with server.connect() as c:
        c.execute(text(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    server.dispose()
    print(f"Database '{name}' siap.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--superadmin", help="username superadmin yang dibuat/diperbarui")
    ap.add_argument("--password")
    ap.add_argument("--nama", default="Superadmin")
    a = ap.parse_args()

    ensure_database()
    from app import models as M
    from app.db import Base, SessionLocal, engine
    from app.security import hash_password
    Base.metadata.create_all(engine)
    print("Tabel siap.")
    if a.superadmin:
        pw = a.password or getpass.getpass("Kata sandi superadmin: ")
        if len(pw) < 6:
            raise SystemExit("Kata sandi minimal 6 karakter.")
        with SessionLocal() as db:
            u = db.scalar(select(M.User).where(M.User.username == a.superadmin))
            if u is None:
                u = M.User(username=a.superadmin, nama=a.nama)
                db.add(u)
            u.peran, u.aktif, u.password_hash = M.SUPERADMIN, True, hash_password(pw)
            db.commit()
        print(f"Superadmin '{a.superadmin}' siap.")


if __name__ == "__main__":
    main()
