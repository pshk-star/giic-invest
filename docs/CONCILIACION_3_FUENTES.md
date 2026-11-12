# Conciliación de 3 fuentes — cifras financieras REALES (no las de una API)

Tercera fuente independiente = **estados oficiales SEC** (companyfacts del 10-K/10-Q, concepto vigente,
con accession como soporte documental). Árbitro cuando EODHD y EDGAR discrepan. Integrado al pipeline
productivo (el motor consume el TTM oficial). 458 pruebas + CI verde. Desplegado (snapshot 2026-11-12).
No se contrató nada. Verificado: advisor "esperar", $0 compras.

## Hallazgo principal

**EODHD infla los ingresos y la utilidad del TTM ~5–26% frente a los estados oficiales.** OCF y capex sí
coinciden (tras resolver el concepto real de capex). El motor usaba las cifras infladas de EODHD; ahora
usa las oficiales.

## NVIDIA — verificación solicitada (TTM hasta jul-2026, 10-K/10-Q 2026)

| Concepto | Oficial SEC | EODHD | Dif | Seleccionado | Fuente documental | Estado |
|---|---:|---:|---:|---|---|---|
| OCF TTM | **$134,4B** | $134,4B | 0% | $134,4B | 10-K 2026-02-25, `NetCashProvidedByUsedInOperatingActivities` | ✅ confirmado |
| CAPEX TTM | **$7,35B** | $7,35B | 0% | $7,35B | `PaymentsToAcquireProductiveAssets` (no el tag estándar, obsoleto 2012) | ✅ confirmado |
| **FCF TTM** | **$127,0B** | $127,0B | 0% | **$127,0B** | derivado OCF−\|capex\| | ✅ **confirmado = tu ~$127B** |
| Ingresos TTM | **$265,4B** | $303,0B | +14% | $265,4B oficial | 10-K, `Revenues` | ⚠ EODHD infla |
| EBIT TTM | **$165,7B** | $197,6B | +19% | $165,7B oficial | 10-K, `OperatingIncomeLoss` | ⚠ EODHD infla |
| Utilidad neta TTM | **$153,3B** | $192,9B | +26% | $153,3B oficial | 10-K, `NetIncomeLoss` | ⚠ EODHD infla |
| Acciones dil. | 24,3B | — | — | 24,3B | 10-K | oficial |

Los **$127B de FCF TTM quedan confirmados contra el estado oficial.** El capex se validó resolviendo que
NVDA usa `PaymentsToAcquireProductiveAssets` (el tag estándar `PaymentsToAcquirePropertyPlantAndEquipment`
estaba congelado desde 2012 en $0,14B — causa de los $96–134B de FCF erróneos anteriores).

## Universo prioritario (TTM, oficial vs EODHD)

| Ticker | Ingresos of. | Ingresos EODHD | OCF of. | CAPEX of. (concepto) | FCF of. | Observación |
|---|---:|---:|---:|---|---:|---|
| NVDA | 265,4 | 303,0 | 134,4 | 7,4 (ProductiveAssets) | 127,0 | EODHD infla ingresos 14% |
| META | 214,3 | 241,6 | 133,1 | 104,4 (PP&E) | 28,6 | capex IA real $104B; FCF bajo |
| NFLX | 46,5 | 49,7 | 10,5 | 0,8 (PP&E) | 9,7 | precio/acciones en verificación |
| ASML | 32,7 | 39,5 | 12,7 | 1,6 (PP&E) | 11,1 | OCF oficial 20-F parcial vs EODHD 22,7 |
| TSM | — | 4.944,8 (TWD) | — | — | — | sin companyfacts US → solo EODHD |
| PFE | 62,5 | 63,6 | 14,2 | 2,4 (PP&E) | 11,8 | coincide |
| AMGN | 37,6 | 38,9 | 12,0 | 2,5 (PP&E) | 9,6 | coincide |
| ADBE | 24,5 | 26,0 | 10,8 | 0,2 (PP&E) | 10,6 | coincide |

(Cifras en miles de millones de la moneda de reporte.)

## Regla de decisión aplicada

- **Coincide con el oficial** → se usa (OCF, capex, FCF en casi todos).
- **Discrepa** → se usa el **oficial** y se documenta (ingresos/EBIT/utilidad: EODHD inflaba; se tomó SEC).
- **No reportado directamente** → derivado con fórmula explícita (FCF = OCF−\|capex\|; ROIC = NOPAT TTM /
  capital invertido del último cierre; capital invertido = equity + deuda − caja).
- **Sin dato en una fuente** → se consulta la otra; **no se completa con cero** (TSM sin oficial → EODHD;
  balance ausente → no_valorable, no cero).

## Integración y efecto en el Fair Value

El motor consume el **TTM oficial** (ingresos, EBIT, utilidad, OCF, capex, FCF). Efecto en NVDA:
**$142 (datos EODHD inflados) → $118,63 (datos oficiales), en_revision** (su FCFF proyectado aún diverge
del FCF real $127B por el supuesto de reinversión g/ROIC — se marca, no se fuerza). **No se ajustó
WACC/crecimiento/ROIC/reinversión para compensar.**

Clasificación: 3 consistentes (LOW, HD, UPS — sobrevaloradas), 7 en revisión, 1 no valorable (TSM).
Advisor **"esperar", $0 compras**; lo no validado, bloqueado.

## Controles de conciliación (en el pipeline)

- Oficial vs EODHD por métrica (>10% ⇒ usa oficial y registra la divergencia).
- Enumeración de conceptos de capex (resuelve tag real) + filtro a 10-K/10-Q/20-F (excluye DEF 14A/8-K).
- Concepto vigente (FY más reciente), no tags en desuso.
- Prueba de realidad FCFF proyectado vs FCF TTM; split/precio; emparejamiento estricto de períodos.

## Pendientes honestos

- **TSM**: sin companyfacts US (no presenta XBRL US); solo EODHD (TWD). Requiere IR/20-F para árbitro.
- **ASML**: OCF oficial del 20-F parece parcial ($12,7B) vs EODHD ($22,7B); queda en revisión hasta
  resolver con el estado oficial completo (IR).
- **NFLX**: precio/acciones en verificación (posible split en la ingesta de Yahoo).
- **Investor Relations (PDF) como 4ª verificación**: para TSM/ASML donde el XBRL US es escaso, el PDF de
  IR sería el árbitro; no se descargó aquí (no se abrió otra fase), queda señalado.
