# SpotWise API image (used by Render). Runs migrations, then the FastAPI app.
FROM python:3.12-slim

# uv from its official image, pinned to the version used in development
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Dependencies first, so this layer is cached when only the code changes
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --locked --no-dev

# Don't run as root
RUN useradd --create-home spotwise
USER spotwise

# Render sets PORT. --proxy-headers makes the rate limit see real client IPs
# (behind Render's proxy every request would otherwise come from the proxy).
CMD ["sh", "-c", "alembic upgrade head && uvicorn spotwise.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
