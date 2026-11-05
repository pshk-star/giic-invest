# GIIC — Global Investment Intelligence Console

CIO cuantitativo personal.

> ## ▶ v0.3 — despliegue gratuito (US$0, sin tarjeta, sin tu PC encendida)
> La forma recomendada de usar GIIC es la **arquitectura gratuita**:
> **Cloudflare Pages** (web) + **Supabase** (datos + login) + **GitHub Actions**
> (scanner diario), con datos reales de **Stooq + SEC EDGAR + Frankfurter**.
> **Guía paso a paso para principiantes: [`DEPLOY_FREE.md`](DEPLOY_FREE.md).**
> Límites verificados de cada servicio: [`FREE_TIER_LIMITS.md`](FREE_TIER_LIMITS.md).
> Cambios de esta versión: [`CHANGES.md`](CHANGES.md).
>
> El backend **FastAPI + SQLAlchemy** descrito más abajo sigue incluido, pero ahora es
> **opcional / solo para desarrollo local**; producción no necesita servidor permanente.

La lógica cuantitativa se entrega como repositorio con **React + TypeScript**
(frontend, en Cloudflare Pages), un **núcleo Python** reutilizado por un **job
programado** (GitHub Actions), y conectores de datos intercambiables. FastAPI +
SQLAlchemy + PostgreSQL quedan como ruta local opcional.

Lee `ARCHITECTURE.md` para la arquitectura, el proveedor de datos, los costos y el
roadmap por fases.

---

## Estado honesto de cada componente (Fase 1)

> **v0.2 — endurecimiento previo a despliegue.** Ver `CHANGES.md` para el resumen
> completo. Añade autenticación obligatoria, scanner escalable (caché incremental +
> lotes + rate limit), validación de calidad de datos y soporte internacional (FX,
> obsolescencia, tickers por bolsa). **73 pruebas unitarias en verde** + integración.

| Componente | Estado | Nota |
|------------|--------|------|
| Núcleo cuantitativo (indicadores, analítica de cartera, scanner) | ✅ **Implementado y probado** | parte de 73 pruebas pytest en verde |
| Seguridad (auth JWT, hashing PBKDF2, fuerza de contraseña) | ✅ **Implementada y probada** | toda la API exige token |
| Scanner escalable (caché incremental, lotes, rate limit) | ✅ **Implementado y probado** | escala a miles de instrumentos |
| Calidad de datos (validación múltiplos, cobertura, ranking sectorial) | ✅ **Implementada y probada** | datos implausibles se anulan con motivo |
| Datos internacionales (FX, obsolescencia, tickers por bolsa) | ✅ **Implementados y probados** | sin tasa FX → marcado, nunca 1:1 |
| Look-through de ETF (exposición efectiva real a cada subyacente) | ✅ **Implementado y probado** | Responde cuánta NVDA cargas vía NVDA+QQQ+SMH+VOO |
| Conector `sample` (offline, datos de EJEMPLO marcados) | ✅ **Funciona sin claves** | Para probar la app de inmediato |
| Conector EODHD / FMP (datos reales) | ✅ **Implementado** · ⚠️ requiere tu API key y despliegue | No se pudo ejecutar contra la red en el entorno de construcción |
| API FastAPI (health, portfolio, market, scanner) | ✅ **Implementada** · verificada en sintaxis | Se ejecuta al instalar dependencias (ver abajo) |
| Base de datos + migraciones Alembic | ✅ **Implementada** | SQLite en dev, Postgres en prod |
| Frontend (3 pantallas) | ✅ **Implementado** | Requiere `npm install` para compilar/servir |
| Motor predictivo, backtesting, decision engine, automatización diaria | ⏳ **Fases 2–8** | Diseñados en la arquitectura; aún no construidos |

> El núcleo se probó en verde en el entorno de construcción. La capa web/DB y el
> frontend no se pudieron **ejecutar** ahí porque el entorno no permitía instalar
> FastAPI/Node ni salir a los proveedores de datos; se entregan verificados en
> sintaxis y listos para correr con los pasos de abajo.

