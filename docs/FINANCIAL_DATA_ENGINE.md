# GIIC Financial Data Engine (FDE) — diagnóstico, arquitectura y plan

Objetivo: motor **universal, escalable y verificable** que, para CUALQUIER ticker, identifique,
recupere, normalice, valide y clasifique datos financieros desde fuentes oficiales gratuitas,
**sin parches por empresa**. Los instrumentos sin cobertura quedan identificados, no inventados.

Principio rector: GIIC debe saber **qué información tiene, qué tan fiable es y qué puede concluir
legítimamente**. Exactitud, trazabilidad, cobertura y mantenibilidad por encima de cantidad.

---

## 1. Diagnóstico de la arquitectura actual

Lo que YA existe y funciona (reutilizable, ver §3):
- Identificación de instrumento (país emisor vs cotización, ADR, moneda, tipo) — `services/identity.py`.
- Conector EDGAR con parser puro: detección de taxonomía/moneda, alineación de período,
  reconstrucción de utilidad neta, TTM por identidad rodante, consistencia, guard de
  plausibilidad, procedencia — `providers/edgar.py`.
- Capa de normalización incipiente: mapas de conceptos US-GAAP/IFRS → campos normalizados.
- Motor de calidad incipiente: `data_quality` (ok/sospechoso/bloqueado), clasificación 4 vías,
  `eps_source`, `ni_source_concept`, `consistency_independent`, `fallback_sources`.
- Multifuente: `CompositeProvider` (precios Yahoo/Stooq + EDGAR + FX Frankfurter) y gancho de
  fallback (`fallback_stats`).
- Routing por tipo de instrumento (equity/etf/commodity) y look-through de ETF (X-Ray).

Limitaciones (lo que motivó el giro):
- La normalización vive **dentro** del conector EDGAR (acoplada); no es una capa independiente
  reutilizable por otros conectores.
- No hay **registro de conectores** con cobertura/formato/limitación/estado declarados.
- El motor de calidad está disperso en el parser; no es una etapa explícita y auditable.
- No hay **medición de cobertura a escala** (sólo se validó con ~10 posiciones).
- Faltan conectores para datos que EDGAR companyfacts no expone (XBRL dimensional del 10-K,
  interinos IFRS, IR oficiales).

Conclusión: **no se requiere reescritura**. Se consolida lo existente en etapas explícitas
(identificación → conectores → normalización → cálculo → calidad) y se mide la cobertura real.

---

## 2. Arquitectura propuesta (modular, sin excepción por ticker)

```
ticker
  │
  ▼
[1] Identidad            services/identity.py (país, emisor, ADR, moneda, tipo, taxonomía esperada)
  │
  ▼
[2] Registro de conectores   connectors/*  (cada uno declara: cobertura, formato, frecuencia,
  │                                          limitaciones, procedencia, estado operativo)
  │   - edgar_companyfacts (US-GAAP/IFRS anual + interinos tagueados)   [existe]
  │   - edgar_companyconcept (concepto puntual, confirmación)           [existe parcial]
  │   - edgar_xbrl_instance (dimensional: clases accionarias, V)        [pendiente]
  │   - edgar_submissions (tipos de formulario, fechas)                 [existe]
  │   - ir_official / ifrs_regulatorio (ASML/TSM interinos)             [registrar límite]
  │   - fallback_stats (Yahoo u otros, SÓLO si fiable)                  [existe, Yahoo 401]
  ▼
[3] Normalización (capa independiente)   core/normalize.py
  │   conceptos canónicos ← mapas US-GAAP/IFRS/extensiones verificadas (semánticamente correctos)
  │   dimensiones XBRL, clases, períodos, unidades, consolidación
  ▼
[4] Cálculo    core/metrics.py  (EPS/FCF anual y TTM, crecimiento, márgenes, deuda neta, ratios)
  │   controles: YTD vs trimestre, Q4 = FY − 9M, ponderadas diluidas, splits/reexpresión,
  │   ADR, moneda reporte vs cotización, FX por fecha/concepto, signos, duplicados/reexpresados
  ▼
[5] Motor de calidad    core/quality.py  (clasifica CADA CAMPO, no sólo el ticker)
  │   plausibilidad, unidades/escala, consistencia entre estados, histórica, entre fuentes,
  │   actualidad, moneda/estructura accionaria, ausencia/insuficiencia
  │   estados: verificado | derivado | parcial | desactualizado | inconsistente/bloqueado
  │   conserva: dato original, fuente, documento, período fiscal, fecha publicación/extracción,
  │             transformación aplicada
  ▼
[6] Salida por instrumento   FinancialRecord  (campos + procedencia + calidad + qué modelos son
      seguros)  → Fundamental / Fair Value / Forecast / Advisor / Scanner
```

