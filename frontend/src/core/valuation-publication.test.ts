import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { PGlite } from "@electric-sql/pglite";

describe("P0 publication transaction (real PostgreSQL in WASM)", () => {
  it("keeps same-day revisions, publishes invalidations, is atomic and denies client writes", async () => {
    const db = new PGlite();
    try {
      await db.exec("create role authenticated; create role service_role bypassrls;");
      await db.exec(readFileSync(new URL("../../../backend/supabase/migrations/0013_governing_valuations.sql", import.meta.url), "utf8"));
      const publish = (id: string, rows: any[]) => db.query("select public.publish_valuations($1::uuid,$2::jsonb)", [id, JSON.stringify(rows)]);
      const good = { ticker: "TSM", payload: { ticker: "TSM", status: "en_revision", modelos: [{modelo:"motor_v2",fair_value_usd:308.8}] } };
      await publish("00000000-0000-0000-0000-000000000001", [good]);
      await publish("00000000-0000-0000-0000-000000000002", [{...good,payload:{...good.payload,modelos:[] ,status:"no_valorable"}}]);
      const rows = await db.query<any>("select * from public.valuation_snapshots order by id desc");
      expect(rows.rows).toHaveLength(2);
      expect(rows.rows[0].payload.status).toBe("no_valorable");
      await expect(publish("00000000-0000-0000-0000-000000000003", [good, {ticker:"BAD",payload:null}])).rejects.toThrow();
      expect((await db.query("select * from public.valuation_snapshots")).rows).toHaveLength(2);
      await db.exec("set role authenticated");
      expect((await db.query("select * from public.valuation_snapshots")).rows).toHaveLength(2);
      await expect(publish("00000000-0000-0000-0000-000000000004", [good])).rejects.toThrow();
      await expect(db.exec("delete from public.valuation_snapshots")).rejects.toThrow();
      await db.exec("reset role");
      await db.exec("set role service_role");
      const retry = await publish("00000000-0000-0000-0000-000000000001", [good]);
      expect((retry.rows[0] as any).publish_valuations).toBe(0);
      await expect(publish("00000000-0000-0000-0000-000000000001", [{...good,payload:{...good.payload,status:"consistente"}}])).rejects.toThrow();
      await db.exec("reset role");
      await expect(db.exec("update public.valuation_snapshots set ticker='X'")).rejects.toThrow();
    } finally { await db.close(); }
  }, 30000);
});
