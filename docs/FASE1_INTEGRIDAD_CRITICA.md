# Fase 1: integridad crítica del motor y su publicación

Base: `main` en `5c4f6e3`. Rama independiente: `fix/codex-financial-integrity`.
Se revisó el PR #1 (`8723ab9`); se reutilizan sus correcciones verificadas de unidades,
capitalización ADR, propagación de bloqueo, contador y escenarios, ampliando sus regresiones.
No se modifica la rama de Claude. No hay autorización de merge ni despliegue.

## Arquitectura y alcance

La ruta activa de producción es React/TypeScript en Cloudflare Pages, lectura con RLS de
Supabase y jobs Python en GitHub Actions. FastAPI es opcional; no se reconstruye el sistema.
Se conservan transacciones, analítica de cartera, scanner multifactor, ETF look-through,
histórico y registro PIT de investigación. Los módulos financieros legacy conservados sirven
para investigación/pruebas; `/advisor` deja de montar el Advisor que recalculaba otro DCF.
La ficha muestra la publicación gobernante en lugar de un segundo DCF de navegador.

Esta entrega P0 corrige admisión, unidades, contratos y publicación. No certifica
la valoración económica ni resuelve los modelos dedicados y supuestos sectoriales P1/P2.
`METHODOLOGY_VALIDATED` sigue en `False`.

## Defectos, reproducción y corrección

| Defecto | Corrección | Evidencia automatizada |
|---|---|---|
| USD/TWD y orden de filas | Unidad exacta por concepto; moneda explícita o inferencia sin empate; ambigüedad rechazada | `test_dual_currency_requires_explicit_reporting_currency_on_tie`, F1 del PR #1 |
| Capitalización incompatible con deuda | Precio USD / FX / ADR × acciones ordinarias; ratios fraccionarios positivos admitidos; contrato de precio y acciones validado | `test_dimensions_are_equivalent_across_currencies_and_adr`, `test_live_price_contract_is_explicit_and_finite`, `test_missing_quote_does_not_invent_wacc_capital_weights` |
| TTM con huecos o ancla antigua | Cuatro cierres a 80–100 días; última ventana completa SEC/EODHD; todos los fallbacks usan el mismo validador | `test_ttm_rejects_gaps_through_all_fallbacks`, `test_latest_complete_window_beats_older_sec_window` |
| Controles TTM perdidos | Se preservan en controles/estado; ausencia de campos necesarios invalida | `test_failed_ttm_control_is_not_silently_discarded` |
| Pérdidas artificialmente positivas / recuperación rechazada | Selección de base TTM antes de normalizar; historia observada sin reescritura; pérdidas sin truncado a +1% | `test_ttm_operating_loss_never_becomes_positive_margin`, `test_recovery_is_assessed_using_the_actual_ttm_base` |
| Caja/deuda ausentes convertidas a cero | Entrada no admisible; cero observado sigue siendo válido | `test_currency_conflict_and_missing_cash_cannot_emit_fv` |
| Monedas distintas entre estados | Rechazo antes de sumar flujos | `test_ttm_cannot_mix_statement_currencies` |
| Revisión intradía ignorada / FV anterior sobreviviendo | Feed inmutable por corrida, publicación atómica, invalidación explícita | `test_job_publishes_same_day_revisions_and_invalidations`, `valuation-publication.test.ts` |
| Venta/recorte con metodología bloqueada | Propagación desde orquestador; estado bloqueado conservado y sin recorte cuantificado por FV | `advisor-engine.test.ts`: regresión P0 de orquestador |
| Consumidores con versiones distintas | Adaptador común y lectura por orden de publicación; sin fallback a snapshots legacy | `valuation-feed.test.ts`, siete rutas Chromium |
| Escenarios objeto mostrados como ausentes | Extracción escalar compatible con objetos nuevos/números anteriores | `fundval-render.test.ts`: render React real |

Las regresiones financieras iniciales produjeron 10 fallos sobre `main`; la regresión del
orquestador reprodujo `REDUCIR` antes de corregirlo. La recuperación ya funcionaba parcialmente
en `main` y es una protección contra la regresión introducida por el PR #1.
Se corrigieron las unidades erróneas de acciones de un fixture anterior (`USD` → `shares`),
sin flexibilizar el selector. La prueba anterior de CAPEX usa ahora el fallback de ventana
común, conserva un control por SEC incompleta y ya no elige una cifra solo por ser mayor.

