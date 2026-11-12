# Conciliación trimestral NVDA — SEC vs EODHD (misma ventana de 4 trimestres)

**RETRACTACIÓN.** La conclusión previa de que "EODHD infla ingresos/EBIT/utilidad 14–26%" era **FALSA**.
Se debía a un bug de mi selector oficial (`FY + YTD − YTD`), que elegía ventanas distintas por concepto.
La conciliación trimestre a trimestre, con la **misma ventana**, demuestra que **SEC y EODHD coinciden**.

## Ventana TTM: 4 trimestres (cierres fiscales NVDA)

| Trimestre | EBIT | Utilidad neta | OCF | CAPEX | Fuente XBRL / forma |
|---|---:|---:|---:|---:|---|
| Q ago–oct 2025 (fin 26-oct-25) | 36,01 | 31,91 | 23,75 | 1,64 | 10-Q 2025-11-19 (3M / YTD-dif) |
| Q nov 2025–ene 2026 (fin 25-ene-26) | 44,30 | 42,96 | 36,19 | 1,28 | 10-K 2026-02-25 (FY − 9M) |
| Q feb–abr 2026 (fin 26-abr-26) | 53,54 | 58,32 | 50,34 | 1,76 | 10-Q 2026-05-20 (3M) |
| Q may–jul 2026 (fin 26-jul-26) | 63,73 | 59,69 | 24,08 | 2,68 | 10-Q 2026-08-26 (6M − 3M) |
| **TTM** | **197,58** | **192,88** | **134,36** | **7,35** | — |

**SEC = EODHD, trimestre a trimestre, diferencia 0,0% en las cinco métricas** (ingresos, EBIT, utilidad,
OCF, capex). Los valores reales de NVDA TTM:

| Métrica | Valor TTM real (SEC = EODHD) |
|---|---:|
| Ingresos | $303,0B (57,0 + 68,1 + 81,6 + 96,2) |
| EBIT | $197,58B |
| Utilidad neta | $192,88B |
| OCF | $134,36B |
| CAPEX | $7,35B (`PaymentsToAcquireProductiveAssets`) |
| **FCF** | **$127,0B** |

Los $265,4B / $165,7B / $153,3B que reporté antes como "oficiales" eran **artefactos del bug de ventana**
(mezclaban períodos). Quedan descartados.

## Causa y corrección (item 6)

- **Causa:** el selector `FY + YTD − YTD` tomaba el último YTD de cada concepto por separado, así que
  distintas métricas caían en ventanas TTM distintas (OCF en 6M, ingresos en otra), y no cerraban.
- **Corrección:** TTM = **suma de 4 trimestres en una VENTANA COMÚN** (anclada en los trimestres de OCF),
  derivando cada trimestre de los acumulados YTD (Q = YTD_n − YTD_{n-1}), con guarda de ~90 días. Todas
  las métricas usan los MISMOS 4 trimestres. Cruce SEC vs EODHD trimestre a trimestre (>2% ⇒ control).
- **Restauración:** NVDA vuelve a EBIT $197,58B / utilidad $192,88B / ingresos $303B / FV ≈ $141–142.
  Companyfacts = EDGAR (no es fuente independiente); IR de NVDA sería el árbitro final (pendiente de
  descarga del press release; los números SEC/EODHD ya cierran entre sí).

## Verificación de períodos en el resto (item 7)

El mismo método de ventana común se aplica a todo el universo antes de gobernar sus datos:

| Ticker | Ingresos TTM | Fuente | Nota de períodos |
|---|---:|---|---|
| NVDA | 303,0 | oficial_SEC | 4 trimestres 10-Q/10-K ✓ |
| META | 241,6 | oficial_SEC | ✓ |
| NFLX | 49,7 | oficial_SEC | ✓ (precio/acciones en verificación) |
| AMGN | 38,9 | oficial_SEC | ✓ |
| ADBE | 26,0 | oficial_SEC | ✓ |
| LOW | 90,4 | oficial_SEC | ✓ |
| HD | 169,2 | oficial_SEC | ✓ |
| UPS | 91,4 | oficial_SEC | ✓ |
| ASML | 39,5 | EODHD | 20-F **semestral**: sin 10-Q; se usan trimestres EODHD (la guarda de 90d descarta los semestrales de SEC) |
| PFE | 63,6 | EODHD | SEC no formó 4 trimestres limpios; EODHD coincide donde ambos existen |
| TSM | — | — | sin companyfacts US (20-F escaso) → no_valorable |

## Estado tras la corrección

- NVDA **$141,47 consistente** (−18,6%) con ingresos $303B oficiales. 4 consistentes (NVDA, LOW, HD, UPS),
  todas sobrevaloradas o bajo umbral; 6 en revisión; 1 no valorable (TSM).
- Advisor **"esperar", $0 compras** (verificado). Lo no validado, bloqueado. **No se tocaron las fórmulas
  de Fair Value** ni se ajustó WACC/crecimiento/ROIC/reinversión.

## Pendiente honesto

- **IR en PDF** (press releases trimestrales) como árbitro final sobre SEC/EODHD, en especial TSM/ASML
  (XBRL US escaso/semestral). Señalado; no descargado (no se abrió otra fase).
