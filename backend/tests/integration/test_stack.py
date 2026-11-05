"""Prueba de integración del stack completo (API + PostgreSQL) ya levantado.

Se omite salvo que se exporte GIIC_STACK_URL apuntando al backend en marcha
(normalmente tras `docker compose up`). Usa solo la librería estándar (urllib) para
no añadir dependencias de prueba.

    docker compose up -d --build
    GIIC_STACK_URL=http://localhost:8000 \
    GIIC_ADMIN_USER=admin GIIC_ADMIN_PASS=... \
    pytest tests/integration/test_stack.py -v

Verifica: /health responde; la API exige autenticación (401 sin token); con login
válido se obtiene token y se accede a la cartera y al scanner.
"""
import json
import os
import urllib.parse
import urllib.request

import pytest

BASE = os.getenv("GIIC_STACK_URL")
USER = os.getenv("GIIC_ADMIN_USER", "admin")
PASS = os.getenv("GIIC_ADMIN_PASS", "")
pytestmark = pytest.mark.skipif(not BASE, reason="GIIC_STACK_URL no configurada (stack no levantado)")


def _get(path, token=None):
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def _login():
    data = urllib.parse.urlencode({"username": USER, "password": PASS}).encode()
    req = urllib.request.Request(BASE + "/auth/login", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())["access_token"]


def test_health_public():
    status, body = _get("/health")
    assert status == 200 and body["status"] == "ok"


def test_portfolio_requires_auth():
    status, _ = _get("/portfolio/positions")
    assert status == 401        # sin token => rechazado


@pytest.mark.skipif(not PASS, reason="GIIC_ADMIN_PASS no configurada")
def test_login_and_access():
    token = _login()
    assert token
    status, body = _get("/portfolio/positions", token)
    assert status == 200 and isinstance(body, list)


@pytest.mark.skipif(not PASS, reason="GIIC_ADMIN_PASS no configurada")
def test_scanner_authenticated():
    token = _login()
    req = urllib.request.Request(
        BASE + "/scanner/run", method="POST",
        data=json.dumps({"scope": "universe", "top": 5, "universe_limit": 20}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read().decode())
    assert "ranking" in body