Reglas transversales:
- Ningún módulo consumidor usa un campo `bloqueado`/`parcial` como si fuera `verificado`.
- Un fallo de proveedor **no** sobrescribe datos fiables (merge por calidad, no por recencia ciega).
- Caché + actualización incremental + reintentos controlados + límites de consumo por fuente.
- Tipos de instrumento: acciones US (EDGAR), internacionales/ADR (IFRS+ADR+FX), ETF (holdings,
  NO DCF de empresa), commodities/trusts (vehículo+subyacente, sin EPS/ROE corporativos).

---

## 3. Componentes existentes que se reutilizan (no se reescriben)

| Etapa | Componente actual | Acción |
|---|---|---|
| Identidad | `services/identity.py` (resolve_identity) | Reutilizar; es el paso [1]. |
| Conector EDGAR | `providers/edgar.py` (parse_companyfacts + helpers) | Extraer normalización/calidad a capas; el parser puro ya es importable sin pandas. |
| Mapas de conceptos | `US_GAAP_MAP` / `IFRS_MAP` | Mover a `core/normalize.py` como diccionario canónico extensible. |
| TTM / período | `ttm_flow`, `_at`, `_concept_at`, `_duration_rows` | Reutilizar en `core/metrics.py`. |
| Calidad | `data_quality`, clasificación 4 vías, procedencia | Consolidar en `core/quality.py`. |
| Multifuente | `CompositeProvider`, `fallback_stats` | Base del registro de conectores. |
| Persistencia | Supabase `fundamentals` (payload jsonb) | Sin cambios de esquema; añadir campos al payload. |
| Orquestación | `scan_engine`, workflows GitHub Actions | Reutilizar; añadir batería de cobertura. |

---

## 4. Plan incremental (con criterios de aceptación y regresión)

Cada etapa es segura, compatible con Supabase/Cloudflare, sin tocar A/B/C (309) ni Fair Value/UI.

- **E0 — Batería de cobertura (medición real).** Harness reproducible sobre ~100 instrumentos
  representativos usando el motor ACTUAL. *Aceptación*: matriz de cobertura por campo y tipo,
  errores materiales detectados, falsos positivos de bloqueo. *Regresión*: V/MU/ASML/TSM como casos.
- **E1 — Extraer `core/normalize.py` y `core/quality.py`** desde `edgar.py` sin cambiar resultados.
  *Aceptación*: salidas idénticas en la batería (diff 0) + 200 pruebas verdes. **✅ HECHO (ver §8).**
- **E2 — Registro de conectores** con metadatos declarados y merge por calidad.
  *Aceptación*: añadir/retirar un conector no rompe la batería; procedencia trazable. **✅ IMPLEMENTADO en rama `fde-e2` (ver §9).**
- **E3 — Conector XBRL dimensional** (EPS/acciones de Visa y multiclase). *Aceptación*: Visa pasa de
  faltante→verificado con cifra que cuadra contra su 10-K; sin romper otros.
- **E4 — Interinos IFRS / IR** (TSM 2025, ASML si hay fuente estable) o registro de límite si no.
- **E5 — Ampliar batería a 100+ y jurisdicciones nuevas**; medir cobertura/exactitud/actualidad.

Criterio de éxito global: incorporar un ticker nuevo **no requiere código específico** (sólo, a lo
sumo, semillas verificables de identidad/ADR), y cada campo llega etiquetado con calidad y procedencia.

---

## 7. Brechas sin solución gratuita (registradas, no inventadas)

- **Visa**: EPS/acciones diluidas sólo en XBRL dimensional del 10-K (E3), no en companyfacts.
- **Micron FY2026**: error del dato de origen (10-K XBRL); correcto sólo desde IR de Micron.
- **ASML interinos/TTM**: 6-K sin XBRL en EDGAR; IR no estructurado estable → límite declarado.
- **TSM**: anual stale 2024 + algunos interinos 2025; TTM completo requiere IR no estructurado.

---

