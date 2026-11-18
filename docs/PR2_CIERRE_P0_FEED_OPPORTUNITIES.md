# PR #2 — cierre P0-A y P0-B

## Alcance y política adoptada

Se conserva el trabajo de Claude en `563d99b` y `8f11b3d`, encontrado en la rama remota después de `3cb8aa0`. Este cierre añade controles transaccionales y caducidad; no modifica el motor financiero, los supuestos económicos ni los fixtures de replay. No resuelve los P1/P2 pendientes.

**Una única corrida completa gobierna todo el universo.** `valuation_universe.json` define `giic-38-v1` y sus 38 tickers. La última publicación `full` admitida es la única fuente gobernante. Las publicaciones `partial` son diagnósticos inmutables: no actualizan ni invalidan ningún FV gobernante, incluidos los cinco tickers de una prueba. Para promover resultados es necesario completar una corrida de 38. Esta decisión evita mezclar fechas, universos y cálculos parciales.

La corrida predeterminada del CLI/workflow ahora cubre 38, no 11. Una lista explícita `--tickers` produce un diagnóstico parcial; `--full` con una lista incompleta falla antes de consultar proveedores. Una petición vacía explícita falla de forma controlada.

Vigencia, medida en tiempo UTC transcurrido:

| Control | Máximo inclusivo | Si falla |
|---|---:|---|
| Publicación completa | 96 horas desde `published_at` del servidor SQL | Todo el feed sin FV vigente |
| Precio de cada emisor | 7 días desde `audit_inputs.price_date` | Emisor `no_valorable`, sin FV vigente |
| Último cierre TTM | 185 días desde `ttm.fin_ttm` | Emisor `no_valorable`, sin FV vigente |

Son límites operativos de admisión, no supuestos de valoración. 96 horas toleran fines de semana; 7 días impiden precios indefinidamente arrastrados; 185 días son un techo conservador para un TTM trimestral. No verifican que no exista un informe fiscal más reciente (esa comparación con fuentes y la antigüedad del balance son trabajo pendiente). Fechas ausentes, inválidas o futuras bloquean. El historial y los resultados brutos calculados permanecen intactos. El objeto admitido tiene además `feed_valid_until`: el adaptador de Advisor vuelve a comprobarlo si se reutiliza posteriormente.

## Publicación, fallo y recuperación

`0014_valuation_run_coverage.sql` es aditiva sobre 0013: conserva sus filas y crea manifiestos inmutables en `valuation_runs`. No se adjudica vigencia retroactiva a los registros anteriores sin manifiesto.

`publish_valuations(uuid,jsonb,jsonb)` valida versión, clase de corrida, conjuntos exactos solicitado/producido, duplicados y correspondencia payload/ticker/run_id/run_kind. Una corrida `full` exige exactamente los 38 tickers canónicos. El manifiesto y todas las filas se insertan bajo el mismo lock y transacción. No existe estado publicado a medias. Reintentar idéntico run_id devuelve cero; cambiar payload o manifiesto es rechazado. El RPC anterior de dos argumentos se elimina y se revoca INSERT directo de service_role; solo el RPC autorizado publica. Autenticados leen mediante RLS y no pueden publicar ni modificar historial. La función SECURITY DEFINER usa relaciones calificadas y search_path restringido. Se revocan explícitamente permisos heredados de default privileges de Supabase sobre tablas, secuencias y RPC (incluidos anon/authenticated), no solo PUBLIC. También se deniega TRUNCATE y setval a service_role. Una prueba con esos permisos predeterminados reprodujo un acceso indebido antes de la revocación explícita y ahora exige que sea rechazado.

Cada ticker termina en valoración o resultado explícito `no_valorable`. Un error por emisor emite una invalidación con causa; no conserva su FV anterior. Una interrupción antes de publicar no produce manifiesto ni filas. Un fallo de publicación devuelve error y salida CLI 1, sin un reconocimiento de éxito. Una respuesta de red perdida después del commit no permite afirmar rollback: un retry del mismo run_id/payload es seguro; la integridad sigue siendo todo o nada.

Un intento fallido no se presenta como una nueva corrida completa. La corrida completa anterior solo sigue admitida hasta su propio vencimiento; ni un fallo ni una prueba parcial renuevan su reloj. Si no hay publicación completa admitida, las 38 empresas quedan explícitamente bloqueadas. El lector fija primero run_id y luego consulta exclusivamente sus filas; una publicación concurrente no puede mezclarse. Una omisión defensivamente detectada en una publicación invalida todo ese feed y nunca activa fallback histórico.

