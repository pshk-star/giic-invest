# Auditoría del motor de Portfolio Forecast (motor estadístico de riesgo)

Auditoría de la **implementación real** en `frontend/src/core/forecast.ts`
(función `forecast()` y helpers `alignReturns` / `buildAssets`). Fecha de la
auditoría: según la fecha declarada por el usuario. No es una descripción
teórica: cada afirmación cita archivo, función y línea conceptual.

Fuente de datos de precios: tabla `price_history.close`, poblada por
`backend/app/jobs/history.py`, que ingiere el **cierre ajustado (adjclose) de
Yahoo — ajustado por splits y dividendos**. Es decir, la serie es de **retorno
total** (reinvierte dividendos), no precio nominal.

---

## Respuestas a las 12 preguntas

### 1. ¿Simula retornos individuales por instrumento y agrega en cada trayectoria?
**Sí.** En el bucle de simulación (`forecast()`), cada trayectoria mantiene un
vector `cum[i]` de retorno acumulado **por activo**. En cada día:
```
cum[i] *= (1 + simRets[i][start + b]);     // retorno diario del activo i
v = cash + Σ_i  assets[i].valueUsd * cum[i]; // valor de cartera ese día
```
El valor de cartera de cada día es la **suma de las posiciones individuales
revaluadas**, no una serie agregada precalculada.

