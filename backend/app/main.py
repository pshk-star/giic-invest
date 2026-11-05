"""Punto de entrada FastAPI de GIIC."""
from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .config import get_settings
from .api import (routes_auth, routes_health, routes_market, routes_portfolio,
                  routes_scanner)
from .api.deps import get_current_user
from .db.session import SessionLocal, init_db

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="CIO cuantitativo personal — Fase 1 endurecida: autenticación, "
                "scanner escalable (caché incremental + lotes + rate limit), "
                "calidad de datos y soporte internacional (FX, obsolescencia).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rutas públicas: salud y login. El resto exige token válido.
app.include_router(routes_health.router)
app.include_router(routes_auth.router)
_auth = [Depends(get_current_user)]
app.include_router(routes_portfolio.router, dependencies=_auth)
app.include_router(routes_market.router, dependencies=_auth)
app.include_router(routes_scanner.router, dependencies=_auth)


def _seed_admin():
    """Crea el usuario admin desde variables de entorno si no hay usuarios."""
    from .db.models import UserRow
    from .security import hash_password
    if not settings.admin_password:
        return
    db = SessionLocal()
    try:
        if db.scalar(select(UserRow).limit(1)) is None:
            db.add(UserRow(username=settings.admin_username,
                           password_hash=hash_password(settings.admin_password)))
            db.commit()
    finally:
        db.close()


@app.on_event("startup")
def _startup():
    settings.require_valid_secret()           # falla rápido si prod mal configurado
    if settings.database_url.startswith("sqlite"):
        init_db()
    _seed_admin()


@app.get("/")
def root():
    return {"name": settings.app_name, "docs": "/docs", "health": "/health"}
