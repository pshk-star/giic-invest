# Auditoría integral de GIIC — diagnóstico y propuesta (fase previa a Fair Value)

**Fecha:** 2026-11-09 · **Alcance:** diagnóstico y propuesta. **No** se modificó código, interfaz,
modelos ni las 309 predicciones. Nada en producción. Requiere aprobación antes de implementar.

**Base revisada:** código real de las 9 páginas (`frontend/src/pages`), 17 módulos de lógica
(`frontend/src/core`), capa de datos (`data.ts` → Supabase), proveedores y jobs del backend
(`app/providers`, `app/jobs`, `app/research`), tema visual (`tailwind.config.js`), y el estado tras
el merge de EODHD a `main` de hoy.

---

## 0. Resumen ejecutivo (claridad brutal)

GIIC es, en el fondo, **mucho más sólido de lo que su interfaz deja ver**. El motor es honesto,
determinístico y bien probado (267 pruebas backend, núcleo financiero con trazabilidad real). El
problema no es falta de rigor: es que **el 70% del valor ya calculado no llega a la pantalla**, y que
**toda la capa de decisión está deliberadamente bloqueada esperando Fair Value**.

Los cinco hechos que mandan sobre todo lo demás:

1. **CRÍTICO — El trabajo de EODHD (B 65→74, interinos ADR/IFRS) no alimenta ninguna pantalla.** El
   scan de producción (`run_scan --provider free`) usa `CompositeProvider(stooq, EDGAR, Frankfurter)`;
   los fundamentales que ve la UI son **EDGAR-only, anuales, sin TTM**. El conector `eodhd_fundamentals`
   que acabamos de fusionar vive solo en los jobs de evaluación. *Evidencia:* `run_scan.py:156`,
   `providers/__init__.py:34-45`, `build_default_registry` usado solo por eval/report.

2. **CRÍTICO — El Advisor no puede recomendar comprar/vender por valoración.** Por diseño actual, sin
   una valoración fundada solo emite REDUCIR (por concentración/riesgo) y MANTENER/REVISAR. Las
   "oportunidades" son explícitamente "preliminares, no decisiones". **Esto es exactamente lo que
   Fair Value desbloquea.** *Evidencia:* `Advisor.tsx:308-405`, `core/opportunities.ts`,
   `core/position-review.ts`.

3. **ALTO — El backend ya calcula los 6 campos del DCF; la UI no los muestra.** El dataclass
   `Fundamentals` tiene `fcf_ttm`, `fcf_annual`, `net_debt`, `diluted_shares`, `operating_margin`,
   `eps_ttm`, etc.; el `FundamentalsPayload` del frontend lee solo ~11 campos. Los TTM/interinos
   vienen `null` desde EDGAR (el interino no está fiable en XBRL) — que es justo lo que EODHD resuelve.
   *Evidencia:* `core/types.py:55-85` vs `core/valuation.ts` / `Ficha.tsx:19-22`.

4. **MEDIO — ASML/TSM sin A/B/C es correcto, no es un bug.** El universo del modelo es
   `get_universe(include_etfs=False)` = 91 acciones US líquidas; los ADR/IFRS quedan fuera **por
   diseño**. La Ficha ya lo explica al usuario. La proyección estadística individual (bootstrap) **sí**
   está disponible para ASML/TSM y ya está diferenciada de los modelos A/B. *Evidencia:*
   `universe.py:19-99`, `model_spec.py`, `Ficha.tsx:45-79, 338-348`.

5. **MEDIO — El sistema visual tiene dos defectos que degradan toda la jerarquía.** `term-faint` (el
   color del tercer nivel de texto, usado en centenares de lugares) **no está definido** en el tema →
   las clases no generan CSS. Y `warn` === `accent` (ambos `#e0a93c`) → advertencias y acento
   indistinguibles. *Evidencia:* `tailwind.config.js` (no hay `faint`; `warn` y `accent` idénticos).

**Dónde estamos vs. las 7 preguntas objetivo de GIIC:**

| Pregunta del inversionista | Estado hoy |
|---|---|
| 1. ¿Cómo evoluciona mi patrimonio? | **Resuelta** (Cartera + Dashboard; falta serie temporal de patrimonio) |
| 2. ¿Qué riesgos/concentraciones tengo? | **Parcial** (calculado en Proyección/Advisor; no en Dashboard ni Cartera) |
| 3. ¿Cuánto vale cada empresa? | **No resuelta** (solo múltiplos relativos; falta Fair Value/DCF) |
| 4. ¿Infra/sobrevalorada? | **No resuelta** (depende de Fair Value) |
| 5. ¿Comprar/mantener/reducir? | **Bloqueada** (Advisor hobbled sin valoración fundada) |
| 6. ¿Dónde van mis próximos USD 3.000? | **Bloqueada** (misma causa) |
| 7. ¿Qué incertidumbre tienen? | **Resuelta parcialmente** (bandas y escenarios existen y son honestos) |

Conclusión: **Fair Value es la pieza que desbloquea 3, 4, 5 y 6 simultáneamente.** Antes conviene
cablear EODHD a la UI y corregir dos defectos visuales; después, Fair Value; después, reorganizar
Dashboard y Oportunidades. El orden importa porque Fair Value sin EODHD nace cojo para los ADR/IFRS.

