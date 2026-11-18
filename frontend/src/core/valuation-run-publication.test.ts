import { expect,it } from 'vitest';
import { PGlite } from '@electric-sql/pglite';
import { readFileSync } from 'node:fs';
import universe from '../../../backend/app/jobs/valuation_universe.json';
it('0014: exact coverage, atomicity, RLS, immutable manifests and idempotent retries',async()=>{
 const db=new PGlite();
 try{
  await db.exec('create role anon; create role authenticated; create role service_role bypassrls; alter default privileges grant all on tables to anon, authenticated, service_role; alter default privileges grant all on sequences to anon, authenticated, service_role; alter default privileges grant execute on functions to anon, authenticated, service_role;');
  for(const f of ['0013_governing_valuations.sql','0014_valuation_run_coverage.sql'])
   await db.exec(readFileSync(new URL('../../../backend/supabase/migrations/'+f,import.meta.url),'utf8'));
  const id=(n:number)=>`00000000-0000-0000-0000-${String(n).padStart(12,'0')}`;
  const manifest=(kind='full',tickers=universe.tickers)=>({run_kind:kind,universe_version:universe.version,requested_tickers:tickers});
  const rows=(n:number,kind='full',tickers=universe.tickers)=>tickers.map(ticker=>({ticker,payload:{ticker,status:'en_revision',run_id:id(n),run_kind:kind,modelos:[]}}));
  const publish=(n:number,r=rows(n),m=manifest())=>db.query<any>('select public.publish_valuations($1::uuid,$2::jsonb,$3::jsonb)',[id(n),JSON.stringify(r),JSON.stringify(m)]);
  await db.exec('set role service_role');
  expect((await publish(1)).rows[0].publish_valuations).toBe(38);
  expect((await publish(1,rows(1).reverse(),manifest('full',[...universe.tickers].reverse()))).rows[0].publish_valuations).toBe(0);
  await expect(publish(1,rows(1).map((r,i)=>i? r:{...r,payload:{...r.payload,status:'no_valorable'}}))).rejects.toThrow('reused');
  await expect(publish(2,rows(2).slice(0,11),manifest('full',universe.tickers.slice(0,11)))).rejects.toThrow('exact');
  await expect(publish(2,rows(2).slice(1))).rejects.toThrow('coverage');
  await expect(publish(2,[...rows(2),rows(2)[0]])).rejects.toThrow('coverage');
  expect((await publish(3,rows(3,'partial',universe.tickers.slice(0,5)),manifest('partial',universe.tickers.slice(0,5)))).rows[0].publish_valuations).toBe(5);
  // A late payload error must leave neither rows nor a manifest.
  const bad=rows(4);(bad[37].payload as any).ticker='WRONG';
  await expect(publish(4,bad)).rejects.toThrow('payload');
  expect((await db.query('select * from public.valuation_runs')).rows).toHaveLength(2);
  expect((await db.query('select * from public.valuation_snapshots')).rows).toHaveLength(43);
  await expect(db.exec("insert into public.valuation_runs(run_id,run_kind,universe_version,requested_tickers) values(gen_random_uuid(),'full','giic-38-v1',array['TSM'])")).rejects.toThrow();
  await expect(db.exec("insert into public.valuation_snapshots(run_id,ticker,payload) values(gen_random_uuid(),'TSM','{}')")).rejects.toThrow();
  await expect(db.exec('truncate public.valuation_runs, public.valuation_snapshots')).rejects.toThrow();
  await expect(db.exec("select setval('public.valuation_runs_id_seq',1000)")).rejects.toThrow();
  await expect(db.exec("update public.valuation_runs set run_kind='partial'")).rejects.toThrow();
  // Real transactional rollback after the manifest insert (simulated storage failure).
  await db.exec('reset role');
  await db.exec("create function public.fail_storage() returns trigger language plpgsql as $$ begin if new.ticker='UPS' then raise exception 'storage failure'; end if; return new; end $$; create trigger fail_storage before insert on public.valuation_snapshots for each row execute function public.fail_storage();");
  await db.exec('set role service_role');
  await expect(publish(5)).rejects.toThrow('storage failure');
  expect((await db.query('select * from public.valuation_runs')).rows).toHaveLength(2);
  expect((await db.query('select * from public.valuation_snapshots')).rows).toHaveLength(43);
  await db.exec('reset role; drop trigger fail_storage on public.valuation_snapshots; set role authenticated');
  expect((await db.query('select * from public.valuation_runs')).rows).toHaveLength(2);
  await expect(publish(6)).rejects.toThrow();
  await expect(db.exec('delete from public.valuation_runs')).rejects.toThrow();
  await expect(db.exec('delete from public.valuation_snapshots')).rejects.toThrow();
  await db.exec('reset role; set role anon');
  await expect(db.exec('select * from public.valuation_runs')).rejects.toThrow();
  await db.exec('reset role');
  await expect(db.exec("update public.valuation_runs set run_kind='partial'")).rejects.toThrow('immutable');
  await expect(db.query('select public.publish_valuations($1::uuid,$2::jsonb)',[id(6),'[]'])).rejects.toThrow();
 }finally{await db.close();}
},30000);
