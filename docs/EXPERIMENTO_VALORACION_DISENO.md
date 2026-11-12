# Experimento de selección de metodología de valoración — diseño inicial

**Propósito:** identificar empíricamente, con datos históricos point-in-time, qué metodología de
valoración es más fiable **por tipo de empresa**, en vez de corregir Fair Values ticker por ticker.
Este documento es el **entregable inicial** (inventario + diseño + métricas + cobertura + auditoría de
datos + plan). **No implementa motores nuevos.** La barrera de accionabilidad sigue activa; no se alteran
decisiones ni registros históricos.

Principio rector: **no calibrar para copiar el consenso.** El consenso y las valoraciones intrínsecas
independientes son **referencias de contraste**, no objetivos de ajuste. El criterio de éxito es el
desempeño económico fuera de muestra, no la cercanía a Wall Street.

---

## 1. Inventario real de datos y modelos

### 1.1 Datos (ya disponibles)
| Fuente | Qué aporta | PIT | Estado |
|---|---|---|---|
| **SEC EDGAR companyfacts** (`jobs/edgar_pit.py` → tabla `fundamentals_pit`) | US-GAAP + IFRS: Revenues, OperatingIncome, NetIncome, GrossProfit, Equity, Assets, Liabilities, LongTermDebt, acciones… con CIK y fechas de filing | **Sí** (fecha de publicación real) | **Operativo, gratuito** |
| **EODHD** `/fundamentals/{symbol}` (pago) | Estados financieros + **consenso/estimaciones** (AnalystRatings, Trend, WallStreetTargetPrice, múltiplos forward) → `pit_snapshots` (`estimates_snapshot.py`) | Sí (3 fechas: captured/published/observation) | Operativo, **de pago** |
| **EODHD** `/eod` (pago) | Precios EOD ajustados | Sí | Operativo |
| **Supabase** | `fundamentals_pit`, `pit_snapshots` (append-only, inmutable, UNIQUE kind/ticker/obs/snapshot), `prices`, `price_history`, `corporate_actions`, `instruments`, `etf_holdings`, `transactions` | — | Operativo |

### 1.2 Modelos de valoración (implementados vs faltantes)
| Modelo | Estado en GIIC |
|---|---|
| **FCFF productivo** (`valuation.ts`/`valuation.fcff.ts`, P1.6) | Implementado, calibrado (5 nombres) — **no tocar** |
| **FCFF multietapa experimental** (`fcff_forward.py`, P1.7.2) | Implementado (espejo de P1.6) |
| **FCFF data-driven** (`fundamental_driver.py`, P2.4) | Implementado — **el que mostró los defectos del diagnóstico PFE** |
| **ROIC / reinversión explícita** | Parcial (dentro del FCFF; no como modelo independiente) |
| **FCFE** (equity directo) | **Falta** |
| **Ingreso residual (RI)** | **Falta** |
| **DDM** (dividendos) | **Falta** |
| **Múltiplos normalizados** (EV/EBIT, P/E ciclo-ajustado) | **Falta** (hay múltiplos forward de EODHD como dato, no como modelo) |
| **SOTP** | **Falta** (solo donde aplique: conglomerados) |

**No se implementarán todos.** Prioridad por **datos suficientes + justificación económica**:
1. **Ingreso residual (RI)** y **múltiplos normalizados** — se nutren de lo que EDGAR ya da (equity, EBIT,
   NOPAT, book value); fuertes para empresas maduras/financieras donde el FCFF falla.
2. **FCFE** — para bancos/seguros (donde FCFF no aplica bien).
3. **FCFF corregido** (reinversión consistente) — el rediseño del motor actual.
4. DDM solo para pagadores estables; SOTP solo conglomerados. **ROIC/reinversión** como disciplina
   transversal, no como modelo suelto.

### 1.3 Infraestructura de experimentación (ya existe — se REUTILIZA)
`backtest.py` (walk-forward), `forecast_backtest.py` (backtest PIT de modelos), `econ_eval.py`
(evaluación económica vs SPY/equiponderado), `perf.py`/`stats.py` (métricas puras sin numpy),
`abc_compare.py` (funnel A/B/C), `confidence_rubric.py`, `consensus_admission.py` (gate de consenso),
`fv_attribution.py`, `pit_integrity_check.py` (control de look-ahead). **El experimento extiende esto a
metodologías de valoración; no se construye de cero.**

