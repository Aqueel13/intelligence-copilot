# Intelligence WatchDog

An AI operations analyst that **watches** business process KPIs, **investigates** why they drift, **recommends** fixes backed by evidence and ROI, and **acts** only with human approval.

**Watch → Investigate → Recommend → Act**

> Status: **M2 — process mining and dashboard.** See [`docs/PROJECT_BRIEF.md`](docs/PROJECT_BRIEF.md) for scope, decisions and milestones.

## Design principles

- **Deterministic numbers.** Every KPI comes from code or SQL; the LLM interprets, never calculates.
- **Evidence-first.** Each recommendation links to the query results, process statistics and policy text behind it.
- **Approval enforced in the backend.** Write actions cannot run without a recorded human approval.
- **Provider-agnostic.** LLM and embedding providers are configuration, not code.

## Stack

FastAPI · LangGraph · PostgreSQL 17 + pgvector · SQL-native process mining · React + Vite + TypeScript + Tailwind · MCP · Docker Compose

## Run locally

Requirements: Docker with Compose, [uv](https://docs.astral.sh/uv/), Node 24+.

```bash
cp .env.example .env          # then set POSTGRES_PASSWORD (and the same value in DATABASE_URL)
make up                       # build and start postgres, migrations, backend, frontend
make data                     # generate 5,000 synthetic claims (seed 42) and load them
```

| What | URL |
|------|-----|
| App: Overview and Process screens | http://localhost:5173 |
| API docs | http://localhost:8000/api/docs |
| Health | http://localhost:8000/api/health |
| Metric catalogue | http://localhost:8000/api/metrics |

Other commands: `make test`, `make lint`, `make check` (everything CI runs), `make psql`, `make logs`, `make down`.

## Repository layout

```
backend/       FastAPI app (src/watchdog_backend), Alembic migrations, tests
  analytics/   metrics engine (domain-pack metrics → safe, parameterised SQL) and
               SQL-native process mining (process map, variants, bottlenecks)
  generator/   synthetic data with planted root causes, decoys and ground truth
domain_packs/  per-industry configuration (process, dimensions, rules, metrics)
frontend/      React + Vite + Tailwind UI
docs/          Project brief, architecture, evaluation reports
.github/       CI: lint, migrate, test, migration round-trip, frontend build
```
