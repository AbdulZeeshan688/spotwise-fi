# Common commands. Run `make <target>`.
.PHONY: install db migrate api test lint format typecheck check

install:     ## install Python dependencies
	uv sync

db:          ## start local Postgres
	docker compose up -d db

migrate:     ## apply database migrations
	uv run alembic upgrade head

api:         ## run the API with auto-reload
	uv run uvicorn spotwise.api.main:app --reload

test:        ## run the test suite
	uv run pytest

lint:        ## lint and check formatting
	uv run ruff check .
	uv run ruff format --check .

format:      ## auto-format code
	uv run ruff format .
	uv run ruff check --fix .

typecheck:   ## type-check src/
	uv run mypy

check: lint typecheck test   ## everything CI runs