---

## Arranque rápido (todo en Docker)

```bash
cd giic
cp .env.docker.example .env     # OBLIGATORIO: rellena POSTGRES_PASSWORD, SECRET_KEY, ADMIN_PASSWORD
# Para datos reales, en el mismo .env: DATA_PROVIDER=eodhd y EODHD_API_KEY=tu_clave
docker compose up --build
```

- Frontend: http://localhost:8080
- API + documentación interactiva: http://localhost:8000/docs
- La base Postgres y las migraciones se aplican solas al levantar el backend.
- **Seguridad:** el arranque falla si faltan los secretos. PostgreSQL no se expone;
  backend y frontend escuchan solo en 127.0.0.1.

## Autenticación

Toda la API (salvo `/health` y `/auth/login`) exige un token Bearer.

```bash
# 1) login (usuario/clave admin del .env)
curl -s -X POST http://localhost:8000/auth/login \
  -d "username=admin&password=TU_ADMIN_PASSWORD" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])"
# 2) usar el token
curl -s http://localhost:8000/portfolio/positions -H "Authorization: Bearer <TOKEN>"
```
El frontend maneja el login y guarda el token automáticamente.

---

## Desarrollo local (sin Docker)

### Backend
```bash
cd giic/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # ajusta DATA_PROVIDER, claves y SECRET_KEY/ADMIN_PASSWORD
pytest -q                       # 73 pruebas deben pasar
uvicorn app.main:app --reload   # API en http://localhost:8000
```
Con `DATABASE_URL` SQLite (default) las tablas se crean solas. Con Postgres:
```bash
alembic upgrade head
```

### Frontend
```bash
cd giic/frontend
npm install
cp .env.example .env            # VITE_API_URL=http://localhost:8000
npm run dev                     # http://localhost:5173
```

---

## Cargar tu cartera

Tres formas:
1. **UI:** pestaña «Mi Cartera» → formulario «Agregar posición».
2. **CSV:** botón «Importar CSV». Columnas mínimas `ticker,quantity,avg_cost`;
   opcionales `opened_at,currency,asset_class,sector,name,country`.
3. **API:** `POST /portfolio/positions` (ver `/docs`).

Ejemplo de CSV:
```csv
ticker,quantity,avg_cost,asset_class,sector,currency
NVDA,10,100.64,equity,Semiconductores,USD
QQQ,15,480,etf,ETF,USD
SMH,8,260,etf,ETF,USD
```

---

## Endpoints principales

| Método | Ruta | Qué hace |
|--------|------|----------|
| GET | `/health` | Estado y proveedor activo (público) |
| POST | `/auth/login` | Login, devuelve token JWT (público) |
| GET | `/auth/me` | Usuario autenticado |
| GET/POST/DELETE | `/portfolio/positions` | CRUD de posiciones |
| POST | `/portfolio/import` | Importa CSV |
| GET/PUT | `/portfolio/settings` | Capital, aportes, límites de riesgo |
| GET | `/portfolio/analysis` | Valuación, distribución, **look-through**, concentración |
| GET | `/market/quote/{t}` · `/market/history/{t}` · `/market/snapshot/{t}` | Datos e indicadores por instrumento |
| POST | `/scanner/run` | Scanner multifactor (universo o cartera) |

---

## Despliegue sugerido

- **Backend + Postgres:** Render, Railway o Fly.io. Define `DATABASE_URL`,
  `DATA_PROVIDER`, `EODHD_API_KEY`. Corre `alembic upgrade head` en el release.
- **Frontend:** Vercel o Netlify. Define `VITE_API_URL` apuntando al backend.
- **Automatización diaria (Fase 8):** GitHub Actions o el cron del hosting que
  dispare el pipeline de actualización.

Nunca subas `.env` ni tus claves al repositorio (ver `.gitignore`).
