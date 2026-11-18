import { expect, it } from 'vitest';
import { latestValuations } from './valuation-feed';
import universe from '../../../backend/app/jobs/valuation_universe.json';
it('expired publication cannot retain a current FV (reproduced red on 8f11b3d)',()=>{
 const now=Date.parse('2026-11-18T12:00:00Z');
 const rows=universe.tickers.map(ticker=>({id:1,run_id:'A',ticker,payload:{ticker,status:'consistente',run_kind:'full',run_id:'A',audit_inputs:{price_date:'2026-11-18'},ttm:{fin_ttm:'2026-09-30'},modelos:[{modelo:'motor_v2',fair_value_usd:308.8,status:'consistente'}]}}));
 const d=latestValuations(rows,{run_id:'A',run_kind:'full',universe_version:universe.version,requested_tickers:universe.tickers,published_at:'2026-11-01T00:00:00Z'},now);
 expect(d.resultados.TSM?.modelos.some(m=>m.fair_value_usd!=null)).toBeFalsy();
});
