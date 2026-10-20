"""Login: hash kata sandi (bcrypt), token JWT, dan dependency peran."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from . import models as M
from .config import SECRET, TOKEN_HOURS
from .db import get_db


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def make_token(user: M.User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode({"sub": str(user.id), "peran": user.peran, "exp": exp}, SECRET, algorithm="HS256")


def _token_from(request: Request, t: str | None):
    h = request.headers.get("Authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:]
    return t        # <img src> tidak bisa mengirim header, jadi token boleh lewat ?t=


def current_user(request: Request, t: str | None = Query(None), db: Session = Depends(get_db)) -> M.User:
    token = _token_from(request, t)
    if not token:
        raise HTTPException(401, "Silakan login dulu.")
    try:
        data = jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Sesi berakhir, silakan login lagi.")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Token tidak sah, silakan login lagi.")
    user = db.get(M.User, int(data["sub"]))
    if user is None or not user.aktif:
        raise HTTPException(401, "Akun tidak aktif.")
    return user


def superadmin(user: M.User = Depends(current_user)) -> M.User:
    if user.peran != M.SUPERADMIN:
        raise HTTPException(403, "Hanya superadmin.")
    return user


def lokasi_ids(user: M.User) -> set[int]:
    return {a.lokasi_id for a in user.akses}


def require_lokasi(user: M.User, lokasi_id: int):
    """Admin daerah hanya boleh mengakses lokasi miliknya; superadmin boleh semua."""
    if user.peran != M.SUPERADMIN and lokasi_id not in lokasi_ids(user):
        raise HTTPException(403, "Anda tidak punya akses ke lokasi ini.")
