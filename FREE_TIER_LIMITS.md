# GIIC — Límites de los servicios gratuitos (verificado nov-2026)

Condiciones consultadas en nov-2026. **Cambian con el tiempo**: confirma en la
página oficial de cada servicio antes de depender de un límite. Ningún servicio de
esta lista exige tarjeta de crédito para el uso que hace GIIC. Donde un plan superior
sí la pediría, se indica.

## Cloudflare Pages (frontend)
- **Tarjeta:** no requerida para empezar.
- **Límites:** ancho de banda ilimitado para sitios estáticos; ~500 builds/mes;
  dominios personalizados y HTTPS incluidos; despliegues de preview ilimitados.
- **Al alcanzar el límite:** se pausan builds adicionales ese mes; el sitio ya
  publicado sigue en línea.
- **Inactividad:** no pausa el sitio.
- **Riesgo de continuidad:** bajo. URL `*.pages.dev` permanente.
- Fuente: resúmenes de planes gratuitos de hosting (sep-2026) y documentación de Cloudflare.

## Supabase (base de datos + auth)
- **Tarjeta:** no requerida en el plan Free.
- **Límites:** 500 MB de base de datos; 50,000 usuarios activos/mes (auth);
  ~5 GB de egreso/mes; 2 proyectos activos.
- **Inactividad:** el proyecto se **pausa tras 7 días sin actividad**. Mitigación:
  el scan diario (GitHub Actions) escribe en la BD y la mantiene activa. Si se
  pausa, se reactiva con un clic desde el dashboard (los datos no se pierden).
- **Al alcanzar el límite:** operaciones de escritura/almacenamiento pueden
  bloquearse hasta liberar espacio o subir de plan (de pago).
- **Riesgo de continuidad:** medio (la pausa por inactividad es el punto a vigilar).
- Fuente: guías de free tier de Supabase 2026 (500 MB / 50k MAU / pausa a 7 días);
  confirmar en supabase.com/pricing.

## GitHub (código + Actions)
- **Tarjeta:** no requerida.
- **Límites:** en **repos públicos**, minutos de Actions **ilimitados** (usado aquí).
  En repos privados, 2,000 min/mes gratis. Por eso se recomienda repo **público de
  solo código** (sin secretos ni datos).
- **Cron:** los workflows programados pueden **deshabilitarse tras ~60 días sin
  commits** en el repo, y ocasionalmente el cron se retrasa en horas pico.
  Mitigación: ejecución manual disponible y cualquier commit reactiva el cron.
- **Al alcanzar el límite (repos privados):** las Actions se detienen hasta el
  siguiente ciclo; repo público evita esto.
- **Riesgo de continuidad:** bajo con repo público.
- Fuente: documentación de billing de GitHub Actions; reportes de comunidad sobre
  cron deshabilitado por inactividad.

## Stooq (precios EOD)
- **Clave/tarjeta:** no.
- **Datos:** OHLC + volumen diarios (EOD) de acciones/ETF US e índices; histórico amplio.
- **Frecuencia:** fin de día.
- **Límites:** sin API formal; uso razonable. Puede limitar por volumen de descargas.
- **Restricciones:** uso personal; **no redistribuir** los datos.
- **Riesgo de continuidad:** medio (servicio informal, sin SLA).

## SEC EDGAR (fundamentales US)
- **Clave/tarjeta:** no. Exige **User-Agent con correo de contacto** (política SEC).
- **Datos:** fundamentales oficiales de las presentaciones (ingresos, utilidad,
  patrimonio, flujo de caja, EPS, acciones). US solamente.
- **Frecuencia:** al ritmo de las presentaciones (trimestral/anual).
- **Límites:** ~10 solicitudes/seg.
- **No disponible aquí (queda en None, no se inventa):** P/E forward, EV/EBITDA, ROIC.
- **Riesgo de continuidad:** bajo (fuente oficial gubernamental).

## Frankfurter (tipos de cambio)
- **Clave/tarjeta:** no. Sin límite de consultas documentado.
- **Datos:** tasas del BCE (cierre diario).
- **Riesgo de continuidad:** bajo-medio (proyecto abierto).

---

## Qué perdemos respecto a una versión de pago
- **Sin intradía ni tiempo real:** solo cierre de mercado (es lo preferido para
  decisiones, pero no sirve para trading intradía).
- **Cobertura US:** no mundial. Fundamentales solo de emisores SEC (US).
- **Sin holdings de ETF automáticos:** el look-through usa los holdings que cargues
  o los que se agreguen manualmente; si faltan, se marca (no se inventa).
- **Universo acotado** (~90 nombres líquidos) para respetar límites gratuitos;
  ampliable con una estrategia escalonada de actualización.
- **Fundamentales parciales:** faltan P/E forward, EV/EBITDA y ROIC (no gratuitos
  de forma fiable); el scanner reponderra los factores con cobertura suficiente.
