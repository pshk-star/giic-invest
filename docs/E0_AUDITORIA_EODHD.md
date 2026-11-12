# Auditoría de uso REAL de EODHD (~USD 60/mes) — evidencia técnica y económica

Read-only. No se tocaron motores, modelos, predicciones ni registros. Evidencia: auditoría estática del
código + sondas en vivo (runs 43256566873 `/api/user`, 43259152695 `/eod·/splits·/div`).

## Conclusión ejecutiva: **CANCELAR o BAJAR de plan**
El plan actual es **"Fundamentals Data Feed" (solo fundamentales)**. **No incluye** precios/splits/
dividendos (403). Lo único que GIIC consume de EODHD es `/fundamentals`, y para US es **reemplazable por
EDGAR (gratis)**. El dato que de verdad nos bloquea —**precios históricos profundos**— **ni siquiera está
en este plan**. Mantenerlo no resuelve el cuello de botella del backtest.

## 1-2. Llamadas efectivas y su utilidad
| Endpoint EODHD | Dónde se usa | Almacén | Consume | Categoría |
|---|---|---|---|---|
| `/fundamentals/{sym}` — estados US | `core/connectors/eodhd.py` → `fundamental_driver`/`valuation_coverage_expand`, `scan` | `pit_snapshots` (valoración) | driver FCFF data-driven (hoy **bloqueado por la barrera**), enriquecimiento de scan | **Reemplazable** (EDGAR gratis) |
| `/fundamentals` — **consenso/estimaciones/targets/múltiplos fwd** | `estimates_snapshot` | `pit_snapshots` (`estimate:*`) | — (foto única: 5 tickers, 1 captura) | **Imprescindible solo si se usa como benchmark** (hoy **no** se usa como PIT) |
| `/fundamentals` — **fundamentales internacionales** | conector (disponible) | — | universo actual es US | **Imprescindible a futuro**, no hoy |
| `/eod` precios ajustados | `providers/eodhd.py` (`EODHDProvider`) | — | **nadie**: `get_provider("eodhd")` no se invoca; y responde **403** | **No utilizado / no disponible** |
| `real-time` quotes | `EODHDProvider` | — | nadie (quotes vía Yahoo) | **No utilizado** |
| `/splits`, `/div` | — | — | **403** (splits/divs vía Yahoo) | **No utilizado / no disponible** |
| `FOREX`, `exchange-symbol-list` | `EODHDProvider` | — | nadie (dormido) | **No utilizado** |

**Precios, quotes, splits y dividendos de producción salen de Yahoo** (`history.py`/`identify.py`,
`source="yahoo"`, reconstruidos), no de EODHD.

## 3. Histórico que entrega el plan actual (sonda en vivo)
`/eod`, `/splits`, `/div` → **403 Forbidden** para NVDA, ASML, TSM, PFE, AAPL, META, KO, EOG, MELI, SHOP.
**El plan no da precios/splits/dividendos** (ni US ni internacional). `/api/user`: subscripción mensual,
límite 100.000 req/día, uso real **720/día (0,7 %)** → no pagamos por volumen.

## 4. Por qué el backtest solo tiene 325 obs forward-1a
Porque **`price_history` se llena con Yahoo** (reconstruido, poco profundo), **no con EODHD**. Y aunque
quisiéramos usar EODHD para precios, **`/eod` da 403** en este plan. El límite de 325 (1a) / 163 (3a) /
0 (5a) es de **profundidad de precios Yahoo**, y **EODHD no lo arregla en el plan actual**.

## 5. Por qué ASML y TSM siguen excluidas de A/B/C
Tienen fundamentales crudos en EDGAR (ASML: us-gaap en **EUR** vía 20-F; TSM: ifrs-full en **TWD**), pero
el pipeline necesita **conversión a USD (FX)** y el **mapeo IFRS→ratios** (pendiente). Sin FX/mapeo sus
campos derivados quedan en None → excluidas, pese a cotizar como ADR en EE. UU. **Es un problema de
FX + mapeo, no de comprar más datos.** (EODHD podría dar fundamentales en USD, pero su `FOREX`/provider
no están cableados y el plan no da precios.)

## 6. ¿EODHD amplía ya el histórico de precios / internacional?
- **Precios (US e internacional): NO** en el plan actual (`/eod` = 403). Requeriría **subir de plan**
  (p. ej. All-In-One ~USD 100) = **más costo**, no el mismo.
- **Fundamentales internacionales: SÍ** (`/fundamentals` internacional funciona), pero **sin precios**
  internacionales no sirve para backtest de retornos.

## 7. Tabla final y costo/beneficio
| Categoría | Qué |
|---|---|
| **Imprescindible** | (condicional) consenso/estimaciones **si** se decide usar como benchmark con captura periódica; fundamentales internacionales **cuando** el universo deje de ser US |
| **Reemplazable** | estados financieros US de `/fundamentals` → **EDGAR gratis** (falta ingerir D&A/caja/ΔWC, que están en los 10-K) |
| **No utilizado** | `/eod`, `real-time`, `/splits`, `/div`, `FOREX`, `exchange-symbol-list` (dormidos y/o 403) |

**Costo/beneficio:** USD 60/mes por un feed de fundamentales cuyos datos US son gratis en EDGAR, cuyo
consenso hoy no se usa como PIT, y que **no incluye** lo que nos bloquea (precios). Beneficio activo
actual ≈ el driver data-driven (hoy **bloqueado**) + enriquecimiento de ratios del scan.

## Recomendación con ruta
1. **Cerrar la dependencia reemplazable:** extender `edgar_pit` para ingerir **D&A, caja y ΔWC** (gratis,
   están en los estados) → elimina la razón principal de usar `/fundamentals` de EODHD.
2. **Confirmar lo que se perdería** al cancelar: consenso (foto, no usado) + fundamentales internacionales
   (no usados hoy) + la serie capex/D&A del driver experimental (migrable a EDGAR).
3. **Cancelar o bajar** tras (1)-(2). Si en el futuro se necesita internacional + consenso **con precios**,
   contratar un plan/proveedor que **incluya precios** (el actual no), para no pagar dos veces.
4. El cuello de botella real (**profundidad de precios**) se resuelve con una **fuente de precios con
   histórico** (no con este plan): decisión aparte de la de EODHD.

**Invariantes:** sin cambios a modelos, predicciones ni registros; barrera activa.
