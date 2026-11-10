# Intelligence WatchDog — Project Brief

> Working document. Records the decisions made so far and the agreed scope.
> Last updated: 2026-11-10.

## 1. One-liner

An AI operations analyst that **watches** business process KPIs, **investigates** why they drift, **recommends** fixes backed by evidence and ROI, and **acts** only with human approval.

**Watch → Investigate → Recommend → Act**

## 2. Purpose and audience

- **Why:** flagship portfolio project for a long-running job search targeting *Enterprise AI Solutions Consultant / Agentic AI / Process Intelligence* roles.
- **Story:** EY (consulting, procurement transformation) → SkanAI (production AI, process intelligence) → Intelligence WatchDog (independent end-to-end solution ownership).
- **What a long job search implies:**
  - A **live public demo** is worth having, not only a video.
  - Every milestone should be **demoable on its own**, so the project is always presentable mid-build.
  - Quality and an honest evaluation matter more than breadth.
  - The project keeps evolving, so a clean architecture pays off.

## 3. Decision log

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Name: **Intelligence WatchDog**; repo: `intelligence-copilot` | The name suggests monitoring, so we add a "Watch" layer (see §4) to back it up. |
| D2 | **Start from a clean repo**; don't use the earlier infrastructure ZIP | Only what we need, built in an order we understand. |
| D3 | **LLM provider is swappable** (chat and embeddings) | Model-agnostic design. The evaluation can compare cost and quality across providers, which is a strong consultant talking point. |
| D4 | **Calculations live in code; the LLM interprets** | The LLM never invents a KPI. Every number traces back to a deterministic function or SQL query. |
| D5 | **Metrics layer, not free-form text-to-SQL** | Metrics are defined as parameterised SQL in the domain pack. The LLM picks metric, filters and grouping. Free-form SQL can come later as a clearly labelled "exploratory" fallback. |
| D6 | **Synthetic data with planted root causes** | Makes recommendations specific, supplies ground truth for evaluation, and gives a controlled demo story. |
| D7 | **Hypothesis-driven investigation** shown in the UI | Hypotheses → evidence for/against → conclusion → action. This is the differentiator, more than "multi-agent". |
| D8 | **Modular monolith**; MCP servers run as separate processes | Simple to run and debug. The MCP interfaces stay independently testable. |
| D9 | **Approvals enforced in the backend** | Write tools can't run without a recorded approval, whichever client calls them (UI, agent or an external MCP client). |
| D10 | **One full domain pack first** (Insurance Claims), then a thin second one (Procure-to-Pay) | Proves the engine is horizontal without tripling the work. |
| D11 | **Local first** (Docker Compose); GCP later | ₹0 infrastructure spend until there is something worth deploying. |
| D12 | **Zero spend, including the LLM.** Default chat model on a **free API tier (Groq)**; **Gemini free tier** as the comparison provider; **Ollama** as the offline fallback | Free tiers are rate-limited (roughly 1,000 requests/day per model on Groq; verify limits on official pages). Prompts may be used for training, which is acceptable because all data is synthetic. |
| D13 | **Embeddings run locally** (sentence-transformers / Ollama embedding model) | Free, no rate limits, works on CPU; no third-party dependency for retrieval. |
| D14 | **Response cache + recorded demo runs** | Investigations are cached by input hash and showcase runs can be replayed, so the public demo survives free-tier limits. |
| D15 | **GitHub OAuth** for the public demo | Free; the audience (recruiters, engineers) mostly has GitHub accounts. |
| D16 | **Currency INR; Indian insurance context** | Realistic and matches the author's domain experience. Amounts in ₹, lakh/crore formatting in the UI. |

## 4. Product shape

### Watch (gives the name its meaning)
- Each domain pack defines **KPI monitors**, e.g. `sla_breach_rate > 15%` or `avg_cycle_time week-over-week +20%`.
- A scheduled job evaluates the monitors in code (no LLM) and raises **alerts**.
- An alert can **start an investigation** with one click. Auto-triage comes later.

