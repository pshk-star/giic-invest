# Reinversión del FCFF con ROIIC OBSERVADO — corrección de la fórmula circular

**Supersede a `FCFF_REINVERSION_FIX.md`**, cuya fórmula `ROIC_incremental = g1/RR_real` era **circular**: al
usar después `reinversión = g1/ROIC_incremental = RR_real`, el crecimiento se cancela algebraicamente y
`FCFF = NOPAT·(1−RR_real) = FCF` por construcción. Eso **no** demuestra que la reinversión económica sea
correcta; solo reproduce una identidad contable. Se retira.

## 1. Se retira la etiqueta "ROIC incremental" y la coincidencia FCFF=FCF como prueba

La fórmula circular se eliminó de `valuation_engine.py` (`_marginal_roic`). El motor **ya no fuerza** que el
FCFF proyectado iguale el FCF histórico. La comparación FCFF-proyectado vs FCF-real queda como
**diagnóstico informativo** (`FCFF_proy_vs_FCF_real_diag`), no como control de validación; solo una brecha
extrema (>3×, indicio de error de datos) manda a revisión.

## 2. FCF ≠ FCFF (distinción real, probada con estados oficiales NVDA FY2026)

| Magnitud | Definición | NVDA FY2026 |
|---|---|---:|
| **FCF** | OCF − CAPEX | **$96,7B** |
| **FCFF** | NOPAT + D&A − CAPEX − ΔNWC | **$77,7B** |
| NOPAT | EBIT·(1−tasa) | $110,7B |
| NOPAT − FCF | — | $14,0B |

Difieren porque el FCFF excluye el efecto de intereses/no-operativo y resta explícitamente el ΔNWC. No son
intercambiables; la ecuación del motor es la del FCFF.

## 3. ROIIC OBSERVADO = ΔNOPAT/ΔCapital invertido (balances oficiales, plurianual)

Reconstruido desde `StockholdersEquity + Deuda − Caja − Inversiones CP` de los 10-K (`capital_roiic_diag.py`,
`official_reconcile.observed_roiic`). Es **inestable o no medible** en la mayoría:

| Empresa | ROIIC 1a | ROIIC 3a | ROIIC plurianual | ¿Estable? |
|---|---:|---:|---:|---|
| NVDA | 36,2% | 78,8% | 71,5% | **sí** (alto) |
| META | −4,3% | 35,5% | 30,7% | **sí** (~33%) |
| LOW | −2,4% | 4,3% | 22,5% | no (razón 5,2×) |
| HD | −11,8% | −11,5% | 35,6% | no (negativo reciente) |
| PFE | — | — | — | **no medible** (EBIT/NOPAT no etiquetado) |

Criterio de estabilidad: ventanas 3a y plurianual **ambas positivas y consistentes** (razón ≤ 3×).

## 4. Descomposición de la brecha NOPAT−FCF con líneas reales (NVDA FY2026)

Del estado de flujos de efectivo, **sin clasificar nada automáticamente**:

| Componente | Valor | Concepto XBRL |
|---|---:|---|
| ΔCuentas por cobrar | +$15,4B | `IncreaseDecreaseInAccountsReceivable` |
| ΔInventario | +$11,3B | `IncreaseDecreaseInInventories` |
| ΔCuentas por pagar | +$3,1B | `IncreaseDecreaseInAccountsPayable` |
| **ΔNWC total** | **+$29,8B** | suma de componentes (uso de caja) |
| SBC (no-caja) | $6,4B | `ShareBasedCompensation` |
| Adquisiciones | $1,5B | `PaymentsToAcquireBusinessesNetOfCashAcquired` |
| D&A | $2,8B | `DepreciationDepletionAndAmortization` |
| CAPEX | $6,0B | `PaymentsToAcquireProductiveAssets` |

El ΔNWC de **$29,8B** (cuentas por cobrar + inventario del ciclo de IA) está **probado con líneas del estado**,
no supuesto. Es el componente dominante de la reinversión de NVDA (muy por encima del capex de $6B).

## 5. Economía de reinversión: ROIIC observado si estable; supuesto conservador documentado si no

```
ROIIC_0 = observado (promedio 3a/plurianual) si estable, acotado a ≤60%   (NVDA 60%, META 33%)
        = 15% conservador por defecto si inestable/no medible              (LOW, HD, PFE)
ROIIC_t  erosiona linealmente de ROIIC_0 a ROIIC_terminal = clamp(2×WACC, 10%, 18%)
Reinversión_t = g_t / ROIIC_t     ;    FCFF_t = NOPAT_t · (1 − g_t/ROIIC_t)
```

FCFF año 1 resultante (NOPAT TTM aprox): NVDA $101B (reinv 42%), META $32B (54%), LOW $5,7B (33%),
HD $13,2B (27%), PFE $8,0B (20%). **No se fabrica un ROIIC implícito para cerrar una identidad contable**;
donde el dato observado no es fiable, el supuesto es explícito, conservador (15%) y documentado.

## 6. Comparación del universo (NVDA, META, PFE, LOW, HD) ANTES de aplicar al resto

Hecha arriba (items 3-5): el ROIIC observado solo es utilizable en NVDA y META; LOW/HD/PFE caen al supuesto
conservador. La corrección se aplica uniformemente con esta regla; no se calibra por empresa.

## 7. Accionabilidad: TODO bloqueado mientras la metodología no esté validada

`METHODOLOGY_VALIDATED = False` en el motor. **Ningún** Fair Value es accionable —aunque pase los controles
aritméticos— hasta que exista validación por **backtest** contra retornos realizados. El FV y los
indicadores son **informativos**, no recomendaciones. El frontend respeta la barrera
(`engineMethodologyValidated`): `passesValueGate` exige `metodología validada`, hoy false ⇒ advisor
"esperar", $0 compras.

## No se tocó

Datos TTM ya conciliados (ingresos/EBIT/OCF/CAPEX por suma de 4 trimestres en ventana común), WACC,
crecimiento, ni se ajustó nada hacia un precio objetivo. Solo se corrigió la **economía de reinversión**.
