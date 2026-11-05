# GIIC — Resumen de cambios v0.3.2 (robustez de publicación)

Tres correcciones de robustez antes de publicar. Sin arquitectura nueva ni motor
predictivo. **Pruebas: 97 → 101 Python en verde**; integración de fuentes gratuitas
preparada (gated).

1. **`sample` fuera de producción.** El workflow `scan.yml` ya no ofrece opción de
   proveedor: siempre `free`. Además el job rechaza por diseño publicar datos de
   ejemplo. `sample` queda solo para pruebas locales/automatizadas
   (`selftest --provider sample`, tests).
2. **Frescura por proporción + cuarentena de obsoletos.** El motor excluye del ranking
   todo instrumento con precio obsoleto (`stale_excluded`) y calcula `fresh_fraction`.
   La validación exige que ≥70% del universo con precio esté actualizado; si no, no se
   publica. Pruebas: `test_fresh_fraction_blocks_low_proportion`,
   `test_stale_instruments_excluded_from_ranking`.
3. **Publicación atómica (pending/completed/failed).** Cada corrida nace `pending`;
   tras escribir todo se marca `completed`; si algo falla a mitad, `failed`. La vista
   `v_latest_scan` y el frontend solo consultan la última corrida **completed**, así un
   fallo intermedio nunca deja datos a medias a la vista. Lógica extraída a
   `publish_run` y probada con un writer simulado (`test_atomic_publish_marks_completed`,
   `test_atomic_publish_marks_failed_on_midway_error`).

Soporte añadido:
- **Integración en vivo** de Stooq/EDGAR/Frankfurter: `tests/integration/test_free_sources_live.py`
  (se activa con `RUN_LIVE_FREE=1` + `EDGAR_USER_AGENT`; no corre en el sandbox).
- **Verificación RLS:** `backend/supabase/rls_check.sql` + Parte G de `DEPLOY_FREE.md`
  para comprobar que la cartera es privada.
- **CI** (`ci.yml`) ejecuta TypeScript (`tsc`), Vitest y el build de React en cada push.

No ejecutado aquí (sin red ni `npm`): descargas reales, `tsc`/`vitest`/build del
frontend, y escritura real a Supabase. Se comprueban con los workflows **GIIC selftest**,
**CI** y la prueba en vivo. GIIC **no está publicado** hasta que lo abras y verifiques.

---

# GIIC — Resumen de cambios v0.3.1 (revisión previa a publicar)

Diez correcciones solicitadas, sin reconstruir y manteniendo US$0.
**Pruebas: 86 → 97 Python en verde**; harness E2E (`selftest`) ejecutado offline aquí
con éxito. No se afirma que las fuentes externas funcionen: su comprobación con datos
reales se hace con el workflow **GIIC selftest** (Parte D de `DEPLOY_FREE.md`).

1. **Sin registro público.** El frontend ya no ofrece "crear cuenta" (solo iniciar
   sesión y restablecer). Se documenta desactivar registros en Supabase y crear el
   único usuario desde el panel (DEPLOY_FREE C5–C6).
2. **Fecha real de cotización.** `prices.as_of` ahora es la fecha del dato del
   proveedor (última barra), no la fecha de ejecución del scanner
   (`scan_engine` + `run_scan`). Prueba: `test_prices_carry_real_data_date_not_run_date`.
3. **Producción no publica datos de ejemplo.** `run_scan` rechaza escribir si el
   proveedor es de ejemplo (guarda + validación). Prueba:
   `test_production_write_blocks_sample_provider`.
4. **No se publican rankings vacíos/incompletos/obsoletos.** Nuevo
   `app/jobs/validation.py`: exige datos reales, ranking no vacío, mínimo de
   instrumentos, al menos un factor fundamental con cobertura y precios frescos.
   7 pruebas en `tests/test_job_safety.py`.
5. **No sobrescribe datos válidos ante fallos de fuentes.** Si la validación falla, el
   job no escribe NADA (se conserva la corrida anterior); los upserts vacíos se omiten,
   así un fallo parcial de Stooq/EDGAR no borra precios buenos.
6. **Config de despliegue revisada.** `frontend/public/_redirects` para el ruteo SPA en
   Cloudflare Pages; DEPLOY_FREE con los campos exactos de build y las Redirect URLs de
   Supabase; alta de usuario único.
7. **TypeScript.** Añadidos `src/vite-env.d.ts` (tipos de `import.meta.env`) y exclusión
   de los tests del build. Revisión manual de tipos (no se pudo correr `tsc`/`npm` en el
   entorno de construcción; `ci.yml` ejecuta `tsc + vitest + build` en GitHub).
8. **Secretos no expuestos.** Los workflows pasan secretos solo por `env` del paso
   (GitHub los enmascara); el job imprime únicamente un JSON saneado y nunca vuelca el
   entorno ni las claves. Errores recortados a un mensaje seguro.