### Investigate
- The user asks a question or opens an alert.
- The **Planner** writes an investigation plan as a list of hypotheses.
- **Evidence gathering** calls tools: metrics, process mining, document retrieval.
- Each hypothesis is marked **supported / refuted / inconclusive** and cites its evidence.
- Simple questions skip the full flow and go straight to one tool.

### Recommend
- Root causes are ranked by impact.
- ROI is computed in code from explicit, editable assumptions (hourly cost, volume, penalty per breach), with guards against double counting.
- Every recommendation links to its evidence: query results, process stats and policy citations.

### Act
- Proposed actions, e.g. change an approval threshold, rebalance a queue, escalate cases.
- Approve or reject; execution goes through the Operations MCP to a mock enterprise API; every step is written to the audit trail.

## 5. Primary scenario: Insurance Claims SLA investigation

> "Why are claims breaching the five-day SLA? Find the causes, the responsible stages, and recommend corrective actions."

### Planted root causes (draft; numbers are tunable in the generator)

| ID | Root cause | How it shows in the data | Corroborating document |
|----|-----------|--------------------------|------------------------|
| RC1 | High-value claims (> ₹5L) wait for senior adjuster approval; the senior queue is understaffed | Long waiting time before `Senior Approval`; ~3 days vs a 24h policy | Approval matrix + SLA policy (24h senior-approval target) |
| RC2 | Broker-channel claims are often missing documents at intake | `Request Additional Documents` loop on ~20% of broker claims, adding ~2–3 days | Intake SOP requires a document checklist at FNOL |
| RC3 | One verification team has a high QA rejection rate | Rework loop `Verification → QA → Verification` ~18% for Team B vs ~5% for others | QA SOP / verification guidelines |
| RC4 | Handoffs late on Fridays sit idle over the weekend | Larger waiting time for cases handed off Friday after 15:00 | Working-hours policy (no weekend coverage) |

### Decoys (test analytical rigour)

| ID | Looks like | Actually |
|----|-----------|----------|
| DC1 | "Health claims are slower" | Confounded by claim value: health claims skew high-value, so the real cause is RC1. |
| DC2 | "The Pune region is underperforming" | Small sample; not statistically meaningful. |

The evaluation checks that the system **finds RC1–RC4** and **does not report DC1–DC2 as root causes**.

### Data volumes
- ~5,000 claims, ~25,000 events, 10–15 policy/SOP documents (generated, realistic, internally consistent with the planted causes).

## 6. Architecture (prototype)

```
React (Vite + TS + Tailwind)
        │  REST + SSE (streamed investigation steps)
        ▼
FastAPI ── LangGraph investigation graph
        │     Planner → Evidence gathering → Synthesis → Action proposal
        │                     │
        │        ┌────────────┼──────────────┐
        │        ▼            ▼              ▼
        │   Metrics layer  Process mining  Retrieval (hybrid + rerank)
        │   (domain pack)  (PM4Py)         (pgvector + full-text)
        │
        ├── Watch: scheduled KPI monitors → alerts
        ├── Governance: approvals, permissions, audit
        └── LLM gateway: provider-agnostic chat + embeddings (config-driven)

PostgreSQL 17 + pgvector    Operations MCP server (separate process) → mock enterprise API
```

### Key internal interfaces
- **LLM gateway:** a single place to configure provider and model per role (planner, synthesis, cheap classification). The embedding model ID and dimension are stored with each vector, and changing the model means a re-embed.
- **Tool registry:** every tool has a Pydantic input/output schema and is marked `read` or `write`. Write tools require an `approval_id`, checked server-side.
- **Domain pack:** `config.yaml`, `process_schema.yaml`, `metrics.yaml`, `monitors.yaml`, `terminology.yaml`, `rules.yaml`, plus sample data and documents.