### 2. ¿O simula directamente retornos de la cartera agregada?
**No.** No existe una "serie de la cartera" que se remuestree. La cartera se
reconstruye activo por activo en cada trayectoria (ver #1). Esto es importante:
permite que cada instrumento conserve su propia volatilidad y su co-movimiento
con los demás.

### 3. ¿Cómo incorpora correlaciones?
De dos formas, para dos usos distintos:
- **Simulación (bandas, P5/P50/P95, prob. pérdida):** *bootstrap por bloques
  **multivariante***. Cada bloque muestreado usa **el mismo índice de día
  histórico** `start+b` para **todos** los activos a la vez. Así, las
  co-ocurrencias reales del mismo día (correlaciones, incluido el solapamiento
  VOO/QQQ) se preservan **sin asumir una matriz de correlación ni normalidad**.
- **Volatilidad y contribución al riesgo:** matriz de **covarianza histórica**
  `cov` (función `covariance()`), usada analíticamente (ver #8).

### 4. ¿Qué tratamiento reciben los ETFs?
Se tratan como **un instrumento más**, con su propia serie de precios ajustados
(VOO es VOO, QQQ es QQQ). Sus correlaciones con las posiciones directas entran
automáticamente por el muestreo conjunto (#3). El motor **no** descompone el ETF
en sus subyacentes.

### 5. ¿Cómo evita duplicar las exposiciones de X-Ray?
Porque **opera exclusivamente a nivel de instrumento**: nunca incorpora los
holdings look-through de X-Ray a la simulación. Una posición directa en AAPL y
el AAPL contenido dentro de VOO **no se combinan** aquí. No hay duplicación
porque el look-through simplemente **no se usa** en este motor. (El look-through
pertenece al motor fundamental y a X-Ray, que son vistas separadas.)

### 6. ¿Cómo maneja efectivo, dividendos, splits y días sin cotización?
- **Efectivo / parte no cubierta:** `cash = currentValue − simValue` se mantiene
  **constante** (0% retorno) durante toda la trayectoria. El efectivo explícito
  se modela como un activo `EFECTIVO` con retornos 0 (`buildAssets`).
- **Dividendos y splits:** resueltos **aguas arriba** por el uso de **adjclose**
  (Yahoo ajusta retroactivamente por splits y dividendos). El motor no vuelve a
  ajustar.
- **Días sin cotización:** `alignReturns` toma la **intersección de fechas
  comunes** a todos los activos y calcula retornos solo entre fechas comunes
  consecutivas. Un hueco de un activo elimina esa fecha para todos; el retorno
  "salta" el hueco. Es una aproximación conservadora que evita falsos retornos.

### 7. ¿Qué ocurre con instrumentos de historial incompleto?
`forecast()` filtra los activos con `< 60` retornos: quedan **excluidos del
riesgo y de la simulación**, pero su **valor se conserva constante** dentro de
`cash` (no desaparecen del valor actual). Se emite un **warning** nombrando las
posiciones excluidas y el **% de cartera sin historial**. Además `alignReturns`
trunca todas las series a la longitud común mínima.

### 8. ¿Qué papel tienen medias, medianas, medias móviles y volatilidad?
- **Medias:** (a) centran la covarianza; (b) en **modo neutral** se restan de
  cada serie para eliminar la deriva estimada (`r − mean_i`), conservando
  volatilidad y correlaciones. En **modo histórico** la media empírica queda
  implícita en los retornos muestreados.
- **Medianas:** únicamente como **P50 del valor final de cartera** (#9).
- **Medias móviles:** **no se usan.**
- **Volatilidad histórica:** `annVol = √(wᵀΣw · 252)`, se **reporta**; no
  conduce la simulación (la volatilidad simulada emerge de los datos, no de un
  parámetro).

### 9. ¿Cómo calcula P5, P50, P95?
Sobre el **corte transversal de los valores finales de cartera** en cada
horizonte:
```
col = paths.map(p => p[dias−1]).sort(asc);   // valores finales de cada trayectoria
P5 = pctile(col, 0.05); P50 = pctile(col, 0.5); P95 = pctile(col, 0.95);
```
Son percentiles **del total de la cartera**, calculados sobre los extremos de
trayectorias agregadas.

### 10. ¿Calcula la mediana sobre valores finales de cartera, sin sumar medianas individuales?
**Sí — y es correcto.** El P50 es el percentil 50 del arreglo ordenado de
**valores totales de cartera** por trayectoria, **no** la suma de las medianas de
cada activo. Ver el ejemplo numérico abajo, que muestra por qué sumar medianas
individuales da un resultado distinto (y erróneo).

### 11. ¿Cómo calcula la probabilidad simulada de pérdida?
```
probLoss = (nº de trayectorias con valor final < currentValue) / nº trayectorias
```
Fracción de simulaciones que terminan por debajo del valor actual. `var95 =
P5 − currentValue` (pérdida en el peor 5%).

### 12. ¿Qué supuestos podrían sesgar las proyecciones?
1. **Deriva histórica (modo histórico):** arrastra el rendimiento del período
   muestreado hacia adelante → **sesgo alcista** si la ventana fue un mercado
   toro. **Mitigado** por el **modo neutral** (deriva ≈ 0).
2. **Estacionariedad:** supone que la distribución futura se parece a la
   muestreada.
3. **Buy & hold:** sin rebalanceo.
4. **Tamaño de bloque (10):** preserva autocorrelación corta; rompe la
   dependencia en los límites de bloque.
5. **Parte no cubierta congelada a 0%:** subestima riesgo y retorno de esa parte.
6. **Sesgo de supervivencia:** usa solo el historial de las posiciones actuales.
7. **Ventana histórica:** por defecto se usa TODO el historial común disponible
   (cap de 10 años solo por memoria; `getPriceHistory` pagina para no truncar en
   1000 filas). `ForecastOpts.windowDays` permite acotar (p. ej. 1 año) para el
   análisis de sensibilidad; una ventana más corta cambia materialmente vol y deriva.
8. **Intersección de fechas:** una posición joven acorta el historial común de
   todos.
9. **HHI/concentración efectiva** se calculan sobre la sub-cartera **cubierta**
   (excluye el efectivo), por lo que pueden sobrestimar la diversificación del
   total si hay mucho efectivo.
10. **adjclose re-ajustado retroactivamente:** Yahoo reescribe la serie ante
    nuevos dividendos/splits (limitación conocida, común a backtest y emisión).

---

## Ejemplo numérico reproducible (agregación y percentiles)

Cartera: **A = 6.000 USD**, **B = 4.000 USD**, efectivo 0. `currentValue =
10.000`. Supongamos **3 trayectorias** con estos multiplicadores finales:

| Trayectoria | A (×) | B (×) | Valor A | Valor B | **Cartera** |
|---|---|---|---|---|---|
| 1 | 1,1667 | 0,7500 | 7.000 | 3.000 | **10.000** |
| 2 | 0,8333 | 1,2500 | 5.000 | 5.000 | **10.000** |
| 3 | 1,0000 | 1,1250 | 6.000 | 4.500 | **10.500** |

- **Correcto (lo que hace el motor):** ordenar los **totales de cartera**
  `[10.000, 10.000, 10.500]` → **P50 = 10.000**.
- **Incorrecto (sumar medianas individuales):** mediana(A)=`med[7.000,5.000,
  6.000]`=6.000; mediana(B)=`med[3.000,5.000,4.500]`=4.500 → 6.000+4.500 =
  **10.500**.

El motor devuelve **10.000**, no 10.500. Sumar medianas por activo infla el
resultado porque ignora que los buenos y malos desempeños de A y B **no ocurren
en la misma trayectoria**. Prob. de pérdida aquí: 0/3 = 0% (ninguna < 10.000).

Reproducción en código: `forecast()` con `paths` = esas 3 trayectorias produce
`horizons[*].valP50 = 10000` y `probLoss = 0`.

---

## Pruebas de consistencia (automatizadas, en CI)

`frontend/src/core/forecast.test.ts` (vitest):
1. **Conciliación:** `currentValue` = suma exacta de posiciones.
2. **Monotonía de percentiles:** `valP5 < valP50 < valP95`.
3. **`probLoss ∈ [0,1]`.**
4. **Contribución al riesgo suma 100%** (`Σ riskPct = 1 ± 1e-6`) y el activo
   grande+volátil domina.
5. **HHI** coincide con `Σ wᵢ²` para pesos conocidos.
6. **Exclusión de historial corto** (< 60) con warning.
7. **Caso vacío:** sin historial suficiente → resultado vacío con aviso.

---

## Errores materiales encontrados y corregidos

1. **Off-by-one en el muestreo por bloques** *(corregido)*. El inicio del bloque
   usaba `Math.floor(rnd() · (n − block))`, que produce índices máximos
   `start+b ≤ n−2`: **la última observación histórica nunca se muestreaba**. Se
   cambió a `Math.max(1, n − block + 1)`, de modo que un bloque pueda terminar en
   `n−1`. Impacto cuantitativo: **marginal** (excluía 1 de ~500 observaciones),
   pero ahora el muestreo cubre **toda** la serie. (`forecast.ts`, bucle de
   simulación.)

No se hallaron errores en: la agregación por trayectoria (#1), el cálculo de
percentiles sobre totales (#9–10), la probabilidad de pérdida (#11), la
suma a 100% de la contribución al riesgo, ni la separación histórico/neutral.

---

## Separación de modos y disciplina

- **Histórico vs. Neutral** están separados por el parámetro `drift` de
  `ForecastOpts`; el neutral resta la media por activo. La UI (`Proyección`)
  permite alternar y comparar.
- **No se usan los modelos experimentales A/B/C** en ninguna parte de este
  motor. Es una simulación de la distribución **histórica**, etiquetada
  explícitamente como tal — **no una predicción calibrada**; los percentiles son
  rango de resultados históricos, no probabilidades predictivas calibradas.
