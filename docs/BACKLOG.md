# Backlog funcional (no bloqueante)

Observaciones aprobadas para abordar más adelante (no reconstruir motores; no modificar Fair Values).

## B1 · Montos de asignación como propuestas experimentales
**Origen:** revisión de cierre de Etapa A (2026-11-11).
Los montos de asignación están muy condicionados por límites y heurísticas. Deben **presentarse como
propuestas experimentales, no como asignaciones óptimas**.
- **Hecho ya (etiquetado):** el guardrail de la asignación ahora dice "PROPUESTAS EXPERIMENTALES … NO
  asignaciones óptimas".
- **Pendiente (P3.0 / posterior):** reflejarlo también en la UI (encabezado de la sección de dinero
  nuevo, tono visual experimental); considerar exponer la sensibilidad del monto a los límites (cuánto
  cambia el leg si se relaja el tope) sin prometer optimalidad.

## B2 · El desacuerdo de modelos debe influir en la MAGNITUD del recorte
**Origen:** revisión de cierre de Etapa A (2026-11-11).
La fórmula actual de reducción (½ del margen productivo, acotada a [20 %, 50 %]) es demasiado
simplificada. El **desacuerdo entre DCF productivo y FCFF debería influir también en la magnitud del
recorte, no solo en la clasificación** (hoy el desacuerdo cambia la acción VENDER→REDUCIR y degrada la
confianza, pero no el tamaño). Mantener los recortes como **escenarios indicativos, no instrucciones
ejecutables**.
- **Hecho ya (etiquetado):** el riesgo de ventas/reducciones ahora dice "ESCENARIOS INDICATIVOS, no
  instrucciones ejecutables" y explicita la fórmula.
- **Pendiente (motor, con aprobación explícita):** modular el recorte por el desacuerdo, p.ej. atenuar el
  tamaño cuando la brecha DCF–FCFF es grande (mayor incertidumbre ⇒ recorte más conservador) y/o acotar
  por sensibilidad del modelo. Requiere cambio en `advisor3.ts` (trim) → NO se hace sin aprobación por la
  restricción de "no reconstruir motores". No tocar Fair Values.
