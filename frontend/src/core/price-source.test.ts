import { describe, expect, it } from "vitest";
import { mergeValuation, type QuoteLike } from "./price-source";
import type { PriceInfo } from "./portfolio-tx";

const eod: Record<string, PriceInfo> = {
  AAPL: { close: 100, as_of: "2026-11-04", currency: "USD" },
  MSFT: { close: 200, as_of: "2026-11-04", currency: "USD" },
};
const q = (over: Partial<QuoteLike>): QuoteLike => ({
  price: 110, previous_close: 105, quote_time: "2026-11-05T15:30:00Z",
  market_state: "REGULAR", delayed: true, currency: "USD", ...over,
});
const NOW = Date.parse("2026-11-05T15:35:00Z");

describe("mergeValuation (fuente de precios unificada)", () => {
  it("prioriza la cotización sobre el cierre EOD y marca mixto", () => {
    const { prices, meta } = mergeValuation(["AAPL", "MSFT"], eod, { AAPL: q({}) }, NOW);
    expect(prices.AAPL.close).toBe(110);
    expect(prices.MSFT.close).toBe(200);
    expect(meta.kind).toBe("mixed");
    expect(meta.nQuotes).toBe(1);
    expect(meta.nEod).toBe(1);
    expect(meta.anyDelayed).toBe(true);
  });

  it("todo intradía cuando el mercado está abierto", () => {
    const { meta } = mergeValuation(["AAPL", "MSFT"],
      eod, { AAPL: q({}), MSFT: q({ price: 205 }) }, NOW);
    expect(meta.kind).toBe("intraday");
    expect(meta.freshness).toBe("live");
    expect(meta.source).toBe("quotes");
  });

  it("cierre cuando el mercado está cerrado", () => {
    const { meta } = mergeValuation(["AAPL"],
      eod, { AAPL: q({ market_state: "CLOSED" }) }, NOW);
    expect(meta.kind).toBe("close");
    expect(meta.asOfTs).toBe("2026-11-05T15:30:00Z");
  });

  it("solo EOD cuando no hay cotizaciones", () => {
    const { prices, meta } = mergeValuation(["AAPL", "MSFT"], eod, {}, NOW);
    expect(prices.AAPL.close).toBe(100);
    expect(meta.kind).toBe("close");
    expect(meta.source).toBe("eod");
    expect(meta.asOfDate).toBe("2026-11-04");
  });

  it("ignora cotizaciones con precio inválido y cae a EOD", () => {
    const { prices, meta } = mergeValuation(["AAPL"], eod, { AAPL: q({ price: 0 }) }, NOW);
    expect(prices.AAPL.close).toBe(100);
    expect(meta.nEod).toBe(1);
    expect(meta.nQuotes).toBe(0);
  });

  it("sin datos devuelve source none", () => {
    const { meta } = mergeValuation(["TSLA"], {}, {}, NOW);
    expect(meta.source).toBe("none");
    expect(meta.kind).toBe("none");
  });
});
