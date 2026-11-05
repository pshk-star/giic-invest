"""Configuración de la aplicación, leída de variables de entorno / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "GIIC — Global Investment Intelligence Console"
    environment: str = "development"

    # Base de datos. SQLite por defecto para desarrollo local sin dependencias.
    # En producción: postgresql+psycopg://user:pass@host:5432/giic
    database_url: str = "sqlite:///./giic.db"

    # Proveedor de datos: "sample" (offline, ejemplo) | "eodhd" | "fmp"
    data_provider: str = "sample"
    eodhd_api_key: str = ""
    fmp_api_key: str = ""
    default_exchange: str = "US"

    # Moneda base de la cartera y FX (se puede sobreescribir por request).
    base_currency: str = "USD"

    # --- Seguridad ---
    # SECRET_KEY firma los tokens. En producción DEBE cambiarse (ver require_valid_secret()).
    secret_key: str = "dev-insecure-change-me"
    access_token_expire_seconds: int = 3600
    # Usuario admin sembrado al iniciar si la tabla de usuarios está vacía.
    admin_username: str = "admin"
    admin_password: str = ""   # vacío => no se siembra; se exige fijarlo en producción

    # --- Límites de API del proveedor (token bucket del scanner) ---
    provider_rate_per_min: float = 60.0
    scanner_batch_size: int = 50
    fundamentals_max_age_days: int = 7
    history_max_gap_days: int = 4

    # CORS: orígenes del frontend permitidos.
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    def require_valid_secret(self) -> None:
        """Falla rápido en producción si el secreto o el admin no se configuraron."""
        if self.is_production():
            if self.secret_key in ("", "dev-insecure-change-me"):
                raise RuntimeError("SECRET_KEY inseguro en producción: define uno fuerte.")
            if not self.admin_password:
                raise RuntimeError("ADMIN_PASSWORD no configurado en producción.")

    def provider_kwargs(self) -> dict:
        if self.data_provider == "eodhd":
            return {"api_key": self.eodhd_api_key, "default_exchange": self.default_exchange}
        if self.data_provider == "fmp":
            return {"api_key": self.fmp_api_key}
        return {}


@lru_cache
def get_settings() -> Settings:
    return Settings()
