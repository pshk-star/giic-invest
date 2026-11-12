# Diagnóstico de credibilidad del motor de valoración — PFE y universo

**Alcance:** reconstrucción end-to-end del FCFF/DCF del driver data-driven (P2.4) con datos reales
(EODHD/Supabase), atribución cuantificada de la discrepancia y extensión al universo. **Solo lectura:
no se modificó ningún motor ni valoración.** Evidencia: `app/jobs/valuation_diagnostic.py` (CI, run
43249813594). Referencias externas: consenso PFE nov-2026 ≈ **$28–30** (Hold), valoración intrínseca
independiente ≈ **$33**; precio ≈ **$29,45**. GIIC: **$61,06** (+107 %).

---

## 1. Reconstrucción de PFE (datos de origen → valor por acción)

**Origen (EODHD, serie anual, fecha fiscal último dato 2025-12-31):**
- Revenue 2025 = **$62,58 B**; serie desde 1985 (incluye pico COVID 2022 = $101,2 B → 2023 $59,6 B → 2024 $63,6 B → 2025 $62,6 B, **plano/decreciente**).
- EBIT/operating income → **margen EBIT 27,8 %**.
- Acciones **5,686 B**; deuda total **$67,42 B**; caja **$1,14 B** → **deuda neta $66,27 B**.
- Capex 4,2 % de ventas; **D&A 10,5 %** de ventas; ΔWC −8,6 %.

**Supuestos derivados (como los fija el driver):**
- g1 = **CAGR histórico 41 años = 7,1 %** (clamp 18 %); margen terminal = **27,8 %** (= margen actual, cap 30 %).
- tax efectivo = **10 %** (piso del clamp); β = 1,10 (default); dv 28,4 %; **WACC 8,04 %**; **gT = RF = 4,1 %** (spread WACC−gT = 3,94 %).
- s2c = 2,0; **reinversión neta = (capex − D&A) = −6,33 % de ventas** (negativa) + ΔWC.

**Proyección (USD, 10 años explícitos):** cada año **FCFF > NOPAT** porque la reinversión es negativa
(−$4,6 B a −$7,2 B/año **se suman** al FCFF):

| Año | g | Revenue | NOPAT | Reinversión | FCFF |
|----:|---:|--------:|------:|-----------:|-----:|
| 1 | 7,2 % | 67,0 B | 16,78 B | −4,62 B | 21,40 B |
| 5 | 5,8 % | 85,5 B | 21,40 B | −5,81 B | 27,21 B |
| 10 | 4,1 % | 107,9 B | 27,01 B | −7,19 B | 34,20 B |

**Puente:** PV FCFF explícito **$180,7 B** + PV valor terminal **$232,8 B** = EV **$413,5 B**; − deuda
neta $66,3 B = equity **$347,2 B** ÷ 5,686 B acciones = **$61,06/acción**. Peso terminal 56 %.

---

## 2. Descomposición de la diferencia ($61 vs $30–33)

Escenarios contrafactuales (cada palanca aislada, FV/acción USD):

| Escenario | FV | Δ vs base |
|---|---:|---:|
| **A — base del driver** | **$61,06** | — |
| B — reinversión por s2c (sin (capex−D&A)) | $51,61 | **−$9,45** |
| C — gT 2,5 % (no 4,1 %) | $50,10 | **−$10,96** |
| D — margen terminal 15 % (no 27,8 %) | $36,10 | **−$24,96** |
| E — g1 0 % (patent cliff, sin crecimiento) | $42,15 | **−$18,91** |
| **F — combinado defendible** (B+C+D+E) | **$14,49** | **−$46,57** |

**Lectura:** el $61 **requiere las cuatro palancas optimistas a la vez**. Cada una vale entre $9 y $25.
Con supuestos moderados y defendibles, el FV cae a la banda **$14–36**, que **contiene** el consenso/
intrínseco de $30–33. El $30–33 es reproducible; el $61 no es defendible. El valor terminal (56 %) **no**
es el problema dominante: la inflación está repartida entre reinversión, crecimiento y margen terminal,
que inflan **tanto los flujos explícitos como el terminal**.

---

## 3. Patent cliff, ingresos, márgenes y reinversión

- **Patent cliff real** (Eliquis y otras pérdidas de exclusividad 2026–2028): el consenso proyecta
  ingresos **planos a decrecientes**. El driver proyecta **+7,1 %** porque mide el CAGR 1985→2025
  (crecimiento por M&A histórico: Warner-Lambert, Pharmacia, Wyeth + pico COVID). **Error de supuesto
  de crecimiento.**
- **Margen:** el driver fija el margen terminal = margen actual (27,8 %) **a perpetuidad**, sin
  compresión por el cliff. **Supuesto discutible** (el de mayor impacto, −$25).