## 8. E1 — resultados y cambios intencionales (medidos, no sintéticos)

Qué cambió en el código (sin reescritura):
- `core/normalize.py`: mapas US-GAAP/IFRS + helpers de período/duración/TTM, **extraídos verbatim**
  de `edgar.py`. Parser puro, sin pandas ni red. Reutilizable por cualquier conector companyfacts.
- `core/quality.py`: al saneo por rangos existente se suman (a) `assess_plausibility` (guard de
  plausibilidad movido), (b) `is_non_operating`/`FUND_TRUST_SIC` (routing por SIC), (c)
  `classify_field` (estado por campo: verificado/derivado/parcial/bloqueado/no_aplica).
- `edgar.py`: **orquesta** normalize+quality; `parse_companyfacts` acepta `sic`/`sic_desc` y
  cortocircuita vehículos a un registro `no_aplica`. Sin SIC → comportamiento idéntico al anterior.
- `types.py`: campo `instrument_class` (empresa_operativa | etf_o_trust).

Regresión antes(main)/después(fde-e1) sobre la misma batería de 76 instrumentos (CI, solo lectura):
- **71 instrumentos idénticos** (diff-0 en data_quality, campos presentes, taxonomía, moneda,
  período, procedencia del EPS y consistencia). **0 regresiones inesperadas.**
- **Cobertura corporativa idéntica campo por campo** (eps_annual 93.7%, eps_ttm 65.1%, fcf_annual
  82.5%, fcf_ttm 60.3%, net_debt 69.8%, diluted_shares 95.2%, márgenes/roe sin cambio).

Señal de routing (jerarquía, verificación pre-merge): **`instrument_type` de la capa de identidad
(`services/identity.py`) es la señal PRIMARIA; el código SIC de la SEC es COMPLEMENTO**, no
clasificación universal. `classify_instrument` resuelve: (a) identidad vehículo → `etf_o_trust`
aunque el SIC calle; (b) identidad operativa + SIC de vehículo (contradicción) → `indeterminado`
sin habilitar métricas; (c) sin identidad → el SIC rescata, y sin ninguna señal → `indeterminado`
(no se asume operativa). El parser usa un centinela: si el caller no aporta señal, conserva el
comportamiento legado (operativa) para no romper fixtures.

Cambios INTENCIONALES (documentados por separado, E1 cond. 1):
1. **Routing de trusts de materias primas a `no_aplica`** — GLD, IAU, SLV, PPLT, PALL. Se rutean
   por **`instrument_type=commodity_etf`** (señal primaria de identidad), confirmado por **SIC 6221
   (Commodity Contracts Brokers & Dealers)** como complemento. Antes recibían métricas corporativas
   espurias (3 bloqueados, 1 sospechoso, 1 "ok"); ahora NO se les calcula EPS/ROE/márgenes/deuda (no
   tienen significado económico). Las equities con identidad aún `unknown` en la batería (sin ymeta
   de Yahoo) las clasifica el SIC operativo como complemento. Conteo de calidad:
   `{ok 60→59, sospechoso 4→3, bloqueado 4→1, +no_aplica 5}`; clase: `empresa_operativa 63, etf_o_trust 5`.
   El `no_aplica`/`indeterminado` afecta ÚNICAMENTE fundamentales corporativos: precios, históricos,
   forecast estadístico y métricas de riesgo salen de pipelines separados y quedan intactos
   (verificado: ningún consumidor de `data_quality` los condiciona).
2. **MU sigue `bloqueado`** (estado sin cambio) pero la razón se re-redactó para NO imputar la
   anomalía al emisor ni al 10-K (E1 cond. 5): de "…multiplicador distinto → probable error de
   origen; verificar 10-K original…" a "…multiplicador distinto; anomalía no resuelta — bloqueado
   hasta contrastar con documentos financieros oficiales". Queda fuera de cualquier valoración.

Financieras (bancos, V/MA como procesadores de pago, SIC 602x/7389): **sin cambios** — son empresas
operativas con EPS/ingresos con significado económico; se excluyen del routing a propósito.

Disponibilidad ≠ exactitud (E1 cond. 3): la batería demuestra COBERTURA y funcionamiento a escala;
`classify_field` marca "verificado" cuando el dato es directo y consistente de forma independiente,
lo que NO equivale a auditar su cifra exacta. La batería no valida independientemente todas las cifras.