### Stack
| Area | Choice |
|------|--------|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, `uv` |
| Orchestration | LangGraph |
| Process mining | PM4Py |
| Database | PostgreSQL 17 + pgvector |
| Frontend | React, Vite, TypeScript, Tailwind, Recharts |
| MCP | Official MCP Python SDK |
| Observability | Langfuse (optional, toggle by env) |
| Evaluation | Pytest (deterministic), custom ground-truth benchmark, RAGAS-style retrieval metrics |
| Runtime | Docker Compose locally; GCP Compute Engine later |

## 7. Scope

**In v1**
- Insurance Claims domain pack (full)
- Data generator with planted causes and decoys
- Metrics layer, process mining (variants, DFG, waiting times, rework, SLA)
- Document ingestion and hybrid retrieval with citations
- Investigation graph with hypotheses and streamed UI
- ROI calculator
- Operations MCP server, approval workflow, audit log
- KPI monitors and alerts (Watch)
- Ground-truth evaluation and report
- 3 screens: **Watch & Overview**, **Investigation**, **Action Centre** (plus a minimal Knowledge upload page)

**Later**
- Procure-to-Pay pack (proves the engine is horizontal)
- Analytics and Knowledge MCP servers, so external MCP clients can use them
- Agent observability screen
- Public deployment, auth, rate limiting
- Exploratory free-form SQL (read-only, sandboxed)

**Out (for now)**
- Multi-tenancy, Kubernetes, Kafka, Databricks/PySpark, Patient Intake pack

## 8. Milestones (each one demoable)

| M | Milestone | Demo at the end |
|---|-----------|-----------------|
| M0 | Foundation: repo layout, Compose (Postgres + backend + frontend), config, CI | `docker compose up` → health page |
| M1 | Data generator + domain pack schema + metrics layer | API returns SLA breach rate and cycle time by stage; tests prove numbers match generator ground truth |
| M2 | Process mining + overview dashboard | Process map, bottleneck stages, rework loops in the UI |
| M3 | Document generation, ingestion, retrieval with citations | Ask a policy question → cited answer |
| M4 | Investigation graph (planner → evidence → synthesis) + ROI | Full SLA investigation streamed in the UI with hypotheses and evidence |
| M5 | Actions: Operations MCP, approvals, audit, mock API | Approve an action → executed → audit trail; same MCP server used from an external MCP client |
| M6 | Watch: monitors, alerts, alert → investigation | Alert fires → one click → investigation |
| M7 | Evaluation: ground-truth benchmark, retrieval metrics, multi-model comparison | `evaluation_report.md` with real numbers, including failures |
| M8 | Second domain pack (P2P) + public deployment + case study | Live URL, README, 3–5 min video |

## 9. Evaluation (targets, not results)

| Metric | Target |
|--------|--------|
| Planted root causes found (RC1–RC4) | ≥ 3 of 4 on average across runs |
| Decoys reported as causes | 0 |
| Metric calculation accuracy vs ground truth | 100% (deterministic) |
| Retrieval Recall@5 | ≥ 85% |
| Citation correctness | ≥ 90% |
| Approval bypass attempts that succeed | 0 |
| Simple query latency | < 15 s |

Report actual results with failures. Compare at least two LLM providers on quality, cost and latency.

## 10. Open questions

- Free hosting for the public demo (M8): candidates are Oracle Cloud Always Free (ARM VM) or GCP trial credits. Decide at M8.
- Confirm which free-tier models handle multi-step tool calling reliably. Test this in M4 before committing to a default.
- Local GPU (RTX 4050, 6 GB) suits small models only. **2026-11-10 smoke test:** `qwen2.5:7b` via Ollama (100% GPU) produced a correct structured `query_metric` call 3/3 times at ~1.6 s. Good enough for tool selection and argument filling, and the default for development. Whether it can handle planning and synthesis is still open (test in M4).
- Docker → host Ollama: Ollama listens on `127.0.0.1:11434` only. When the backend container needs it (M3/M4), add `host.docker.internal:host-gateway` to the backend service and make Ollama listen on the Docker bridge (`OLLAMA_HOST` in its systemd unit).
