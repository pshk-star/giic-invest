# GIIC — Publicar gratis, paso a paso (para no programadores)

Sigue esto en orden. No hace falta saber programar ni poner tarjeta. Al final tendrás
GIIC en una dirección web privada, solo para ti, con datos reales que se actualizan
solos. Tiempo: ~35 min.

Ten a mano un bloc de notas para pegar 3 valores que iremos copiando:
`URL`, `anon key`, `service_role key`.

> Si **cualquier** pantalla te pide una tarjeta de crédito, detente: no es necesario.

---

# PARTE A — Crear las 3 cuentas (5 min)
A1. Entra a **github.com** → **Sign up**. Crea tu cuenta.
A2. Entra a **supabase.com** → **Start your project** → **Continue with GitHub**.
A3. Entra a **dash.cloudflare.com/sign-up** → crea tu cuenta.

---

# PARTE B — Subir GIIC a GitHub (5 min)
B1. En **github.com**, arriba a la derecha: **+** → **New repository**.
B2. **Repository name:** escribe `giic`.
B3. Marca **Public**. *(Tu información privada NO va aquí; vive en Supabase. El código
    no contiene contraseñas.)*
B4. Clic **Create repository**.
B5. En la página del repo nuevo, clic en el enlace **uploading an existing file**
    (o **Add file → Upload files**).
B6. Descomprime el ZIP `giic` en tu computadora y **arrastra TODO el contenido** a la
    zona de carga. Espera a que suban.
B7. Abajo, clic **Commit changes**.

---

# PARTE C — Base de datos y login (Supabase) (10 min)
C1. En **supabase.com** → **New project**. Nombre: `giic`. Elige una **Database
    Password** (invéntala fuerte y guárdala). Región: la más cercana (p. ej. *East US*).
    Clic **Create new project** y espera ~2 min a que se cree.
C2. Menú izquierdo: **SQL Editor** → **New query**.
C3. En tu computadora abre el archivo `backend/supabase/schema.sql`, copia **todo** su
    contenido, pégalo en el editor y clic **Run** (abajo a la derecha). Debe decir
    *Success*. Esto crea las tablas y la seguridad.
C4. Copia los 3 valores. Menú **Project Settings** (ícono de engrane) → **API**:
    - **Project URL** → pégalo en tu bloc como `URL`.
    - En **Project API keys**: **anon public** → pégalo como `anon key`.
    - **service_role** → pégalo como `service_role key`. *(Esta es SECRETA: solo se
      usa en la Parte D. Nunca la pongas en la web ni se la des a nadie.)*

### C5. Desactivar el registro público (GIIC es solo tuyo)
C5a. Menú **Authentication** → **Sign In / Providers** (o **Providers → Email**).
C5b. **Desactiva** la opción **Allow new users to sign up** (Permitir registros) y
     **Guarda**. Así nadie más podrá crear cuenta.
C5c. (Recomendado) En **Email**, **desactiva "Confirm email"** para no tener que
     confirmar por correo tu propio usuario.

### C6. Crear TU usuario (el único)
C6a. Menú **Authentication** → **Users** → **Add user** → **Create new user**.
C6b. Escribe tu **correo** y una **contraseña** fuerte. Marca **Auto Confirm User**.
     Clic **Create user**. Con este usuario entrarás a GIIC.

---

# PARTE D — Encender el scanner automático (GitHub Actions) (5 min)
D1. En tu repo de GitHub: **Settings** (del repo) → menú izquierdo
    **Secrets and variables** → **Actions**.
D2. Clic **New repository secret** y crea estos tres (uno por uno):
    - Name: `SUPABASE_URL` · Secret: tu `URL` → **Add secret**.
    - Name: `SUPABASE_SERVICE_ROLE_KEY` · Secret: tu `service_role key` → **Add secret**.
    - Name: `EDGAR_USER_AGENT` · Secret: `GIIC tu-correo@ejemplo.com`
      *(la SEC exige un correo de contacto; usa el tuyo)* → **Add secret**.
