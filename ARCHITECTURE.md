# GIIC — Arquitectura técnica

**Global Investment Intelligence Console** · CIO cuantitativo personal.

Este documento define la arquitectura **definitiva** del sistema. Cada componente
que se construye a partir de la Fase 1 encaja en esta estructura; nada es desechable.

---

## 1. Principio rector: dominio independiente del framework

La lógica de inversión (indicadores, analítica de cartera, scoring, y más adelante
modelos predictivos y backtesting) vive en `backend/app/core/`, como **funciones
puras sobre pandas/numpy**, sin dependencias de web ni de base de datos. Encima se
apoyan tres capas delgadas:

```
            ┌─────────────────────────────────────────────┐
  Frontend  │  React + TypeScript + Tailwind (Vite)        │  Pantallas / UX
            └───────────────▲─────────────────────────────┘
                            │ HTTP/JSON
            ┌───────────────┴─────────────────────────────┐
  API       │  FastAPI  (routers: portfolio, market,       │  Orquestación
            │           scanner, health)                   │
            └───────┬───────────────────────┬─────────────┘
                    │                        │
       ┌────────────▼──────────┐   ┌─────────▼─────────────┐
  Core │  app/core (PURO)      │   │  app/providers        │  Conectores de datos
       │  indicators / portfolio│   │  base + sample/eodhd/ │  (intercambiables)
       │  scanner / types       │   │  fmp                  │
       └────────────▲──────────┘   └─────────▲─────────────┘
                    │                        │
            ┌───────┴────────────────────────┴─────────────┐
  Datos     │  SQLAlchemy ORM + Postgres (cartera,          │  Persistencia
            │  operaciones, settings) · Alembic migraciones │
            └──────────────────────────────────────────────┘
```

**Por qué importa:** cambiar de proveedor de datos, o añadir un modelo predictivo,
no obliga a reescribir el resto. El núcleo se prueba sin levantar servidor (ver
`backend/tests/`, 86 pruebas en verde).

---

## 1b. Despliegue gratuito US$0 (v0.3) — sin servidor permanente

Se eliminó la dependencia de un backend FastAPI encendido 24/7. El mismo núcleo puro
ahora corre como **job programado**. Arquitectura seleccionada (justificación en
`FREE_TIER_LIMITS.md`):

```
   iPhone / navegador
          │ HTTPS
          ▼
  ┌───────────────────┐      lee/escribe (RLS)      ┌───────────────────────┐
  │  Cloudflare Pages │ ─────────────────────────▶ │  Supabase (Postgres +  │
  │  React + Supabase │   cartera privada por user  │  Auth + RLS)           │
  │  (analítica TS)   │ ◀───────────────────────── │  mercado/scan: lectura │
  └───────────────────┘   mercado + snapshots scan  └──────────▲────────────┘
                                                                │ service_role (escribe)
                                   cron diario                  │
                          ┌─────────────────────────┐           │
                          │  GitHub Actions          │ ──────────┘
                          │  app/jobs/run_scan.py    │
                          │  (núcleo v0.2 reutilizado)│
                          └───────────┬──────────────┘
                                      │ sin clave, gratis
            ┌──────────────┬──────────┴───────────┬───────────────┐
            ▼              ▼                       ▼               ▼
          Stooq        SEC EDGAR             Frankfurter      (futuro: más)
        precios EOD   fundamentales US          FX BCE
```

- **Frontend:** Cloudflare Pages (HTTPS, sin tarjeta, sin pausa).
- **Datos + Auth:** Supabase Free (RLS → cartera privada por `auth.uid()`).
- **Procesamiento:** GitHub Actions (cron). Repo de **código público** (sin secretos
  ni datos) para cron fiable y minutos ilimitados; los secretos van en GitHub Secrets,
  los datos privados en Supabase.
- **Reparto de cálculo:** el **scanner** (pesado, requiere todo el universo) corre en
  el job Python; la **analítica de cartera** (ligera, interactiva) corre en el
  navegador en TypeScript, portada fielmente del núcleo y con pruebas de paridad.
- **FastAPI:** opcional/local (desarrollo); no se usa en producción $0.

---

## 2. Proveedor de datos inicial

| Proveedor | Cobertura | Fundamentales | Holdings ETF | Costo aprox. | Rol en GIIC |
|-----------|-----------|---------------|--------------|--------------|-------------|
| **EODHD** | 70+ bolsas: US, EU, JP, TW, KR, HK, MX, CL, BR | Sí | Sí | **~US$20–100/mes** | **Primario (recomendado)** |
| FMP | US + internacional parcial | Sí | Sí | ~US$30–70/mes | Alternativo (implementado) |
| Polygon | US (excelente) | Limitado | No | ~US$30–200/mes | Futuro (US intradía) |
| Sample | — (ejemplo) | Ejemplo | Ejemplo | US$0 | Arranque/pruebas offline |

**Elección: EODHD como proveedor inicial.** Tu prioridad #1 es un scanner sobre el
universo bursátil mundial (US, Europa, Japón, Taiwán, Corea, HK, México, Chile,
Brasil). EODHD es el que mejor cubre esa lista con precios EOD + fundamentales +
holdings de ETF bajo una sola suscripción.

Los tres conectores implementan la **misma interfaz** (`providers/base.py`), así que
migrar a otro proveedor —o incorporar más adelante un dataset *point-in-time*
institucional (Sharadar, CRSP/Compustat) para backtesting sin sesgo de
supervivencia— es escribir una clase nueva, no rehacer el sistema.

