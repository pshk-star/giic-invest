import { useEffect, useState } from "react";
import { Panel } from "./Panel";
import { getFundamentalValuations } from "../data";
import { engineBlock, valuationInput } from "../core/valuation-feed";
import { governingValuation } from "../core/valuation-policy";
import { scenarioFv, type CompanyValuation } from "../core/fundval";
import { money } from "../format";

export function FairValue({ ticker }: { ticker: string }) {
  const [cv,setCv] = useState<CompanyValuation>();
  const [error,setError] = useState<string>();
  useEffect(() => {
    let live = true;
    setCv(undefined); setError(undefined);
    getFundamentalValuations().then(d => {if(live) setCv(d.resultados[ticker]);})
      .catch(e => {if(live) setError(String(e));});
    return () => { live = false; };
  }, [ticker]);
  const m = engineBlock(cv), g = governingValuation(valuationInput(cv));
  return <Panel title="Fair Value · motor gobernante">
    <div className="text-xl font-mono">{money(m?.fair_value_usd, "USD")}</div>
    <p className="text-sm text-term-muted">{error ?? (g.blocked ? g.blockReason : g.note)}</p>
    {m?.escenarios && <div className="grid grid-cols-3 gap-3 mt-3">
      {(["conservador","base","optimista"] as const).map(k => <div key={k}>
        <span className="text-xs">{k}</span><div>{money(scenarioFv(m.escenarios![k]),"USD")}</div>
      </div>)}
    </div>}
  </Panel>;
}