- **Reinversión:** D&A (10,5 %) ≫ capex (4,2 %) porque la D&A está dominada por **amortización de
  intangibles adquiridos** (no es caja recuperable). La fórmula FCFF = NOPAT − (capex − D&A) − ΔWC es
  correcta contablemente, pero **proyectar (capex − D&A) negativo durante 10 años + terminal asume que
  PFE cosecha su base de activos para siempre manteniendo crecimiento y margen** — económicamente
  inconsistente (crecimiento con desinversión neta ⇒ ROIC incremental infinito). Además hay
  **inconsistencia interna:** los años explícitos usan reinversión negativa, pero el terminal usa
  rr_T = gT/ROIC = **+29,3 %** positiva.

---

## 4. Verificación de unidades, moneda, deuda, acciones, signos, fechas, datos

- **Deuda neta, acciones, revenue, fechas:** correctos (deuda neta $66 B, 5,69 B acciones, fecha fiscal 2025 ✔).
- **Tax efectivo 10 %** por el piso del clamp (real ≈ 15 %+): **infla NOPAT ~5 %**. Dato/implementación menor.
- **Caja $1,14 B** parece baja (EODHD "cash" excluye inversiones de corto plazo); sobreestima deuda neta → *reduce* FV, no lo infla. No es la causa.
- **ADR/moneda — bug real:** en la muestra, **TSM FV $5.173 (+1.151 %)** y **ASML −61 %** son absurdos:
  el driver **no maneja bien ADR/moneda** (TWD/EUR × ADR). Estas valoraciones no son fiables y **no deben
  ser accionables**. (En producción TSM/ASML usan P1.9, no este driver; pero el driver falla en ADR.)

---

## 5. Extensión al universo — ¿es sistemático? **Sí.**

| Ticker | Sector | FV | Precio | Margen | Reinv. neta %rev | Años reinv<0 |
|---|---|---:|---:|---:|---:|---:|
| **PFE** | Salud | 61,06 | 29,45 | **+107 %** | **−6,3 %** | 10 |
| AMGN | Salud | 577,67 | 468,11 | +23 % | **−9,0 %** | 10 |
| HD | Consumo | 421,62 | 351,31 | +20 % | −0,3 % | 10 |
| UPS | Industrial | 123,96 | 112,45 | +10 % | −0,1 % | 10 |
| MRK | Salud | 142,78 | 147,18 | −3 % | −2,7 % | 10 |
| EOG | Energía | 187,98 | 153,77 | +22 % | **+9,4 %** | 0 |
| LOW | Consumo | 296,58 | 231,60 | +28 % | +0,0 % | 0 |
| NVDA | Semis | 79,95 | 173,73 | −54 % | +1,5 % | 0 |
| TSM | — | 5.173 | 2.413 | +1.152 % | +15,3 % | 0 |
| ASML | — | 594 | 1.534 | −61 % | +1,7 % | 0 |

**Patrón:** las sobrevaloradas de salud/consumo (PFE, AMGN, HD, UPS) comparten **reinversión neta
negativa los 10 años** (D&A > capex por amortización de adquisiciones) + g1 = CAGR largo + margen terminal
= actual. **No es un problema de PFE: es el mecanismo del driver.** PFE es el caso extremo por combinar la
mayor brecha D&A−capex con el mayor CAGR histórico y un margen alto. Importante: el guard `FV_VS_PX_MAX`
(1,8×) sólo atrapa a **PFE y ADBE**; **AMGN/HD/UPS quedan por debajo del umbral y SÍ generaban señal de
compra** (estaban en la lista de la Etapa A). El clamp es cosmético: no corrige el mecanismo.

---

## 6. Clasificación de las diferencias

- **Error de datos:** tax efectivo forzado a 10 % (piso); caja EODHD parcial (menor, no infla).
- **Error de implementación:** (a) **ADR/moneda** → FV absurdos en TSM/ASML; (b) **reinversión negativa
  perpetua con crecimiento positivo** (crecimiento gratis) e **inconsistencia explícito (reinv<0) vs
  terminal (reinv +29 %)**.
- **Supuestos discutibles:** g1 = CAGR 41 años (ignora cliff y tendencia reciente); margen terminal =
  margen actual a perpetuidad; gT = RF 4,1 % perpetuo.
- **Discrepancia legítima de metodología:** DCF intrínseco vs consenso de precio objetivo a 12 m (no
  comparables directamente); pero aun como DCF intrínseco, el $61 no es defendible.

---

## 7. Propuesta de salvaguarda (pendiente de tu aprobación — no implementada)

Mientras se resuelve, suprimir la **accionabilidad** (no la valoración, no los registros) de FVs con
discrepancia material no explicada, con criterios **económicos, no un clamp arbitrario**:
1. **Inconsistencia crecimiento/reinversión:** si reinversión neta < 0 con g1 > 0 (crecimiento gratis) ⇒
   no accionable (confianza baja + motivo explícito).
2. **ADR/moneda no resuelta** ⇒ no accionable.
3. (Ya existe) FV > 1,8× precio ⇒ baja; se mantiene como respaldo, no como mecanismo principal.

Esto **no altera Fair Values ni registros históricos**; solo impide que estas valoraciones generen
compras/asignaciones hasta corregir el motor. La corrección del motor (crecimiento con cliff, margen
terminal con compresión, reinversión consistente, ADR) se diseñará y validará **con evidencia antes de
tocar nada**.
