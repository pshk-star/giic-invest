const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const path = require('node:path');
const universe = require('../../backend/app/jobs/valuation_universe.json');
(async()=>{
 const server=spawn(process.execPath,[path.join(process.cwd(),'node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port','5174','--strictPort'],{
  env:{...process.env,VITE_SUPABASE_URL:'https://example.supabase.co',VITE_SUPABASE_ANON_KEY:'fixture',VITE_FF_UNIFIED:'1',VITE_FF_SCANNER:'1',VITE_FF_ADVISOR3:'1',VITE_FF_FUNDVAL:'1',VITE_FF_P30:'1'},stdio:'ignore'});
 let browser;
 try {
 for(let i=0;i<100;i++){try{const r=await fetch('http://127.0.0.1:5174');if(r.ok)break;}catch{} await new Promise(r=>setTimeout(r,100));}

 browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE_PATH,headless:true,args:['--no-sandbox']});
 const page=await browser.newPage(); const failures=[];page.on('pageerror',e=>failures.push(e.message));
 const uid='00000000-0000-0000-0000-000000000001';
 const enc=x=>Buffer.from(JSON.stringify(x)).toString('base64url');
 const token=enc({alg:'HS256',typ:'JWT'})+'.'+enc({sub:uid,role:'authenticated',aud:'authenticated',exp:Math.floor(Date.now()/1000)+3600})+'.test';
 await page.addInitScript(({token,uid})=>localStorage.setItem('sb-example-auth-token',JSON.stringify({access_token:token,refresh_token:'fixture',expires_at:Math.floor(Date.now()/1000)+3600,expires_in:3600,token_type:'bearer',user:{id:uid,aud:'authenticated',email:'fixture@example.test'}})),{token,uid});
 let scenario='invalidation';
 const today=new Date().toISOString().slice(0,10);
 const invalid={ticker:'NVDA',ccy:'USD',precio:50,status:'no_valorable',modelos:[{modelo:'motor_v2',disponible:false,status:'no_valorable',metodologia_validada:false,fair_value_usd:null,review_reasons:['fixture invalidation']}]};
 await page.route('https://example.supabase.co/**',async route=>{
  const u=new URL(route.request().url());let body=[];
  if(u.pathname.includes('/auth/')) body={id:uid,email:'fixture@example.test',aud:'authenticated'};
  if(u.pathname.endsWith('/settings')) body=[{user_id:uid,base_currency:'USD',risk_tolerance:'moderado',monthly_contribution:3000,capital_available:3000,min_cash:0,horizon_years:10}];
  if(u.pathname.endsWith('/transactions')) body=[{id:'1',user_id:uid,ticker:'NVDA',side:'buy',qty:40,quantity:40,price:50,fees:0,currency:'USD',executed_at:'2026-01-02',trade_date:'2026-01-02',date:'2026-01-02',type:'buy'}];
  if(u.pathname.endsWith('/instruments')) body=[{ticker:'NVDA',name:'Fixture NVDA',currency:'USD',asset_class:'equity',sector:'Tech',status:'active'}];
  if(u.pathname.endsWith('/prices')) body=[{ticker:'NVDA',close:50,currency:'USD',as_of:'2026-11-13'}];
  if(u.pathname.endsWith('/v_latest_scan')) body=[{ticker:'NVDA',rank:1,sector:'Tech',composite:99,factor_value:99,factor_quality:99,factor_growth:99,factor_momentum:99,tags:['value','quality']}];
  if(u.pathname.endsWith('/scan_runs')) body=[{status:'completed',as_of:today,evaluated:38,usable_factors:['value'],using_sample_data:false}];
  if(u.pathname.endsWith('/valuation_runs')) {
   if(scenario==='transport') {await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'fixture provider unavailable'})});return;}
   body=[{id:2,run_id:'R2',run_kind:'full',universe_version:universe.version,requested_tickers:universe.tickers,
    published_at:new Date(Date.now()-(scenario==='expired'?97:1)*3600000).toISOString()}];
  }
  if(u.pathname.endsWith('/valuation_snapshots')) {
   const current=universe.tickers.map((ticker,i)=>({id:i+2,run_id:'R2',ticker,payload:{...invalid,ticker,run_id:'R2',run_kind:'full'}}));
   // An old but extremely attractive FV must never leak into recommendations.
   const old={id:1,run_id:'R1',ticker:'NVDA',payload:{...invalid,status:'consistente',run_id:'R1',run_kind:'full',audit_inputs:{price_date:today},ttm:{fin_ttm:today},modelos:[{modelo:'motor_v2',status:'consistente',fair_value_usd:500,margen_seguridad_pct:900,metodologia_validada:true,confianza:'alta'}]}};
   if(scenario==='mixed') current[0].payload={...old.payload,run_id:'R2'};
   if(scenario==='expired') current.forEach(r=>{r.payload={...old.payload,ticker:r.ticker,run_id:'R2'};});
   body=u.searchParams.has('run_id')?current:[...current,old];
   if(u.searchParams.get('select')==='id')body=[{id:39}];
  }
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body),headers:{'access-control-allow-origin':'*'}});
 });
 for(const path of ['/command','/portfolio','/advisor','/asesor','/opportunities','/research','/scanner','/advisor3','/research/NVDA','/fundamental','/p30','/p30/oportunidades','/p30/oportunidades/NVDA','/p30/cartera','/p30/asignacion']){
  await page.goto('http://127.0.0.1:5174'+path);await page.waitForLoadState('networkidle');
  const text=await page.locator('body').innerText();
  if(/Error:|ReferenceError|TypeError/.test(text))failures.push(path+': '+text.slice(0,300));
  if(['/advisor','/asesor','/advisor3'].includes(path)&&(!text.includes('NVDA')||!text.includes('REVISAR')))failures.push(path+' missing blocked position');
  if(path==='/research/NVDA'&&!text.includes('fixture invalidation'))failures.push('research did not show governing invalidation: '+text.slice(-1200));
  if(/COMPRAR|ACUMULAR/.test(text)&&/900%/.test(text))failures.push(path+' resurrected stale FV');
  if(['/opportunities','/command','/research'].includes(path)){
   const note=page.getByTestId('opportunity-disclosure');
   if(await note.count()===0 || !/no accionable/i.test(await note.innerText()))failures.push(path+' missing non-actionable factor disclosure');
  }
  console.log(path, text.slice(0,140).replace(/\n/g,' | '));
 }
 // The same active pages must fail closed for stale publications and REST/provider failure.
 for(const mode of ['expired','transport','mixed']){
  scenario=mode;
  for(const path of (mode==='mixed'?['/opportunities']:['/advisor','/opportunities','/research/NVDA'])){
   await page.goto('http://127.0.0.1:5174'+path);await page.waitForLoadState('networkidle');
   const text=await page.locator('body').innerText();
   if(path==='/opportunities' && !/No accionable/.test(text))failures.push(mode+' actionable factor ranking');
   if(mode==='mixed'&&!/metodología bloqueada/.test(text))failures.push('one validated issuer incorrectly lifted global disclosure');
   if(mode!=='mixed'&&/900(?:[.,]0)?%/.test(text))failures.push(mode+' old FV leaked into '+path);
   if(mode==='expired'&&path==='/advisor'&&!text.includes('REVISAR'))failures.push('expired publication did not block Advisor');
   console.log(mode,path,text.slice(0,80).replace(/\n/g,' | '));
  }
 }
 console.log('BROWSER_FAILURES' ,JSON.stringify(failures));if(failures.length)process.exitCode=1;
 } finally {if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