---

## 1. Diagnóstico de las siete pantallas

### 1.1 Dashboard (`CommandCenter.tsx`, 136 líneas)

**Qué hace:** patrimonio invertido (valor de mercado, costo remanente, P&L no realizado %,
realizado+dividendos), mejores/peores 3 posiciones, top-6 del scanner, panel de "calidad de la
información" (fecha, evaluados, fuente real/ejemplo, estado).

**Qué aporta valor:** foto de un vistazo; misma fuente de precios que Cartera (coherencia). Honesto
sobre datos de ejemplo.

**Qué falta (vs. "resumen ejecutivo de patrimonio, rendimiento, riesgos y decisiones prioritarias"):**
- **No muestra riesgo ni concentración** aunque GIIC los calcula (volatilidad anual, HHI, N efectivo,
  prob. de pérdida 12m) en `core/forecast`. Dato calculado, no mostrado.
- **No muestra decisiones prioritarias** (el Advisor ya las produce; el Dashboard no las trae).
- **No hay serie temporal de patrimonio** (la pregunta #1 "cómo evoluciona" se responde con un número,
  no con una curva). No existe tabla de snapshots de patrimonio.
- Sin P&L del día (sí está en Cartera).

**Depende de Fair Value:** parcialmente (las "decisiones prioritarias" ganan con valoración; el resto
—riesgo, concentración, evolución— es independiente y puede hacerse ya).

### 1.2 Mi Cartera (`Portfolio.tsx`, 405 líneas)

**Qué hace:** resumen (MV, P&L día, no realizado, realizado+div), **TIR/XIRR money-weighted** (USD;
"pendiente" si hay multimoneda), **X-Ray look-through de ETF**, alta de operaciones con autocompletado,
tabla de posiciones (frescura de cotización por semáforo, ajustes por split, peso), historial.

**Qué aporta valor:** es la pantalla más completa y correcta. XIRR real, splits automáticos sin tocar
el costo, X-Ray de exposición subyacente. Avisos cuando mezcla precios de fechas distintas.

**Qué falta (vs. "exposición real, diversificación, concentración, contribución al riesgo"):**
- **Sin desglose por sector ni diversificación** en esta pantalla (el X-Ray da empresas subyacentes,
  pero no hay vista de exposición sectorial ni de concentración directa aquí).
- **Sin contribución al riesgo** (existe en Proyección; no se reutiliza aquí).
- **Multimoneda:** XIRR y valor total asumen USD; con posiciones en otra divisa, XIRR queda "pendiente".
- Fintual oculto (código conservado) — deuda funcional para quien tenga fondos.

**Depende de Fair Value:** no. Todo lo anterior es independiente.

### 1.3 Proyección (`Forecast.tsx`, 385 líneas + `core/forecast.ts`, 217)

**Qué hace:** **dos motores explícitamente separados** —
- **A · Riesgo histórico:** bootstrap por bloques multivariante con correlaciones; bandas p5/p50/p95,
  VaR, probabilidad de pérdida, sensibilidad a ventana/deriva; **contribución al riesgo por instrumento**
  (HHI, N efectivo, top-5); **simulador "¿qué pasa si…?"** (reducir/aumentar/vender/comprar/aportar).
- **B · Valoración fundamental:** vista `FundamentalView` por empresa bajo escenarios.

Con panel de **cobertura ponderada por patrimonio** (con precio / con simulación / con fundamental /
sin cobertura), banner de **exclusión por ajuste mixto** (series que mezclan precios ajustados y sin
ajustar se excluyen, no se usan en silencio) y banner de **proyección parcial**.

**Qué aporta valor:** es lo mejor de GIIC. Riguroso, honesto, con limitaciones declaradas. "Neutral
sin deriva" para no extrapolar el alcismo reciente. No promete probabilidades calibradas.

**Qué falta / riesgo de confusión:**
- **Colisión de nomenclatura:** aquí "A/B" = riesgo vs fundamental; en Laboratorio "A/B(/C)" = modelos
  ridge. **Son cosas distintas con el mismo nombre.** Alto riesgo de confusión para el usuario.
- La "valoración fundamental" (motor B) hoy se apoya en `valuateCompany` (múltiplos relativos), no en
  DCF — mejora sustancialmente con Fair Value.

**Depende de Fair Value:** el motor B mejora con Fair Value; el motor A es independiente y ya es fuerte.

### 1.4 Investment Advisor (`Advisor.tsx`, 630 + `core/advisor.ts` 669 + `position-review.ts` 188)

**Qué hace:** motor **determinístico** sobre datos reales. Revisión por posición (con exposición
efectiva vía X-Ray, riesgo por covarianzas, calidad de evidencia), decisiones de higiene priorizadas,
"señales de oportunidad" (candidatas fuera de cartera), cumplimiento de límites, alternativas, timing,
diagnóstico de cartera, y datos usados con procedencia.

