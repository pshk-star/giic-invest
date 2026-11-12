# Reparación GIIC — resultados verificados (P1–P5)

Ejecutado sin abrir fases nuevas. Todo probado (445 passed) y desplegado con evidencia de producción
(escritura + re-lectura verificada en Supabase). No se contrató nada. Barrera de seguridad intacta.
Los nuevos Fair Values NO se presentan como validados: son experimentales y no gobiernan compras.

## PRIORIDAD 1 — EDGAR: capital invertido, ROIC, reinversión, FCF, deuda neta

- **Ingesta ampliada** (`edgar_pit.py`): +22 conceptos us-gaap / +13 ifrs. Se ingieren ahora D&A total,
  **amortización de intangibles adquiridos** (separable), caja, deuda corriente/total, activo/pasivo
  corriente (ΔWC), acciones diluidas, goodwill, intangibles, impuesto, pretax e **interés**.
  Re-ingesta real: **325.049 filas, 82 tickers con datos**.
- **Adaptador EDGAR→serie** (`edgar_series.py`, point-in-time por `filing_date`, sin look-ahead):
  **capital invertido real = equity + deuda total − caja**; **D&A operativa = D&A total − amort.
  adquisiciones**; **EBIT reconstruido = pretax + interés** donde no se reporta OperatingIncomeLoss
  (PFE, MRK). No inventa: campo ausente si EDGAR no lo trae.
- **Driver** (`fundamental_driver.py`): con capital real, `s2c = ingresos/capital` y `ROIC = NOPAT/capital`
  son REALES; el capital ES reconstruible ⇒ **deja de bloquearse por amortización de adquisiciones**
  (ese bloqueo existía solo por aproximar el capital desde el capex). Guarda de escala de acciones
  (<1e5 ⇒ insuficiente). Capital ≤ 0 ⇒ bloqueo honesto.

**Desbloqueo verificado (datos reales, driver desde EDGAR):**

| Ticker | Antes | Ahora | Capital | ROIC | FV exp. | Margen |
|---|---|---|---|---:|---:|---:|
| PFE | bloqueada (amort. adq.) | **confiable** | EDGAR real | 6,1 % | 9,22 | −68,7 % |
| MRK | insuficiente (sin EBIT) | **confiable** | EDGAR real | 22,1 % | 103,74 | −29,5 % |
| AMGN | bloqueada | **confiable** | EDGAR real | 14,3 % | 156,00 | −66,7 % |
| JNJ | bloqueada | **confiable** | EDGAR real | 25,5 % | 127,97 | −54,4 % |
| ADBE | bloqueada | **confiable** | EDGAR real | 58,8 % | 316,68 | +33,3 % |
| LOW / UPS / HD / EOG | — | confiable/exp. | EDGAR real | 14–67 % | — | — |
| MCD | FV absurdo ($185 M/acc.) | **insuficiente** | — | — | — | guarda de escala |

> El antiguo bug de PFE (FV $61 "atractivo") desapareció: PFE queda en −68,7 % (no-compra) con capital real.

## PRIORIDAD 2 — NVDA y modelos productivos

- **Hallazgo material corregido:** el stack de valoración usaba **crecimiento terminal = tasa libre de
  riesgo (4,1 % USD)** cuando no se fijaba `g_terminal` — indefendible (perpetuidad = RF supera el GDP
  nominal de largo plazo). **Acotado a ≤2,5%** (`fcff_forward.py`), tope común con el driver experimental
  y el DCF productivo frontend (que ya usaba ≤3%).

  | Ticker | FCFF_GIIC antes | después | peso terminal |
  |---|---:|---:|---:|
  | NVDA | 145 | **126** | 0,60 → 0,54 |
  | META | 670 | **563** (de +10% a −8%) | 0,65 → 0,59 |
  | NFLX | 69 | **57** (de +9% a −10%) | 0,66 → 0,60 |
  | TSM | 240 | 240 (RF TWD 1,5% < 2,5%) | — |
  | ASML | 828 | **817** | — |

