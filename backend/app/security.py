"""Seguridad: hashing de contraseñas (PBKDF2-SHA256), tokens JWT HS256 y validación
de fuerza de contraseña. Implementado solo con la librería estándar para evitar
dependencias frágiles y poder probarlo de forma aislada.

El hashing usa PBKDF2-HMAC-SHA256 con sal por usuario. Los tokens son JWT HS256
estándar (header.payload.signature en base64url) firmados con SECRET_KEY.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional, Tuple

PBKDF2_ITERATIONS = 200_000
_ALG = "pbkdf2_sha256"


# ---------------- base64url ----------------
def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


# ---------------- contraseñas ----------------
def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    if not password:
        raise ValueError("contraseña vacía")
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_ALG}${iterations}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        alg, iters, salt_b64, hash_b64 = stored.split("$")
        if alg != _ALG:
            return False
        salt = _b64d(salt_b64)
        expected = _b64d(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str, min_length: int = 12) -> Tuple[bool, list[str]]:
    """Reglas: largo mínimo, mayúscula, minúscula, dígito y símbolo. Devuelve (ok, faltantes)."""
    problems = []
    if len(password) < min_length:
        problems.append(f"al menos {min_length} caracteres")
    if not any(c.islower() for c in password):
        problems.append("una minúscula")
    if not any(c.isupper() for c in password):
        problems.append("una mayúscula")
    if not any(c.isdigit() for c in password):
        problems.append("un dígito")
    if all(c.isalnum() for c in password):
        problems.append("un símbolo")
    return (len(problems) == 0, problems)


# ---------------- JWT HS256 ----------------
def create_access_token(subject: str, secret: str, expires_seconds: int = 3600,
                        now: Optional[int] = None, extra: Optional[dict] = None) -> str:
    if not secret:
        raise ValueError("SECRET_KEY no configurado")
    now = int(now if now is not None else time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": subject, "iat": now, "exp": now + expires_seconds}
    if extra:
        payload.update(extra)
    signing_input = f"{_b64e(json.dumps(header).encode())}.{_b64e(json.dumps(payload).encode())}"
    sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64e(sig)}"


def decode_token(token: str, secret: str, now: Optional[int] = None) -> dict:
    """Verifica firma y expiración. Lanza ValueError si el token es inválido/expirado."""
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise ValueError("token mal formado")
    signing_input = f"{header_b64}.{payload_b64}"
    expected = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64d(sig_b64)):
        raise ValueError("firma inválida")
    payload = json.loads(_b64d(payload_b64))
    now = int(now if now is not None else time.time())
    if "exp" in payload and now >= int(payload["exp"]):
        raise ValueError("token expirado")
    return payload
