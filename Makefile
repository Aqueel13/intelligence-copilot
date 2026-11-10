.PHONY: up down logs ps test lint fmt check migrate data psql reset-db

up:            ## Build and start the full stack
	docker compose up --build -d

down:          ## Stop the stack (data is kept)
	docker compose down

logs:          ## Follow backend logs
	docker compose logs -f backend

ps:
	docker compose ps

migrate:       ## Apply database migrations
	docker compose run --rm migrate

data:          ## Generate the synthetic dataset (seed 42) and load it into the database
	cd backend && uv run python -m watchdog_backend.generator --load

test:          ## Run backend tests (needs the stack's Postgres running)
	cd backend && uv run pytest

lint:          ## Lint backend and frontend
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint

fmt:           ## Auto-format backend code
	cd backend && uv run ruff check --fix . && uv run ruff format .

check: lint test   ## Everything CI runs, locally
	cd frontend && npm run build

psql:          ## Open a psql shell in the database container
	docker compose exec postgres sh -c 'psql -U $$POSTGRES_USER -d $$POSTGRES_DB'

reset-db:      ## DANGER: delete all local database data
	docker compose down -v
