"""Dependencias compartidas de la API: autenticación, proveedor de datos y caché."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import UserRow
from ..db.session import get_db
from ..providers import MarketDataProvider, get_provider
from ..security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

_provider_cache: dict[str, MarketDataProvider] = {}


def get_market_provider() -> MarketDataProvider:
    """Devuelve el proveedor configurado. Cae a 'sample' si el real no tiene clave."""
    s = get_settings()
    key = s.data_provider
    if key in _provider_cache:
        return _provider_cache[key]
    try:
        provider = get_provider(s.data_provider, **s.provider_kwargs())
    except Exception:
        provider = get_provider("sample")  # arranque sin claves => datos de EJEMPLO
    _provider_cache[key] = provider
    return provider


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> UserRow:
    """Valida el JWT y devuelve el usuario. 401 si falta/expira/invalida."""
    s = get_settings()
    cred_exc = HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o expirado",
                             headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(token, s.secret_key)
    except ValueError:
        raise cred_exc
    username = payload.get("sub")
    if not username:
        raise cred_exc
    user = db.scalar(select(UserRow).where(UserRow.username == username))
    if user is None or not user.is_active:
        raise cred_exc
    return user
