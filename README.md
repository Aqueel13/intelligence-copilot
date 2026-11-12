# Intelligence WatchDog

An AI operations analyst that **watches** business-process KPIs, **investigates** why they
drift, **recommends** fixes backed by evidence and ROI, and **acts** only with human approval.

**Watch → Investigate → Recommend → Act**, on two processes with one engine: insurance claims
and procure-to-pay.

> **Read first:** the [case study](docs/CASE_STUDY.md) (what and why, results, what broke) ·
> the [evaluation report](docs/evaluation_report.md) (every number, every failure) ·
> the [project brief](docs/PROJECT_BRIEF.md) (decisions D1–D47, scope, milestones).

![Watch: procure-to-pay monitors raised from policy thresholds](docs/images/watch-p2p.png)

*Procure-to-pay investigation, local 7B model: an executive summary whose every number is
verified against the analysis, and a decoy the model called "supported" that the confounder
rule ruled out (MSME suppliers: the effect is explained by AP team).*

![Executive summary of a procure-to-pay investigation](docs/images/investigation-summary.png)
![Hypotheses with a rule override on a confounded decoy](docs/images/investigation-safeguards.png)

## What it does

- **Watch:** KPI monitors with thresholds from the client's own policies. Alerts open,
  update and resolve themselves; one click investigates.
- **Investigate:** a LangGraph workflow. Code scans for every significant pattern and runs
  every check, including confounder controls. The LLM writes hypotheses and judges the
  evidence. Rule overrides keep it honest in both directions.
- **Recommend:** only actions from the client's catalogue, each valued by a deterministic
  what-if on the event log (breaches avoided, net value a year) and cited to the policy that
  permits it.
- **Act:** propose → human approval by the right role → execution through an MCP server →
  hash-chained audit log → follow-up metric. Agents can never approve.

Around the loop, the platform an enterprise would ask for:

- **Accounts and role-based access.** Local accounts (scrypt-hashed passwords, HttpOnly
  session cookies). Platform roles (viewer, analyst, admin) gate what someone can do; a
  business role per process (e.g. Head of Claims, Treasury Head) gates what they can approve.
  Admins manage users and can act as another user for demos, recorded in the audit log.
- **Observability.** Every LLM call and API request is recorded: latency percentiles, tokens,
  errors, cache hits, the free-tier quota per model, and a timeline trace per investigation.
- **Cost control.** Repeated or near-identical policy questions are answered from a cache
  (invalidated when any document changes; never reused across different amounts). Simple
  requests can go to a cheaper model tier (`LLM_LIGHT_MODEL`), with the reason shown.
- **Replay instead of re-running.** Every investigation records its steps. An identical request
  on the same data, documents and models replays the recorded run in seconds with no model
  call. Admins pick showcase runs that anyone, read-only visitors included, can watch step by
  step.
- **Rate limits** on requests that spend tokens only: per person per hour, and for everyone per
  day, sized for a free model tier (`RATE_LIMIT_*` settings). Cache hits and replays are free.
- **Model comparison.** A page built from the saved evaluation runs, so every new run shows up.

## Results in one table

Scored against planted ground truth (generators plant root causes and decoys, with an exact
counterfactual per case). Full detail in the [evaluation report](docs/evaluation_report.md).

| | Insurance claims | Procure-to-pay |
|---|---|---|
| Investigations (models × seeds × questions) | 36 (4 × 3 × 3) | 9 (local 7B × 3 × 3) |
| Mean recall of planted causes | 79–100% by model; local 7B 100% | 100% |
| Decoys accepted as causes | **0** in every run | **0** in every run |
| Policy Q&A: answers citing a relevant passage | 96% for every model | 100% |
| What-if vs exact counterfactual | 0.51–0.99 of truth (understates) | 0.63–0.99 of truth (understates) |

Every miss was over-caution (a real cause left inconclusive), never a decoy accepted; the
evaluation also found nine product defects, each fixed and re-measured
([notes](evaluation/results/NOTES.md)).

## Design principles

- **Deterministic numbers.** Every KPI comes from code or SQL; the LLM interprets, never
  calculates. Summaries are checked number by number.
- **Evidence-first.** Each finding links to the query results, process statistics and policy
  text behind it. Confounded effects cannot be reported as causes.
- **Approval enforced in the backend.** Write actions cannot run without a recorded human
  approval by an authorised role; the proposer cannot approve.
- **A process is configuration.** Each domain pack holds the process definition, metrics,
  monitors, actions, governance, policies and benchmark. See
  [adding a domain pack](docs/ADDING_A_DOMAIN_PACK.md).
