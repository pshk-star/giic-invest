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
