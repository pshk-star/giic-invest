# Corrección del motor de valoración — resultados verificados

CI verde (`b05f15e`). Verificado end-to-end con datos reales (dry-run del job real + advisor_preview).
No se tocó P3.0 ni la interfaz anterior; no se contrataron servicios.

## Qué errores se corrigieron realmente
1. **"Crecimiento gratis" (reinversión negativa artificial).** El driver usaba reinversión neta
   `(capex − D&A)`, que se volvía **negativa** cuando la D&A está dominada por **amortización de
   intangibles adquiridos** (PFE, AMGN…), inflando el FCFF (FCFF > NOPAT todos los años con crecimiento
   positivo). **Corregido:** reinversión por **sales-to-capital desde el capital implícito del capex**
   (PP&E ≈ capex/0,10), **siempre positiva al crecer** y consistente con el ROIC. Ya no se usa `(capex−D&A)`.
2. **Capital no reconstruible → bloqueo honesto.** Donde **D&A ≫ capex** (ratio > 1,5) el capital invertido
   no se puede reconstruir del capex (es amortización de adquisiciones). Esas valoraciones se **bloquean**
   con causa explícita en vez de inventar capital.
3. **Crecimiento sesgado.** g1 pasó de **CAGR de toda la historia** (41 años para PFE) a **ventana reciente
   (~5 años)**, que refleja la trayectoria actual (patent cliff, fin del pico COVID).
4. **Crecimiento terminal.** De `gT = RF (4,1 %)` a **gT ≤ 2,5 %** (defendible, no = tasa libre de riesgo).

No se ajustó ningún supuesto para coincidir con precios objetivo de analistas; no se promedió con otras
valoraciones.

## Qué Fair Values / indicadores cambiaron (antes → después)
| Ticker | FV antes | FV después | Margen antes | Margen después | Estado |
|---|---:|---:|---:|---:|---|
| PFE | 61,06 | **44,51** | +107 % | **+51 %** | **BLOQUEADA** (amort. adq.) |
| AMGN | 577,67 | **227,36** | +23 % | **−51 %** | **BLOQUEADA** |
| ADBE | 462,47 | **307,02** | +95 % | **+29 %** | **BLOQUEADA** |
| HD | 421,62 | **189,41** | +20 % | **−46 %** | sobrevalorada (no compra) |
| LOW | 296,58 | **120,09** | +28 % | **−48 %** | sobrevalorada (no compra) |
| UPS | 123,96 | **76,27** | +10 % | **−32 %** | sobrevalorada (no compra) |
| EOG | 187,98 | **149,93** | +22 % | **−2,5 %** | ~ razonable (no compra) |
| MRK | 142,78 | **117,13** | −3 % | **−20 %** | sobrevalorada |

**Efecto neto:** las "atractivas" (margen ≥ 10 %) cayeron de **7 a 2**, y **ambas (PFE, ADBE) están
bloqueadas** ⇒ el Advisor pasó de desplegar en nombres defectuosos a **postura "esperar", dinero nuevo
$0, efectivo $3.000**. **Cero señales de compra sobre datos defectuosos.** Misma política para Advisor,
Scanner y Allocation (verificado en el preview).

## Empresas que siguen bloqueadas y por qué
- **PFE, AMGN, ABBV, JNJ, ADBE** (FCFF data-driven): **D&A ≫ capex** ⇒ capital invertido dominado por
  amortización de adquisiciones; **falta el capital invertido real** (equity/goodwill con fecha de
  publicación, hoy no ingerido de EDGAR). No se inventa: quedan **en revisión**.
- **TSM, ASML** (FCFF data-driven): **ADR/divisa (TWD/EUR)** no validada en el driver ⇒ bloqueadas; en
  producción **gobierna su FV productivo (P1.9)**, que sí maneja ADR/FX. El driver experimental no se usa
  para ellas.

## Gobernadas por el modelo productivo (sin cambios, no afectadas por el bug)
**NVDA, TSM, ASML, META, NFLX** tienen FV productivo (P1.9) que **manda**; el driver data-driven no las
valora. Sus acciones en cartera (REDUCIR/MANTENER) provienen del productivo.

## Resultado de las pruebas
- **Backend: 431 passed, 6 skipped.** Incluye **4 pruebas de regresión nuevas** del fix: empresa normal no
  bloqueada + terminal defendible; bloqueo por amortización de adquisiciones; sin `free_growth` y
  reinversión positiva al crecer; ADR/divisa en revisión. **Las pruebas impiden la reaparición del error.**
- **Frontend: CI verde** (P3.0 y la interfaz anterior intactas).
- Verificación de datos reales: dry-run del job (FV corregidos) + advisor_preview (postura esperar, $0 en
  compras, 5 bloqueadas).

## Lo que NO se hizo (honesto, para no declarar corregido lo no comprobado)
- **Ingesta ampliada de EDGAR** (D&A separada op/amortización, caja, equity, **capital invertido**) para
  **desbloquear** PFE/AMGN/ABBV/JNJ/ADBE y **eliminar la dependencia de EODHD en US**: pendiente (requiere
  ampliar `fundamentals_pit`). Sin ese capital, esas valoraciones **permanecen bloqueadas** (es la data que
  falta).
- **Recalcular NVDA productivo** y reconciliar su FCF FY/TTM: el productivo es el modelo calibrado; su
  refresco de insumos es tarea aparte (no afectada por este bug).

## Commit y despliegue
- Commits: `a292ca3` (fix del motor + regresión), `b05f15e` (persistencia append-only corregida).
- CI verde; Cloudflare Pages redeploya desde `main`. P3.0 bajo `VITE_FF_P30`; interfaz anterior intacta.