- **Provider-agnostic, zero spend.** Local Ollama or free-tier Groq/Gemini, set in `.env`.

## Stack

FastAPI · LangGraph · PostgreSQL 17 + pgvector · SQL-native process mining · hybrid retrieval
(BGE embeddings + full-text, cross-encoder citation checks) · MCP · React + Vite + TypeScript +
Tailwind · Docker Compose

## Run locally

Requirements: Docker with Compose, [uv](https://docs.astral.sh/uv/), Node 24+.

```bash
cp .env.example .env          # then set POSTGRES_PASSWORD (and the same value in DATABASE_URL)
make secrets                  # generate MCP tokens, the mock system's key, account passwords
make up                       # build and start postgres, migrations, backend, frontend
make seed                     # both packs' data and policies, plus the admin and demo accounts
```

| What | URL |
|------|-----|
| App: sign in as `admin@watchdog.local` with `ADMIN_PASSWORD` from `.env` | http://localhost:5173 |
| API docs | http://localhost:8000/api/docs |
| Health | http://localhost:8000/api/health |

Other commands: `make eval DOMAIN=procure_to_pay` / `make eval-report` (evaluation),
`make watch` (evaluate monitors now), `make test`, `make lint`, `make check` (everything CI
runs), `make eval-retrieval`, `make psql`, `make logs`, `make down`. The `watcher` service
evaluates every pack's monitors hourly (`WATCH_INTERVAL_SECONDS`).

Demo accounts (one per governance role in each pack, e.g. `a.rao@demo.watchdog`, plus a
read-only `guest@demo.watchdog`) use `DEMO_PASSWORD`. Every `/api` route except health and
sign-in needs a session.

The LLM defaults to a local model through [Ollama](https://ollama.com)
(`ollama pull qwen2.5:7b`). Set `LLM_DEFAULT_MODEL` / `LLM_MODELS` in `.env` to use Groq or
Gemini instead.

## Connect an MCP client to the Operations server

The Operations MCP server (`http://localhost:8103/mcp`, localhost only) lets any MCP client
list a pack's action catalogue, propose actions and execute actions a person has approved. It
has no approve tool. Use the `OPERATIONS_MCP_EXTERNAL_TOKEN` from `.env`, for example with
Claude Code:

```bash
claude mcp add --transport http watchdog-ops http://localhost:8103/mcp \
  --header "Authorization: Bearer $(grep ^OPERATIONS_MCP_EXTERNAL_TOKEN= .env | cut -d= -f2-)"
```

Tools take an optional `domain` (`insurance_claims`, `procure_to_pay`). Every call is recorded
in the hash-chained audit log under the client's name.

## Repository layout

```
backend/            FastAPI app (src/watchdog_backend), Alembic migrations, tests
  domain/           domain-pack schema and the active pack (per request / job / thread)
  analytics/        metrics engine (pack metrics → safe, parameterised SQL) and
                    SQL-native process mining (process map, variants, bottlenecks)
  generator/        synthetic data per pack, with planted root causes, decoys, ground truth
  knowledge/        document parsing, section-aware chunking, hybrid retrieval, cited answers
  llm/              provider-agnostic LLM gateway (Ollama, Groq, Gemini)
  investigation/    LangGraph investigation: scan → plan → evidence → assess → recommend →
                    summary, with confounder and evidence rules, what-if, number verification
  governance/       action rules (roles, separation of duties, approve-before-execute), audit
  identity/         accounts, sessions, platform roles (RBAC) and per-pack business roles
  observability/    LLM-call and API-request recording, summaries, investigation traces
  watch/            KPI monitors, alerts, action follow-ups, next-month simulator (demo)
  evaluation/       harness: investigations vs planted truth, Q&A, retrieval, what-if
  mcp_servers/      Operations MCP server (governed actions for any MCP client)
  enterprise_mock/  stand-in for the client's systems of record
domain_packs/       one folder per process: pack, metrics, monitors, actions, governance,
                    policy documents, benchmarks (insurance_claims, procure_to_pay)
evaluation/         saved evaluation runs (results.jsonl per run) and notes on fixes
frontend/           React + Vite + Tailwind UI
docs/               case study, evaluation report, project brief, demo script, pack guide
.github/            CI: lint, migrate, test, migration round-trip, frontend build
```

> Status: **M8 in progress**: second domain pack, case study, accounts and RBAC,
> observability, cost controls and model comparison done; public deployment next.
