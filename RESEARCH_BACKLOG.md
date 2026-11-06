# Pendientes de Research (siguiente entrega, NO mezclar con X-Ray / Hito 2)

Registrados a petición de Pablo (2026-11-05). Abordar después de cerrar el Hito 2.

## A. ASML sin proyección
- ASML aparece correctamente en la cartera pero NO tiene proyección del modelo.
- Causa probable (a confirmar con evidencia): ASML **no está en el universo invertible**
  (`backend/app/jobs/universe.py` no lo incluye) y/o no tiene suficiente historial de precios
  / fundamentales PIT para generar features.
- Tarea: diagnosticar la causa EXACTA (universo, cobertura de precio, fundamentales EDGAR —
  ASML es emisor extranjero, presenta 20-F, puede no estar en companyfacts) y evaluar su
  **incorporación legítima al modelo A** (precio) sin alterar las 309 predicciones oficiales
  (sería una nueva versión/emisión, no una modificación retroactiva).

## B. Fichas de Research — tooltips y gráficos
- Cada métrica fundamental debe llevar **tooltip**: definición, fórmula, interpretación,
  limitaciones y fuente (SEC EDGAR).
- Corregir los gráficos de precio para mostrar **ejes de precio y fechas** (y tooltips),
  consistente con el diseño premium.

(Prioridad: después del Hito 2 — Portfolio X-Ray. Luego sigue Portfolio Forecast.)

## Mantenimiento Portfolio X-Ray (registrado 2026-11-06)
- **C. Sector SIC≈GICS:** el mapeo sector usa el código SIC de la SEC (verificable) aproximado a
  GICS; no es GICS oficial. Indicado en la UI ("SIC≈GICS"). Mejorar el mapeo para reducir el
  % "Sin clasificar" (ampliar reglas SIC o incorporar una fuente GICS).
- **D. Antigüedad N-PORT:** las composiciones SEC N-PORT tienen rezago (VOO/QQQ al 30/06/2026).
  La UI muestra un badge de días de antigüedad (>35d). El cron diario ya reintenta y tomará
  automáticamente declaraciones más recientes cuando la SEC las publique; verificar periódicamente.

## Valoración fundamental — cobertura de emisores extranjeros (registrado 2026-11-06)
- **E. RESUELTO (2026-11-06): ASML y TSM con fundamentales reales.** Causa raíz: el parser
  (`providers/edgar.py::parse_companyfacts`, fuente real del `payload`) solo leía us-gaap/USD/10-K.
  Diagnóstico en vivo: ASML publica bajo **us-gaap pero en EUR** (20-F); TSM bajo **ifrs-full/TWD**.
  Fix: detección de taxonomía y DIVISA data-driven, formularios 10-K/20-F/40-F, conversión FX
  (USD por unidad) y adr_ratio (TSM 5, ASML 1); variante de concepto más reciente.
  Verificado tras ingesta real: ASML ROE 49%, P/E 51.4, margen 29.4%, crec. EPS 28.4%;
  TSM ROE 27%, margen 40%, crecimientos reales.
- **E.1 PENDIENTE — TSM P/E/FCF en USD:** requieren FX TWD→USD, que Frankfurter (ECB) no publica.
  Hoy TSM muestra ratios adimensionales (ROE, márgenes, crecimientos) y P/E/FCF como "no
  disponible" con causa. Buscar fuente FX TWD→USD gratis o derivarla.
- **E.2 PENDIENTE — cobertura de `shares` (market cap/FCF) de algunos US (p. ej. META):**
  market_cap/fcf_yield quedan null cuando no se resuelve EntityCommonStockSharesOutstanding;
  ampliar fuentes de acciones en circulación.
- **F. Enriquecer el payload** con historial (ingresos/EPS/FCF), P/E histórico y procedencia por
  campo (period_end + filing_date) para múltiplo histórico y DCF (hoy múltiplo central = P/E
  actual, un supuesto preliminar). `edgar_pit.py` ya ingiere el crudo (us-gaap + ifrs-full).
- **G. A/B/C y emisores extranjeros:** ASML/TSM no están en `universe.py` (universo US). Para
  incluirlos en A/B/C se requiere una emisión nueva y validada (no modificar las 309).