## Publicación y despliegue pendiente de autorización

La migración `backend/supabase/migrations/0013_governing_valuations.sql` crea un feed
separado: no altera ni borra `pit_snapshots` ni las predicciones históricas.

- `valuation_snapshots`: una fila inmutable por ticker/corrida; mismo día admite varias revisiones.
- RPC `publish_valuations`: lote atómico, escritura exclusiva de service_role, serialización de
  publicaciones y reintento idempotente del mismo ID/payload. Un ID reutilizado con otro payload falla.
- Cada ticker intentado publica resultado o `no_valorable` sin FV. Un fallo actual no recupera el FV previo.
- Lectura autenticada; escritura de clientes denegada; UPDATE/DELETE rechazados por trigger.
- El frontend congela un límite de identidad para paginar una vista consistente. La captura más
  reciente gobierna aunque invalide; un payload mal formado falla cerrado.
- Los jobs antiguos pueden seguir publicando investigación PIT; esas filas no sustituyen el feed gobernante.

Orden de despliegue futuro: aprobar/aplicar migración, ejecutar job nuevo y revisar su publicación,
publicar frontend. No se ejecutó la migración ni se cambió Cloudflare/Supabase en producción.
Si el feed/migración falta, la UI muestra error/ausencia y no recupera valoraciones antiguas.
La prueba PostgreSQL embebida valida SQL, atomicidad, permisos, inmutabilidad e idempotencia;
no equivale a una prueba de PostgREST/Supabase real. Esta última requiere el despliegue autorizado.

## Inputs, unidades y consecuencias financieras

El payload guarda `audit_inputs`: base TTM por campo, ventana, fuentes/conceptos/contextos SEC
disponibles, historia anual observada, fechas de balance/acciones, moneda de precio, base accionaria,
ADR, FX, pesos/WACC exactos, impuesto y supuestos identificados como estimados. Incluye revisión
de código cuando Actions proporciona `GITHUB_SHA`. No se calibra a cotizaciones ni a cifras anteriores.

La tasa de impuesto TTM se usa con su signo observado (sin elevarla silenciosamente al 8% ni
aplicar valor absoluto); tasas fuera del dominio admitido requieren revisión y no producen FV.
El escudo fiscal del Kd estimado se sincroniza con esa misma base. Rf, ERP, betas, FX, ROIIC
por defecto, convergencia y paquetes de escenarios NO se cambian ni se consideran validados.
Esto puede cambiar FV además del arreglo dimensional: se registra el input, no se compensa con otra tasa.

Comparación controlada con fixtures sintéticos idénticos (NO valoraciones de emisores):

| Fixture | FV anterior | FV P0 | Causa |
|---|---:|---:|---|
| USD ordinarias | 720,71 | 720,71 | Identidad doméstica conservada |
| EUR con cotización USD | 908,20 | 928,47 | Pesos del WACC en EUR, en lugar de mezclar USD/EUR |
| TWD/ADR | 309,52 | 122,50 | Ratio/FX aplicados a capitalización; fixture con deuda elevada |

En TSM, el efecto aislado previamente reproducido con los inputs publicados es WACC
8,23% → aproximadamente 8,75% y FV 338,38 → aproximadamente 308,80 USD. No es un objetivo
ni la certificación de una nueva valoración integral: el log anterior redondeaba tasas y no
conservaba el JSON original completo. Una corrida de solo lectura con datos actuales puede
producir otro FV o invalidación. No se rellenan los inputs ausentes para obtener un número.

## Reproducción

```sh
cd backend
pytest -q --ignore=tests/integration
cd ../frontend
npm install
npm test
VITE_SUPABASE_URL=https://example.supabase.co VITE_SUPABASE_ANON_KEY=fixture npm run build
npx playwright install chromium
npm run test:browser
# Con navegador del sistema: CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm run test:browser
```

