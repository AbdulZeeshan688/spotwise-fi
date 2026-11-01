# Deploy SpotWise FI (free, step by step)

Everything here uses **free plans only**. You never need to enter a credit card; if a
site asks for one, stop and pick the free option. Total time: about 45 minutes, most of
it waiting.

| What | Where | Why there |
|---|---|---|
| Database (PostgreSQL) | **Neon** | Free managed Postgres |
| API (FastAPI, Python) | **Render** | Runs Docker containers for free; Netlify can't run Python servers |
| Web app (React) | **Netlify** | Free static hosting |
| Daily price update | **GitHub Actions** | Already in the repo (`ingest.yml`) |

Do the steps **in this order**: each one needs a value from the step before.
Keep a note open for three values: **Neon URL**, **Render URL**, **Netlify URL**.
Never paste the Neon URL into a chat or a commit: it contains your database password.

Button names on these websites change sometimes. If a name below doesn't match exactly,
look for the closest one.

---

## Step 1 — Database on Neon (5 min)

1. Go to <https://neon.tech> → **Sign up** → **Continue with GitHub**.
2. Create a project:
   - Name: `spotwise`
   - Region: **AWS Europe Central 1 (Frankfurt)** (close to Finland and to Render's Frankfurt)
   - Postgres version: the default is fine (16 or newer)
3. On the project dashboard click **Connect**.
   - Turn **Connection pooling OFF** (the host name must *not* contain `-pooler`).
   - Copy the connection string. It looks like
     `postgresql://neondb_owner:xxxx@ep-something-123456.eu-central-1.aws.neon.tech/neondb?sslmode=require`
   - You can paste it exactly as shown; SpotWise adds the driver name itself.

✅ You have: **Neon URL**.

## Step 2 — Fill the database from GitHub (2 min + ~15 min waiting)

1. Open <https://github.com/AbdulZeeshan688/spotwise-fi> → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
   - Name: `DATABASE_URL`
   - Secret: the **Neon URL**
2. Go to the **Actions** tab → **Daily ingest** (left list) → **Run workflow**.
   - `backfill_days`: `14`
   - Click **Run workflow**.
3. Wait until it shows a green ✓ (about 10–15 minutes: without an ENTSO-E token,
   porssisahko.net is asked one price at a time). The workflow also creates the tables.

From now on this workflow runs by itself every day at 12:30 and 14:30 UTC and adds
the new prices. (Optional, later: when your ENTSO-E token arrives, add it as a second
secret named `ENTSOE_TOKEN`; backfills then take seconds.)

## Step 3 — API on Render (5 min + ~5 min build)

1. Go to <https://render.com> → **Get Started** → **GitHub**.
   Choose the free **Hobby** workspace if asked.
2. **New** → **Blueprint** → connect GitHub → give Render access to the
   `spotwise-fi` repository → select it.
3. Render reads `render.yaml` and shows the service **spotwise-api** (Free plan).
   It asks for two values:
   - `DATABASE_URL`: the **Neon URL**
   - `CORS_ORIGINS`: for now `http://localhost:5173` (you change it in Step 5)
4. Click **Apply** / **Deploy Blueprint** and wait for **Live** (first build ~5 min).
5. Copy the service URL from the top of the page, e.g. `https://spotwise-api.onrender.com`.
6. Test it in your browser:
   - `https://<your-api>.onrender.com/health` → `{"status":"ok","db":"ok"}`
   - `https://<your-api>.onrender.com/prices` → JSON with today's prices
   - `https://<your-api>.onrender.com/docs` → the interactive API docs

✅ You have: **Render URL** (no `/` at the end).

> The free API **sleeps after ~15 minutes without visitors**. The next visit wakes it up
> in 30–60 seconds; the web app shows "Waking up the free server…" meanwhile. That's
> normal for free hosting.

## Step 4 — Web app on Netlify (5 min + ~2 min build)

1. Go to <https://app.netlify.com> → **Sign up** → **GitHub**.
2. **Add new site** → **Import an existing project** → **GitHub** → give access to
   `spotwise-fi` → select it.
3. Netlify reads `netlify.toml`, so the build settings are already filled in
   (base `web`, publish `dist`). Don't change them.
4. Before deploying, add an environment variable (on the same page under
   **Environment variables**, or later in **Site configuration → Environment variables**):
   - Key: `VITE_API_URL`
   - Value: the **Render URL**
5. Click **Deploy**. When it's done, open the site.
6. Optional: **Site configuration → Change site name** → `spotwise-fi` (or any free name),
   so the URL becomes `https://spotwise-fi.netlify.app`.

✅ You have: **Netlify URL**.

> Changed `VITE_API_URL` later? Trigger a new deploy (**Deploys → Trigger deploy**):
> it is built into the site at build time.

## Step 5 — Connect them (2 min)

The API only accepts browser requests from sites listed in `CORS_ORIGINS`.

1. Render → **spotwise-api** → **Environment** → edit `CORS_ORIGINS` → set it to the
   **Netlify URL**, e.g. `https://spotwise-fi.netlify.app` (no `/` at the end).
   You can keep local development too: `https://spotwise-fi.netlify.app,http://localhost:5173`
2. **Save changes** (Render redeploys, ~2 min).

## Step 6 — Check everything (2 min)

Open the **Netlify URL** on your laptop and your phone:
- [ ] The chart shows today's prices, with a "Now" line and a green cheapest window.
- [ ] The badge in the top right says "Data OK" (or explains a problem).
- [ ] Click a chat chip, e.g. "What's the price right now?" → an answer appears.
- [ ] Hourly / VAT toggles change the chart.
- [ ] Tomorrow: after ~15:00 Finnish time, tomorrow's prices appear by themselves.

Then put the Netlify URL into `README.md` (the "Live demo" line) and push.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Web app: "Couldn't load prices: Failed to fetch" | `CORS_ORIGINS` on Render doesn't match the Netlify URL exactly (https, no trailing `/`), or `VITE_API_URL` is wrong → fix it and redeploy Netlify. |
| `/health` says `"db":"unreachable"` | `DATABASE_URL` on Render is wrong, or you copied the *pooled* Neon URL. Use the direct one. |
| Chart says "No prices stored for today yet" | Run **Actions → Daily ingest → Run workflow** (Step 2). |
| Daily ingest job fails | Open the job log; the last red line says why. Re-running is always safe. |
| The page takes a minute to load | The free API was asleep. Normal. |
| Daily ingest stopped running after a while | GitHub pauses scheduled workflows in repos without activity for 60 days. Push any commit, or re-enable it in the Actions tab. |

## What this costs

€0. All four services are on free plans; nothing here needs a credit card or an API key.
The chat uses the built-in rule-based assistant (`AGENT_MODE=rules`), not a paid AI model.
