# Validación empírica de EODHD (independiente — no es el conector productivo)

Comprueba con datos REALES si EODHD da acceso a los fundamentales que GIIC necesita, con qué
cobertura/actualidad, y si mejora la cobertura **vigente (B)** frente a EDGAR. No contrata, no toca
el núcleo de GIIC, no inicia Fair Value.

## Requisitos
- Python 3 (solo biblioteca estándar; sin `pip install`).
- `EODHD_API_KEY` en el entorno (clave gratuita/trial o de pago).
- `EDGAR_USER_AGENT="giic tu@correo"` (opcional) para el contraste oficial contra EDGAR.

## Uso
```bash
python3 validate_eodhd.py --selftest          # prueba el pipeline con fixtures (sin red ni clave)
export EODHD_API_KEY=xxxxx                     # tu clave
export EDGAR_USER_AGENT="giic tu@correo"       # opcional (habilita contraste EDGAR)
python3 validate_eodhd.py                       # informe markdown a stdout
python3 validate_eodhd.py --json salida.json    # además guarda el detalle en JSON
```

## Seguridad de credenciales
- La clave se lee SOLO de la variable de entorno `EODHD_API_KEY`. **Nunca** se escribe en disco ni
  en logs: las URLs se redactan (`api_token=***`) antes de imprimirse o de aparecer en errores.
- No pongas la clave en el repo ni la pegues en el chat. El `.gitignore` de esta carpeta ignora
  `.env`, `*.key` y `*.json` de salida.
- Si falta la clave, el script no consulta nada y lo informa.

## Qué valida (los 9 prioritarios: ASML, TSM, SAP, NVO, AZN, BABA, V, MA, MU)
1. **Acceso real**: primero prueba `AAPL.US`; no asume que la clave habilita fundamentales. Si da
   402/403 u otro bloqueo, lo reporta como **BLOQUEO** y lista alternativas, sin inventar cifras.
2. **Cobertura anual y trimestral**, último período disponible y **fecha de publicación** (filing_date)
   por estado.
3. **Moneda de reporte** (se consulta el símbolo del mercado local para ver la divisa real) y
   **ratio ADR** por emisor.
4. Los **9 campos**: revenue, net_income, EPS diluido, acciones diluidas, OCF, CAPEX, FCF, cash,
   deuda total.
5. **Contraste contra EDGAR** del último anual (revenue/NI/EPS) → clasifica
   **verificado / inconsistente / parcial / ausente** (parcial = presente sin contraste directo,
   p. ej. moneda distinta).
6. **Actualidad**: marca si EODHD trae un período más reciente que EDGAR (señal de mejora de B).
7. Recordatorio de **licencia** (uso personal vs comercial) a verificar en el ToS de EODHD.

## Dónde ejecutarlo
Este contenedor de desarrollo **no puede alcanzar `eodhd.com`** (allowlist) y no tiene clave, por lo
que aquí solo se validó con `--selftest`. Para la prueba real:
- **Opción A — local**: córrelo en una máquina con internet y tu clave (lo anterior). Entrega el
  informe que imprime.
- **Opción B — CI**: se puede añadir un workflow de solo lectura que lea `EODHD_API_KEY` como secreto
  del repo. Requiere un pequeño cambio en `main` (el workflow), que NO se hará sin tu aprobación.

## Estimación de mejora de B
El informe solo afirma mejora sobre los emisores **efectivamente comprobados**; no extrapola al resto
de los 63 sin probarlos.