Arquitectura sin parches por empresa (E1 cond. 6): incorporar un conector/instrumento nuevo usa la
señal de tipo (SIC) y los mapas canónicos; no requiere código específico por ticker. No se avanza a
E3 (XBRL dimensional de Visa) ni a Fair Value.

---

## 9. E2 — registro universal de conectores (diseño implementado, rama `fde-e2`)

Capa **aditiva**: no toca `emit_predictions` ni las 309 predicciones A/B/C, no avanza a Fair Value
ni UI, y mantiene USD 0. Vive en `core/connectors/` (puro; sin red ni pandas en spec/registry).

Componentes:
- **`ConnectorSpec`** (declarado por cada conector): `id`, `kind` (fundamentals/prices/fx/stats/
  holdings/identity), `provenance`, `quality` (official/regulatory/aggregator/fallback/sample),
  `priority`, `cost_tier` (free/trial/commercial), `Coverage` (tipos de instrumento, campos,
  jurisdicciones), `cache_ttl_s`, `rate_limit_per_s`, `frequency`, `limitations`, `status`
  (operational/degraded/down), `enabled`.
- **`ConnectorRegistry`**:
  - *selección* por `kind` + cobertura (tipo/campo/jurisdicción) + **tope de costo** (FREE por
    defecto; TRIAL/COMMERCIAL exigen subir el tope = autorización del operador) + estado (DOWN y
    deshabilitados se excluyen), ordenada por prioridad;
  - *resolución de CONFLICTOS por campo* con semántica distinta por veredicto terminal:
    · **`no_aplica`** — restricción SEMÁNTICA del tipo de instrumento (de una fuente con autoridad
      ≥ aggregator): bloquea el campo; ningún proveedor, ni con `verificado`, pobla un fundamental
      corporativo de un vehículo (un trust no recibe EPS).
    · **`bloqueado`** — invalida la observación de ESA fuente, NO el campo: otro proveedor
      independiente con un valor positivo lo resuelve; si nadie aporta, el campo queda `bloqueado`
      (MU: EDGAR bloqueado puede resolverse con una fuente oficial independiente; sin ella, sigue
      bloqueado).
    · **`indeterminado`** — incertidumbre pendiente: otra fuente la resuelve con un valor positivo;
      si nadie la resuelve, sigue `indeterminado` (NO se asume operativo).
    La elección entre valores positivos es **MULTICRITERIO** y lexicográfica: (1) calidad del dato
    (verificado>derivado>parcial>desactualizado), (2) autoridad de la fuente (official>regulatory>
    aggregator>fallback), (3) comparabilidad (moneda esperada, período fiscal, ajuste por splits),
    (4) actualidad, (5) **prioridad del conector sólo como último desempate** — nunca por prioridad
    o fecha de forma aislada;
  - *caché* por conector con el `cache_ttl_s` declarado;
  - *procedencia por dato*: `ProvenancedField` = valor + calidad + conector + procedencia + fecha +
    método.
- **Adaptadores** (envuelven proveedores existentes SIN cambiar su lógica; construcción perezosa →
  catálogo legible offline): `edgar_companyfacts` (oficial, prio 10), `prices_yahoo_stooq`
  (agregador), `frankfurter_fx` (regulatorio), `yahoo_stats` (fallback, declarado **DOWN** por el
  401 del endpoint público). `build_default_registry()` arma la arquitectura $0.

**Sin conectores por empresa** (no hay nada de Visa): el routing y la cobertura son por metadatos.
Incorporar cualquier proveedor futuro (API gratuita, trial o comercial) = adaptador fino que
implementa `fetch(tickers, fields, context) -> {ticker:{campo:ProvenancedField}}` + declarar su
spec + `register(...)`. No se modifica el registro ni la lógica consumidora; el tope de costo decide
si participa.

Evidencia: `jobs/connector_registry_report.py` + `.github/workflows/connectors.yml` imprimen el
catálogo declarado (legible offline) y, con `EDGAR_USER_AGENT`, una demo en vivo del merge sobre
AAPL (operativa), GLD (trust → `no_aplica`) y MU (bloqueado). 23 pruebas deterministas
(`tests/test_connector_registry.py`) fijan: cost gate que **impide la invocación** de conectores
trial/commercial sin autorización, cobertura, semántica de conflicto de los 3 veredictos
(`no_aplica` bloquea; `bloqueado`/`indeterminado` los resuelve una fuente independiente; sin ella
persisten), selección multicriterio (calidad/autoridad/comparabilidad/actualidad, prioridad como
último desempate), relleno de `faltante`, caché TTL y "añadir proveedor comercial = sólo registrar
+ subir el tope". Pendiente (no en E2): migrar `CompositeProvider`/scan para consumir el registro;
E3 (XBRL dimensional de Visa); Fair Value.