9. **E2E con datos reales antes de la cartera.** Nuevo `app/jobs/selftest.py` y workflow
   **GIIC selftest** (manual): comprueba precios/fundamentales/FX reales y la validez del
   scanner, sin escribir ni usar tu cartera.
10. **DEPLOY_FREE reescrito** pantalla por pantalla, para no programadores.

---

# GIIC — Resumen de cambios v0.3 (arquitectura gratuita US$0)

Objetivo: GIIC como **plataforma web privada**, accesible desde cualquier navegador e
iPhone, **sin servidor permanente, sin la computadora encendida y US$0/mes**. Se
conserva todo el núcleo cuantitativo v0.2; cambia el **despliegue** y las **fuentes de
datos** (gratuitas y reales). **Pruebas: 73 → 86 unitarias (Python) en verde**, más
pruebas de paridad de la analítica en TypeScript (vitest, CI).

## Arquitectura seleccionada (justificada en ARCHITECTURE.md)
- **Frontend:** Cloudflare Pages (HTTPS permanente, sin tarjeta, sin pausa).
- **Base de datos + Auth:** Supabase Free (Postgres + Auth + RLS; reset de contraseña).
- **Procesamiento sin tu PC:** GitHub Actions (cron diario). Repo de **código público**
  (sin secretos ni datos) para cron fiable y minutos ilimitados.
- **Datos reales gratis y sin clave:** Stooq (precios EOD US), SEC EDGAR
  (fundamentales oficiales US), Frankfurter (FX del BCE).

## Qué se conservó del núcleo v0.2 (intacto y probado)
Indicadores, scanner multifactor, validación de calidad, FX y símbolos, analítica de
cartera, ETF look-through, rankings, modelos/estructuras, controles de seguridad y las
73 pruebas previas. El servidor FastAPI permanente pasa a ser **opcional/local**; su
lógica ahora se ejecuta como **job programado** (`app/jobs/run_scan.py`).

## Nuevo en v0.3
- **Proveedores gratuitos** (`app/providers/`): `stooq.py`, `edgar.py`,
  `frankfurter.py` y `composite.py` (combínalos tras la interfaz única). Parsers puros
  probados con fixtures (`tests/test_free_providers.py`).
- **Job programado** (`app/jobs/`): `universe.py` (universo US sistemático y
  documentado), `run_scan.py` (reutiliza el motor v0.2), `supabase_writer.py` (escribe
  vía REST con service_role). Metadatos **point-in-time** (fecha, versión de universo y
  de algoritmo, cobertura, factores) para habilitar backtesting futuro sin look-ahead.
  Probado de punta a punta con el proveedor de ejemplo (`tests/test_jobs.py`).
- **Esquema Supabase** (`backend/supabase/schema.sql`): tablas + **RLS** (cartera y
  ajustes privados por `auth.uid()`; mercado y scanner de solo lectura para
  autenticados; escritura solo del job).
- **Frontend sobre Supabase** (`frontend/src/`): auth (login/alta/reset), CRUD de
  cartera persistente, dashboard (cartera, mercado, oportunidades, capital, calidad de
  datos), scanner desde snapshots. Analítica de cartera **portada a TypeScript**
  (`core/analytics.ts`) con **pruebas de paridad** frente al núcleo Python
  (`core/analytics.test.ts`).
- **CI/CD** (`.github/workflows/`): `ci.yml` (pytest + vitest + build en cada push),
  `scan.yml` (scanner diario + manual).
- **Docs:** `DEPLOY_FREE.md` (guía para principiantes) y `FREE_TIER_LIMITS.md`
  (condiciones verificadas y avisos de tarjeta).

## Qué se ejecutó aquí y qué no
- **Ejecutado y verde en este entorno:** 86 pruebas Python; el job completo en
  modo `--dry-run` con proveedor de ejemplo (orquestación real).
- **No ejecutable en este entorno (se corre en despliegue/CI):** descargas reales de
  Stooq/EDGAR/Frankfurter (sin red saliente aquí), build y pruebas del frontend
  (sin `npm`), y la escritura a Supabase. Por eso se incluyen workflows de CI y la
  guía para que lo verifiques tú. No se declara "publicado": tú completas el despliegue
  con `DEPLOY_FREE.md`.

## Limitaciones de la versión gratuita
Datos EOD (no intradía), cobertura US, fundamentales parciales (sin P/E forward,
EV/EBITDA, ROIC), universo ~90 nombres, Supabase pausa a 7 días (mitigado por el scan
diario). Detalle en `FREE_TIER_LIMITS.md`.

---

# GIIC — Resumen de cambios (v0.1 → v0.2, endurecimiento previo a despliegue)

