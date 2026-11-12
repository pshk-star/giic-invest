# E-0 — Resultados cuantificados de la auditoría de datos (read-only)

Fuente: `app/jobs/e0_data_audit.py` (CI run 43256566873, read-only; no escribe, no toca motores, FVs ni
decisiones; barrera activa). Fecha 2026-11-12.

## 1. Cobertura real `fundamentals_pit` (EDGAR)
- **210.564 filas**, 100 % **EDGAR**, **82 tickers**. Años fiscales **2006–2026**.
- Densidad por año fiscal: 2008 ≈ 4.252, 2009 ≈ 9.018, 2010–2024 ≈ **11–13k/año**, 2025 ≈ 9.430, 2026 ≈ 3.134.
- 3 fechas distintas confirmadas: fiscal (`period_end`), publicación (`filing_date`), captura (`retrieved_at`).
- **No supongas 2008 como punto de partida sólido:** 2006–2007 son marginales; la base densa empieza ~2009.

## 2. Disponibilidad de variables por modelo (lo que EDGAR ingiere hoy)
**EDGAR ingiere:** revenue, EBIT (OperatingIncome), net income, gross profit, EPS (básico/diluido), OCF,
**capex**, equity, assets, liabilities, deuda LP. **EDGAR NO ingiere:** **D&A, caja, ΔWC**, deuda corto,
dividendos, EBITDA, y **acciones** (shares no se ingiere como concepto, pero es **derivable** de
NetIncome/EPS).

| Modelo | Variables faltantes en EDGAR | Lectura |
|---|---|---|
| **FCFF** | **D&A, ΔWC, caja**, (shares derivable) | Reinversión y deuda neta **no** reconstruibles PIT solo con EDGAR |
| **FCFE** | deuda corto, (shares derivable) | Casi completo; falta deuda corto (aproximable) |
| **Ingreso Residual** | (solo shares, derivable) | **Completo con EDGAR** |
| **Múltiplos normalizados** | (solo shares, derivable) | **Completo con EDGAR** (+ precio) |

## 3. Reconciliación, moneda, ADR, precios
- **FY 68.392 filas / Q 140.468 filas** → hay anual **y** trimestral ⇒ TTM y reconciliación FY/Q **posibles**.
- Monedas de instrumentos: USD (catálogo). **ADR no trivial: TSM** (único con ratio ≠ 1 en lo resuelto).
- **`price_history` es reconstruido (`reconstructed=true`, origen yahoo), no vendor oficial** → calidad y
  profundidad a verificar; es el **cuello de botella** (ver §5).

## 4. Deslistadas y sesgo de supervivencia
- `instruments`: **catalog 12.787 / resolved 93**; **deslistadas marcadas = 0**.
- **El sesgo de supervivencia NO es corregible con los datos actuales** (no hay emisores deslistados/
  adquiridos/quebrados en la base). Cualquier backtest hoy sobrevalora por supervivencia.

## 5. Observaciones elegibles para retornos forward (el límite real)
Sobre 81 tickers con fundamentales anuales y precio disponible:

| Horizonte | Observaciones elegibles |
|---|---|
| **1 año** | **325** |
| **3 años** | **163** |
| **5 años** | **0** |

- **5 años = 0**: la profundidad de `price_history` no alcanza para evaluar ningún horizonte a 5a. El
  límite **no** es la historia de fundamentales (llega a 2006) sino la **profundidad de precios**.
- 1a (325) es usable; 3a (163) es limitado; **5a no es viable hoy**.

## 6. Auditoría EODHD (`/api/user`)
- Cuenta `pshk-star`, **subscripción mensual**, límite **100.000 req/día**, uso hoy **720** (≈ 0,7 %).
- Endpoints en código: `/fundamentals` (estados + **consenso/targets/múltiplos forward**), `/eod`
  (precios ajustados), `/api/user`, `/api/xbrl`.
- **Lo que justifica el pago no es volumen** (usamos <1 % del límite) sino **consenso/estimaciones** y
  **cobertura internacional**; los fundamentales US son gratis en EDGAR.

## 7. Consenso: ¿PIT histórico o foto?
- `estimate:*`: **360 filas, 1 sola fecha de captura (2026-11-10), 5 tickers, 0 con ≥2 capturas**.
- **Veredicto: FOTO ACTUAL, no PIT histórico.** El consenso **no** sirve como benchmark histórico; solo
  como contraste puntual de hoy. Para usarlo en backtest habría que capturarlo periódicamente a futuro.

## 8. Tabla de factibilidad (tres estados)

| Qué | Estado | Motivo cuantificado |
|---|---|---|
| **Ingreso Residual** (backtest PIT) | **VIABLE AHORA** | todas las variables en EDGAR (shares derivable); 82 tickers, 2009–2025 |
| **Múltiplos normalizados** (backtest PIT) | **VIABLE AHORA** | EBIT/NI/equity/assets/liab en EDGAR + precio |
| **Horizonte forward 1 año** | **VIABLE AHORA** | 325 observaciones elegibles |
| **FCFE** (backtest PIT) | **VIABLE CON DATOS ADICIONALES** | falta deuda corto (aproximable) |
| **Horizonte forward 3 años** | **VIABLE CON DATOS ADICIONALES** | solo 163 obs; requiere más profundidad de precios |
| **Universo sin sesgo de supervivencia** | **VIABLE CON DATOS ADICIONALES** | hoy 0 deslistadas; requiere ingesta de emisores retirados |
| **Precios de vendor oficial (ajustados)** | **VIABLE CON DATOS ADICIONALES** | hoy reconstruidos (yahoo); EODHD `/eod` o EDGAR no cubren esto |
| **FCFF** (backtest PIT riguroso) | **NO VIABLE AHORA** | faltan **D&A, caja, ΔWC** en EDGAR; EODHD los tiene pero **no PIT** |
| **Consenso como benchmark histórico** | **NO VIABLE AHORA** | es **foto actual** (1 captura, 5 tickers) |
| **Horizonte forward 5 años** | **NO VIABLE AHORA** | **0 observaciones** elegibles (profundidad de precios) |

## Recomendación concreta
- **Competir primero los modelos VIABLES AHORA:** **Ingreso Residual** y **Múltiplos normalizados**, en
  horizonte **1 año** (y 3a como secundario con la salvedad de N=163), sobre 2009–2025, con los **82
  tickers EDGAR**. Son económicamente defendibles donde el FCFF falla (maduras, financieras, cíclicas).
- **FCFF/FCFE PIT:** aplazar hasta ingerir D&A/caja/ΔWC (y deuda corto) **con fecha de publicación**
  (EDGAR cash-flow/balance adicionales, o captura PIT propia). No usar la serie EODHD actual como PIT.
- **Antes de cualquier backtest accionable:** (a) resolver profundidad de **precios** (bloquea 3a/5a y el
  sesgo de supervivencia), (b) empezar a **capturar consenso periódicamente** si se quiere como benchmark.
- **EODHD:** mantener por consenso + internacional; el volumen no justifica el costo, así que al decidir
  mantener/bajar se evalúa por cobertura, no por uso.
- **Invariantes:** barrera activa; sin motores nuevos; sin cambios a FV ni a decisiones históricas.