El smoke de Chromium levanta Vite local y simula Auth/REST: no usa cuentas reales ni escribe datos.
Comprueba `/advisor`, `/asesor`, `/scanner`, `/advisor3`, `/research/NVDA`, `/fundamental`, `/p30`.
CI ejecuta unitarias, SQL embebido, render, build y smoke de navegador.

## Pendientes separados por fase

P1: balance trimestral más reciente y reconciliación temporal entre fuentes; deuda total/caja/inversiones
y leases; acciones diluidas y splits; ROIC observado versus truncado y capital medio; ROIIC con denominadores
comparables; puente FCFF/FCFE con financiación y signos de NWC; conciliación oficial de discrepancias por emisor;
política de normalización fiscal económica y Kd sustentado. Los inputs de balance actuales se fechan, no
se presentan como corregidos por esta fase. El diagnóstico de signos NWC original queda pendiente.

P2: drivers específicos por sector/empresa, ciclos, modelos dedicados de bancos/REITs, escenarios económicos,
sensibilidades aisladas y backtesting PIT sin calibración a precios actuales.

Coordinación frontend/UX: Claude puede conservar/rediseñar componentes visuales consumiendo
`getFundamentalValuations` + `valuationInput`; no introducir otro cálculo de FV ni omitir bloqueos.
Esta nota documenta el contrato de integración; no afirma que se haya realizado una comunicación externa.
GIIC no está declarado apto para invertir dinero real.

## Evidencia de ejecución con datos reales, sin escritura

Corrida: https://github.com/pshk-star/giic-invest/actions/runs/43474187631
Código financiero: `1e32a7a38c1c04e1a7d8f8c1065ecab5ee74e046`.
`escritura.intentada=false`, `insertadas=0`, `error=null`.
Precios de cierre usados: 2026-11-12; cálculo: 2026-11-13.

| Emisor | FV de la auditoría inicial (USD) | FV de esta corrida (USD) | Cambio | WACC nuevo | Estado |
|---|---:|---:|---:|---:|---|
| NVDA | 125,44 | 125,45 | +0,01 | 12,34% | en revisión |
| TSM | 338,38 | 308,82 | −29,56 | 8,75% | en revisión |
| META | 549,62 | 567,66 | +18,04 | 9,71% | en revisión |
| PFE | 49,84 | 51,28 | +1,44 | 6,53% | en revisión |
| ASML | 613,42 | 613,71 | +0,29 | 9,72% | en revisión |

Las bases TTM de ingresos/EBIT, los denominadores y los precios coinciden con los logs anteriores;
no se ajustó un parámetro para alcanzar un resultado. TSM cambia principalmente por unidades del
WACC; también queda corregida la selección monetaria del capital invertido (su ROIC sigue truncado).
META/PFE cambian por utilizar la tasa TTM observada en vez del suelo silencioso del 8% y por
sincronizar el escudo fiscal del Kd. Los cambios pequeños de NVDA/ASML provienen del WACC/escudo fiscal.
El resultado real TSM es **308,82**, no se fuerza a los **308,80** del cálculo aislado aproximado.

Los cinco siguen bloqueados por metodología y revisión: NVDA documenta fallbacks incompletos SEC;
TSM tiene 83,5% de peso terminal; META/ASML presentan divergencia FCFF/FCFE; PFE conserva margen
extremo y bandera de acciones/split. Las discrepancias originales oficiales de TSM/ASML siguen
pendientes de conciliación P1. No se presentan estos FV como validados económicamente.

`backend/tests/fixtures/p0_valuation_inputs.json` conserva los inputs utilizados de esta corrida.
`test_valuation_replay.py` reproduce los cinco FV al centavo y verifica con un ledger independiente
los flujos descontados, EV, deuda neta, equity, acciones, ADR y FX. Es una prueba de aritmética y
trazabilidad histórica, no un objetivo económico para futuras versiones del modelo.

Resultado local final: **481 backend aprobadas, 1 omitida; 322 frontend aprobadas; build correcto;
7 rutas Chromium sin fallos**. CI de código: https://github.com/pshk-star/giic-invest/actions/runs/43474195231
(el replay adicional se incorpora después de esa corrida y se ejecuta en el CI del commit final).
