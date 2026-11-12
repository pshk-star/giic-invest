# Motor de valoración GIIC v2 — entrega verificada

Motor único FCFF DCF data-driven y reproducible que reemplaza los modelos fragmentados (PRODUCTIVE_DCF
congelado, FCFF_GIIC calibrado, driver experimental). Datos reales reconciliados EODHD + SEC EDGAR.
Controles automáticos y estado de validación explícito. Un solo Fair Value gobernante. 454 pruebas
backend + CI frontend verde. Desplegado (snapshot 2026-11-15, re-lectura verificada). No se contrató nada.

## Arquitectura (sin supuestos ocultos)

1. **Reconciliación EODHD + EDGAR** por campo, periodo, moneda, unidad. Sin preferencia dogmática: gana la
   fuente más completa; discrepancias >25% en ingresos/equity/capital ⇒ control de revisión (no se calibra).
2. **Normalización**: margen operativo (mediana reciente), tasa efectiva (mediana acotada), crecimiento
   (CAGR reciente acotado 0–25%), capital invertido (equity+deuda−caja), ROIC=NOPAT/capital, D&A operativa
   separada de amortización de adquisiciones, EBIT reconstruido (pretax+interés) donde no se reporta.
3. **FCFF DCF doble ancla reconciliada**:
   - (A) FCFF/WACC: NOPAT·(1 − g/ROIC), descontado al WACC (Ke CAPM + Kd + estructura de capital).
   - (B) FCFE/Ke: FCF real (OCF−capex) proyectado, descontado al coste de equity.
   - La divergencia A↔B es el control central ("FCF histórico vs proyectado"): >35% ⇒ revisión.
4. **Terminal** económico: gT = min(tasa libre de riesgo, GDP nominal LP) ≤2,5%; ROIC terminal sostenible.
5. **ADR + FX**: FV/acción local × ratio ADR × FX a USD (parámetros fechados 2026-11).
6. **Controles** (revisión, no calibración): WACC>gT, peso terminal, reinversión<ROIC, margen plausible,
   escala de acciones, reconciliación FCFF/FCFE, consistencia entre fuentes, margen extremo.
7. **Validación**: `validado` solo si pasa todos los controles ⇒ accionable. `en_revision`/`no_valorable`
   ⇒ FV visible pero **bloqueado** (no genera compras/asignaciones). Advisor/Scanner/Allocation consumen
   este FV único gobernante.

Parámetros de mercado centralizados y fechados (2026-11): RF {USD 4,2% EUR 2,6% TWD 1,5%}, ERP {USD 4,8%
EUR 5,5% TWD 7,0%}, FX a USD {EUR 1,08 TWD 0,031}, betas de mercado publicadas por ticker.

## Tabla comparativa de las 11 (antes → después)

Precios al 2026-11-11 (fuente: tabla `prices`, Yahoo). "Antes" = FV gobernante previo (productivo
congelado o data-driven, con sus absurdos). "Después" = motor v2.

| Ticker | Precio | FV antes | FV v2 | MoS v2 | WACC | ROIC | g1→gT | Term.%EV | Div. FCFF/FCFE | Estado |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NVDA | 173,73 | 90 (cong.) | **81,64** | −53,0% | 12,3% | 42,7% | 25→2,5% | 55,8% | 13,9% | **validado** |
| META | 628,77 | 559 (cong.) | **442,50** | −29,6% | 9,7% | 19,0% | 18,5→2,5% | 71,4% | 32,9% | **validado** |
| NFLX | 64,54* | 37 (cong.) | **27,41** | −57,5% | 10,2% | 22,9% | 12,6→2,5% | 59,7% | 23,0% | **validado**¹ |
| TSM | — | 98 (cong.) | — | — | — | — | — | — | — | **no_valorable**² |
| ASML | 1534,42* | 720 (cong.) | **615,36** | −59,9% | 9,7% | 60,0% | 18,5→2,2% | 58,5% | 22,8% | **validado**¹ |
| PFE | 29,45 | 61→9,22 (absurdo) | **41,88** | +42,2% | 6,5% | 9,5% | 8,5→2,5% | 80,6% | 13,1% | en_revision³ |
| AMGN | 468,11 | 227 (bloq.) | **355,63** | −24,0% | 6,7% | 17,3% | 7,6→2,5% | 72,9% | 39,6% | en_revision⁴ |
| ADBE | 237,60 | 307 (bloq.) | **295,49** | +24,4% | 10,0% | 53,9% | 13,1→2,5% | 55,8% | 37,0% | en_revision⁴ |
| LOW | 231,60 | 120 (data-dr.) | **167,23** | −27,8% | 7,8% | 28,7% | 0→2,5% | 58,1% | 9,6% | **validado** |
| HD | 351,31 | 189 (data-dr.) | **255,72** | −27,2% | 8,2% | 28,5% | 4,5→2,5% | 59,8% | 2,5% | **validado** |
| UPS | 112,45 | 76 (data-dr.) | **121,05** | +7,6% | 7,9% | 60,0% | 1,0→2,5% | 59,0% | 14,7% | **validado** |