Objetivo de esta iteración: plataforma **segura**, con **datos fiables** y un
**scanner escalable**, antes de cualquier motor predictivo. Núcleo cuantitativo
intacto. **Pruebas: 34 → 73 en verde**, más dos suites de integración.

## 1. Seguridad
- **Autenticación obligatoria** en toda la API. Rutas públicas: solo `/health` y
  `/auth/login`. El resto exige token (`Depends(get_current_user)` en `main.py`).
- **Tokens JWT HS256** y **hashing PBKDF2-SHA256** con sal por usuario
  (`app/security.py`, solo librería estándar — sin dependencias frágiles).
- **Validación de fuerza de contraseña** (largo, mayúscula, minúscula, dígito, símbolo).
- **Secreto obligatorio en producción**: `require_valid_secret()` aborta el arranque
  si `SECRET_KEY` es el de desarrollo o si falta `ADMIN_PASSWORD`.
- **Usuario admin sembrado por entorno** al primer arranque (no hay credenciales en código).
- **Exposición reducida**: en `docker-compose.yml` PostgreSQL ya **no publica puerto**
  (solo red interna); backend y frontend escuchan en **127.0.0.1** (no en toda la red).
  Contraseñas de BD y secretos **obligatorios por `.env`** (el arranque falla si faltan).
- Pruebas: `tests/test_security.py` (hash/verify salteado, JWT roundtrip, firma
  alterada, secreto incorrecto, expiración).

## 2. Scanner escalable
- **Caché incremental en BD** (`app/services/cache.py`, tablas `price_bars` y
  `fundamentals_cache`): solo se descargan fechas nuevas y fundamentales obsoletos.
- **Procesamiento por lotes** y **token bucket** configurable para respetar límites de
  API (`app/services/rate_limiter.py`).
- **Motor del scanner** (`app/services/scan_engine.py`) que orquesta todo y escala a
  miles de instrumentos sin re-descargar ni exceder cuotas.
- Pruebas: `tests/test_scalability.py` (bucket con reloj simulado, batching, frescura
  y descarga incremental de la caché).

## 3. Calidad de datos
- **Validación de múltiplos** (`app/core/quality.py`): P/E, EV/EBITDA, márgenes,
  crecimiento, ROE/ROIC fuera de rango plausible se **anulan con motivo explícito**
  (nunca se corrigen inventando). Captura basura como margen >100% o crecimiento +5000%.
- **Cobertura mínima por factor**: un factor sin cobertura suficiente se **excluye del
  compuesto** y este se **reponderra** sobre los factores válidos.
- **Suficiencia por instrumento**: los que no alcanzan un mínimo de métricas se
  excluyen y se listan en `excluded_insufficient_data`.
- **Ranking comparable por sector** (`sector_relative`): value/quality/growth se
  rankean dentro del sector; momentum y bajo riesgo siguen siendo de mercado.
- Pruebas: `tests/test_quality.py` y `tests/test_scanner_advanced.py`.

## 4. Datos internacionales
- **FX a moneda base** (`app/core/fx.py`): conversión con tasas del proveedor; si falta
  una tasa, la posición se **marca como no convertida** (nunca se asume 1:1).
- **Moneda/país por bolsa** y **tickers consistentes** (`app/core/symbols.py`):
  parsing `TICKER.EXCHANGE`, split por la derecha (soporta `BRK.B`), mapa de divisas.
- **Detección de datos obsoletos** (`is_stale`, días hábiles): el análisis de cartera
  reporta `stale_quotes` y `fx_missing`; `/market/quote` incluye `stale`.
- El conector EODHD implementa `get_fx_rates` vía pares `FOREX`.
- Pruebas: `tests/test_international.py`.

## 5. Pruebas de integración
- **EODHD en vivo** (`tests/integration/test_eodhd_live.py`): se omite sin
  `EODHD_API_KEY`; valida cotización, histórico ordenado, fundamentales, holdings y FX.
- **Stack completo** (`tests/integration/test_stack.py` + `scripts/integration_test.sh`):
  levanta Docker Compose (Postgres+API+frontend), verifica `/health`, que la API
  **exige token** (401 sin auth), login y acceso a cartera y scanner.

## Cómo ejecutar
```bash
# Unitarias (núcleo + seguridad + calidad + escalabilidad + internacional)
cd backend && pytest -q                      # 73 pruebas

# Integración EODHD (con tu clave)
EODHD_API_KEY=xxx pytest tests/integration/test_eodhd_live.py -v

# Integración de stack completo (Docker)
cp .env.docker.example .env   # y rellena secretos
./scripts/integration_test.sh
```

## Pendiente deliberado
Motor predictivo, backtesting y decision engine (Fases 4–6) **no** se tocaron, por
indicación expresa: primero una plataforma segura, fiable y escalable.
