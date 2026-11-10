.PHONY: secrets users watch eval eval-report up down logs ps test lint fmt check migrate data knowledge seed psql reset-db

secrets:       ## Add any missing generated secrets to .env (never overwrites existing ones)
	@for k in OPERATIONS_MCP_BACKEND_TOKEN OPERATIONS_MCP_EXTERNAL_TOKEN ENTERPRISE_API_KEY ADMIN_PASSWORD DEMO_PASSWORD; do \
	  grep -qE "^$$k=.+" .env || { sed -i "/^$$k=$$/d" .env; echo "$$k=$$(openssl rand -hex 24)" >> .env; echo "added $$k"; }; \
	done

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

data:          ## Generate every enabled pack's synthetic dataset (seed 42) and load it
	cd backend && uv run python -m watchdog_backend.generator --load

knowledge:     ## Ingest every enabled pack's policy documents into the knowledge base
	cd backend && uv run python -m watchdog_backend.knowledge ingest

users:         ## Create the admin and the demo accounts (passwords from .env: make secrets)
	cd backend && uv run python -m watchdog_backend.identity seed

seed: data knowledge users   ## Everything a fresh database needs

eval-retrieval: ## Retrieval benchmark (no LLM): hit@k and MRR per method
	cd backend && uv run python -m watchdog_backend.knowledge evaluate

watch:         ## Evaluate the KPI monitors once and update alerts
	cd backend && uv run python -m watchdog_backend.watch

eval:          ## Full evaluation (isolated <db>_eval_<pack> database). DOMAIN / MODELS / SEEDS overridable
	cd backend && uv run python -m watchdog_backend.evaluation run --domain $${DOMAIN:-insurance_claims} \
	  --db-suffix eval_$${DOMAIN:-insurance_claims} --models $${MODELS:-ollama:qwen2.5:7b} --seeds $${SEEDS:-42,7,1234}

eval-report:   ## Rebuild docs/evaluation_report.md from all saved evaluation runs
	cd backend && uv run python -m watchdog_backend.evaluation report $$(ls -d ../evaluation/results/2*/ | sort)

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
