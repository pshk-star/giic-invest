import { describe, it, expect, vi } from "vitest";
import { latestValuations, readGoverningFeed, valuationInput, type ValuationRun } from "./valuation-feed";
import { governingValuation, passesValueGate } from "./valuation-policy";
import universe from '../../../backend/app/jobs/valuation_universe.json';
const now = Date.parse('2026-11-18T12:00:00Z');
const run: ValuationRun = {run_id:'A',run_kind:'full',universe_version:universe.version,
 requested_tickers:universe.tickers,published_at:'2026-11-18T10:00:00Z'};
const cv = (ticker: string): any => ({ticker,status:'en_revision',audit_inputs:{price_date:'2026-11-18'},
 ttm:{fin_ttm:'2026-09-30'},modelos:[{modelo:'motor_v2',status:'en_revision',fair_value_usd:308.8,
 margen_seguridad_pct:-23.8,confianza:'baja',metodologia_validada:false}]});
const rows = () => universe.tickers.map(ticker=>({ticker,run_id:'A',payload:cv(ticker)}));
describe('P0-A governing publication coverage and freshness',()=>{
 it('admits precisely 38 dated valuations with one governing source',()=>{
  const d=latestValuations(rows(),run,now);
  expect(Object.keys(d.resultados)).toHaveLength(38);
  expect(governingValuation(valuationInput(d.resultados.TSM)).margin).toBeCloseTo(-.238,12);
  expect(passesValueGate(valuationInput(d.resultados.TSM),.1)).toBe(false);
 });
 it('a new complete tombstone supersedes an older positive FV',()=>{
  const r=rows(); r.find(r=>r.ticker==='TSM')!.payload={ticker:'TSM',status:'no_valorable',modelos:[]};
  const d=latestValuations([...r,{ticker:'TSM',run_id:'OLD',payload:cv('TSM')}],run,now);
  expect(valuationInput(d.resultados.TSM).engineMargin).toBeNull();
 });
 it('an omitted ticker invalidates the incomplete publication, never resurrecting old data',()=>{
  const r=rows().filter(r=>r.ticker!=='TSM');
  const d=latestValuations([...r,{ticker:'TSM',run_id:'OLD',payload:cv('TSM')}],run,now);
  expect(Object.values(d.resultados).every(v=>v.status==='no_valorable')).toBe(true);
 });
 it('duplicate rows and incomplete manifests fail closed',()=>{
  for(const [r,m] of [[rows().concat(rows()[0]),run],[rows(),{...run,requested_tickers:['TSM']}]] as const)
   expect(latestValuations([...r],m,now).resultados.TSM.status).toBe('no_valorable');
 });
 it('five-ticker partial diagnostics cannot replace or invalidate any of the 38 full valuations',()=>{
  const partial=rows().slice(0,5).map(r=>({...r,run_id:'PART',payload:{...r.payload,status:'no_valorable',modelos:[]}}));
  const d=latestValuations([...partial,...rows()],run,now);
  expect(Object.values(d.resultados).filter(v=>v.status==='en_revision')).toHaveLength(38);
  expect(latestValuations(partial,{...run,run_kind:'partial'},now).resultados.TSM.status).toBe('no_valorable');
 });
 it('legacy rows without a manifest never govern',()=>{
  expect(latestValuations(rows(),undefined,now).resultados.TSM.status).toBe('no_valorable');
 });
 it.each(['2026-11-14T11:59:59Z','2026-11-19T00:00:00Z','bad'])('rejects stale/future/invalid publication date %s',published_at=>{
  expect(latestValuations(rows(),{...run,published_at},now).resultados.TSM.status).toBe('no_valorable');
 });
 it('admits the exact publication expiry boundary, then expires',()=>{
  expect(latestValuations(rows(),{...run,published_at:'2026-11-14T12:00:00Z'},now).resultados.TSM.status).toBe('en_revision');
  expect(latestValuations(rows(),{...run,published_at:'2026-11-14T12:00:00Z'},now+1).resultados.TSM.status).toBe('no_valorable');
 });
 it.each([['price','2026-11-10'],['price',undefined],['price','2026-11-19'],['ttm','2026-01-01'],['ttm',undefined],['ttm','2027-01-01']])('invalidates %s date %s without affecting other issuers',(field,date)=>{
  const r=rows(); const t=r.find(r=>r.ticker==='TSM')!;
  if(field==='price') t.payload.audit_inputs.price_date=date; else t.payload.ttm.fin_ttm=date;
  const d=latestValuations(r,run,now);
  expect(d.resultados.TSM.status).toBe('no_valorable');
  expect(d.resultados.ASML.status).toBe('en_revision');
 });
 it('provider failure tombstones remain explicit without requiring input dates',()=>{
  const r=rows();r[0].payload={ticker:r[0].ticker,status:'no_valorable',modelos:[]};
  expect(latestValuations(r,run,now).resultados[r[0].ticker].status).toBe('no_valorable');
 });
 it('malformed payload fails closed for that issuer',()=>{
  const r=rows();r.find(r=>r.ticker==='TSM')!.payload.modelos='bad';
  expect(latestValuations(r,run,now).resultados.TSM.precio).toBeNull();
 });
 it('cached admissible valuations expire before a subsequent Advisor decision',()=>{
  const d=latestValuations(rows(),run,now);
  expect(valuationInput(d.resultados.TSM,now).engineMargin).not.toBeNull();
  expect(valuationInput(d.resultados.TSM,now+97*3600000).engineMargin).toBeNull();
 });
 it('cached Advisor inputs cannot buy or recommend a sale after expiry without reloading the feed',()=>{
  const r=rows();
  const t=r.find(r=>r.ticker==='TSM')!;
  t.payload.status='consistente';
  Object.assign(t.payload.modelos[0],{status:'consistente',metodologia_validada:true,confianza:'alta',margen_seguridad_pct:20});
  const clock=vi.spyOn(Date,'now').mockReturnValue(now);
  try {
   const input=valuationInput(latestValuations(r,run,now).resultados.TSM,now);
   expect(passesValueGate(input,.1)).toBe(true);
   clock.mockReturnValue(now+97*3600000);
   expect(passesValueGate(input,.1)).toBe(false);
   expect(governingValuation(input).margin).toBeNull();
   expect(governingValuation({...input,engineMargin:-.3}).blocked).toBe(true);
  }finally{clock.mockRestore();}
 });
 it('pins an immutable manifest before reading only its rows',async()=>{
  const requests: any[]=[];
  const d=await readGoverningFeed(async(table,params)=>{requests.push([table,params]);return table==='valuation_runs'?[run]:rows();},now);
  expect(requests[0][1]).toMatchObject({run_kind:'eq.full',limit:'1',order:'id.desc'});
  expect(requests[1][1].run_id).toBe('eq.A');
  expect(d.resultados.TSM.status).toBe('en_revision');
 });
 it('a row transport failure propagates; there is no cache/legacy fallback',async()=>{
  await expect(readGoverningFeed(async table=>{if(table==='valuation_runs')return [run];throw Error('offline');},now)).rejects.toThrow('offline');
 });
});
