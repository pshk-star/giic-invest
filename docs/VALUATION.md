# Valoración — estado, limitaciones y costura de integración

Estado: **PRELIMINAR / SOLO SEÑALES**. El motor NO emite decisiones de inversión
(COMPRAR / VENDER / AUMENTAR) por valoración. Describe señales y gestiona riesgo.

## Qué hace hoy

- **Señal descriptiva** por acción (núcleo: `frontend/src/core/fundamental.ts`):
  - `earningsYield` = EPS **anual reportado** (EDGAR) ÷ precio actual. No circular.
  - `fcfYield` = FCF / market cap (reportado).
  - `yieldVsReference` ∈ {encima, cerca, debajo} vs una **referencia descriptiva** (`referenceYield`, hoy 7%).
    **No implica cara/barata**: ignora crecimiento, riesgo, calidad de beneficios y sector.
  - `cyclicalAlert`: `|crec. EPS YoY| ≥ 75%` ⇒ **alerta** de posible ciclicidad/efecto
    extraordinario. Es una alerta, **no** una afirmación de que los beneficios estén en un pico.
  - `epsConsistent` / `consistencyNotes`: identidad EPS×acciones ≈ utilidad neta (backend
    `edgar.py`), más aviso de conversión de moneda/ADR.
- **Proyección de precio a 12m** (`scenarios`, EPS×P/E con múltiplo constante): es **CIRCULAR**
  respecto al precio (`priceAnchored=true`) y se muestra **sólo como contexto**. No es valor razonable.
- **Clasificación operativa** (no decisión de inversión):
  - Oportunidades (`core/opportunities.ts`): `INVESTIGAR` (brecha de datos) o `ESPERAR`
    (EN OBSERVACIÓN; hay datos, se muestra la señal). **Nunca COMPRAR.** Sin montos; liquidez íntegra.
  - Posiciones (`core/position-review.ts`): `REDUCIR` **sólo** por concentración/riesgo
    (reversible, independiente de valoración), `REVISAR` (calidad baja / alerta cíclica /
    inconsistencia / sin cobertura), `MANTENER` por defecto. **AUMENTAR y VENDER por valoración
    están desactivados.**
- `decisionReady=false` en todas las valoraciones: marca que **no hay** valoración fundada.

## Por qué (auditoría)

1. EPS×P/E con múltiplo constante da `valor central = precio×(1+g)`: **circular**.
2. Un rendimiento exigido **fijo** (7%) no distingue crecimiento, riesgo, calidad ni sector;
   clasificar cara/barata contra él sería tan arbitrario como el modelo circular.
3. Cobertura de fundamentales limitada (p. ej. Visa sin EPS en EDGAR); brecha de datos ≠ falta de atractivo.

## Lo que falta para DECIDIR (costura de integración)

Cuando se defina el proveedor de datos, rellenar en `CompanyValuation`/`FundamentalsPayload`:

- **Bases de beneficio separadas** (ya hay slots, hoy `null`): `ttmEps`, `normalizedEps`
  (through-cycle), `forwardEps` (consenso). No mezclar periodos/bases por acción
  (`earningsBasis` identifica la base usada).
- **Múltiplos históricos** (P/E, EV/EBITDA, P/B por empresa y sector) para juzgar el precio
  actual contra su propia historia y pares.
- **Estimaciones forward** (ingresos/EPS de consenso) para valor prospectivo, no extrapolado.
- **Valoración normalizada** (DCF / múltiplos sobre beneficios normalizados) ajustada por
  crecimiento, riesgo (coste de capital por empresa/sector) y calidad de beneficios.

### Activación

Con esos datos, `decisionReady` pasa a `true` y un `valueVerdict` **fundado** (no la referencia
fija) habilita de nuevo COMPRAR/AUMENTAR/VENDER en `opportunities.ts` y `position-review.ts`.
El flujo COMPRAR / ESPERAR / INVESTIGAR y la conservación de liquidez se mantienen; sólo cambia
la señal que los dispara. Entregar especificaciones del proveedor para esta fase.

## Invariantes

- No inventar valoraciones, precios objetivo ni márgenes de seguridad.
- A/B/C experimentales intactos (309 predicciones históricas); no se amplían ni alteran aquí.
- Toda cifra de EPS debe ser coherente con precio, moneda, acciones y relación ADR antes de usarse.
