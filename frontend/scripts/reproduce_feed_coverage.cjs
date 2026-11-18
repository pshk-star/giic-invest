// Read-only reproduction against actual git source, rather than a rewritten legacy algorithm.
// Run from frontend: node scripts/reproduce_feed_coverage.cjs [baseline SHA]
const {execFileSync}=require('node:child_process');
const {readFileSync}=require('node:fs');
const {createRequire}=require('node:module');
const vm=require('node:vm');
const ts=require('typescript');
const path=require('node:path');
const root=path.resolve(__dirname,'../..');
const filename=path.join(root,'frontend/src/core/valuation-feed.ts');
const baseline=process.argv[2]||'3cb8aa0ef20fc136cd82906d4d8ceed95d4ab977';
function load(source){
 const output=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,esModuleInterop:true}}).outputText;
 const exports={};vm.runInNewContext(output,{exports,require:createRequire(filename),Date,Number,console});return exports;
}
const before=load(execFileSync('git',['show',baseline+':frontend/src/core/valuation-feed.ts'],{cwd:root,encoding:'utf8'}));
const after=load(readFileSync(filename,'utf8'));
const universe=require('../../backend/app/jobs/valuation_universe.json');
const now=Date.parse('2026-11-18T12:00:00Z');
const old=universe.tickers.map(ticker=>({ticker,run_id:'OLD',payload:{ticker,status:'consistente',audit_inputs:{price_date:'2026-11-18'},ttm:{fin_ttm:'2026-09-30'},modelos:[{modelo:'motor_v2',fair_value_usd:100}]}}));
const prefix=universe.tickers.slice(0,11).map(ticker=>({ticker,run_id:'NEW',payload:{ticker,status:'no_valorable',modelos:[]}}));
const manifest={run_id:'NEW',run_kind:'full',universe_version:universe.version,requested_tickers:universe.tickers,published_at:'2026-11-18T11:00:00Z'};
const count=d=>Object.values(d.resultados).filter(v=>v.modelos.some(m=>m.fair_value_usd>0)).length;
const result={baseline,omitted_old_fv_before:count(before.latestValuations([...prefix,...old])),omitted_old_fv_after:count(after.latestValuations([...prefix,...old],manifest,now)),expired_fv_before:count(before.latestValuations(old)),expired_fv_after:count(after.latestValuations(old,{...manifest,run_id:'OLD',published_at:'2026-11-01T00:00:00Z'},now))};
console.log(JSON.stringify(result,null,2));
if(result.omitted_old_fv_before!==27||result.omitted_old_fv_after!==0||result.expired_fv_before!==38||result.expired_fv_after!==0)process.exitCode=1;
