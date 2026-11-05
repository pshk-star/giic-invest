"""Motor y fábrica de sesiones de SQLAlchemy."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from .base import Base

settings = get_settings()

# check_same_thread solo aplica a SQLite (desarrollo).
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def init_db() -> None:
    """Crea las tablas si no existen (dev). En producción usar las migraciones Alembic."""
    from . import models  # noqa: F401  (registra los modelos en el metadata)
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependencia FastAPI: sesión por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
