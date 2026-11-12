# Reconciliación cuantitativa NVDA — motor v2 ($81,64) vs ilustrativo (~$252)

No se ajustó el modelo para llegar a $252. Se identificó TODA la diferencia matemáticamente. Ambos
cálculos reproducen exactamente: ilustrativo **$249,83** (≈$252 ✓), motor **$81,64** ✓.

## 1. NVDA año por año (datos reconciliados EODHD+EDGAR, USD)

| Cierre fiscal | Ingresos | EBIT | NOPAT | Capex | FCF real (OCF−capex) | Deuda | Caja | Acciones |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2024-01 | 60,9B | 33,0B | 28,9B | 1,1B | 27,0B | 11,1B | 7,3B | 24,9B |
| 2025-01 | 130,5B | 81,5B | 70,3B | 3,2B | 60,9B | 10,3B | 8,6B | 24,8B |
| 2026-01 | 215,9B | 130,4B | 109,0B | 6,0B | **96,7B** | 11,4B | 10,6B | 24,5B |

NVDA genera **$96,7B de FCF real** con capex de solo $6B (modelo capital-ligero / fabless).

## 2. Escenario ilustrativo (verificado)

FCF₀ $140B, 22% (5a) + 10% (5a), descuento 9,5%, terminal 3%, +$30B neto, 24,51B acciones →
EV $6.094B, PV terminal $3.896B (64%), equity $6.124B, **FV/acción $249,83**. Reproduce el ~$252.

## 3. Puente cuantitativo (una variable a la vez) — datos vs supuestos

| Paso | FV | Δ | Tipo |
|---|---:|---:|---|
| 0) Ilustrativo | 249,83 | — | — |
| 1) Base caja $140B → FCF real NVDA $96,7B | 172,90 | **−76,93** | **DATO** (el ilustrativo sobreestima el FCF actual 45%) |
| 2) FCF real → FCFF motor $43B (reinversión g/ROIC) | 76,71 | **−96,19** | **SUPUESTO — driver dominante** |
| 3) Crecimiento 22/10 → lineal 25→2,5% | 66,15 | −10,56 | SUPUESTO |
| 4) Descuento 9,5% → WACC 12,34% (beta 1,70) | 44,56 | −21,59 | SUPUESTO |
| 5) Terminal 3% → 2,5% | 43,39 | −1,17 | SUPUESTO |
| 6) Ajuste +$30B → caja neta real −$1B | 42,13 | −1,26 | DATO |
| = motor (estructura NOPAT·(1−g/ROIC) anual) | 81,64 | +39,51 | ajuste de estructura¹ |

¹ El puente usa "crecer una caja base"; el motor crece NOPAT y aplica reinversión cada año (el margen
FCFF se expande al caer g), lo que explica el +39,51 hasta el valor real del motor.

**Diagnóstico:** la diferencia se descompone en **datos (~−$78: FCF base sobreestimado en el ilustrativo)**
y **supuestos (~−$130: reinversión g/ROIC, senda de crecimiento, WACC)**. El **driver dominante (−$96) es
el supuesto de reinversión g/ROIC**: el motor proyecta FCFF de $43B cuando NVDA YA genera $96,7B de FCF.
Con ROIC medio 42,7% y g 25%, la fórmula exige reinvertir el 59% del NOPAT — económicamente falso para
NVDA, cuyo capex real es $6B. **Es un defecto del supuesto de reinversión, no del WACC ni de los datos.**

## 4. Construcción del WACC 12,34% (item 4 — sin bajarlo artificialmente)

RF(USD) 4,2% + beta **1,70** × ERP(USD) 4,8% = Ke **12,36%**. Peso equity 100% (NVDA sin deuda neta;
Kd después de impuestos 4,56% con peso ~0) → **WACC 12,34%**. Fuentes: RF bono 10A USD, ERP de mercado,
beta de mercado publicada de NVDA (~1,7). El ilustrativo usa descuento 9,5%, que implica beta ~1,1 —
demasiado baja para NVDA. **No se baja el WACC para elevar el FV**; 12,3% es defendible para un valor de
beta alta. (Efecto del WACC en el puente: −$21,59, menor que el supuesto de reinversión.)

## Correcciones implementadas (items 5–8)

- **Item 6 — prueba de realidad FCFF vs FCF real:** control nuevo. Si el FCFF proyectado difiere >30% del
  FCF real reciente, la valoración pasa a **en_revision**. NVDA (43B vs 97B), META, NFLX, ASML, UPS, AMGN,
  ADBE caen a revisión. El supuesto de reinversión g/ROIC con ROIC medio no reconcilia con la caja real.
- **Item 6 — validación aritmética vs económica:** el estado "validado" se renombró a **"consistente"** =
  pasa los controles ARITMÉTICOS; **no** implica validación económica ni predictiva (eso exige backtest/
  track record, pendiente). No se declara el modelo validado por pasar pruebas.
- **Item 5 — NFLX/ASML/splits:** control de datos dudosos (salto de acciones YoY >3x = split no ajustado)
  ⇒ en_revision. NFLX marcada. Ninguna empresa con datos cuestionados figura como consistente. (TSM sigue
  **no_valorable**: ni EODHD ni EDGAR dan balance en TWD.)
- **Item 7 — fecha de snapshot:** el frontend lee por `captured_at` (hora real de escritura), no por
  `snapshot_date` (datable a futuro). Reescrito con fecha de hoy (2026-11-12).
- **Item 8 — bloqueo:** solo lo "consistente" es accionable. Hoy consistentes = LOW, HD, ambas
  sobrevaloradas ⇒ **advisor en "esperar", $0 compras** (verificado). El resto, bloqueado.

## Clasificación resultante (11)

| Estado | Empresas |
|---|---|
| consistente (aritmético) | LOW (−28%), HD (−27%) — ambas sobrevaloradas, no compra |
| en_revision (bloqueadas) | NVDA, META, NFLX, ASML, UPS, PFE, AMGN, ADBE |
| no_valorable | TSM (balance TWD no reconstruible) |

El FV de NVDA ($81,64) **no se declara correcto**: queda en revisión porque su FCFF proyectado no
reconcilia con el FCF real. La corrección del supuesto de reinversión (ROIC marginal / anclaje al FCF
real para empresas capital-ligeras) es el siguiente paso de modelado — no se hace aquí para no "ajustar
a un número", sino que se marca explícitamente como no consistente.
