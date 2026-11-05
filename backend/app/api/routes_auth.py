"""Autenticación: login que devuelve un token JWT. Toda la demás API lo exige."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import UserRow
from ..db.session import get_db
from ..security import create_access_token, verify_password
from .deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(UserRow).where(UserRow.username == form.username))
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas")
    s = get_settings()
    token = create_access_token(user.username, s.secret_key, s.access_token_expire_seconds)
    return {"access_token": token, "token_type": "bearer",
            "expires_in": s.access_token_expire_seconds}


@router.get("/me")
def me(current: UserRow = Depends(get_current_user)):
    return {"username": current.username, "is_active": bool(current.is_active)}
