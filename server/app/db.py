"""Koneksi database (SQLAlchemy). Dipakai sebagai dependency FastAPI: get_db()."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_URL

engine = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=3600, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def upgrade_schema():
    """Penyesuaian tabel yang sudah ada (create_all hanya membuat tabel baru, tidak mengubah yang lama).
    Aman dijalankan berulang dan oleh beberapa worker sekaligus.

    master_bidang: dulu nama bidang UNIK; sekarang nama boleh sama (yang unik kode naskah)."""
    if engine.dialect.name != "mysql":
        return
    insp = inspect(engine)
    if not insp.has_table("master_bidang"):
        return
    for ix in insp.get_indexes("master_bidang"):
        if ix.get("unique") and ix.get("column_names") == ["nama"]:
            try:
                with engine.begin() as c:
                    c.execute(text(f"ALTER TABLE master_bidang DROP INDEX `{ix['name']}`"))
            except OperationalError:
                pass        # sudah dihapus worker lain


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
