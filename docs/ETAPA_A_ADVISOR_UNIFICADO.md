# Etapa A — Investment Advisor unificado (perfil + orquestador)

**Estado:** funcional con **datos reales**, experimental y reversible (flag `VITE_FF_UNIFIED`, ruta
`/asesor`). Reutiliza los motores existentes (Scanner, Advisor 3.0, asignación, política de valoración,
riesgo) sin duplicar lógica. **Advisor 2.2 y funciones productivas intactas.** CI verde (295 frontend).
Recomendaciones **SIMULADAS**, no ejecutadas.

---

## Qué entrega (sin parámetros manuales)

Al abrir, GIIC responde automáticamente, gobernado por el **perfil**:
1. **Qué hacer con cada posición** — MANTENER / ACUMULAR / REDUCIR / VENDER / REVISAR.
2. **Qué comprar con dinero nuevo y cuánto** — montos concretos o conservar efectivo.
3. **Oportunidades priorizadas** del universo, clasificadas.
4. **Explicación financiera y de riesgo** por decisión.
5. **Pendientes de análisis profundo** (insumo de la Etapa B).

## Perfil persistente (`core/advisor-profile.ts`)

Se configura **una vez** en `settings` (ya existente): moneda base, capital disponible, aporte mensual,
efectivo mínimo, horizonte, tolerancia al riesgo. Los **límites de decisión se derivan**: topes
explícitos del perfil si existen; si no, por **tolerancia al riesgo** (bandas documentadas y revisables:
conservador 0.20/0.35, moderado 0.30/0.45, agresivo 0.45/0.55; margen mínimo 0.15/0.10/0.08). El capital
a invertir = aporte mensual, o (disponible − efectivo mínimo). **Si falta un dato esencial** (moneda,
capital, tolerancia), GIIC **lo pide** y no lo inventa.

## Orquestador (`core/advisor-engine.ts`)

Compone en una tubería fija: perfil → constraints → Scanner → Advisor 3.0 (acción por posición) →
asignación multiposición → `AdvisorReport` único. **Una sola decisión por instrumento**, distinguiendo
acción sobre posición existente, compra nueva y prioridad de investigación. Scanner, Advisor y asignación
**comparten la misma política** (no hay voces contradictorias). ACUMULAR = posición en cartera
infravalorada con holgura de peso.

## Resultado real (vista previa, perfil demo moderado, aporte USD 3.000)

**Resumen:** *"Hoy: desplegar USD 2.129 en 5 nombres y conservar USD 871. 4 a reducir. 5 a revisar."*
Postura: **desplegar**. Topes 0.30/empresa, 0.45/sector (tolerancia moderado), margen mínimo 0.10.

**Acciones sobre la cartera (real):** ASML **VENDER** (−49.5%), TSM/NVDA/NFLX **REDUCIR** (−74%/−49%/−42%),
META **MANTENER** (−8%), ETFs (QQQ, SCHD, GLD, VOO, SLV) **REVISAR** (sin FV; se evalúan por rol).

**Dinero nuevo:** LOW $450, AMGN $450, EOG $450, HD $450, UPS $329; efectivo $871.

**Oportunidades:** LOW/AMGN/EOG/HD/UPS = *pendiente de análisis* **comprables** (FCFF experimental,
asignación acotada); FCX/MRK/AMT/PEP/LMT = *pendiente de análisis* no comprables. Ninguna se trata como
confiable sin análisis profundo, pero tampoco quedan excluidas.

**Riesgos:** concentración elevada; vol anual ~23%, HHI sector 0.341; 5 nombres de la asignación se
apoyan en valoración experimental (acotada a propósito).

**Lectura honesta:** hoy **todas** las compras nuevas son *experimentales* (FCFF), porque solo 5
empresas tienen FV productivo y están sobrevaloradas. Por eso la asignación es conservadora (sleeves
pequeños + efectivo). Subir la convicción es exactamente el objetivo de la **Etapa B** (evaluación
escalonada y ampliación de cobertura fundamental).

## Pruebas (`advisor-engine.test.ts`, 11)

Perfil: deriva constraints por tolerancia / topes del perfil, capital a invertir, datos faltantes,
mapeo de settings. Orquestador: una acción por posición; ACUMULAR vs REDUCIR; clasificación
atractiva/pendiente/poco/insuficiente; asignación integrada con conservación exacta; coherencia (sin
contradicción); constraints desde el perfil con procedencia; ESPERAR sin oportunidades.

## Criterio de aceptación de la Etapa A — estado

1. Recomendación por posición ✅  2. Oportunidades priorizadas ✅  3. Asignación concreta ✅
4. Explicación financiera y de riesgo ✅  5. Pendientes de análisis ✅.
(El historial verificable, criterio 6, ya existe en P2.6 y se integrará en la Etapa C.)

## Archivos y siguiente paso

`core/advisor-profile.ts`, `core/advisor-engine.ts` (+test), `pages/UnifiedAdvisor.tsx`,
`App.tsx`/`vite-env.d.ts` (`VITE_FF_UNIFIED`, `/asesor`), `scripts/advisor_preview.ts` +
`advisor_preview.yml` (resultado real).

**Siguiente (Etapa B):** evaluación escalonada del universo (Nivel 1 screening → Nivel 2 valoración →
Nivel 3 análisis profundo) y ampliación de cobertura fundamental **sin degradar el rigor**, para subir
la proporción de oportunidades con evidencia sólida.