Sensibilidad (FV USD con WACC ±1pp): p.ej. NVDA [72,03 ; 93,59]; META [367 ; 544]; HD [207 ; 325]. FCFF
base (FCFF₀) y FCFE histórico por empresa en el payload `motor_v2` (campo `fcff0` / `fcfe0_hist`). Fuente
de cada variable: campo `procedencia.fuentes_por_campo` del payload (EODHD/EDGAR por campo).

**Notas:**
1. **NFLX/ASML**: precio de la tabla (NFLX 64,54; ASML 1534) posiblemente obsoleto/mal escalado en la
   ingesta Yahoo (NFLX reporta ~4,3B acciones en AMBAS fuentes, coherente con un posible split posterior).
   El motor computa fielmente sobre el dato disponible; es un tema de **ingesta de precios**, no del motor.
2. **TSM**: no valorable — ni EODHD ni EDGAR aportan equity/deuda en TWD (IFRS/ADR). Marcado explícito
   (Pablo: "si no aplica, indícalo"). Requiere mapeo de balance IFRS o plan EODHD con cobertura de Taiwán.
3. **PFE**: +42% pero **en revisión** (peso terminal 80,6% >80%). Ya no es el absurdo ($61 "atractivo" o
   $9,22): $41,88 es defendible pero frágil por dependencia del valor terminal ⇒ no accionable.
4. **AMGN/ADBE**: en revisión por divergencia FCFF/FCFE >35% (ADBE con mucho SBC, AMGN apalancada). ADBE
   +24% pero **bloqueado**: no genera compra hasta reconciliar. (Mandato: no accionar lo no validado.)

## Validación y despliegue

- **Pruebas**: 454 backend passed (+18 del motor: reconciliación, FCFF/FCFE, controles, validación, ADR/FX,
  consistencia de fuentes) + CI frontend verde (política motor_v2, typecheck, vitest).
- **Despliegue efectivo**: FV gobernante escrito a `pit_snapshots` (origen `motor_v2`, snapshot 2026-11-15,
  10 insertadas; TSM no_valorable no escribe FV). El frontend lee el snapshot más reciente por ticker.
- **Política única verificada**: `advisor_preview` sobre los datos nuevos ⇒ postura **"esperar", $0
  compras**. Validadas sobrevaloradas (o UPS +7,6% <umbral) ⇒ no compra; PFE/ADBE (margen positivo) **en
  revisión ⇒ bloqueadas**. Ninguna señal no validada es accionable.
- **Fair Values no presentados como validados por haber cambiado**: cada FV trae su estado de validación y
  los controles que falla; los extremos quedan en revisión, no se calibran al consenso.

## Pendientes honestos

- **TSM**: mapeo de balance IFRS (TWD) o fuente con cobertura de Taiwán para reconstruir capital invertido.
- **NFLX/ASML**: corregir la ingesta de precios (Yahoo) — dato posiblemente obsoleto/mal escalado.
- **Migración al universo completo**: el motor gobierna hoy las 11; extender al resto del universo del
  Scanner para un FV único en todos los nombres (hoy los demás conservan el modelo previo, ya seguro).
