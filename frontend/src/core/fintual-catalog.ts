// Catálogo de fondos Fintual México (fuentes públicas: rankia.mx, BMV, TwelveData).
// El valor cuota (NAV) se ingresa manualmente: no hay fuente gratuita confiable en tiempo
// real todavía. La clave BMV sirve para validar/confirmar; el NAV lo tomas de tu estado
// de cuenta Fintual o de BMV. Símbolo = identificador estable dentro de GIIC.
export interface FintualFund {
  symbol: string;
  name: string;
  currency: string;
  bmv?: string;     // clave de pizarra en BMV (confirmada)
  note?: string;
}

export const FINTUAL_MX_FUNDS: FintualFund[] = [
  { symbol: "PORTMANA", name: "Fintual Moderate Portman", currency: "MXN", bmv: "PORTMANA",
    note: "Renta variable moderada · clave BMV PORTMANA (verificada)" },
  { symbol: "RISKY-HAYEK", name: "Fintual Risky Hayek", currency: "MXN",
    note: "Portafolio agresivo · clave BMV por confirmar con tu estado de cuenta" },
  { symbol: "FT-LIQU", name: "Fintual Liquidez (Franklin Templeton deuda corto plazo)", currency: "MXN",
    note: "Fondo de liquidez/deuda · clave BMV por confirmar" },
];
