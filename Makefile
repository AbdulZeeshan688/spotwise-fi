# Common commands. Run `make <target>`.
.PHONY: install db migrate api test lint format typecheck check daily backfill quality eval-load eval-check eval

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

daily:       ## ingest today + tomorrow
	uv run python -m spotwise.ingest.cli daily

backfill:    ## ingest history, e.g. `make backfill DAYS=30`
	uv run python -m spotwise.ingest.cli backfill --days $(or $(DAYS),30)

quality:     ## run data-quality checks, e.g. `make quality DAYS=30`
	uv run python -m spotwise.ingest.cli quality --days $(or $(DAYS),1)

eval-load:   ## (re)load the frozen fixture into the eval database
	uv run python -m evals.fixtures.loader

eval-check:  ## validate the golden set and ground truth (no LLM, free)
	uv run python -m evals.runner --check

eval:        ## full eval run with the real LLM (costs money), e.g. `make eval LIMIT=5`
	uv run python -m evals.runner --suite golden $(if $(LIMIT),--limit $(LIMIT),)
