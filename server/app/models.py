"""Tabel database (lihat dokumentasi/arsitektur-sistem.html, bagian Struktur database)."""
from datetime import datetime

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

SUPERADMIN, ADMIN_DAERAH = "superadmin", "admin_daerah"

# Status lembar di server
GAGAL = "gagal"                    # mesin tidak bisa membaca foto; admin diminta foto ulang
MENUNGGU = "menunggu"              # sudah dibaca, menunggu konfirmasi admin daerah
DIKONFIRMASI = "dikonfirmasi"      # admin daerah menyatakan hasil baca benar
DITANDAI = "ditandai"              # admin daerah memperbaiki data / peserta baru / ada catatan
STATUS = (GAGAL, MENUNGGU, DIKONFIRMASI, DITANDAI)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(120))
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    peran: Mapped[str] = mapped_column(String(20), default=ADMIN_DAERAH)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    dibuat: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    akses: Mapped[list["Akses"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Kompetisi(Base):
    __tablename__ = "kompetisi"
    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(160))
    tanggal: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default="aktif")      # aktif | selesai
    dibuat: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lokasi: Mapped[list["Lokasi"]] = relationship(back_populates="kompetisi", cascade="all, delete-orphan",
                                                  order_by="Lokasi.kota")
    bidang: Mapped[list["Bidang"]] = relationship(back_populates="kompetisi", cascade="all, delete-orphan",
                                                  order_by="Bidang.kode_naskah")


class Lokasi(Base):
    __tablename__ = "lokasi"
    id: Mapped[int] = mapped_column(primary_key=True)
    kompetisi_id: Mapped[int] = mapped_column(ForeignKey("kompetisi.id", ondelete="CASCADE"), index=True)
    kota: Mapped[str] = mapped_column(String(120))
    target_lembar: Mapped[int] = mapped_column(Integer, default=0)

    kompetisi: Mapped[Kompetisi] = relationship(back_populates="lokasi")
    akses: Mapped[list["Akses"]] = relationship(back_populates="lokasi", cascade="all, delete-orphan")


class Akses(Base):
    """Admin daerah boleh mengirim LJK untuk lokasi ini."""
    __tablename__ = "akses"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    lokasi_id: Mapped[int] = mapped_column(ForeignKey("lokasi.id", ondelete="CASCADE"), primary_key=True)

    user: Mapped[User] = relationship(back_populates="akses")
    lokasi: Mapped[Lokasi] = relationship(back_populates="akses")


class Bidang(Base):
    """Kode naskah + nama bidang. Kunci jawaban sengaja TIDAK disimpan di server."""
    __tablename__ = "bidang"
    __table_args__ = (UniqueConstraint("kompetisi_id", "kode_naskah"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kompetisi_id: Mapped[int] = mapped_column(ForeignKey("kompetisi.id", ondelete="CASCADE"), index=True)
    kode_naskah: Mapped[str] = mapped_column(String(10))
    nama: Mapped[str] = mapped_column(String(120))
    jumlah_soal: Mapped[int] = mapped_column(Integer, default=0)

    kompetisi: Mapped[Kompetisi] = relationship(back_populates="bidang")


class MasterBidang(Base):
    """Daftar bidang baku. Saat menambah bidang ke kompetisi cukup memilih dari sini;
    kode naskah & jumlah soal di sini hanya nilai awal yang boleh diubah per kompetisi."""
    __tablename__ = "master_bidang"
    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(120), unique=True)
    kode_naskah: Mapped[str] = mapped_column(String(10), default="")
    jumlah_soal: Mapped[int] = mapped_column(Integer, default=0)


class Peserta(Base):
    __tablename__ = "peserta"
    __table_args__ = (UniqueConstraint("kompetisi_id", "nomor"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kompetisi_id: Mapped[int] = mapped_column(ForeignKey("kompetisi.id", ondelete="CASCADE"), index=True)
    lokasi_id: Mapped[int | None] = mapped_column(ForeignKey("lokasi.id", ondelete="SET NULL"), nullable=True)
    nomor: Mapped[str] = mapped_column(String(30))
    nama: Mapped[str] = mapped_column(String(160))
    sekolah: Mapped[str] = mapped_column(String(160), default="")
    daftar_di_tempat: Mapped[bool] = mapped_column(Boolean, default=False)


class Lembar(Base):
    __tablename__ = "lembar"
    __table_args__ = (UniqueConstraint("kompetisi_id", "foto_hash"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kompetisi_id: Mapped[int] = mapped_column(ForeignKey("kompetisi.id", ondelete="CASCADE"), index=True)
    lokasi_id: Mapped[int] = mapped_column(ForeignKey("lokasi.id", ondelete="CASCADE"), index=True)
    bidang_id: Mapped[int] = mapped_column(ForeignKey("bidang.id", ondelete="RESTRICT"))
    peserta_id: Mapped[int | None] = mapped_column(ForeignKey("peserta.id", ondelete="SET NULL"), nullable=True)
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    foto_path: Mapped[str] = mapped_column(String(300))
    foto_hash: Mapped[str] = mapped_column(String(64))
    foto_ukuran: Mapped[str] = mapped_column(String(30), default="")          # "3072x4096"
    skor_kualitas: Mapped[int] = mapped_column(Integer, default=0)            # dari HP, 0-100
    metrik: Mapped[dict] = mapped_column(JSON, default=dict)                  # metrik kualitas dari HP
    kualitas_server: Mapped[dict] = mapped_column(JSON, default=dict)         # cek ulang di server
    hasil_baca: Mapped[dict] = mapped_column(JSON, default=dict)              # nama/nomor/kode/jawaban/...
    keyakinan: Mapped[int] = mapped_column(Integer, default=0)                # keyakinan baca 0-100
    catatan: Mapped[list] = mapped_column(JSON, default=list)                 # validasi server (teks)
    error: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default=MENUNGGU, index=True)
    konfirmasi: Mapped[dict] = mapped_column(JSON, default=dict)              # aksi admin daerah
    peserta_baru: Mapped[dict | None] = mapped_column(JSON, nullable=True)    # {nomor, nama, sekolah}
    # None | "diajukan" (menunggu persetujuan superadmin) | "disetujui"
    peserta_baru_status: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    cek_path: Mapped[str] = mapped_column(String(300), default="")            # gambar cek (lembar.jpg)
    potongan: Mapped[dict] = mapped_column(JSON, default=dict)                # potongan tulisan tangan

    dibuat: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    dikonfirmasi_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ditarik_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dicek_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lokasi: Mapped[Lokasi] = relationship()
    bidang: Mapped[Bidang] = relationship()
    peserta: Mapped[Peserta | None] = relationship()
    uploader: Mapped[User | None] = relationship()