---

## 10. E3 — diagnóstico de cobertura, plan y estimación (PARA REVISIÓN; sin extractores aún)

Diagnóstico medido en CI (`jobs/e3_coverage_diag.py`, solo lectura) sobre las 63 empresas
operativas de la batería de 76 (ETF/trusts excluidos por routing; MU bloqueado).

### 10.1 Cobertura actual Fair Value (% "completo", EDGAR gratuito)
| Campo | Cobertura | | Campo | Cobertura |
|---|---|---|---|---|
| diluted_shares | 95.2% | | ocf | 63.5% |
| cash | 84.1% | | revenue | 60.3% |
| gross_debt | 84.1% | | fcf_ttm | 60.3% |
| fcf_annual | 82.5% | | capex | 58.7% |
| net_debt | 69.8% | | operating_income | 46.0% |
| net_income / eps | 65.1% | | | |

### 10.2 Causa raíz de los huecos (qué falta REALMENTE y qué es recuperable gratis)
1. **TTM "solo_anual" — el hueco MÁS grande.** La mayoría de huecos de eps/ni/revenue/op_income
   son "hay anual, falta TTM". Dos subgrupos:
   - **Extranjeros ADR/IFRS (13: ASML, TSM, SAP, TM, NVO, AZN, BABA, SONY, UL, RIO, SE, NVS, HSBC).**
     Presentan 20-F anual pero **no taguean interinos en XBRL de EDGAR** → el TTM por identidad
     rodante no se puede cerrar. **NO recuperable desde EDGAR gratis.**
   - **US con desalineación de interinos (AAPL, AMZN, COST, C).** Taguean 10-Q, pero la
     reconstrucción TTM actual no cierra la identidad (calendario fiscal / ventanas). **Recuperable
     gratis** mejorando el reconstructor TTM (Q4 = FY−9M, mejor emparejamiento de ventanas).
2. **EPS/acciones SÓLO dimensional (ausente en APIs agregadas).** Confirmado parseando el XBRL
   inline del 10-K: **Visa = 28/28 hechos de EPS diluido y de acciones diluidas son dimensionales
   (por clase A/B/C), 0 agregados** → por eso companyfacts no los tiene. GOOGL los da agregados + por
   clase (9/15 dim); MA sólo agregados. Candidatos adicionales con EPS ausente en agregado: XOM, BP,
   SHEL (confirmar si dimensional o variante de concepto). **Recuperable gratis** con extractor
   dimensional del instance (universal, sin lógica por ticker). Alcance: ~1 cierto (V) + hasta 3.
3. **operating_income el más bajo (46%) — en parte N/A real.** Los **bancos (JPM, BAC, WFC, C, GS,
   MS)** no reportan "OperatingIncomeLoss": es **N/A semántico**, no un hueco a rellenar. No-bancos
   (XOM, CVX, MRK, LLY, Fox/News) usan conceptos alternos → **recuperable gratis** extendiendo mapas.
