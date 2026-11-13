# GIIC — Motor de valoración profesional: entrega contra el pliego (secciones 1-9)

Fecha: 2026-11-13. Despliegue verificado (write=true, 38 nombres). Advisor **"esperar", $0 compras**.
459 pruebas backend + CI frontend (tsc+vitest) verdes. **Nada accionable**: barrera de metodología activa
(sección 7) hasta validación por backtest.

---

## 1. Cobertura y calidad de datos (universo del advisor, 38 nombres)

Ingesta: **EODHD** (series e IFRS internacional) + **SEC EDGAR/XBRL** (US) + **TTM oficial** por suma de 4
trimestres en ventana común (árbitro SEC). Reconciliación por campo con procedencia y discrepancia. No se
inventan cifras ni se rellena con cero; campo ausente ⇒ no se emite.

| Estado | n | Nombres |
|---|--:|---|
| **Consistente** (pasa controles aritméticos) | 10 | NVDA, AMGN, LOW, HD, PG, PEP, CAT, RTX, LMT, MCD |
| **En revisión** (control financiero no superado) | 19 | META, NFLX, TSM, ASML, PFE, ADBE, UPS, AAPL, MSFT, GOOGL, KO, JNJ, CVX, LLY, GE, SHW, CL, EOG, FCX |
| **No valorable** (control duro / método dedicado pendiente) | 9 | AMZN, MRK, ABBV, XOM, COP, NEE, DUK, AMT, PLD |

TSM (antes sin valoración) **resuelto**: el `invested_capital` del 20-F parcial de EDGAR venía negativo
(−1,9B TWD, equity 130B vs 5,42T real); el motor ahora recalcula equity+deuda−caja desde EODHD (TWD
coherente) ⇒ TSM valorable ($338 en revisión por discrepancia EDGAR/EODHD).

## 2. Indicadores (reales, conciliados)

Por nombre el motor publica (snapshot): ingresos/EBIT/OCF/CAPEX TTM, NOPAT, ROIC medio, ROIIC observado,
reinversión, WACC, Ke, g1, gT, peso terminal, FCFF0, FCFE0, divergencia FCFF/FCFE, procedencia por campo.
Definiciones reconocidas; sin precisión falsa cuando faltan datos (se marca en revisión).

## 3. Metodología por empresa (selección documentada)

No se aplica un DCF único a todo. `_select_method` enruta por clase económica:

| Clase | Método | Estado en el motor |
|---|---|---|
| Operativa (tech, consumo, salud, industrial) | **FCFF DCF multietapa** | implementado |
| Utilities / Energía | FCFF (con cautela cíclica) | implementado; cíclicas a menudo caen por control duro |
| **Bancos / aseguradoras** | RIM / exceso de capital | dedicado **pendiente** ⇒ bloqueado (no se fuerza FCFF) |
| **REITs** (AMT, PLD) | FFO / NAV | dedicado **pendiente** ⇒ bloqueado (no se fuerza FCFF) |

REITs y bancos quedan `no_valorable` por `metodo_apropiado` en vez de producir un FCFF inapropiado.

## 4. Supuestos (fundamento y fuente)

- **WACC**: CAPM. Ke = Rf + β·ERP por moneda (USD Rf 4,2%/ERP 4,8%; TWD 1,5%/7,0%; EUR 2,6%/5,5%),
  fechado 2026-11. Kd después de impuestos con spread acotado. Ponderación equity/deuda por estructura real.
- **Crecimiento g1**: CAGR histórico real acotado; converge a gT.
- **gT terminal**: min(Rf, PIB nominal LP), ≤ 2,5-3,0% por moneda. Nunca > WACC.
- **Reinversión**: **ROIIC observado** (ΔNOPAT/ΔcapitalInvertido de balances oficiales, ventanas 3a/plurianual)
  cuando es estable (NVDA 60% capado, META 33%); **supuesto conservador 15% documentado** cuando es inestable
  o no medible (LOW, HD, PFE). ROIIC erosiona a ≈2×WACC (competencia). **Sin fórmula circular**: el FCFF ya
  NO se fuerza a igualar el FCF histórico.

