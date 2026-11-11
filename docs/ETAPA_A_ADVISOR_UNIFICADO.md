# Etapa A — Investment Advisor unificado (perfil + orquestador)

**Estado:** funcional con **datos reales**, experimental y reversible (flag `VITE_FF_UNIFIED`, ruta
`/asesor`). Reutiliza los motores existentes (Scanner, Advisor 3.0, asignación, política de valoración,
riesgo) sin duplicar lógica. **Advisor 2.2 y funciones productivas intactas.** CI verde (301 frontend).
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

## Correcciones aplicadas (tras revisión) y resultado real

Tres correcciones (sin tocar Fair Values ni reconstruir motores), demostradas con **datos reales** y
**perfil PERSISTIDO** (`perfil_demo: false`, round-trip `settings`→motor; posiciones reales):

**1. Política de valoración ÚNICA honrada (corrección posterior).** El orquestador había quedado
sobre-restringido: sobrescribía `scanInput.fcffFallback` con `false`, reimponiendo "sólo FV productivo"
para compras y descartando `VITE_FF_VALPOLICY` aunque la página lo cableara. **Corregido:** un único valor
de fallback (del flag) gobierna Scanner, Advisor 3.0, asignación y clasificación. El **FCFF como fallback
bajo controles P2.4** (confianza suficiente, margen no extremo) es **accionable a tier experimental**
(menor convicción que un FV productivo); el FCFF que **no** supera los controles queda en **investigación**.
Un margen positivo por sí solo no basta (`passesValueGate` exige confianza + fuente gobernante). No se
modifican Fair Values. Taxonomía: compra_recomendada (FV productivo) / oportunidad_analizada (FCFF fallback
accionable, o productiva restringida) / candidata_investigacion (FCFF que no gobierna) / poco_atractiva /
evidencia_insuficiente.

**2. VENDER/REDUCIR con sustento.** Ninguna venta automática por margen negativo: sobrevaloración
**extrema** (≤ −45 %) ⇒ **REDUCIR** por alta sensibilidad, no VENDER; VENDER exige corroboración de un
2º modelo y datos completos (los datos faltantes NO corroboran). **REDUCIR cuantificado** y con
incertidumbre explícita (horizonte, costos/impuestos, reinversión no incorporados).

**3. ETFs por su naturaleza.** Rol (renta variable amplia vs metal/commodity), solapamiento con
posiciones directas y peso; **no** REVISAR por carecer de FCFF. Costos/liquidez marcados como no
disponibles. La concentración agregada de vehículos se reporta como riesgo aparte.

**Ejecución real (perfil persistido `perfil_demo: false`, aporte USD 3.000) — dos corridas CI (commit
`2a0c6cc`) que contrastan el flag:**

*VALPOLICY **ACTIVO** (preview run 43120133646):* postura **desplegar** — **USD 2.129** en 5 nombres,
efectivo **871**. Dinero nuevo (FCFF fallback bajo controles, tier experimental): **LOW $450 (+28 %),
AMGN $450 (+24 %), EOG $450 (+24 %), HD $450 (+20 %), UPS $329 (+12 %)**. Estos 5 **superan** los
controles P2.4 (confianza suficiente, margen no extremo) ⇒ accionables; antes quedaban relegados a
investigación por el override. **Control de calidad:** PFE (+108 %) y ADBE (+95 %) ⇒ margen **extremo**
(≥80 %) ⇒ confianza degradada ⇒ **candidata_investigacion, no comprables**. La política discrimina: ni
"todo FCFF a investigación" (el bug) ni "todo FCFF a compra" (imprudente).

*VALPOLICY **inactivo** (preview run 43120142630):* la misma cartera da postura **esperar**, **efectivo
$3.000**, y los 5 nombres a **investigación** (sólo el FV productivo gobierna). Comportamiento histórico,
reversible por flag.

- **Cartera (idéntica en ambas corridas — gobierna el FV productivo):** TSM **REDUCIR −37 % (≈$1.720)**,
  NVDA **−25 % (≈$1.145)**, ASML **−25 % (≈$942)**, NFLX **−21 % (≈$224)** — con incertidumbre explícita;
  **ninguna VENDER**. META MANTENER. ETFs QQQ/SCHD/VOO (renta variable amplia, solapamiento 11,5/0/9,9 %)
  y GLD/SLV (metal) **MANTENER**. El % de recorte = ½·|margen| productivo, acotado [20 %, 50 %]; el
  desacuerdo DCF–FCFF degrada la confianza y puede bajar VENDER→REDUCIR (NFLX, brecha 51 pp), no altera
  la fórmula del recorte.

**Lectura:** la decisión ahora proviene de **una sola política** (P2.4) gobernada por el flag, sin que el
orquestador reimponga restricciones ya resueltas. Ampliar la cobertura de **evidencia productiva** (subir
nombres de experimental a confiable) sigue siendo el objetivo de la **Etapa B**.

## Pruebas (`advisor-engine.test.ts`, 17)

Perfil: deriva constraints por tolerancia / topes del perfil, capital a invertir, datos faltantes,
mapeo de settings. Orquestador: una acción por posición; ACUMULAR vs REDUCIR; clasificación
atractiva/pendiente/poco/insuficiente; asignación integrada con conservación exacta; coherencia (sin
contradicción); constraints desde el perfil con procedencia; ESPERAR sin oportunidades.

## Criterios de aceptación de la Etapa A — estado

Prueba funcional end-to-end (datos reales, perfil persistido) que demuestra:
- Perfil persistente conectado ✅ (`perfil_demo: false`).
- Recomendaciones coherentes entre módulos ✅ (una sola política).
- Ninguna compra basada en valoración que no supere los controles ✅ (FCFF extremo/baja confianza →
  investigación; FCFF que pasa P2.4 → accionable tier experimental; no se modifican FVs).
- Ventas y reducciones justificadas y **cuantificadas** ✅ (% y USD, con incertidumbre).
- ETFs evaluados según su naturaleza ✅ (rol/solapamiento, no por falta de FCFF).
- Asignación de capital coherente con las recomendaciones ✅ (efectivo, sin forzar compras).
- Separación simulación/ejecución ✅ (`simulated`).
- Ninguna dependencia de parámetros financieros manuales ✅ (topes del perfil/tolerancia).

## Archivos y siguiente paso

`core/advisor-profile.ts`, `core/advisor-engine.ts` (+test), `pages/UnifiedAdvisor.tsx`,
`App.tsx`/`vite-env.d.ts` (`VITE_FF_UNIFIED`, `/asesor`), `scripts/advisor_preview.ts` +
`advisor_preview.yml` (resultado real).

**Siguiente (Etapa B):** evaluación escalonada del universo (Nivel 1 screening → Nivel 2 valoración →
Nivel 3 análisis profundo) y ampliación de cobertura fundamental **sin degradar el rigor**, para subir
la proporción de oportunidades con evidencia sólida.
