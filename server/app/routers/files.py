"""Gambar lembar (foto asli, gambar cek, potongan tulisan tangan) dengan pengecekan hak akses."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..security import current_user, require_lokasi

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/lembar/{lid}/{kind}")
def lembar_file(lid: int, kind: str, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    lb = db.get(M.Lembar, lid)
    if lb is None:
        raise HTTPException(404, "Lembar tidak ditemukan.")
    require_lokasi(user, lb.lokasi_id)
    if kind == "foto":
        path = lb.foto_path
    elif kind == "cek":
        path = lb.cek_path
    else:
        path = (lb.potongan or {}).get(kind)
    if not path or not Path(path).exists():
        raise HTTPException(404, "Gambar tidak tersedia.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