### Planes concretos EODHD (referencia; verificar precios vigentes)
- **All World (EOD)** ~US$19.99/mes: precios diarios ajustados de todas las bolsas. Suficiente para cartera + scanner técnico.
- **Fundamentals Data** add-on: habilita el scoring fundamental del scanner.
- **All-In-One** ~US$99.99/mes: EOD + fundamentals + intradía (retrasado). Recomendado cuando el scanner fundamental entre en producción.

---

## 3. Costos de operación estimados (mensual)

| Partida | Arranque (EOD) | Producción (All-In-One) |
|---------|----------------|-------------------------|
| Datos (EODHD) | ~US$20 | ~US$100 |
| Hosting backend + Postgres (Render / Railway / Fly.io) | ~US$14 | ~US$25 |
| Frontend (Vercel / Netlify, free tier) | US$0 | US$0–20 |
| Scheduler diario (GitHub Actions / cron del hosting) | US$0 | US$0 |
| **Total** | **~US$34/mes** | **~US$125–145/mes** |

Datos point-in-time institucionales (fase de backtesting serio) son aparte y
costosos (cientos a miles de US$/año); se incorporan sólo cuando el backtesting lo
justifique, sin rediseñar el sistema.

---

## 4. Estructura del repositorio

```
giic/
├── ARCHITECTURE.md          ← este documento
├── README.md                ← cómo correr y desplegar + estado honesto por componente
├── docker-compose.yml       ← Postgres + backend + frontend en un comando
├── backend/
│   ├── app/
│   │   ├── core/            ← NÚCLEO PURO (probado): indicators, portfolio, scanner,
│   │   │                      quality, fx, symbols, types
│   │   ├── providers/       ← base + sample (offline) + eodhd + fmp
│   │   ├── services/        ← cache (incremental), rate_limiter, scan_engine
│   │   ├── db/              ← SQLAlchemy: base, models (+ users, caché), session
│   │   ├── api/             ← routers: health, auth, portfolio, market, scanner
│   │   ├── security.py      ← hashing PBKDF2 + JWT HS256 (stdlib)
│   │   ├── config.py        ← settings por entorno (.env)
│   │   └── main.py          ← app FastAPI (auth obligatoria)
│   ├── tests/               ← 34 pruebas del núcleo + SampleProvider (pytest)
│   ├── alembic/             ← migraciones de BD
│   ├── requirements.txt
│   └── Dockerfile
└── frontend/
    ├── src/
    │   ├── pages/           ← CommandCenter, Portfolio, Opportunities
    │   ├── components/      ← Panel, SampleBadge
    │   └── api/client.ts    ← cliente tipado del backend
    ├── package.json
    └── Dockerfile
```

---

## 5. Roadmap por fases

Cada fase entrega código funcional y probado; no se declara terminada sin pruebas.

| Fase | Contenido | Estado |
|------|-----------|--------|
| **0** | Arquitectura, proveedor, costos, estructura | ✅ **Entregada** (este doc) |
| **1** | **MVP:** cartera (CRUD + CSV), datos reales al desplegar, scanner multifactor, analítica con look-through de ETF | ✅ **Entregada** |
| **1.5** | **Endurecimiento:** autenticación obligatoria (JWT), scanner escalable (caché incremental + lotes + rate limit), calidad de datos (validación de múltiplos, cobertura, ranking sectorial), internacional (FX, obsolescencia, tickers), integración Docker/EODHD | ✅ **Entregada** (ver `CHANGES.md`) |
| **1.9** | **Arquitectura $0:** Cloudflare Pages + Supabase (RLS) + GitHub Actions; datos reales gratis (Stooq/EDGAR/Frankfurter); job programado; frontend Supabase; analítica TS con paridad; snapshots point-in-time; CI/CD; guías de despliegue | ✅ **Entregada** (ver `CHANGES.md`, `DEPLOY_FREE.md`) |
| 2 | Portfolio Intelligence ampliado: correlaciones, volatilidad de cartera, exposición por factor, drawdown histórico de la cartera | ⏳ Diseñado (funciones `correlation_matrix`, `portfolio_volatility` ya existen) |
| 3 | Scanner global a escala: universos por región, filtros guardados, evolución de rankings, persistencia de snapshots diarios | ⏳ |
| 4 | Backtesting y análogos históricos: walk-forward, costos/slippage, episodios comparables con distribuciones | ⏳ (requiere datos point-in-time para rigor pleno) |
| 5 | Motor predictivo: modelos probabilísticos calibrados (benchmarks simples → ML), con validación fuera de muestra | ⏳ |
| 6 | Investment Decision Engine: propuesta concreta (importe, horizonte, riesgo, vs. VOO/QQQ, vs. aumentar posición) sujeta a límites | ⏳ |
| 7 | Dashboard completo: las 8 pantallas del brief | ⏳ (3 en Fase 1) |
| 8 | Automatización diaria + prediction tracker (registro y calibración de cada predicción) | ⏳ |

---

## 6. Reglas de integridad (no negociables, incrustadas en el código)

- **Nada ficticio presentado como real.** Los datos de ejemplo salen marcados
  `is_sample=True` en cada estructura y con aviso visible en la UI (`SampleBadge`).
- **Dato faltante → None/NaN, nunca inventado.** Si el proveedor no entrega un campo
  o falla la API, se reporta; no se rellena.
- **Un score no es una probabilidad.** El scanner produce atractivo *relativo*
  (percentil transversal). Las probabilidades calibradas llegan sólo con el motor
  predictivo validado (Fase 5), con su evidencia de backtesting.
- **Ponderaciones del scanner = punto de partida, no verdad.** Quedan expuestas para
  calibrarse contra backtesting; el código lo declara explícitamente.
