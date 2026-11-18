import { it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FundamentalValuationView } from "../components/FundamentalValuationView";

it("renders backend object scenarios and legacy numeric scenarios without recalculating FV", () => {
  for (const objectShape of [true,false]) {
    const point = (v:number) => objectShape ? {fv_usd:v,margen:-.1,supuestos:"fixture"} : v;
    const html = renderToStaticMarkup(createElement(FundamentalValuationView, {data:{resultados:{
      TEST: {ticker:"TEST",ccy:"USD",precio:100,gT_pct:2.5,status:"en_revision",modelos:[{
        modelo:"motor_v2",fair_value_usd:90,confianza:"baja",
        escenarios:{conservador:point(81),base:point(91),optimista:point(101)}
      }]}
    }}}));
    expect(html).toContain("81");
    expect(html).toContain("91");
    expect(html).toContain("101");
    expect(html).not.toContain("[object Object]");
    expect(html).not.toContain("NaN");
  }
});
