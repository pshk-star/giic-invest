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
  *Aceptación*: salidas idénticas en la batería (diff 0) + 200 pruebas verdes.
- **E2 — Registro de conectores** con metadatos declarados y merge por calidad.
  *Aceptación*: añadir/retirar un conector no rompe la batería; procedencia trazable.
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
