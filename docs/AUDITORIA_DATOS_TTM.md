# Auditoría de datos y actualización TTM — GIIC

Corrección de DATOS (no de fórmulas): el motor usaba el último cierre ANUAL (rezagado) en vez del TTM.
Verificado con NVIDIA y aplicado al universo. 458 pruebas backend + CI frontend verde. Desplegado
(snapshot 2026-11-12, lectura por `captured_at`). No se contrató nada.

## 1. Auditoría NVIDIA (datos verificables)

| Concepto | FY2026 (cierre 25-ene-2026) | TTM (hasta 26-jul-2026) | Fuente | Filing |
|---|---:|---:|---|---|
| Operating Cash Flow | $102,7B | **$134,4B** | EDGAR y EODHD coinciden | 10-K 2026-02-25 / 10-Q 2026-08-26 |
| CAPEX | $0,1B (EDGAR, **subestimado**) | **$7,35B** (EODHD, correcto) | EODHD (EDGAR PP&E incompleto) | — |
| **FCF** | ~$102B (con capex EDGAR malo) | **$127,0B** | EODHD OCF−capex | — |

- **Origen del FCF:** EDGAR `NetCashProvidedByUsedInOperatingActivities` − capex. El capex de EDGAR
  (`PaymentsToAcquirePropertyPlantAndEquipment`) **subestima** a NVDA ($0,1B vs $7,35B real de EODHD);
  por eso el FCF salía inflado y, además, era del **FY rezagado**.
- **Por qué ~$96–102B y no ~$127B:** el motor tomaba el **FY** (cerrado en enero 2026), no el TTM. El
  TTM (FY + YTD actual − YTD comparable) da **$127B**, que coincide con el FCF TTM de EODHD (4 trimestres).
- **TTM reconstruido** (fórmula `FY + YTD_actual − YTD_anterior`, misma clase de período, ~1 año aparte):
  OCF = 102,7 + 74,4 − 42,8 = **$134,3B** ✓. **No había mezcla de trimestres**, pero sí período
  equivocado (FY) y fuente de capex equivocada. Ambos corregidos.

## 2. Actualización TTM — universo (datos al 2026-11-12)

Flujos = TTM (ingresos, EBIT, utilidad, OCF, capex, FCF). Balance = último cierre. Crecimiento = historia
anual. Moneda/ADR/split reconciliados. Fuente y período registrados por variable.

| Ticker | Base | FV v2 | MoS | FCF TTM | Estado | Controles que fallan |
|---|---|---:|---:|---:|---|---|
| NVDA | TTM | 142,17 | −18,2% | $127,0B | **consistente** | — |
| META | TTM | 486,62 | −22,6% | $28,6B | en_revision | FCFF/FCFE, FCFF vs FCF real |
| NFLX | TTM | 49,08 | −24,0% | $11,4B | en_revision | datos precio/acciones (split) |
| TSM | FY | — | — | — | no_valorable | balance TWD no reconstruible |
| ASML | TTM | 634,23 | −58,7% | $11,1B | en_revision | FCFF vs FCF real |
| PFE | TTM | 40,31 | +36,9% | $11,8B | en_revision | peso terminal, FCFF vs FCF real, precio/acciones |
| AMGN | TTM | 296,75 | −36,6% | $9,6B | en_revision | FCFF/FCFE, FCFF vs FCF real |
| ADBE | TTM | 344,45 | +45,0% | $10,6B | en_revision | FCFF vs FCF real |
| LOW | TTM | 144,42 | −37,6% | $7,0B | **consistente** | — |
| HD | TTM | 211,02 | −39,9% | $15,1B | **consistente** | — |
| UPS | TTM | 73,23 | −34,9% | $6,4B | **consistente** | — |

**NVDA pasó de $81,64 (FY rezagado) a $142,17 (TTM), MoS −53% → −18%.** Las 4 consistentes
(NVDA, LOW, HD, UPS) están todas sobrevaloradas o bajo el umbral ⇒ **advisor "esperar", $0 compras**
(verificado). El resto queda bloqueado.

## 3. Controles de calidad (implementados)

- **Prueba de realidad FCFF vs FCF real:** FCFF proyectado vs FCF TTM; >30% ⇒ en_revision.
- **Reconciliación de fuentes:** divergencia EDGAR vs EODHD >15% (ingresos) o capex incompleto ⇒ se usa
  la fuente más completa y se registra; >25% en ingresos/equity/capital ⇒ en_revision.
- **CAPEX incompleto (EDGAR PP&E):** detectado y sustituido por EODHD cuando <50% de la otra fuente.
- **Split/precio/acciones:** salto de acciones YoY >3x ⇒ precio/acciones en verificación ⇒ en_revision.
- **Emparejamiento de períodos:** TTM exige misma clase de YTD y ~1 año; si falta YTD comparable, cae a
  FY y lo marca (no mezcla 6M con 9M; evita duplicar períodos).
- **Balance = último cierre** (no suma TTM). **ROIC = NOPAT TTM / capital invertido del último cierre.**
- **Consistencia aritmética ≠ validación económica:** estado "consistente" = pasa controles aritméticos;
  no implica validación económica/predictiva (backtest/track record pendiente).

## 4. Integración con Fair Value

- El motor se alimenta de TTM como año base (ingresos, margen, tasa, NOPAT, FCF real). **No se ajustó
  WACC, crecimiento, ROIC ni reinversión** para compensar datos.
- FCF TTM es la referencia histórica; el FCFF proyectado se compara contra él (control de realidad). Si
  difieren >30%, se explica y la empresa queda en revisión (META, ASML, PFE, AMGN, ADBE).
- Recomendaciones bloqueadas cuando los datos o la valoración no están validados (en_revision/no_valorable).

## Pendientes honestos

- **TSM:** balance en TWD no reconstruible por EDGAR (IFRS) ni EODHD → no_valorable.
- **NFLX/precio:** precio de la tabla ($64,54) marcado en verificación (posible split no ajustado en la
  ingesta de Yahoo). El FCF/ingresos TTM sí reconcilian entre fuentes.
- **Supuesto de reinversión g/ROIC:** sigue siendo el driver que más aparta el FCFF proyectado del FCF
  real en empresas capital-ligeras; los casos divergentes quedan en revisión (no se fuerza el número).