- **Cross-check del DCF productivo** contra datos frescos de EDGAR (réplica de `valuation.ts`):
  **META validado** (559 fresco vs 559 congelado, +0,1 %), **NFLX validado** (+5,4 %),
  **ASML razonable** (−10,8 %). **TSM no recomputable** (acciones IFRS no mapeadas). **NVDA no
  validable desde EDGAR**: su serie anual de FCF viene escasa (cierre fiscal en enero rompe el
  emparejamiento), solo 3 años ⇒ no se puede recomputar con fiabilidad. El FV productivo gobernante de
  NVDA ($90, −49 %) es un **snapshot congelado**; queda señalado como pendiente de recálculo con
  pipeline productivo (no se fabrica un número nuevo).

## PRIORIDAD 3 — Indicadores en pantalla

- **Ficha P3.0** muestra: ROIC, crecimiento de ventas, margen operativo, margen neto, margen de
  seguridad por modelo, **fuente gobernante** (productivo/FCFF/confianza), y nota explícita de que lo
  experimental no es confiable sin valoración productiva.
- **Análisis profundo (Fair Value)** muestra con unidades/método: FCF base normalizado + método, FCF
  último año, caja/deuda neta, histórico, CAGR de ingresos, **WACC/Ke (rf+β·ERP)**, crecimiento terminal,
  **peso del valor terminal**, rejilla de sensibilidad (tasa × crec. terminal) y crecimiento implícito
  (DCF inverso). El payload data-driven ahora expone ROIC, WACC, g1, gT, capital invertido y fuente.

## PRIORIDAD 4 — Proveedor: EDGAR reemplaza a EODHD

- EDGAR es la **fuente primaria** de series; EODHD solo respaldo. Verificado en producción:
  **fuentes = {EDGAR: 31, EODHD: 0}** ⇒ **dependencia residual de EODHD = 0** para fundamentales US.
- Probado con **EODHD deshabilitado** (opción `disable_eodhd`): el sistema valora igual solo con EDGAR.
- **Dependencias EODHD restantes:** ninguna en la ruta de valoración US. EODHD solo quedaría necesario
  (a futuro, no hoy) para fundamentales internacionales y consenso; el plan actual **no** da precios
  (son de Yahoo). Conclusión de la auditoría previa: cancelable/bajable. No se contrató nada.

## PRIORIDAD 5 — Validación y despliegue efectivo

- **Pruebas:** 445 passed, 6 skipped (incluye +15 nuevas: adaptador EDGAR, reconstrucción EBIT, capital
  invertido real, guarda de escala, regresión del driver; anclas de paridad actualizadas al terminal
  corregido). CI verde en todos los commits.
- **Despliegue efectivo (no solo CI):** valoraciones corregidas **escritas y re-leídas** en Supabase
  (`pit_snapshots`, snapshot 2026-11-14, append-only, histórico intacto); verificación de lectura
  `coincide: True`. El frontend productivo lee este snapshot.
- **Señales no validadas siguen bloqueadas:** con la política de producción (VALPOLICY apagado, el
  default), el Advisor da **postura "esperar", $0 compras, efectivo $3000**; las valoraciones
  experimentales data-driven quedan "FUERA de la asignación ejecutable: no se compran hasta tener
  valoración productiva". Barrera activa (ABBV en revisión).
- **Fair Values NO presentados como validados:** son experimentales, `no_calibrado_a_mercado`, y no
  gobiernan compras. PFE a −68,7 % es una lectura conservadora (no el falso $61), no una verdad validada.

## Advertencia de control (requiere tu decisión)

El flag **VITE_FF_VALPOLICY** controla si las valoraciones FCFF experimentales pueden ser accionables
como *fallback* cuando no hay FV productivo. Con el flag **apagado** (default de producción, verificado):
$0 compras — mandato cumplido. Si se **activa**, los nombres experimentales desbloqueados con margen
positivo (ADBE +33 %, COP +10 %) se vuelven accionables **pese a no estar validados productivamente**.
**Recomendación:** mantener VALPOLICY apagado hasta que esas valoraciones tengan validación productiva.

## Pendientes honestos (no comprobados = no declarados hechos)

- **NVDA productivo**: recomputar el FV congelado ($90) con el pipeline productivo (su serie EDGAR de
  FCF es escasa por el cierre fiscal de enero; no se fabrica número).
- **TSM/ASML (IFRS)**: mapear acciones/FX IFRS para cross-check productivo desde EDGAR.
- **ABBV**: usa proxy capex pese a tener capital invertido en EDGAR (equity negativo + Allergan);
  queda correctamente conservador/bloqueado, pero conviene revisar la consistencia del adaptador.
