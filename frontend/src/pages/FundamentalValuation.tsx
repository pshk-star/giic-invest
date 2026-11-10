// P1.9 — Página de valoración fundamental (experimental, bajo feature flag). Solo lectura.
import { useEffect, useState } from "react";
import { FundamentalValuationView } from "../components/FundamentalValuationView";
import { getFundamentalValuations } from "../data";
import type { FundValPayload } from "../core/fundval";

export function FundamentalValuation() {
  const [data, setData] = useState<FundValPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getFundamentalValuations()
      .then(setData)
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8 text-term-muted">Cargando valoración fundamental…</div>;
  if (err) return <div className="p-8 text-rose-400">Error: {err}</div>;
  if (!data || Object.keys(data.resultados).length === 0)
    return <div className="p-8 text-term-muted">Sin valoraciones fundamentales disponibles todavía.</div>;
  return (
    <div className="p-4 md:p-6">
      <FundamentalValuationView data={data} />
    </div>
  );
}