D3. **Comprobación con datos reales ANTES de cargar tu cartera:** pestaña **Actions**
    (arriba) → si pide habilitarlas, acéptalo → en la izquierda elige
    **GIIC selftest (datos reales)** → botón **Run workflow** → **Run workflow**.
    Ábrelo; en ~1 min debe terminar en verde y mostrar un reporte con precios,
    fundamentales, FX y un top del scanner **reales**. Si sale en rojo, revisa que el
    `EDGAR_USER_AGENT` tenga tu correo. *(Este paso no escribe nada.)*
D4. Ahora la carga real: en **Actions** elige **GIIC scan** → **Run workflow**
    (deja `free`) → **Run workflow**. En 1–2 min cargará precios, fundamentales y el
    ranking en Supabase. A partir de aquí corre **solo** cada día hábil.

---

# PARTE E — Publicar la web (Cloudflare Pages) (5 min)
E1. En **dash.cloudflare.com** → menú **Workers & Pages** → **Create** → pestaña
    **Pages** → **Connect to Git** → autoriza GitHub → elige el repo **giic**.
E2. En **Set up builds and deployments**, escribe EXACTAMENTE:
    - **Framework preset:** `Vite`
    - **Build command:** `npm install && npm run build`
    - **Build output directory:** `dist`
    - **Root directory:** (clic en **Advanced** si no aparece) escribe `frontend`
E3. Abre **Environment variables (Production)** → **Add variable**, crea dos:
    - `VITE_SUPABASE_URL` = tu `URL`
    - `VITE_SUPABASE_ANON_KEY` = tu `anon key`
E4. Clic **Save and Deploy**. Espera ~2 min. Te dará una dirección como
    `https://giic-ab1.pages.dev`. Cópiala.
E5. Vuelve a **Supabase** → **Authentication** → **URL Configuration**:
    - **Site URL:** pega tu dirección `*.pages.dev`.
    - **Redirect URLs:** **Add URL** y pega también tu dirección `*.pages.dev`.
    - **Save**. *(Esto hace que el enlace de "olvidé mi contraseña" funcione.)*

---

# PARTE F — Entrar y usar (2 min)
F1. Abre tu dirección `*.pages.dev` (en tu laptop o en el iPhone; es responsive).
F2. Escribe el **correo y contraseña** que creaste en C6 → **Entrar**.
    *(No hay opción de "crear cuenta": es intencional, GIIC es solo tuyo.)*
F3. Pestaña **Mi Cartera** → agrega tus posiciones (o **Importar CSV**).
F4. **Dashboard** y **Oportunidades** muestran los datos reales del último scan.
F5. Cierra y vuelve a entrar: tus datos siguen ahí (están en Supabase).

---

# PARTE G — Comprobar que tus datos son privados (2 min)
G1. En GIIC (ya con sesión iniciada) agrega una posición en **Mi Cartera**.
G2. En **Supabase → SQL Editor → New query**, pega el contenido de
    `backend/supabase/rls_check.sql` y **Run**. Confirma que:
    - todas las tablas salen con `rowsecurity = true`;
    - `positions` y `settings` tienen una política cuya condición incluye
      `user_id = auth.uid()` (privadas por dueño);
    - las tablas de mercado/scanner solo tienen una política de lectura `read`.
G3. (Opcional, prueba fuerte) Abre tu URL `*.pages.dev` en una **ventana privada**
    del navegador SIN iniciar sesión: no debe mostrarse ninguna posición; la app pide
    login. Tus datos solo existen tras autenticarte y, por RLS, cada usuario solo ve
    los suyos.

---

# Mantenimiento

**Actualizar GIIC a una versión nueva:** sube los archivos nuevos al repo (Parte B, de
nuevo). Cloudflare **redepliega solo** en cada cambio. Si cambió la base de datos, te
diré qué SQL correr.

**Recuperar tus datos si algo falla:** en Supabase → **Table Editor** → tabla
`positions` → **Export → CSV**. Guarda ese archivo; lo puedes reimportar en *Mi Cartera*.

**Olvidaste tu contraseña:** en la pantalla de inicio → **Olvidé mi contraseña** →
recibes un enlace por correo. (Requiere el paso E5.)

**Si Supabase "pausa" el proyecto** (pasa tras 7 días sin uso): entra a supabase.com y
clic en **Restore**. El scan diario normalmente lo mantiene activo.

Límites y condiciones de cada servicio: ver `FREE_TIER_LIMITS.md`.