## 5. Fair Value y escenarios

Cada snapshot lleva **conservador / base / optimista** con paquetes de supuestos documentados (no calibrados
a precio): conservador (WACC+1,5pp, g1×0,70, ROIIC×0,80, gT−0,5pp), base (fundamentado), optimista (inverso),
más rango y margen de seguridad por escenario y sensibilidad WACC±1pp / gT±0,5pp.

FV base y margen de seguridad (selección; universo completo en GIIC):

| Ticker | FV base USD | Margen | Estado |
|---|--:|--:|---|
| NVDA | 125,44 | −24,5% | consistente |
| AMGN | 379,43 | −18,8% | consistente |
| PEP | 107,80 | −24,2% | consistente |
| MCD | 175,23 | −36,0% | consistente |
| LMT | 400,05 | −33,8% | consistente |
| TSM | 338,38 | −16,6% | en revisión |
| META | 549,62 | −11,9% | en revisión |
| PFE | 49,84 | +72,9% | en revisión (margen extremo) |
| EOG | 290,61 | +86,7% | en revisión (cíclica) |
| AMT / PLD | — | — | no valorable (REIT, método FFO/NAV pendiente) |

**Ningún nombre consistente tiene margen positivo**: el proceso no encuentra gangas entre la calidad; los
aparentemente "baratos" (PFE, EOG, CVX, COP) quedan en revisión/no valorables, no como compra ingenua.

## 6. Comparación anterior vs nuevo (cambios materiales)

- **NVDA $145 → $125,44**: se retiró la fórmula de ROIC incremental circular (forzaba FCFF=FCF). El ROIIC
  observado (79%/72%, capado 60%) exige más reinversión que el modelo circular ⇒ FCFF menor ⇒ FV más bajo.
  Sin ajuste a ningún objetivo.
- **TSM: no_valorable → $338 (en revisión)**: corregido el capital invertido roto del 20-F.
- **Accionabilidad: antes "consistente"=accionable → ahora TODO bloqueado** por barrera de metodología
  (sección 7). Antes una compra legacy (COP vía FV productivo) se colaba; la barrera global la cerró.

## 7. Problemas abiertos (sin ocultar)

- **Validación económica/predictiva pendiente**: no hay backtest contra retornos realizados. Por eso NADA es
  accionable (barrera `METHODOLOGY_VALIDATED=False`). Pasar pruebas de software ≠ validar una valoración.
- **Modelos dedicados sin implementar**: RIM (bancos/aseguradoras) y FFO/NAV (REITs). Esos nombres quedan
  bloqueados en vez de forzar FCFF.
- **Cíclicas** (energía, materiales): FCFF sobre utilidades no normalizadas las manda a revisión/no valorable;
  falta normalización de ciclo (mid-cycle earnings).
- **TSM**: discrepancia EDGAR (20-F parcial) vs EODHD en equity ⇒ en revisión; árbitro final serían los
  estados IFRS oficiales / IR (no descargados).
- **Discrepancias de fuentes** en varios nombres (EDGAR vs EODHD) mandan a revisión; se investigan caso a caso.

## 8. Evidencia (pruebas, commit, despliegue, verificación)

- Commits: `b4862b0` (ROIIC observado, retira circular), `1000fa4` (self-test determinista), `eb42f3c`
  (barrera global), `3754341` (escenarios + método), y capital invertido internacional (TSM).
- Pruebas: 459 backend verdes; CI frontend (tsc + vitest, incl. barrera) verde.
- Despliegue: `valuation_engine_run` write=true, 38 nombres, success.
- Verificación producción: advisor preview ⇒ `dinero_nuevo: efectivo`, 0 comprables, universo bloqueado.

---

**Criterio de éxito**: GIIC entrega datos reales conciliados, indicadores definidos, método por empresa,
supuestos fundamentados y FV con escenarios reproducibles. Lo accionable permanece **bloqueado** —
honestamente — hasta el backtest. No se declaró nada validado por pasar pruebas.
