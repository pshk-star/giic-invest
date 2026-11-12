# Corrección de la reinversión del FCFF — ROIC incremental (NVDA y universo)

El problema central del Fair Value era la **reinversión proyectada**, no los datos (ya conciliados). Se
corrige con una ecuación reproducible sobre datos confiables de flujo de caja, sin ajustar al precio.
459 pruebas + CI verde. Desplegado (snapshot 2026-11-12). Advisor "esperar", $0 compras.

## 1–2. Transición FCF TTM $127B → FCFF proyectado año 1 (NVDA), descompuesta

| Componente TTM | Valor | Fuente |
|---|---:|---|
| NOPAT (EBIT $197,6B × (1−tasa)) | $173,3B | oficial SEC / EODHD |
| D&A | ~$4,3B | cash flow |
| CAPEX | $7,4B | `PaymentsToAcquireProductiveAssets` |
| ΔCapital de trabajo | ~$24B (uso de caja) | cash flow |
| **Reinversión neta real** (NOPAT − FCF) | **~$46B** | = NOPAT $173B − FCF $127B |
| **FCF real** | **$127B** | OCF $134,4B − capex $7,4B |

**La reinversión real de NVDA está DOMINADA por el capital de trabajo (~$24B: inventario y cuentas por
cobrar del ciclo de IA), no por el capex ($7,4B).** NVDA es capital-ligera en activos fijos.

## 3. Diagnóstico: el ROIC equivocado, no doble conteo

| Tratamiento de reinversión año 1 | Reinversión | FCFF año 1 | vs FCF real $127B |
|---|---:|---:|---:|
| g/ROIC con **ROIC MEDIO** (60% capado) | $72B | $101B | **−20%** |
| g/ROIC con **ROIC INCREMENTAL** | $46B | **$127B** | **0%** (reconcilia) |

La fórmula `g/ROIC` con **ROIC medio** exige $72B de reinversión — ~$26B MÁS de capital del que la
estructura de NVDA requiere. **No hay doble conteo**: el error es usar el ROIC MEDIO (sobre el capital
legado) en vez del ROIC INCREMENTAL (sobre el capital NUEVO).

## 4. Corrección (ecuación reproducible, sin ajustar al precio)

```
RR_real            = (NOPAT − FCF_real) / NOPAT              (tasa de reinversión REAL)
ROIC_incremental   = g1 / RR_real   (= ΔNOPAT / reinversión = retorno sobre el capital NUEVO)
Reinversión_t      = g_t / ROIC_incremental
FCFF_t             = NOPAT_t · (1 − g_t/ROIC_incremental)
```

Así **FCFF año 1 = NOPAT·(1 − RR_real) = FCF real** (reconcilia por construcción). El ROIC incremental
se deriva de datos de flujo de caja **confiables** (NOPAT y FCF ya conciliados), no del balance (que para
NVDA viene incompleto). El **ROIC terminal es conservador (≤25%)**: la competencia erosiona los retornos
excedentes, de modo que el valor terminal no hereda el ROIC incremental alto. **No se tocó WACC,
crecimiento ni se ajustó nada hacia el precio de mercado.** Si no hay FCF real confiable, se usa el ROIC
medio (comportamiento anterior).

## 5. Verificación capital-ligeras vs intensivas (sin errores nuevos)

| Ticker | Perfil | FV | MoS | Estado | Nota |
|---|---|---:|---:|---|---|
| NVDA | capital-ligera (fijo) | 145,55 | −16,2% | **consistente** | FCFF año 1 reconcilia con FCF real ✓ |
| AMGN | farma | 471,26 | +0,7% | consistente | ~fair value |
| LOW | retail capital-intensivo | 144,74 | −37,5% | consistente | reinversión alta, FV bajo ✓ |
| HD | retail capital-intensivo | 224,05 | −36,2% | consistente | ✓ |
| META | capex IA alto | 580,67 | −7,6% | en_revision | FCFF/FCFE divergen |
| UPS | logística capital-intensiva | 69,61 | −38,1% | en_revision | FCFF/FCFE divergen |
| ASML | semi (20-F semestral) | 827,97 | −46,0% | en_revision | FCFF vs FCF real |
| ADBE | software | 320,30 | +34,8% | en_revision | FCFF vs FCF real |
| NFLX | — | 52,15 | −19,2% | en_revision | precio/acciones en verificación |
| PFE | farma, WACC bajo | 62,15 | +111% | en_revision | margen extremo (WACC 6,5% + terminal) ⇒ bloqueado |
| TSM | ADR TWD | — | — | no_valorable | sin XBRL US |

Capital-ligeras (NVDA) e intensivas (LOW, HD) funcionan sin errores nuevos. Los casos cuyo FCFF no
reconcilia con el FCF real, o con datos no conciliados (TSM/ASML/NFLX) o margen extremo (PFE), quedan
**en revisión / no valorables ⇒ bloqueados** (items 6).

## 6–7. Accionabilidad y validación

- **Bloqueadas (no accionables):** TSM, ASML, NFLX, PFE, META, ADBE, UPS (en_revision/no_valorable).
- Consistentes hoy (NVDA −16%, AMGN +0,7%, LOW −38%, HD −36%): **ninguna supera el umbral de compra**
  (≥+10%) ⇒ advisor **"esperar", $0 compras** (verificado).
- **"Consistente" = pasa controles ARITMÉTICOS, NO validación económica/predictiva** (requiere backtest/
  track record, pendiente). No se declara ningún Fair Value validado por pasar pruebas.

## Pendiente honesto

- **Capital invertido de NVDA incompleto** en la ingesta (equity/deuda faltan en años recientes): por eso
  el ROIC incremental se deriva del flujo de caja (RR real), no del balance. Reconstruir el balance
  completo permitiría un ROIC incremental por ΔNOPAT/ΔIC directo.
- **PFE**: FV sensible al WACC bajo (beta 0,62) + spread WACC−gT; queda en revisión (no accionable).
