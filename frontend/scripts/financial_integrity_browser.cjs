const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const path = require('node:path');
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
 const invalid={ticker:'NVDA',ccy:'USD',precio:50,status:'no_valorable',modelos:[{modelo:'motor_v2',disponible:false,status:'no_valorable',metodologia_validada:false,fair_value_usd:null,review_reasons:['fixture invalidation']}]};
 await page.route('https://example.supabase.co/**',async route=>{
  const u=new URL(route.request().url());let body=[];
  if(u.pathname.includes('/auth/')) body={id:uid,email:'fixture@example.test',aud:'authenticated'};
  if(u.pathname.endsWith('/settings')) body=[{user_id:uid,base_currency:'USD',risk_tolerance:'moderado',monthly_contribution:3000,capital_available:3000,min_cash:0,horizon_years:10}];
  if(u.pathname.endsWith('/transactions')) body=[{id:'1',user_id:uid,ticker:'NVDA',side:'buy',qty:40,quantity:40,price:50,fees:0,currency:'USD',executed_at:'2026-01-02',trade_date:'2026-01-02',date:'2026-01-02',type:'buy'}];
  if(u.pathname.endsWith('/instruments')) body=[{ticker:'NVDA',name:'Fixture NVDA',currency:'USD',asset_class:'equity',sector:'Tech',status:'active'}];
  if(u.pathname.endsWith('/prices')) body=[{ticker:'NVDA',close:50,currency:'USD',as_of:'2026-11-13'}];
  if(u.pathname.endsWith('/valuation_snapshots')) body=u.searchParams.get('select')==='id'?[{id:2}]:[{id:2,ticker:'NVDA',payload:invalid},{id:1,ticker:'NVDA',payload:{...invalid,status:'consistente',modelos:[{modelo:'motor_v2',status:'consistente',fair_value_usd:500,margen_seguridad_pct:900,metodologia_validada:true,confianza:'alta'}]}}];
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body),headers:{'access-control-allow-origin':'*'}});
 });
 for(const path of ['/advisor','/asesor','/scanner','/advisor3','/research/NVDA','/fundamental','/p30']){
  await page.goto('http://127.0.0.1:5174'+path);await page.waitForTimeout(400);
  const text=await page.locator('body').innerText();
  if(/Error:|ReferenceError|TypeError/.test(text))failures.push(path+': '+text.slice(0,300));
  if(['/advisor','/asesor','/advisor3'].includes(path)&&(!text.includes('NVDA')||!text.includes('REVISAR')))failures.push(path+' missing blocked position');
  if(path==='/research/NVDA'&&!text.includes('fixture invalidation'))failures.push('research did not show governing invalidation');
  if(/COMPRAR|ACUMULAR/.test(text)&&/900%/.test(text))failures.push(path+' resurrected stale FV');
  console.log(path, text.slice(0,140).replace(/\n/g,' | '));
 }
 console.log('BROWSER_FAILURES',JSON.stringify(failures));if(failures.length)process.exitCode=1;
 } finally {if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
