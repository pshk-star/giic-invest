# GIIC — Roadmap

Estado actual: **v0.3** — plataforma web privada, US$0, con datos reales, gestión de
cartera y scanner de oportunidades. Sin motor predictivo (deliberado).

## Próximo (sin costo, incremental)
1. **Holdings de ETF** desde fuentes gratuitas/manuales para completar el look-through
   (hoy se marca cuando faltan).
2. **Universo ampliable por lotes**: pasar de ~90 a varios cientos con actualización
   escalonada (p.ej. 1/5 del universo por día) respetando límites gratuitos.
3. **Histórico de rankings en la UI**: ver cómo cambió el score de un instrumento
   entre corridas (ya se guardan snapshots point-in-time).
4. **Más fundamentales**: derivar EV/EBITDA y deuda/equity de EDGAR cuando los
   conceptos XBRL lo permitan; dejar en None lo que no sea fiable.

## Fase de validación (requisito antes de predecir)
5. **Backtesting del scanner** con los snapshots point-in-time acumulados:
   ¿las señales (value/quality/growth/momentum) generan retorno ajustado por riesgo
   fuera de muestra? Walk-forward, sin look-ahead ni survivorship bias.
6. **Métricas de calibración** del propio sistema (Brier/IC) antes de mostrar
   cualquier probabilidad.

## Fase predictiva (solo si 5–6 lo justifican)
7. **Motor predictivo** probabilístico calibrado y **Investment Decision Engine**
   (propuesta de importe, horizonte, riesgo, comparación vs. VOO/QQQ y vs. aumentar
   posición), con restricciones de riesgo y evidencia. No se construye sin la
   validación previa.

## Escalado de infraestructura (si algún día se sale del $0)
8. Si el universo o la frecuencia superan los límites gratuitos: mover el job a un
   runner de pago por uso con tope, o un dataset point-in-time institucional. La
   arquitectura ya aísla proveedores y job, así que es un cambio localizado.
