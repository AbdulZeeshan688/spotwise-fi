# Phase 8 — Deploy & polish: summary

Requirements: OPS-03, OPS-04, DOC-01, DOC-02.

## What was built
- **`Dockerfile`** for the API: python 3.12-slim + uv (pinned 0.13.6), dependency layer cached separately, runs as a non-root user. At start it runs `alembic upgrade head` (migrations on every deploy), then uvicorn on Render's `$PORT` with `--proxy-headers`.
- **`render.yaml`** (Render Blueprint): free web service `spotwise-api` in Frankfurt, health check `/health`, auto-deploy on push. `DATABASE_URL` and `CORS_ORIGINS` are asked for at setup (never stored in git), and `AGENT_MODE=rules` is set.
- **`netlify.toml`**: builds `web/` with Node 24, single-page-app redirect, security headers, long caching for hashed assets.
- **Daily ingest from the GitHub website**: `ingest.yml` got a `backfill_days` input, so the production database can be filled with **Actions → Daily ingest → Run workflow**, with nothing installed locally.
- **CI `docker` job**: builds the production image, starts it against Postgres with a plain `postgresql://` URL (like Neon's), and smoke-tests `/health`, `/prices` and `/chat`. That's how the image gets tested even though Docker isn't installed locally.
- **Docs**: `README.md` (pitch, architecture diagram, eval table, local setup, decisions, cost & limits, next steps), `docs/DECISIONS.md`, and **`docs/DEPLOY.md`**, a click-by-click free deployment guide.

## Decisions (and why)
- **Netlify + Render + Neon, all free plans.** Netlify can't run a Python server, so the API goes to Render (free Docker web service), the database to Neon (free Postgres), and the daily job stays on GitHub Actions. No credit card anywhere.
- **Neon URLs are accepted as copied.** `Settings` turns `postgresql://` / `postgres://` into `postgresql+psycopg://`, removing a common deploy mistake.
- **Use Neon's direct (non-pooled) connection.** Our API is one long-running process with its own SQLAlchemy pool, so PgBouncer adds nothing, and psycopg's prepared statements can conflict with transaction pooling.
- **`--proxy-headers`.** Behind Render's proxy every request would look like it came from the proxy, so all users would share one rate limit. With proxy headers the limiter sees real client IPs.
- **"Waking up the free server…" message** after 4 s of loading. Render's free tier sleeps when idle, and a silent 40-second spinner looks broken.
- **Migrations at container start** instead of a separate release step: simplest on the free plan, and Alembic does nothing when the database is already up to date.

## Verified
- Backend: tests, ruff, mypy. Frontend: 22 tests, lint, build. The Docker image in CI: see the commit's CI run.
- **Not verified by me: the actual deployment.** It needs your Neon, Render and Netlify accounts. Follow `docs/DEPLOY.md`.

## Learn this (interview)
- **Why the API and the web app are hosted separately:** the web app is static files (any CDN can serve them); the API is a long-running Python process that needs a server and a database connection. CORS is what lets the browser call one from the other, and we only allow our own Netlify domain.
- **Docker layer caching:** copy `pyproject.toml` + `uv.lock` and install dependencies *before* copying the code, so a code change doesn't reinstall everything.
- **Twelve-factor config:** the same image runs everywhere; only environment variables (`DATABASE_URL`, `CORS_ORIGINS`) differ, and secrets never enter git.