4. **fcf_ttm (60%)** depende de OCF_TTM y CAPEX_TTM; sube con la mejora de reconstrucción TTM (#1 US).
5. **MU** sigue **bloqueado** (1 ticker) hasta contraste con documentos oficiales.

### 10.3 Plan de implementación E3 (priorizado por impacto/costo, sin excepción por ticker)
- **E3.1 — Reconstrucción TTM robusta desde interinos de EDGAR ya presentes** (gratis, universal).
  Q4 = FY−9M, mejor detección/emparejamiento de ventanas YTD. *Mayor palanca para filers US.*
- **E3.2 — Extractor XBRL dimensional reutilizable** registrado como conector E2 (calidad `official`,
  procedencia = instance del 10-K con accession). Recupera EPS/acciones por **clase** cuando el
  agregado no existe (Visa) y como enriquecimiento (GOOGL). Sin lógica por ticker: itera hechos
  `ix:nonFraction` y sus contextos dimensionales. Guarda **clase accionaria** y método.
- **E3.3 — Extensión de mapas de conceptos** (operating_income/revenue variantes). Marca
  `operating_income` como **no_aplica por campo** para bancos (restricción semántica, análoga a E1).
- **E3.4 — Interinos de extranjeros**: **límite declarado** (no recuperable gratis) + ranura de
  conector externo (API) **detrás del gate de costo** — sin tocar el núcleo (ya soportado por E2).
- **Trazabilidad** (E3 en todos): documento (accession/URL), fecha, período fiscal, moneda, unidad,
  **clase accionaria** y método de cálculo en `ProvenancedField`; no mezclar períodos/monedas/clases.
- **Regresión**: re-correr la batería de 76 antes/después; además de cobertura, **validar cifras**
  dimensionales contra el 10-K (p. ej. EPS por clase de Visa cuadra con el reporte). MU sigue bloqueado.

### 10.4 Estimación de mejora esperada (sólo trabajo GRATIS en EDGAR)
| Campo | Hoy | Esperado | Palanca | No recuperable gratis |
|---|---|---|---|---|
| eps "completo" | 65% | **73–78%** | E3.1 (AAPL/AMZN/COST/C) + E3.2 (V,+≤3) | 13 extranjeros (TTM) |
| diluted_shares | 95% | **97–100%** | E3.2 (V, XOM, BP) | — |
| operating_income (no-banco) | ~46% | **65–72%** | E3.3 mapas + E3.1 | bancos = N/A; extranjeros TTM |
| fcf_ttm | 60% | **70–75%** | E3.1 (OCF/CAPEX TTM US) | extranjeros |
| revenue/net_income TTM | 60–65% | **72–78%** | E3.1 | extranjeros |

La cobertura de **extranjeros ADR/IFRS** sólo sube con un conector externo (E3.4, de pago → gate de
costo con autorización), no con EDGAR. **No basta con subir cobertura**: cada recuperación dimensional
se validará contra el documento oficial antes de marcarse `verificado`.

---

## 11. E3.1 — reconstrucción TTM (resultados medidos)

**Causa verificada (no supuesta)** con sonda de solo lectura sobre muestra representativa: en AAPL,
AMZN, COST, C los interinos SÍ están en EDGAR (266–300 hechos), pero su período COMPLETO más reciente
es el anual (10-K; aún sin 10-Q posterior) → la identidad rodante devuelve `window="anual"` y el
parser lo descartaba por exigir ventana YTD. Es **disponible-no-recuperado por gating**, no ausencia
ni rechazo por calidad. Contraste: MSFT/NVDA/META sí tienen YTD fresco y ya funcionaban. (Hallazgo
lateral: NVDA CAPEX sale de un concepto viejo → E3.3.)

**Fix (universal, en `parse_companyfacts`):** cuando no hay TTM rodante pero el período completo más
reciente es el anual, `eps_ttm = EPS anual diluido REPORTADO` y `fcf_ttm = FCF anual` (idénticos por
definición), usando la cifra OFICIAL (no re-derivada), con `window="anual"` para trazabilidad. Sólo
rellena cuando antes era `None`; el camino YTD no se toca.

**Cobertura antes→después (63 operativas, batería de 76, medido en CI):**
| Campo | Antes | Después | | Campo | Antes | Después |
|---|---|---|---|---|---|---|
| eps_ttm | 65.1% | **93.7%** | | fcf_ttm | 60.3% | **85.7%** |

18 tickers ganan eps_ttm (incluidos extranjeros ASML/TSM/SAP/AZN/BABA/HSBC/NVO/NVS/RIO/SE/SONY/TM/UL,
cuyo último período completo es el 20-F anual), 16 ganan fcf_ttm. **0 regresiones**: ningún campo
perdido, ningún otro cambio de presencia; márgenes/ROE/net_debt/eps_annual idénticos; MU sigue
**bloqueado**; no_aplica 5.

**Validación de valor (independiente, vs endpoint oficial `companyconcept` de la SEC):** los cuatro
casos anual-como-TTM coinciden EXACTO con el EPS diluido oficial — AAPL 8.98, AMZN 7.17, COST 20.76,
C 6.99 (diferencia relativa 0.0). Los casos YTD (WMT, HD) difieren ~1% del último anual, como debe
ser (un TTM rodante a mitad de año ≠ EPS del ejercicio previo). Exactitud confirmada, sin estimación.
