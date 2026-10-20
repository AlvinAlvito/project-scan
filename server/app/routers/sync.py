"""Sinkron dengan aplikasi desktop (superadmin): tarik lembar baru, laporkan status dicek."""
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..security import superadmin
from ..serial import kompetisi_out, lembar_out

router = APIRouter(prefix="/api/sync", tags=["desktop"], dependencies=[Depends(superadmin)])


@router.get("/kompetisi")
def kompetisi(db: Session = Depends(get_db)):
    return [kompetisi_out(k, detail=True) for k in db.scalars(select(M.Kompetisi).order_by(M.Kompetisi.id.desc()))]


@router.get("/kompetisi/{kid}/lembar")
def pending(kid: int, semua: bool = False, db: Session = Depends(get_db)):
    """Lembar yang siap ditarik: sudah dikonfirmasi/ditandai admin daerah dan belum ditarik.
    semua=true: termasuk yang sudah pernah ditarik (untuk menarik ulang)."""
    cond = [M.Lembar.kompetisi_id == kid, M.Lembar.status.in_([M.DIKONFIRMASI, M.DITANDAI])]
    if not semua:
        cond.append(M.Lembar.ditarik_at.is_(None))
    menunggu = db.scalars(select(M.Lembar.id).where(M.Lembar.kompetisi_id == kid,
                                                    M.Lembar.status == M.MENUNGGU)).all()
    rows = db.scalars(select(M.Lembar).where(*cond).order_by(M.Lembar.id)).all()
    return {"items": [lembar_out(lb, detail=True) for lb in rows], "menunggu_konfirmasi": len(menunggu)}


class IdsIn(BaseModel):
    ids: list[int]


def _stamp(db, ids, field):
    now = datetime.now()
    rows = db.scalars(select(M.Lembar).where(M.Lembar.id.in_(ids))).all() if ids else []
    for lb in rows:
        setattr(lb, field, now)
    db.commit()
    return {"ok": True, "jumlah": len(rows)}


@router.post("/ditarik")
def mark_pulled(body: IdsIn, db: Session = Depends(get_db)):
    return _stamp(db, body.ids, "ditarik_at")


@router.post("/dicek")
def mark_checked(body: IdsIn, db: Session = Depends(get_db)):
    return _stamp(db, body.ids, "dicek_at")