---

## 2. Diseño del experimento histórico

- **Unidad de observación:** (empresa, fecha de valoración t). En cada t se construye el input **solo**
  con datos cuyo `published_at ≤ t` (EDGAR filing date; EODHD captured_at). Prohibido usar revisiones
  posteriores. `pit_integrity_check` ya verifica `observation_date ≤ captured_at`.
- **Sin look-ahead:** inputs de `fundamentals_pit`/`pit_snapshots` a la fecha; precios con `as_of ≤ t`;
  retorno forward con precios **posteriores** a t (ajustados por acciones corporativas).
- **Sin sesgo de supervivencia:** el universo en cada t incluye las empresas **listadas en t**
  (incluidas las que luego fueron deslistadas/adquiridas/quebraron). Se reconstruye desde el histórico de
  `instruments`/EDGAR, no desde el universo actual.
- **Reconciliación anual/TTM/trimestral obligatoria:** para cada observación se concilian las tres vistas
  (anual auditada, TTM, último trimestral) y se registra la discrepancia; si no concilian dentro de
  tolerancia, la observación se marca de **baja calidad** (no se descarta en silencio).
- **Metadatos por observación (exigidos):** `published_at`, período fiscal, moneda, unidades, acciones
  (básicas y diluidas), origen (edgar/eodhd), taxonomía (us-gaap/ifrs).
- **Partición temporal estricta (anti-overfitting):**
  - **Desarrollo** (p. ej. 2005–2014): elegir especificaciones y rangos de supuestos.
  - **Validación temporal** (2015–2019): ajuste de la política de selección por sector.
  - **Prueba final fuera de muestra** (2020–2025): **se toca una sola vez**, al final.
  - Cruza **ciclos** (crisis 2008 si hay datos, COVID 2020, subida de tasas 2022).

---

## 3. Métricas y criterios de selección

Por modelo × sector × horizonte, sobre la ventana de validación (nunca la de prueba hasta el final):
1. **Retorno total forward 1/3/5 años** condicionado al margen de seguridad del modelo (quintiles).
2. **Error y calibración:** error de valoración (|FV−precio futuro realizado|), curva de calibración
   (¿un margen +30 % predice retorno mayor que +10 %?), sesgo sistemático por sector.
3. **Discriminación infravalorado/sobrevalorado:** IC (rank correlation) entre margen del modelo y retorno
   forward; decil largo-corto.
4. **Carteras simuladas vs benchmark:** long-only y long-short por quintil de margen, **con costos de
   transacción y límites de riesgo**, vs SPY y equiponderado (`econ_eval.py`).
5. **Estabilidad de parámetros:** varianza de los supuestos derivados (g, margen terminal, WACC,
   reinversión) entre períodos; penaliza inestabilidad.
6. **Sensibilidad:** elasticidad del FV a cada supuesto; penaliza modelos donde el valor vive en el
   terminal o en un supuesto frágil (lección PFE).
7. **Cobertura y tasa de errores de datos:** % del universo valorable, % de observaciones con error de
   unidades/moneda/acciones.
8. **Costos y riesgo:** turnover, drawdown, volatilidad de la cartera simulada.

**Controles anti-trampa:**
- **Separación desarrollo/validación/prueba** (sección 2); el ganador **no** se elige sobre los datos
  usados para optimizarlo.
- **Corrección por comparaciones múltiples** (Benjamini-Hochberg / Deflated Sharpe) al comparar muchos
  modelos×sectores.
- **Prohibido** presentar backtest como rentabilidad futura garantizada; se reporta con intervalos y
  degradación esperada.

---

## 4. Selección (política por tipo de empresa)

- **No se fuerza un modelo único.** Si FCFF corregido gana en tecnología/industria pero **ingreso
  residual** es más fiable en bancos y **múltiplos normalizados** en cíclicas, la política de valoración
  compartida enruta por **tipo de negocio** (ya hay `kind_of`: empresa/banco/etf/otro; se extiende a
  sector/modelo de negocio).
- **Si ningún modelo demuestra superioridad robusta** (fuera de muestra, tras corrección múltiple), se
  **informa ese resultado** y las valoraciones quedan **experimentales/bloqueadas** (la barrera persiste).
  No se habilitan compras sobre un modelo no validado.

---

## 5. Limitaciones de cobertura (declaradas)

