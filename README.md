# Intelligence WatchDog

An AI operations analyst that **watches** business process KPIs, **investigates** why they drift, **recommends** fixes backed by evidence and ROI, and **acts** only with human approval.

**Watch → Investigate → Recommend → Act**

> Status: **M7 — evaluated.** Results in [`docs/evaluation_report.md`](docs/evaluation_report.md). See [`docs/PROJECT_BRIEF.md`](docs/PROJECT_BRIEF.md) for scope, decisions and milestones.

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
make secrets                  # generate MCP tokens and the mock system's API key
make up                       # build and start postgres, migrations, backend, frontend
make seed                     # generate 5,000 synthetic claims and ingest the policy documents
```

| What | URL |
|------|-----|
| App: Watch, Overview, Process, Knowledge, Investigate and Actions screens | http://localhost:5173 |
| API docs | http://localhost:8000/api/docs |
| Health | http://localhost:8000/api/health |
| Metric catalogue | http://localhost:8000/api/metrics |

Other commands: `make eval` / `make eval-report` (evaluation), `make watch` (evaluate monitors now), `make test`, `make lint`, `make check` (everything CI runs), `make eval-retrieval`, `make psql`, `make logs`, `make down`. The `watcher` service evaluates monitors every hour (`WATCH_INTERVAL_SECONDS`).

The LLM defaults to a local model through [Ollama](https://ollama.com) (`ollama pull qwen2.5:7b`). Set `LLM_DEFAULT_MODEL` / `LLM_MODELS` in `.env` to use Groq or Gemini instead.

## Connect an MCP client to the Operations server

The Operations MCP server (`http://localhost:8103/mcp`, localhost only) lets any MCP client list
the action catalogue, propose actions and execute actions a person has approved. It has no
approve tool. Use the `OPERATIONS_MCP_EXTERNAL_TOKEN` from `.env`, for example with Claude Code:

```bash
claude mcp add --transport http watchdog-ops http://localhost:8103/mcp \
  --header "Authorization: Bearer $(grep ^OPERATIONS_MCP_EXTERNAL_TOKEN= .env | cut -d= -f2-)"
```

Every call is recorded in the hash-chained audit log under the client's name.

## Repository layout

```
backend/       FastAPI app (src/watchdog_backend), Alembic migrations, tests
  analytics/   metrics engine (domain-pack metrics → safe, parameterised SQL) and
               SQL-native process mining (process map, variants, bottlenecks)
  generator/   synthetic data with planted root causes, decoys and ground truth
  knowledge/   document parsing, section-aware chunking, hybrid retrieval, cited answers
  llm/         provider-agnostic LLM gateway (Ollama, Groq, Gemini)
  investigation/  LangGraph investigation: scan → plan → evidence → assess → recommend → summary,
                  with confounder overrides, what-if valuation and number verification
  governance/  action rules (roles, separation of duties, approve-before-execute), audit chain
  watch/       KPI monitors, alerts, action follow-ups, next-month simulator (demo)
  evaluation/  evaluation harness: investigations vs planted truth, Q&A, retrieval, what-if
evaluation/    saved evaluation runs (results.jsonl per run) and notes on fixes they triggered
  mcp_servers/ Operations MCP server (governed actions for any MCP client)
  enterprise_mock/  stand-in for the client's claims administration system
domain_packs/  per-industry configuration (process, dimensions, rules, metrics, monitors,
               action catalogue, governance), policy documents and evaluation sets
frontend/      React + Vite + Tailwind UI
docs/          Project brief, architecture, evaluation reports
.github/       CI: lint, migrate, test, migration round-trip, frontend build
```