**Qué aporta valor:** transparencia total, cada decisión explicable y reversible, sin pronosticar
retornos. Honestidad ejemplar: distingue "señal" de "decisión".

**El problema central:** **toda la capa de compra/venta por valoración está deliberadamente
bloqueada.** Sin valoración fundada, solo emite:
- REDUCIR (por concentración/riesgo — reversible),
- MANTENER / REVISAR,
- y en oportunidades, EN OBSERVACIÓN / INVESTIGAR — **nunca COMPRAR**.

Es la pantalla que **más gana con Fair Value** y la que hoy se siente más incompleta para el usuario,
precisamente porque es honesta sobre lo que no puede afirmar.

**Depende de Fair Value:** **CRÍTICAMENTE.** Es la razón de ser del próximo desarrollo.

### 1.5 Research + Ficha (`Research.tsx` 99 + `Ficha.tsx` 555)

**Qué hace:** buscador → **Ficha de empresa** (la pantalla más rica). La Ficha tiene:
identificación del instrumento (persistida + derivada, sin inventar), precio histórico vs SPY/QQQ,
**proyección estadística individual** (bootstrap, cualquier acción con ≥61 sesiones, etiquetada "B ·
simulación histórica"), **proyecciones del modelo A/B experimental** (con explicación concreta de por
qué un ticker no tiene cobertura), **fundamentales EDGAR** (P/E anual —no TTM—, FCF yield, ROE, margen,
crecimientos, D/E, market cap con procedencia), **valoración relativa** (mediana de pares del sector,
Fair Value por P/E y por FCF yield, Gordon inverso), factores del scanner explicados, riesgos
determinísticos, y bloque de datos/procedencia.

**Qué aporta valor:** densa, honesta, con procedencia por métrica. Ya diferencia simulación individual
de modelos experimentales. Ya explica las ausencias de A/B/C.