- **EDGAR:** excelente para emisores SEC (US + algunos IFRS extranjeros con 20-F). **No** cubre empresas
  que no reportan a la SEC (gran parte de Europa/Asia/LatAm) → ahí dependemos de EODHD.
- **Historia productiva corta:** solo 5 nombres con FV productivo; la mayoría es experimental. El
  experimento amplía la evidencia, no la inventa.
- **Ciclos:** la profundidad histórica de `fundamentals_pit` limita cuántos ciclos cubrimos; se reporta
  explícitamente qué períodos tienen datos PIT reales.
- **ADR/moneda:** defecto conocido del driver (TSM/ASML); el experimento trata ADR/FX como primer control
  de calidad de datos.

---

## 6. Auditoría del proveedor de datos (~USD 60)

**Proveedor:** **EODHD** (eodhd.com). Endpoints realmente consumidos en el código:
`/fundamentals/{symbol}` (estados + **consenso/estimaciones/targets/múltiplos forward**), `/eod` (precios
ajustados), `/api/user` (plan/uso), `/api/xbrl`. Frecuencia: cache 12 h, ~1 req/s, trimestral/anual.

| Dato | Clasificación |
|---|---|
| Estados financieros US (revenue, EBIT, deuda, acciones) | **Gratis en EDGAR** (ya ingerido en `fundamentals_pit`) |
| Estados financieros internacionales (no-SEC) | **Exclusivo/mejor en EODHD** (EDGAR no los tiene) |
| **Consenso/estimaciones/price targets/múltiplos forward** | **Exclusivo en EODHD** (no están en EDGAR); otras fuentes de pago equivalentes |
| Precios EOD ajustados | Gratis/casi-gratis en otras fuentes (Stooq/Tiingo free), EODHD más cómodo y ya ajustado |
| ETF holdings / dividends / splits | Mixto (algunos gratis; EODHD conveniente) |
| `/api/xbrl`, `/api/user` | Infra; no aporta valor de inversión |

**Recomendación (marco, a confirmar con uso real):**
- **Mantener por ahora**, porque el experimento necesita (a) **consenso como benchmark de contraste** y
  (b) **cobertura internacional** y precios ajustados estables. Cancelar a mitad del experimento rompería
  la comparabilidad.
- **Reducir dependencia** desplazando los **fundamentales US a EDGAR** (ya hecho) → si el experimento
  concluye que solo usamos de EODHD el consenso + internacional, se puede **bajar de plan** o sustituir.
- **Primer paso medible del plan:** llamar a `/api/user` (plan y consumo reales) y contar, sobre los logs,
  qué fracción del valor proviene de endpoints no reemplazables por EDGAR. Decidir **mantener/bajar/
  cancelar** con ese dato, no por impresión.

---

## 7. Plan acotado de ejecución (por etapas, cada una verificable; sin motores nuevos hasta tu visto bueno)

1. **E-0 Auditoría de datos (1 corrida):** `/api/user` (plan/uso) + inventario de cobertura PIT real por
   año/sector (cuántas observaciones EDGAR vs EODHD). Entrega: tabla de cobertura + decisión de costo.
2. **E-1 Dataset PIT de valoración:** materializar observaciones (empresa, t) con inputs PIT reconciliados
   (anual/TTM/Q), retornos forward 1/3/5a y metadatos. Controles de look-ahead y supervivencia.
   **No valora todavía.** Entrega: dataset + reporte de calidad/cobertura/errores.
3. **E-2 Modelos candidatos (pocos, justificados):** FCFF corregido, ingreso residual, múltiplos
   normalizados (+ FCFE para financieras). Puros y testeables. Entrega: specs congeladas + pruebas.
4. **E-3 Backtest en desarrollo + validación:** métricas de la sección 3 por modelo×sector, con corrección
   múltiple. Entrega: ranking por sector con intervalos. **Sin tocar la prueba final.**
5. **E-4 Política por tipo de empresa + prueba fuera de muestra (una vez):** selección y evaluación final.
   Entrega: recomendación de política (o el resultado de que ningún modelo es robusto).
6. **E-5 Decisión de habilitación:** solo si un modelo supera los controles fuera de muestra se propone
   levantar la barrera para ese tipo de empresa; si no, se mantiene experimental.

**Invariantes:** barrera activa; sin clamps ni ajustes manuales; no se altera el FV productivo ni los
registros históricos; evidencia antes de implementar.
