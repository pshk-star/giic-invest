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
- **E. IFRS/20-F (ASML, TSM) — mapeo a payload de ratios.** `edgar_pit.py` YA ingiere los
  conceptos crudos ifrs-full (Revenue, ProfitLoss, EPS, Equity, etc.) a `fundamentals_pit`
  además de us-gaap (soporte preparado y testeado). PENDIENTE: que `run_scan.py` mapee los
  conceptos IFRS → el `payload` de ratios (pe_ttm, eps_growth_yoy, fcf_yield, etc.) para que
  ASML/TSM tengan valoración fundamental. Hoy aparecen SIEMPRE en proyección y Advisor con
  acción REVISAR y causa concreta ("emisor extranjero 20-F / IFRS, fuera de us-gaap"). No se
  inventan sus fundamentales.
- **F. Enriquecer el payload** con historial (ingresos/EPS/FCF), acciones diluidas, deuda neta,
  P/E histórico y procedencia por campo (period_end + filing_date) para mejorar el motor
  fundamental (hoy usa pe_ttm/eps_growth_yoy/fcf_yield; múltiplo histórico y DCF pendientes).