## Rutas activas

`/opportunities` mantiene su ranking factorial como información independiente y **nunca accionable por sí sola**, incluso si la metodología llegara a validarse. Consume el mismo feed y evalúa el estado mediante `governingValuation(valuationInput(...))`. Una sola empresa que declare metodología validada no levanta el aviso para todas. Ante error del feed se conserva el bloqueo. Dashboard y Research también identifican sus rankings factoriales como no accionables (commits de Claude preservados).

`data.ts` y el preview de Advisor usan `readGoverningFeed`; no consultan versiones anteriores para completar huecos. No se alteran precios de cartera, compras registradas ni simulaciones manuales.

## Reproducciones antes/después

Contra el código real de `3cb8aa0ef20fc136cd82906d4d8ceed95d4ab977`:

```bash
node frontend/scripts/reproduce_feed_coverage.cjs
```

El script extrae el módulo original con `git show`, lo transpila y ejecuta junto al módulo actual, sin cambiar de rama ni acceder a producción. Requiere disponer del commit original en el clon.

| Reproducción | Antes | Después |
|---|---:|---:|
| 38 valores anteriores + nueva corrida de 11; FV antiguos que sobreviven | 27 | 0 |
| Publicación caducada con 38 FV positivos; FV vigentes | 38 | 0 |

La primera reproducción simula un feed incompleto para probar la defensa del lector; además, PostgreSQL rechaza publicar esos 11 como `full`. Una publicación parcial legítima de cinco se conserva separadamente y las 38 valoraciones gobernantes permanecen sin alteración mientras sigan vigentes.

Prueba de navegador ejecutada también contra un archivo temporal del SHA original, con el mismo script y servicios simulados:

- Antes: `/opportunities` carecía de `opportunity-disclosure`; también Dashboard y Research. La publicación caducada dejaba aparecer el 900% de margen en Advisor y Research; Advisor no quedaba en REVISAR.
- Después: las rutas tienen el aviso no accionable y no recuperan el 900%; la caducidad bloquea Advisor. Un REST 503 mantiene `/opportunities` informativa, sin levantar el bloqueo. También se prueba una sola empresa validada frente al resto bloqueado.

La hipótesis de omisión silenciosa por proveedores no se observó en una ejecución real nueva. Se reprodujeron sus desencadenantes mediante inyección: RuntimeError por ticker, proveedor caído, instrumento/precio ausente, interrupción en el segundo emisor y fallo global de lectura. Las pruebas exigen resultado explícito para cada solicitado o aborto sin publicación. No se presenta la inyección como evidencia de que un proveedor real haya omitido ese ticker.

## Verificación local

```bash
cd backend
python -m pytest -q --ignore=tests/integration
cd ../frontend
npm test
npm run build
CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm run test:browser
```

- Backend: 493 passed, 1 skipped; incluye replay independiente de NVDA, TSM, META, PFE y ASML sin modificar sus resultados esperados.
- Frontend: 344 passed / 35 archivos; TypeScript y build Vite correctos (solo aviso existente de tamaño del bundle). CI se enlaza en el PR.
- PostgreSQL real en WASM/PGlite: migraciones 0013 + 0014, permisos de ambos roles, cobertura exacta, parciales, retries, historial inmutable y rollback después de insertar el manifiesto mediante fallo de almacenamiento inyectado.
- Chromium: 15 rutas activas, más caducidad, REST 503 y metodología mixta (22 visitas en total), contra servicios simulados; no es una prueba de la producción desplegada.

## Estado y futura activación

No se aplicaron migraciones ni se ejecutó `--write` contra producción. No se hizo merge ni despliegue. Main se verificó en `5c4f6e3d7531a4d0cb477fca283776980194b705` antes y después del trabajo.

Tras revisión y autorización de despliegue habrá que aplicar 0013 y después 0014, coordinar el lector/escritor nuevo y publicar una corrida completa de 38. Los escritores antiguos de dos argumentos fallarán de forma controlada después de 0014. El nuevo frontend falla cerrado si todavía no existe 0014 o una corrida completa admitida. No debe etiquetarse historial previo como nuevo para ocultar su antigüedad. El job es manual: si no se renueva la publicación antes de 96 horas, el bloqueo por caducidad es el comportamiento esperado.
