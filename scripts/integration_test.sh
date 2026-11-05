#!/usr/bin/env bash
# Prueba de integración del stack completo con Docker Compose:
# levanta Postgres + backend + frontend, espera a /health, corre las pruebas de
# stack (auth obligatoria, login, cartera, scanner) y derriba todo al final.
#
# Uso:
#   ./scripts/integration_test.sh
# Variables (o .env en la raíz): POSTGRES_PASSWORD, SECRET_KEY, ADMIN_PASSWORD.
set -euo pipefail
cd "$(dirname "$0")/.."

# Valores de prueba si no hay .env (NO usar en producción).
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-test_pg_$(openssl rand -hex 6)}"
export SECRET_KEY="${SECRET_KEY:-$(openssl rand -hex 32)}"
export ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-Test-Admin-123!}"
export DATA_PROVIDER="${DATA_PROVIDER:-sample}"

echo "==> Levantando stack…"
docker compose up -d --build

cleanup() { echo "==> Derribando stack…"; docker compose down -v; }
trap cleanup EXIT

echo "==> Esperando /health…"
for i in $(seq 1 40); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    echo "   backend listo."
    break
  fi
  sleep 3
  [ "$i" = "40" ] && { echo "backend no respondió"; docker compose logs backend; exit 1; }
done

echo "==> Corriendo pruebas de stack…"
GIIC_STACK_URL=http://localhost:8000 \
GIIC_ADMIN_USER="$ADMIN_USERNAME" \
GIIC_ADMIN_PASS="$ADMIN_PASSWORD" \
docker compose exec -T backend pytest tests/integration/test_stack.py -v

echo "==> Prueba de integración OK."