**Qué falta (vs. "análisis fundamental profundo, evolución financiera, Fair Value, escenarios, riesgos,
competidores, calidad del negocio"):**
- **Sin evolución financiera multi-año** (solo el último ejercicio anual; no hay serie de ingresos/
  márgenes/FCF por año, aunque EDGAR los tiene).
- **Sin Fair Value (DCF).** Hoy solo múltiplos relativos.
- **Sin competidores explícitos** (usa "pares del sector" del scanner, no un set de comparables curado).
- **Sin calidad del negocio estructurada** (ROIC vs WACC, tendencia de márgenes, durabilidad).
- **No aprovecha EODHD** (interino/TTM, que es lo que haría el P/E un TTM real y no anual).

**Depende de Fair Value:** sí, para la pieza central; el resto (evolución, competidores) es independiente.

### 1.6 Oportunidades (`Opportunities.tsx`, 98)

**Qué hace:** **solo** la tabla de ranking del scanner (compuesto multifactor: value/quality/growth/
momentum + etiquetas).

**El problema:** el **motor de oportunidades por valoración** (`buildOpportunities`, que decide COMPRAR/
ESPERAR/INVESTIGAR por valoración, no por score) **vive en el Advisor, no aquí.** La pantalla
"Oportunidades" es un volcado del score; no distingue calidad / valoración / crecimiento / riesgo /
momentum como pide el objetivo, ni compara candidatas.

**Redundancia/arquitectura:** hay **dos sitios** hablando de oportunidades (Advisor y esta pantalla) con
lógicas distintas. Confuso: ¿cuál responde "qué comprar"?

**Depende de Fair Value:** sí (la decisión de compra por valoración es lo que falta).

### 1.7 Laboratorio (`Lab.tsx`, 165)

**Qué hace:** ventana **solo-lectura** a las 309 predicciones (modelos, versiones, horizontes, madurez,
sección transversal top-10 por percentil, conteo de outcomes). Banner EXPERIMENTAL·NO VALIDADO.

**Qué aporta valor:** separa limpiamente la investigación de la recomendación. Registro inmutable.

**Qué falta (calculado pero no mostrado):**
- **Sin scorecard de skill.** `prediction_outcomes` **ya almacena** `realized_return`,
  `benchmark_return`, `outperformed` (`eval_predictions.py:72-73`), pero el Lab solo muestra el
  **conteo** de outcomes. No hay tasa de acierto, % de outperformance, ni coeficiente de información.
  Es el mayor "dato calculado y no mostrado" del sistema.
- No distingue visualmente los dos modelos (A price-only, B price+fundamental) en términos de
  desempeño relativo.

**Depende de Fair Value:** no.

---

## 2. Matriz MANTENER / MEJORAR / AGREGAR / ELIMINAR

| Elemento | Acción | Justificación (evidencia) |
|---|---|---|
| Motor de Proyección (bootstrap, contribución al riesgo, simulador) | **MANTENER** | Es el núcleo honesto y correcto; `core/forecast.ts` |
| XIRR money-weighted + splits automáticos + X-Ray | **MANTENER** | Correcto y diferenciador; `core/returns.ts`, `core/xray.ts` |
| Advisor determinístico (reglas transparentes, procedencia) | **MANTENER** | Arquitectura de decisión correcta; solo le falta el insumo (Fair Value) |
| Explicación de ausencia de A/B/C en Ficha | **MANTENER** | Honestidad ejemplar; `Ficha.tsx:338-348` |
| Fundamentales de la UI (EDGAR-only, ~11 campos) | **MEJORAR** | Cablear EODHD + exponer fcf_ttm/net_debt/diluted/márgenes ya calculados |
| Dashboard | **MEJORAR** | Añadir riesgo, concentración, decisiones prioritarias y evolución de patrimonio |
| Ficha (Research) | **MEJORAR** | Añadir evolución multi-año, Fair Value, competidores, calidad del negocio |
| Laboratorio | **MEJORAR** | Exponer scorecard de skill desde `prediction_outcomes` |
| Nomenclatura "A/B" en Proyección vs "A/B/C" en Lab | **MEJORAR** | Renombrar para eliminar la colisión (p. ej. "Riesgo/Valoración" vs "Modelos ML") |
| `term-faint` (indefinido) y `warn`===`accent` | **MEJORAR** | Defecto de tema que rompe la jerarquía; `tailwind.config.js` |
| Serie temporal de patrimonio | **AGREGAR** | Responde la pregunta #1 ("cómo evoluciona"); hoy solo hay un número |
| Exposición sectorial + concentración en Cartera | **AGREGAR** | Pide el objetivo; los datos existen, falta la vista |
| Fair Value (DCF) como servicio | **AGREGAR** | Desbloquea preguntas 3,4,5,6; siguiente desarrollo |
| Capa de "decisión de compra por valoración" | **AGREGAR** | Depende de Fair Value; ya hay andamiaje en Advisor |
| Pantalla Oportunidades (score crudo duplicado) | **MOVER/UNIFICAR** | Fusionar con el motor de valoración del Advisor; una sola fuente de "qué comprar" |
| ADR_SEED hardcodeado en frontend (`Ficha.tsx:28`) y backend | **ELIMINAR** (reemplazar) | Debe venir de identidad persistida, no de listas en la UI |
| Fintual oculto | **DECIDIR** | Reactivar o eliminar; hoy es deuda muerta |

**Nada se elimina todavía** (restricción respetada). "ELIMINAR" arriba = marcar para reemplazo/retiro
previa aprobación.

---

## 3. Auditoría visual y propuesta de sistema de diseño

**Estado actual:** tema oscuro "terminal" ya establecido — `bg #0b0f16`, `panel #121824`,
`panel2 #1a2230`, `border #263142`, `fg #e6eaf0`, `muted #8b95a5`, `accent #e0a93c` (ámbar),
`good #35c07a`, `crit #e5604d`. Fuentes: IBM Plex Mono (cifras/tickers), IBM Plex Sans (texto),
Saira Semi Condensed (títulos). Números con `tabular-nums`. Gráficos SVG hechos a mano
(`PriceChart`, `ForecastChart`).

**Buena base** (dark financiero, monospace para cifras, sin decoración). Problemas concretos:

| Severidad | Hallazgo | Evidencia | Efecto |
|---|---|---|---|
| **Medio** | `term-faint` no está definido en el tema | no aparece en `tailwind.config.js` | Centenares de textos de 3er nivel no reciben color → jerarquía colapsa |
| **Medio** | `warn` === `accent` (ambos `#e0a93c`) | `tailwind.config.js` | Advertencias y acento indistinguibles; se pierde señal de alerta |
| **Medio** | Paleta de **un solo acento** | ídem | Pobre para diferenciar factores/series en gráficos (value/quality/growth/momentum comparten color) |
| **Bajo** | Gráficos SVG sin interactividad | `PriceChart.tsx`, `ForecastChart` | Sin hover/tooltip/zoom; dificulta leer valores exactos |
| **Bajo** | `money()` siempre símbolo USD y locale es-MX | `format.ts` | Riesgo de ambigüedad con instrumentos en otra divisa |
| **Bajo** | Sin estados de carga unificados | varía por página (algunas `animate-pulse`, otras texto) | Inconsistencia de "cargando/sin datos/error" |

**Propuesta de sistema (conceptual, inspirado en Koyfin sin copiarlo):**

1. **Tokens completos y semánticos.** Definir `faint` y separar `warn` de `accent`. Escala de texto de
   4 niveles (fg / muted / faint / ghost) con contraste verificado (AA en dark). Semántica de color
   **consistente y con significado financiero**: verde = ganancia/positivo, rojo = pérdida/negativo,
   ámbar = atención, azul/teal = informativo/seleccionado, gris = neutral/sin dato.
2. **Paleta de datos** separada de la paleta semántica: 5–6 colores categóricos (uno por factor) con
   buen contraste en dark, para gráficos y badges — nunca usar el color semántico para series.
3. **Jerarquía tipográfica** de 4 niveles con tamaños/pesos definidos; cifras siempre `tabular-nums`;
   tickers siempre monospace. Títulos Saira solo en encabezados de panel.
4. **Densidad financiera "premium":** tablas compactas con cabecera fija, filas con hover, alineación
   decimal, separadores sutiles; tarjetas de métrica con etiqueta·valor·contexto (como ya hace
   `Metric`), estandarizadas.
5. **Gráficos útiles e interactivos** donde aporten: tooltip con valor exacto y fecha, línea de
   referencia (hoy/0%), bandas con leyenda; mantener SVG propio (cero dependencias) pero añadir capa
   de interacción. Nunca gráfico decorativo.
6. **Componentes reutilizables:** un único `StatTile`, `DataTable`, `Badge`, `ProvenanceStamp`,
   `EmptyState`, `LoadingState`, `ErrorState` — hoy cada página los reimplementa.
7. **Procedencia visible pero no ruidosa:** un sello compacto (fuente · período · fecha · estado de
   calidad) reutilizable, con color por nivel de calidad (verificado/parcial/desactualizado/bloqueado),
   alineado al trabajo de E3.4.

**Principio rector (del usuario):** cada mejora visual debe facilitar la **interpretación**, no decorar.
Prioridad: (a) arreglar `faint`/`warn` —rompe la jerarquía hoy—, (b) tokens de datos, (c) componentes
reutilizables, (d) interactividad de gráficos.

---

## 4. Auditoría de fuentes y coherencia financiera

**Las tres rutas de fundamentales (y por qué importa):**

1. **Producción (lo que ve la UI):** `run_scan --provider free` → `CompositeProvider(stooq, EDGARProvider,
   Frankfurter)` → `get_fundamentals` **solo EDGAR** → tabla `fundamentals.payload`. Anual, sin TTM.
   *Evidencia:* `run_scan.py:156-157`, `providers/__init__.py:34-45`, `scan_engine.py:77,149`.
2. **`EODHDProvider`** (proveedor simple, lee `Highlights`): existe (`providers/eodhd.py`) pero **no se
   usa** en `free`.
3. **`EodhdFundamentalsConnector`** (E3.4, el bueno: interino + anual, conciliación contra EDGAR,
   niveles de calidad, cuarentena): **solo** en `eodhd_ab_eval` y `connector_registry_report`. **No
   toca la UI.** *Evidencia:* usos de `build_default_registry`.

**Consecuencia:** el gran avance de E3.4 (B 65→74, interinos ADR/IFRS frescos) **es invisible en
producto.** Para surfacearlo hace falta cablear el registry a `run_scan` (o un job de fundamentales
dedicado) y extender el payload + la UI.

**Lo que SÍ mejoró en producción hoy (merge EODHD):** el fix de identificación ticker→CIK
(`EDGARProvider._facts`) llega a `run_scan`: el próximo scan resolverá **XOM a Exxon 34088** con datos
reales (antes vacío). Ganancia concreta sin tocar la UI.

**Coherencia de datos — hallazgos:**
- **Período/actualidad:** el P/E de la Ficha es sobre **EPS anual, no TTM** — y así lo dice la UI
  (honesto). Pero el dataclass ya tiene `eps_ttm`/`fcf_ttm`; vienen `null` desde EDGAR por el interino
  no fiable en XBRL. EODHD los llenaría. *Evidencia:* `types.py:71-78`, `Ficha.tsx:409,420`.
- **Moneda reporte vs cotización + ADR:** bien tratado en Ficha (márgenes adimensionales; P/E y market
  cap en USD; ratio ADR). Pero **`ADR_SEED` está hardcodeado en el frontend** (`Ficha.tsx:28`) y en
  `coverage_battery` — debería venir de la identidad persistida (tabla `instruments`), ya existe la
  columna `adr_ratio`.
- **Cuarentena:** 16 discrepancias EODHD `inconsistente` quedan registradas y **no se usan** (correcto).
  Pero como EODHD no llega a la UI, el usuario aún no ve ni el dato bueno ni la marca de cuarentena.
- **Snapshots entre pantallas:** Dashboard y Cartera comparten `mergeValuation` (coherente). Advisor y
  Proyección comparten el motor de riesgo. Bien. Ficha usa el último anual; Proyección usa precios
  ajustados — convive bien porque están etiquetados.
- **No confundir disponible con apto para valoración:** la matriz DCF de E3.4 ya lo formaliza
  (vigente/verificado · parcial · desactualizado · bloqueado). **Falta llevar esos estados a la UI.**

---

## 5. Diagnóstico de las proyecciones A/B/C y de ASML/TSM

**Qué son realmente los modelos** (`model_spec.py`):
- **MODEL_A "price-ridge" (a-1.0.0):** regresión ridge solo con precio; horizontes 20/60/252 sesiones.
  Benchmark experimental.
- **MODEL_B "price-fund-ridge" (b-1.0.0):** ridge con precio + fundamentales; horizonte 252. Candidato
  experimental, sin superioridad probada.
- **No existe un "MODEL_C"** en el código (`MODELS = [MODEL_A, MODEL_B]`). "A/B/C" es nomenclatura del
  usuario; el sistema tiene **dos** modelos. La Ficha ya dice "modelos A/B experimentales".
- Salida = **retorno relativo** al universo equiponderado + percentil (sección transversal), **no**
  retorno absoluto → por eso **no se deriva precio objetivo** (correcto).

**Por qué algunos instrumentos tienen cobertura y otros (ASML) no:**
- Universo de emisión = `get_universe(include_etfs=False)` = **91 acciones US líquidas**
  (`universe.py`). La emisión itera ese universo (`emit_predictions.py:207`).
- **ASML, TSM, SAP, BABA, NVO, AZN, SONY, etc. no están en ese universo → sin A/B/C por DISEÑO.** Es una
  **exclusión metodológica legítima**, no un error de extracción, identificación ni integración. La
  Ficha lo explica explícitamente (`Ficha.tsx:343-347`).
- **EODHD no cambia esto.** Que ahora tengamos fundamentales de ASML no habilita A/B/C para ASML: el
  modelo se entrenó sobre el universo US; incorporar ADR exigiría **reentrenamiento y validación fuera
  de muestra** — que el usuario **explícitamente no quiere** sin controles estadísticos. Correcto
  mantenerlo fuera.

**Clasificación de las ausencias (lo que pide el punto 4):**

| Causa | Instrumentos | ¿Acción? |
|---|---|---|
| Exclusión metodológica (universo US) | ADR/IFRS: ASML, TSM, SAP, TM, SHEL, BP, NVO, AZN, BABA, SONY, UL, RIO, SE, NVS, HSBC | **Ninguna** sin reentrenar/validar |
| Exclusión por clase (ETF/commodity no aplican) | SPY, QQQ, GLD, SLV, … | **Ninguna** (no aplica) |
| Cobertura real EDGAR limitada | TM (hasta 2020), SONY (hasta 2021) | Mitigado por EODHD (fundamentales), **no** por A/B/C |
| Error de identificación (corregido hoy) | XOM | **Resuelto** (CIK 34088) |

**Simulación individual vs modelos A/B/C — ya diferenciados:** la Ficha ofrece **proyección estadística
individual** (bootstrap, para cualquier acción con ≥61 sesiones, incluidas ASML/TSM), claramente
etiquetada y separada del bloque "modelos A/B experimental" (`Ficha.tsx:45-79` vs `338-396`). Esto ya
cumple el requisito de no confundir ambas cosas. **Recomendación:** reforzar la distinción con la
nomenclatura (ver §1.3) para que "A/B" no choque entre Proyección y Laboratorio.

**Predicciones calculadas no mostradas:** el **skill** (realized/benchmark/outperformed en
`prediction_outcomes`) está calculado y **no** se muestra como scorecard (solo conteo). Oportunidad de
alto valor y bajo esfuerzo para el Laboratorio.

**Preservación de las 309:** ninguna propuesta las toca. Cualquier extensión de cobertura (p. ej.
emitir sobre ADR) sería **emisión nueva y validada**, no edición de las existentes.

---

## 6. Matriz transversal de cobertura (76 instrumentos)

Universo GIIC = `coverage_battery.UNIVERSE` (76): us_large 20 · us_mid_small 8 · multi_class 5 ·
recent_splits 5 · financials 8 · adr_ifrs 15 · etf 8 · commodity_trust 5 · regression 2.

**Matriz por capacidad (resumen por grupo; el detalle por ticker se adjunta como anexo generable):**

| Grupo (n) | Precio/hist | Fund. EDGAR | Fund. EODHD (nuevo) | Simulación individual | Modelos A/B | Riesgo/cartera | A/B/C elegible | Fair Value elegible |
|---|---|---|---|---|---|---|---|---|
| us_large (20) | ✔ | ✔ | ✔ (no en UI) | ✔ | ✔ (si en universo) | ✔ | Sí | **Listo** (mayoría 6/6) |
| us_mid_small (8) | ✔ | ✔ | ✔ (no en UI) | ✔ | parcial | ✔ | Sí | Mixto |
| multi_class (5) | ✔ | ✔ | ✔ (no en UI) | ✔ | parcial | ✔ | Sí | Mixto (cuidar clase de acción) |
| recent_splits (5) | ✔ | ✔ | ✔ (no en UI) | ✔ (ajuste verificado) | parcial | ✔ | Sí | Listo/Mixto |
| financials (8) | ✔ | ✔ | parcial (revenue inconsistente→cuarentena) | ✔ | parcial | ✔ | Sí | **DCF estándar NO aplica** (bancos) |
| adr_ifrs (15) | ✔ | parcial/desactualizado | ✔ interino fresco (no en UI) | ✔ | **No (diseño)** | ✔ | **No** | Parcial (EDGAR anual + EODHD interino) |
| etf (8) | ✔ | n/a | n/a | ✔ | n/a | ✔ (+X-Ray) | No (no aplica) | **No aplica** (usar look-through) |
| commodity_trust (5) | ✔ | n/a | n/a | ✔ | n/a | ✔ | No (no aplica) | **No aplica** |
| regression (2: MU, LLY) | ✔ | ✔ (LLY) / bloqueado (MU) | ✔ | ✔ | parcial | ✔ | Sí | LLY mixto; MU **bloqueado** |

**Hallazgos de la matriz (lo que pide el punto 5):**
- **Datos suficientes sin cobertura visible:** los 15 ADR/IFRS tienen fundamentales EODHD frescos **que
  la UI no muestra**. Es el hueco injustificado más grande — pero su causa es de **integración
  (cableado), no de datos**.
- **Funcionalidad implementada y no usada:** `buildOpportunities` (valoración) existe y solo corre en
  Advisor; la pantalla Oportunidades no lo usa. `prediction_outcomes` (skill) calculado y no mostrado.
  Campos TTM/FCF/net_debt/diluted del dataclass, calculados y no mostrados.
- **Diferencias injustificadas entre módulos:** "oportunidades" significa cosas distintas en Advisor y
  en Oportunidades. Riesgo/concentración se muestra en Proyección/Advisor pero no en Dashboard/Cartera.
- **Errores de ticker/CIK/ADR:** XOM (CIK) corregido hoy. `ADR_SEED` hardcodeado (deuda, no error
  activo). TM/SONY = cobertura real limitada (no error).
- **Estados vacíos sin explicación:** en general **bien** manejados (la Ficha explica ausencias). El
  Dashboard y Oportunidades sí tienen estados vacíos genéricos ("sin snapshot") sin guía de acción.
- **Exclusiones legítimas:** ETF/commodity sin fundamentales ni DCF; ADR fuera de A/B/C; bancos fuera
  de DCF industrial. Todas correctas y deben quedar **documentadas en la UI**, no forzadas.

**No todos los instrumentos deben tener todo** (principio respetado): cada "No/No aplica" arriba tiene
causa metodológica explícita.

---

## 7. Arquitectura funcional objetivo (qué pregunta responde cada pantalla)

Para eliminar duplicaciones, cada pantalla responde **una** pregunta:

- **Dashboard — "¿Cómo estoy y qué es lo urgente?"** Patrimonio + **evolución** (curva), rendimiento,
  **riesgo y concentración** (traídos de Proyección), y **3–5 decisiones prioritarias** (traídas del
  Advisor). Es el resumen ejecutivo, no una pantalla de captura.
- **Mi Cartera — "¿Qué tengo exactamente?"** Posiciones, rentabilidad (XIRR), **exposición real
  (directa + X-Ray), diversificación sectorial, concentración y contribución al riesgo**. Operación y
  registro. (Traer aquí la vista de riesgo/sector que hoy solo está en Proyección.)
- **Proyección — "¿Qué podría pasar y cuánto riesgo corro?"** Dos motores separados y **renombrados**
  (Riesgo histórico / Valoración) para no chocar con los modelos ML. Sensibilidad y simulador.
- **Investment Advisor — "¿Qué hago: mantener/comprar/reducir y dónde pongo mis próximos aportes?"**
  Desbloqueado por Fair Value. Evalúa posiciones por **valoración + riesgo + concentración +
  incertidumbre**. Única fuente de decisiones de compra.
- **Research/Ficha — "¿Cuánto vale y qué tan buena es esta empresa?"** Análisis profundo: **evolución
  financiera multi-año, Fair Value (DCF), escenarios, riesgos, competidores, calidad del negocio**.
- **Oportunidades — "¿Qué empresas atractivas hay y cómo se comparan?"** **Fusionar** aquí el motor de
  valoración (hoy en Advisor): comparar candidatas por calidad/valoración/crecimiento/riesgo/momentum.
  Advisor decide sobre **tu cartera**; Oportunidades explora **fuera** de ella.
- **Laboratorio — "¿Funcionan mis modelos?"** Predicciones + **scorecard de skill** (outperformance,
  acierto), backtesting, validación. Investigación, nunca recomendación.

**Regla anti-duplicación:** "qué comprar" se decide en **un** lugar (motor de valoración, compartido
entre Advisor —cartera— y Oportunidades —exploración—). "Riesgo" se calcula **una** vez
(`core/forecast`) y se **muestra** en Dashboard, Cartera, Proyección y Advisor.

---

## 8. Preparación para Fair Value

**Insumo (matriz DCF de E3.4):** 30 listas (6/6 verificado), 15 mixtas, 17 parciales/desactualizadas,
1 bloqueada (MU). Los 6 campos (FCF TTM, OCF, CAPEX, deuda, caja, acciones diluidas) **ya se modelan**
en el dataclass `Fundamentals`; faltan poblar los interinos/TTM (EODHD) y **exponerlos**.

**Cómo integrar Fair Value (propuesta conceptual, sin implementar):**
- **Research/Ficha:** hogar natural del DCF por empresa, con escenarios (bull/base/bear) y el **estado
  de calidad por campo** (verificado/parcial/desactualizado/bloqueado) visible. Nunca presentar una
  estimación no validada como precio objetivo confiable.
- **Oportunidades:** ordenar/comparar por margen de seguridad (precio vs Fair Value) **solo** para
  instrumentos elegibles (estado suficiente).
- **Investment Advisor:** Fair Value es el insumo que desbloquea COMPRAR/REDUCIR/VENDER por valoración,
  combinado con riesgo, concentración e incertidumbre (ya calculados).
- **Dashboard:** señal agregada (p. ej. "cartera cotiza a X% de su Fair Value estimado") **solo** si la
  cobertura es suficiente; si no, declararlo.

**Reglas no negociables (del usuario):**
- **Distinguir** valoración fundamental (DCF) de proyección estadística (A/B/C y bootstrap): pantallas y
  etiquetas separadas, nunca una cifra combinada.
- **No DCF industrial estándar a bancos ni ETF.** Bancos → modelos específicos (p. ej. exceso de
  retorno / dividendos); ETF → look-through, no DCF.
- **No inventar datos** para completar valoraciones. Un campo faltante/bloqueado se declara; no se
  rellena. Elegibilidad = estado de calidad suficiente, no "existe en EODHD".
- **Precedencia:** cablear EODHD a la UI **antes** de Fair Value, o el DCF de los 15 ADR/IFRS nace
  cojo (sin interinos frescos).

---

## 9. Roadmap priorizado (impacto para el inversionista · esfuerzo · dependencias · riesgo)

Severidad: **Crítico** = error financiero o decisión potencialmente engañosa · **Alto** = funcionalidad
incompleta o interpretación · **Medio** = UX/claridad · **Bajo** = estético.

### Bloque A — Mejoras inmediatas (independientes de Fair Value)

| # | Acción | Sev. | Impacto | Esfuerzo | Dep. | Riesgo |
|---|---|---|---|---|---|---|
| A1 | **Cablear EODHD a producción** (registry → `run_scan`/job de fundamentales; payload con interino/TTM/calidad) | Crítico | Muy alto (desbloquea ADR/IFRS y TTM reales) | Alto | EODHD (hecho) | Medio (nuevo job; costo API ya aprobado) |
| A2 | **Exponer campos ya calculados** en Ficha (fcf_ttm, net_debt, diluted, OCF, CAPEX, márgenes) + sello de calidad por campo | Alto | Alto | Bajo | A1 para TTM | Bajo |
| A3 | **Arreglar tema:** definir `faint`, separar `warn` de `accent`, paleta de datos | Medio | Alto (legibilidad global) | Bajo | — | Bajo |
| A4 | **Scorecard de skill en Laboratorio** (outperformance, acierto desde `prediction_outcomes`) | Medio | Medio-alto | Bajo | — | Bajo |
| A5 | **Riesgo/concentración/sector en Dashboard y Cartera** (reusar `core/forecast`) | Alto | Alto | Medio | — | Bajo |
| A6 | **Evolución de patrimonio** (serie temporal; snapshots) | Alto | Alto (pregunta #1) | Medio | — | Bajo |
| A7 | **Renombrar nomenclatura** A/B (Proyección) vs modelos ML (Lab) | Medio | Medio (evita confusión) | Bajo | — | Bajo |
| A8 | **ADR_ratio desde identidad persistida** (quitar hardcode) | Medio | Medio (correctitud) | Bajo | — | Bajo |

### Bloque B — Fair Value (siguiente desarrollo mayor)

| # | Acción | Sev. | Dep. |
|---|---|---|---|
| B1 | Servicio DCF por empresa con escenarios y estado de calidad por campo | Crítico (valor central) | A1, A2 |
| B2 | Modelos específicos para bancos (no DCF industrial) | Alto | B1 |
| B3 | Integrar Fair Value en Ficha → Oportunidades → Advisor → Dashboard (en ese orden) | Crítico | B1 |
| B4 | Desbloquear decisiones de compra por valoración en Advisor | Crítico | B1, B3 |

### Bloque C — Mejoras posteriores

| # | Acción | Sev. |
|---|---|---|
| C1 | Unificar "Oportunidades" (fusionar motor de valoración; eliminar duplicación) | Medio |
| C2 | Evolución financiera multi-año + competidores + calidad del negocio en Ficha | Alto |
| C3 | Interactividad de gráficos (tooltip/zoom/referencia) | Bajo |
| C4 | Componentes reutilizables (StatTile/DataTable/EmptyState/…) + estados unificados | Medio |
| C5 | Multimoneda en Cartera (XIRR y valor con FX) | Medio |
| C6 | Decidir Fintual (reactivar o retirar) | Bajo |

**Secuencia recomendada:** A3 + A2 + A4 (rápidos, alto impacto visible) → A1 (habilitador) → A5 + A6 →
Bloque B (Fair Value) → Bloque C. **A1 antes de B** es la dependencia dura: Fair Value sin EODHD deja
cojos a los 15 ADR/IFRS.

---

## 10. Cierre

**Lo que GIIC ya hace bien y hay que proteger:** honestidad metodológica, trazabilidad de procedencia,
separación de investigación vs recomendación, y un motor de riesgo correcto. No tocar esa base.

**El diagnóstico en una frase:** GIIC calcula como plataforma profesional pero **muestra** como
prototipo; el próximo salto no es más métricas, es **llevar a la pantalla lo que ya se calcula**,
**cablear EODHD**, y **construir Fair Value** para desbloquear las decisiones.

**Restricciones respetadas:** no se modificó código, interfaz ni modelos; las 309 intactas; nada en
producción (salvo el merge de EODHD ya aprobado); no se inició Fair Value; no se eliminó nada.

Pendiente de tu aprobación para pasar a implementación, empezando por el Bloque A.
