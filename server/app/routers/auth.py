"""Login dan profil."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..security import check_password, current_user, hash_password, make_token
from ..serial import user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    lama: str
    baru: str


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(M.User).where(M.User.username == body.username.strip()))
    if u is None or not check_password(body.password, u.password_hash):
        raise HTTPException(401, "Username atau kata sandi salah.")
    if not u.aktif:
        raise HTTPException(403, "Akun ini dinonaktifkan. Hubungi superadmin.")
    return {"token": make_token(u), "user": user_out(u)}


@router.get("/me")
def me(user: M.User = Depends(current_user)):
    return user_out(user)


@router.post("/password")
def change_password(body: PasswordIn, user: M.User = Depends(current_user), db: Session = Depends(get_db)):
    if not check_password(body.lama, user.password_hash):
        raise HTTPException(400, "Kata sandi lama salah.")
    if len(body.baru) < 6:
        raise HTTPException(400, "Kata sandi baru minimal 6 karakter.")
    user.password_hash = hash_password(body.baru)
    db.commit()
    return {"ok": True}
