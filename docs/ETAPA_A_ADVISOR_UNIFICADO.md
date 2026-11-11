# Etapa A — Investment Advisor unificado (perfil + orquestador)

**Estado:** funcional con **datos reales**, experimental y reversible (flag `VITE_FF_UNIFIED`, ruta
`/asesor`). Reutiliza los motores existentes (Scanner, Advisor 3.0, asignación, política de valoración,
riesgo) sin duplicar lógica. **Advisor 2.2 y funciones productivas intactas.** CI verde (300 frontend).
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

**1. No se recomienda comprar lo que está pendiente de análisis.** La asignación EJECUTABLE usa solo
valoraciones **productivas/confiables**. Los nombres con FCFF experimental (LOW, AMGN, EOG, HD, UPS)
quedan como **candidatas de investigación — NO comprables**. Taxonomía explícita: compra_recomendada /
oportunidad_analizada / candidata_investigacion / poco_atractiva / evidencia_insuficiente.

**2. VENDER/REDUCIR con sustento.** Ninguna venta automática por margen negativo: sobrevaloración
**extrema** (≤ −45 %) ⇒ **REDUCIR** por alta sensibilidad, no VENDER; VENDER exige corroboración de un
2º modelo y datos completos (los datos faltantes NO corroboran). **REDUCIR cuantificado** y con
incertidumbre explícita (horizonte, costos/impuestos, reinversión no incorporados).

**3. ETFs por su naturaleza.** Rol (renta variable amplia vs metal/commodity), solapamiento con
posiciones directas y peso; **no** REVISAR por carecer de FCFF. Costos/liquidez marcados como no
disponibles. La concentración agregada de vehículos se reporta como riesgo aparte.

**Ejecución real (perfil persistido, aporte USD 3.000):**
- **Resumen:** *"Hoy: mantener la cartera y CONSERVAR el efectivo — las oportunidades no superan el
  umbral; 4 posiciones a reducir."* Postura: **esperar** (dinero nuevo → **efectivo**).
- **Cartera:** TSM **REDUCIR −37 % (≈$1.720)**, NVDA **−25 % (≈$1.145)**, ASML **−25 % (≈$942)**, NFLX
  **−21 % (≈$224)** — todas con incertidumbre explícita; **ninguna VENDER**. META MANTENER. ETFs
  QQQ/SCHD/VOO (renta variable amplia, solapamiento 11,5 %/0 %/9,9 %) y GLD/SLV (metal) **MANTENER**.
- **Dinero nuevo:** **efectivo $3.000** (ninguna compra sobre valoración incompleta).
- **Investigación:** LOW, AMGN, EOG, HD, UPS (señal FCFF preliminar; requieren valoración productiva/
  análisis profundo antes de ser comprables).

**Por qué ESPERAR es la respuesta honesta hoy:** la evaluación es amplia (universo 54, 35 valoradas),
pero solo 5 empresas tienen FV productivo (confiable) y están **sobrevaloradas**; el resto tiene FV
experimental, que **no** habilita compra. Por eso GIIC recomienda efectivo + una lista de investigación,
en vez de forzar compras. Ampliar la cobertura de evidencia **sólida** es el objetivo de la **Etapa B**.

## Pruebas (`advisor-engine.test.ts`, 16)

Perfil: deriva constraints por tolerancia / topes del perfil, capital a invertir, datos faltantes,
mapeo de settings. Orquestador: una acción por posición; ACUMULAR vs REDUCIR; clasificación
atractiva/pendiente/poco/insuficiente; asignación integrada con conservación exacta; coherencia (sin
contradicción); constraints desde el perfil con procedencia; ESPERAR sin oportunidades.

## Criterios de aceptación de la Etapa A — estado

Prueba funcional end-to-end (datos reales, perfil persistido) que demuestra:
- Perfil persistente conectado ✅ (`perfil_demo: false`).
- Recomendaciones coherentes entre módulos ✅ (una sola política).
- Ninguna compra basada exclusivamente en valoración incompleta ✅ (experimental → investigación).
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
