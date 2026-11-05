-- Verificación de Row Level Security (RLS) en GIIC.
-- Pégalo en Supabase → SQL Editor → Run. Sirve para comprobar que tu cartera está
-- protegida: RLS activo en todas las tablas y políticas correctas.

-- 1) RLS debe estar HABILITADO (rowsecurity = true) en todas las tablas.
select tablename, rowsecurity
from pg_tables
where schemaname = 'public'
  and tablename in ('positions','settings','prices','fundamentals',
                    'etf_holdings','fx_rates','scan_runs','scan_snapshots')
order by tablename;

-- 2) Políticas existentes. Debe verse:
--    - positions / settings: política 'for all' por auth.uid() (privadas por dueño).
--    - prices/fundamentals/etf_holdings/fx_rates/scan_runs/scan_snapshots:
--      política de SOLO lectura ('read') para el rol authenticated.
select tablename, policyname, cmd, qual, with_check
from pg_policies
where schemaname = 'public'
order by tablename, policyname;

-- 3) Comprobación lógica: 'positions' y 'settings' NO deben tener política que
--    permita leer filas de otros usuarios. La condición debe mencionar auth.uid().
select tablename, policyname, qual
from pg_policies
where schemaname = 'public' and tablename in ('positions','settings');

-- Esperado: 'positions_owner' y 'settings_owner' con qual que contiene (user_id = auth.uid()).
-- Si alguna de estas tablas apareciera con rowsecurity=false o con una política
-- 'using (true)', tu cartera NO estaría protegida: vuelve a correr schema.sql.
