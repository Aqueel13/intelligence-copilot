# Intelligence WatchDog — Project Brief

> Working document. Records the decisions made so far and the agreed scope.
> Last updated: 2026-11-12 (M8: cache, showcase, limits; Analytics/Knowledge MCP, exploratory SQL, auto-triage).

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
| D14 | **Response cache + recorded demo runs** | Investigations are cached by input hash and showcase runs can be replayed, so the public demo survives free-tier limits. Built in M8, see D48. |
| D15 | **GitHub OAuth** for the public demo | Free; the audience (recruiters, engineers) mostly has GitHub accounts. |
| D16 | **Currency INR; Indian insurance context** | Realistic and matches the author's domain experience. Amounts in ₹, lakh/crore formatting in the UI. |
| D17 | **Process mining in SQL, not PM4Py** | PM4Py is AGPL v3, which would force the whole app (including the hosted demo) to be AGPL. The process map, variants and bottlenecks are computed exactly in SQL, keeping the license choice open. |
| D18 | **Embeddings and reranking via fastembed (ONNX)**: `BAAI/bge-small-en-v1.5` (384-d, MIT) and `Xenova/ms-marco-MiniLM-L-6-v2` (Apache) | No PyTorch (environment stays ~450 MB), CPU-only, runs in CI. Embeddings are stored with their model ID in an untyped `vector` column, so changing models means re-embedding, not a schema change. |
| D19 | **Default retrieval = hybrid (vector + full-text, RRF), no reranking** | Measured on the 28-question benchmark: hybrid reaches Hit@3 = Hit@5 = 1.00; reranking adds ~300 ms per query and no measurable gain on this corpus. Reranking stays available and benchmarked. |
| D20 | **Citations are verified, not trusted** | The cross-encoder scores every answer sentence against every retrieved source. Unsupported citations are corrected to the best source (only if it scores ≥ 3.0) or flagged. Both the model's own citation accuracy and the final grounding are recorded. qwen2.5:7b often cites the wrong source number for correct statements. |
| D21 | **Containers reach host Ollama through a relay** | A socat container on the host network listens only on the Docker bridge (172.17.0.1) and forwards to Ollama on localhost. Ollama is never exposed to the LAN (the laptop has no firewall). |
| D22 | **Investigations: code computes, the LLM reasons** | A deterministic scan (significance tests, bottlenecks, weekday effects, trend) runs before any LLM call. The planner picks checks from a typed menu; code runs them and writes the evidence text the model reads. Outputs use flat schemas so a local 7B model fills them reliably. |
| D23 | **Rule overrides on verdicts** | Segment effects are automatically re-tested within amount band, line of business and channel. If the effect disappears, a "supported" verdict is overridden to "refuted" and the override is shown. Small, non-significant samples cannot be "supported". |
| D24 | **Coverage rule** | Any strong, significant signal that no planned hypothesis tests gets its own hypothesis (marked "coverage"), so planner variance cannot silently drop a root cause. If planning fails, hypotheses are built from signals alone. |
| D25 | **Action catalogue + what-if engine** | Corrective actions live in the domain pack with the policy clause that permits them and a lever. A deterministic what-if on the event log values each one (breaches avoided, illustrative ROI). Validated against the generator's exact counterfactuals; the Saturday rota lever was corrected after it overstated impact 4×. |
| D26 | **Every number in the summary is verified** | Numbers in the executive summary must match the computed facts (±1%); otherwise the model rewrites once, and anything still unverified is flagged in the UI. |
| D27 | **One governance service, two doors** | Proposal, approval and execution rules live in `governance/service.py`; the API and the Operations MCP server both call it. The backend executes through the MCP server like any other client, and the server re-checks before anything changes. |
| D28 | **Agents cannot approve** | The Operations MCP server has no approve tool, and the service refuses decisions from non-users. Approvers need a role named in `governance.yaml` (taken from the policies, e.g. POL-002 §4.3 → Head of Claims), and the proposer may not approve (separation of duties). |
| D29 | **Tamper-evident audit log** | Every attempt, including every refusal, is appended with a SHA-256 hash chain; refusals are committed even when the request fails. Editing, inserting or deleting an entry is detected by `/api/audit/verify`. |
| D30 | **MCP SDK v2, static bearer tokens** | Each MCP client has its own token (identity in the audit log). Published on localhost only. Refusals are raised as `ToolError` so clients see *why*; unexpected errors stay opaque. Demo user identities are self-asserted until M8 adds login. |
| D31 | **Monitors as configuration, thresholds from policy** | `monitors.yaml` in the domain pack; evaluated monthly through the metrics engine. Consecutive-month rules mirror the policies (POL-002 §5, SOP-105 §5.1); low-sample months never alert. One open alert per monitor and segment, resolved automatically. |
| D32 | **Follow-ups close the loop** | Each catalogue action names the metric it should move and a target; after execution the Watch layer compares before vs after and reports on target / improving / no change / worse. |
| D33 | **"Simulate next month" is a labelled demo device** | The historical data ends in September, so the same generator appends a synthetic month with executed actions applied (trends continue). Recorded in `simulated_months`; `make seed` resets it. |
| D34 | **Per-case activity counts are materialized** | Postgres cannot estimate selectivity of JSONB-attribute filters; for narrow filters it chose a plan that re-aggregated all events per case (a 2-second query took ~5 minutes). An indexed materialized view, refreshed by the loader, makes every plan cheap. |
| D35 | **Evaluation in an isolated database, scored against planted truth** | `python -m watchdog_backend.evaluation` reloads `<db>_eval` per generator seed and runs four suites (investigations, grounded Q&A, retrieval, what-if). Results are appended per run, merged across runs (later re-runs replace earlier results, which stay listed), and written to `docs/evaluation_report.md`. Rate-limited runs are reported separately from model failures; provider account ids are redacted. |
| D36 | **JSON-schema structured output by default, wall-clock LLM deadlines** | Found by the evaluation: tool calling failed on two Groq models (JSON schema 3/3), and a slowly streaming server could stall a run for minutes. |
| D37 | **Symmetric safeguards without re-judging the model's words** | Downgrades stop decoys; upgrades stop over-caution. Upgrades act only on code-worded hypotheses (coverage hypotheses, or a new "Evidence-confirmed" finding) whose evidence meets strict criteria, because flipping a verdict on a sentence the model wrote can assert something false. |
| D38 | **Parallel hypothesis assessment** | Hypotheses are independent; judged concurrently (`LLM_PARALLEL_CALLS`). Small gain on a single local GPU (Ollama serialises), real gain on cloud providers. |
| D39 | **Packs side by side, chosen per request** | Both packs share one database (every row carries `domain`). The active pack is a context variable set from the `X-Domain` header, per watcher job and per CLI run; threads copy it. A UI switcher shows the same engine on two processes, which a one-pack-per-deployment setup would hide. |
| D40 | **Everything the investigation assumes about a process lives in `pack.yaml`** | Scanned dimensions, confounder controls, loop outcomes, wait targets, prompt wording, Overview tiles and example questions were constants in code; moving them out was most of the work of the second pack. Planted-truth scoring moved to each pack's benchmark file. |
| D41 | **Second pack: Procure-to-Pay, invoice-to-pay** | Closest to the author's procurement-transformation background. Planted causes exercise different checks from insurance: a plant-specific queue (goods receipts), a PO-type loop (price exceptions), a team loop (capture errors), and a change over time (payment runs cut to weekly). Decoys are confounded by a *different* control each (PO type, AP team). |
| D42 | **Month-by-month queue check** | A queue every case passes through has no "without" group, so the existing bottleneck evidence could not confirm P2P's weekly payment run. The activity check now reports monthly waits and their correlation with the breach rate; the scan and the strict evidence rule accept a material queue whose wait rose 30%+ and moved with breaches (r ≥ 0.8, p < 0.05). Generic: it applies to every pack. |
| D43 | **Local accounts now, GitHub sign-in later** | Sign-in with scrypt-hashed passwords and a database session in an HttpOnly, SameSite=Lax cookie (the token is stored hashed). GitHub OAuth will attach to the same `identity.users` table at deployment. |
| D44 | **Two-layer access: platform role + business role per pack** | Platform roles (viewer, analyst, admin) gate capabilities (investigate, propose, approve, execute, simulate, manage users), enforced per route. Approval still needs the business role the pack's governance names, so an admin cannot approve an action unless their role in that pack allows it. Admins may act as another user for demos: the effective user is the governance actor (separation of duties still holds) and the real admin is recorded in `via` and the audit log. |
| D45 | **Built-in observability** | Every LLM call (role, model, tier, tokens, latency, status, investigation, user) and API request is written to Postgres by a background writer, never on the request path, kept 30 days. An Observability page shows percentiles, errors, cache hits, the Groq free-tier quota per model and per-investigation traces. It found two bugs on its first day (parallel assessment lost its context; cache hits were never recorded). |
| D46 | **Answer cache: exact or near-identical, same numbers, same corpus** | Reuse an answer when the normalised question matches, or embedding similarity ≥ 0.97 AND the questions mention the same numbers (₹3 lakh and ₹30 lakh embed almost identically). Keyed by a hash of the pack's document versions and the retrieval settings, so any document change invalidates it. Evaluation bypasses the cache. |
| D47 | **A light model tier for simple requests** | Question routing and short single-document policy lookups go to `LLM_LIGHT_MODEL` when set; reasoning, comparison and multi-document questions stay on the standard model. The rule is explainable and its reason is shown and recorded. On one small local GPU a second local model mostly adds swap time; the tier pays off on quota-limited cloud models. |
| D48 | **Investigations replay from a recording: cache hits and showcase runs** | Each run stores the event stream it produced. An identical request (normalised question, scope, models, and hashes of the case data, documents and pack YAML) replays the latest run in seconds with no model call; "Run it fresh" forces a new one. Admins mark good runs as showcase; anyone, viewers included, can replay them at a watchable pace. Runs from before the recording existed can be read but not replayed. The evaluation calls the graph directly and never uses the cache. |
| D49 | **Rate limits only on what spends tokens, counted in Postgres** | Per person per hour and for everyone per day (the free tier's daily token cap is shared by every visitor), sized for Groq's 200k tokens/day/model: 4 and 12 investigations, 20 and 80 policy questions by default. Cache hits and replays are free, so limits never block the demo path. Admins are exempt; while an admin acts as someone, the admin's own limits apply. Counts live in `identity.usage_events`, so they survive restarts and hold with several workers. A limited request gets HTTP 429 with Retry-After and a plain-language reason. |
| D50 | **Analytics and Knowledge MCP servers: read-only, own tokens, no LLM** | Analytics wraps the metrics engine, process mining, alerts, investigations and exploratory SQL, so a client gets the same numbers as the web app. Knowledge returns passages and documents, not answers: the client is a model and can read them, so the server spends no tokens. Each server accepts only its own tokens (a Knowledge token is refused by Analytics). Shared plumbing (token check, pack switching, transport) is in `mcp_servers/common.py`, which Operations now uses too. |
| D51 | **Exploratory SQL: labelled, and sandboxed in layers** | D5's fallback. One SELECT over three views of the active pack (`cases`, `events`, `feedback`), typed or drafted by a model and always shown before it runs. Layers: validation (one statement; no comments, dollar quoting, backslashes, unbalanced parentheses or session/server functions), then a `watchdog_explorer` role that can only SELECT those views, in a READ ONLY transaction with a 5 s timeout, wrapped as a subquery (Postgres then rejects data-modifying CTEs), capped at 500 rows, on a connection that is closed afterwards. Results are marked "not a verified metric". Analysts and admins only; model drafts count against the question limit. |
| D52 | **Automatic triage: rank, then investigate the top alert** | After monitors run (watcher schedule, "Run monitors", "Simulate next month"), open untriaged alerts are ranked: critical first, then distance past threshold, then age. The top one per pack per run is investigated as the system user with the alert's own question and scope; an identical earlier run is linked instead (free, and does not use up the run's slot); the shared daily investigation budget applies, and an alert over budget is marked skipped with the reason and reconsidered on later runs (a failed run is not retried automatically, and is never linked to the alert). Alerts are claimed with a conditional UPDATE so the watcher and the app never double-run one. `WATCH_AUTO_INVESTIGATE` = off, critical (default) or all. The first live run found that the watcher container could not reach the models (no model cache or Ollama route), recorded as "failed" on the alerts; fixed in compose. Two flaws found the same way and fixed: failed runs were linked to the alert (hiding the Investigate button), and skipped alerts were never retried. |

## 4. Product shape

### Watch (gives the name its meaning)
- Each domain pack defines **KPI monitors**, e.g. `sla_breach_rate > 15%` or `avg_cycle_time week-over-week +20%`.
- A scheduled job evaluates the monitors in code (no LLM) and raises **alerts**.
- An alert can **start an investigation** with one click, and new critical alerts are
  **triaged automatically** (D52).

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
| RC1 | High-value claims (> ₹2L) wait for senior adjuster approval; the senior queue is understaffed | Long waiting time before `Senior Approval`; ~4 days (96h average) vs a 24h policy, worsening Apr → Sep | Approval matrix (senior sign-off above ₹2,00,000) + SLA policy (24h senior-approval target) |
| RC2 | Broker-channel claims are often missing documents at intake | `Request Additional Documents` loop on ~20% of broker claims, adding ~2–3 days | Intake SOP requires a document checklist at FNOL |
| RC3 | One verification team has a high QA rejection rate | Rework loop `Verification → QA → Verification` ~18% for Team B vs ~5% for others | QA SOP / verification guidelines |
| RC4 | Handoffs late on Fridays sit idle over the weekend | Larger waiting time for cases handed off Friday after 15:00 | Working-hours policy (no weekend coverage) |

### Decoys (test analytical rigour)

| ID | Looks like | Actually |
|----|-----------|----------|
| DC1 | "Health claims are slower" | Confounded by claim value: health claims skew high-value, so the real cause is RC1. |
| DC2 | "The Pune region is underperforming" | Small sample; not statistically meaningful. |
| DC3 | "Average CSAT is 2.9, so customers are broadly unhappy" | Response bias: dissatisfied customers respond more often. The raw average understates true satisfaction and must be reported with its sample caveat. |

The evaluation checks that the system **finds RC1–RC4** and **does not report DC1–DC3 as conclusions**.

### Process flows (reimbursement claims; cashless pre-authorisation is out of v1)

```
Motor:  FNOL → Document Check → (Request Docs loop) → Survey & Loss Assessment → Verification → QA → (Senior Approval > ₹2L) → Settlement → Closed
Health: FNOL → Document Check → (Request Docs loop) → Medical Adjudication     → Verification → QA → (Senior Approval > ₹2L) → Settlement → Closed
```

Survey = IRDAI-licensed surveyor inspects the vehicle and files a loss assessment. Medical Adjudication = TPA or in-house medical team reviews bills and coverage.

### Customer satisfaction survey (post-closure)

- **Separate table** (`claim_feedback`), not a process event, so it can't distort cycle times or appear as a bottleneck.
- Fields: `claim_id`, `sent_at`, `responded_at`, `csat` (1–5), `nps` (0–10), `comment`.
- Sent 1–3 days after closure; a minority responds, and dissatisfied customers respond more often (planted bias, DC3).
- **Scores are driven by the planted causes.** Claims affected by RC1–RC4 score lower, so investigations can quantify customer impact per root cause.
- **Comments are generated from templates** with varied wording that reference the claim's actual experience (re-requested documents, approval waits, surveyor no-shows). No LLM is used, so the data is reproducible and the ground truth is exact.
- Data lands in M1. A feedback/theme-analysis tool for the agents comes in M4.

### Data volumes
- ~5,000 claims, ~38,000 events, ~1,250 survey responses, 10–15 policy/SOP documents (generated, realistic, internally consistent with the planted causes).

### Calibrated ground truth (seed 42, M1)

Computed by exact counterfactual: each claim is re-simulated with one cause switched off, using identical randomness. A breach is *attributable* to a cause if removing that cause alone would have met the SLA.

| | Value |
|---|---|
| SLA breach rate | 31.0% (10.0% with no planted cause) |
| RC1 senior approval queue | 40.4% of breaches · 1,239 claims affected |
| RC2 broker missing documents | 8.0% of breaches · 274 claims |
| RC3 Team B rework | 4.9% of breaches · 206 claims |
| RC4 late-Friday handoffs | 6.4% of breaches · 847 claims |
| Delegating ₹2L–₹5L approvals | avoids 33% of breaches |
| DC1 | health ≈ motor within each amount band (e.g. 3.07 vs 3.16 days below ₹50K) |
| DC2 | Pune: 58 claims, 66% broker (vs 30% elsewhere) |
| DC3 | respondent CSAT 3.58 vs true 3.91; 25% response rate |

Calibration ranges are enforced by tests, so a generator change that weakens the story fails CI.

## 5b. Second scenario: Procure-to-Pay (invoice-to-pay)

> "Why are invoices missing the ten-day payment target? Find the root causes and recommend corrective actions."

Varaha Auto Components (fictional), five plants, 6,000 supplier invoices over six months. One
case is one invoice, from receipt to payment release; the target is 10 calendar days (early-
payment discounts; well inside the MSMED Act limits for small suppliers).

| ID | Root cause | How it shows in the data | Corroborating document |
|----|-----------|--------------------------|------------------------|
| RC1 | Chakan's stores post goods receipts late (one GRN clerk short since March) | More invoices reach matching before their GRN, and wait ~5–6 days for it | WH-201 (GRN within 1 working day; Chakan staffing) |
| RC2 | Free-text POs have no agreed price | Price exceptions on ~55% of free-text invoices vs ~5% otherwise | PRC-101 (free-text rules), AP-103 (tolerance) |
| RC3 | The BPO Partner's capture errors | Re-capture loop on ~40% of BPO-captured invoices vs ~4% in-house | AP-102 (97% first-time-right; BPO quality plan) |
| RC4 | Treasury suspended the Tuesday payment run from 1 July | Wait before `Payment Run` rises from ~54h to ~78h; breach rate steps up in July | TRS-401 (twice-weekly calendar; change log) |

| ID | Looks like | Actually |
|----|-----------|----------|
| DC1 | "IT and professional services invoices are slow" | They are mostly free-text POs (RC2); within the same PO type they are not slower. |
| DC2 | "MSME suppliers are paid late" | Their paper invoices mostly go to the BPO Partner (RC3); within the same AP team they are not slower. |

Calibrated ground truth (seed 42): breach rate 30.7% (8.3% without any planted cause); share of
breaches attributable to RC1 12%, RC2 23%, RC3 20%, RC4 18%. Stable across seeds 7 and 1234.

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
        │   (domain pack)  (SQL-native)    (pgvector + full-text)
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
| Process mining | SQL-native (directly-follows graph, variants, waiting times). PM4Py is AGPL v3, so it is not a dependency; it may return later as an optional extra for conformance checking. |
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

**Later** (all built in M8 except deployment and GitHub sign-in)
- Procure-to-Pay pack (proves the engine is horizontal)
- Analytics and Knowledge MCP servers, so external MCP clients can use them (D50)
- Public deployment, GitHub sign-in, rate limiting (limits: D49)
- Exploratory free-form SQL (read-only, sandboxed) (D51)
- Automatic triage of alerts (D52)

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

### M4 results (2026-11-10, seed 42, question: "Why are claims breaching the five-day SLA?")

| | Groq `openai/gpt-oss-120b` | Local `qwen2.5:7b` (RTX 4050) |
|---|---|---|
| Planted causes found | 4 / 4 | 4 / 4 (RC4 inside a combined broker hypothesis) |
| Decoys accepted | 0 (DC1 caught by override) | 0 (DC1 caught by override; DC2 refuted) |
| Summary numbers unverified | 0 / 41 | 0 / 15 |
| Duration | ~80 s | ~60 s |

Single runs, not yet a benchmark: M7 repeats these across seeds and models. Observations: the 7B model needed the coverage rule and the override more often; the 120B model is more conservative and initially called loop effects "inconclusive" until mechanism evidence (breach rate with vs without the loop) was added.

### M6 results (2026-11-10)

Closed loop on the dev data: delegation and Team B retraining were executed in M5, then October was simulated with both applied.

| Monitor | Sep | Oct | Outcome |
|---|---|---|---|
| SLA breach rate | 34.0% | 19.0% | alert resolved |
| Team B rework | 20.1% | 3.6% | resolved; follow-up on target (≤ 5%) |
| Senior Approval wait, ₹2L–₹5L | ~111 h | 14.7 h | delegation follow-up on target (≤ 24 h) |
| Senior Approval wait, all | 130 h | 37.7 h | still critical: claims above ₹5L still queue |
| Broker documents | 22.8% | 26.5% | still critical: no action taken yet |

### M7 results (2026-11-10): see `docs/evaluation_report.md`

36 scored investigations (4 models × 3 seeds × 3 questions; 5 refused by Groq's free daily quota; 12 earlier runs repeated after fixes), 132 policy answers, retrieval and what-if suites.

| Model | Investigations completed | Mean recall | Decoys accepted | Model's own citation accuracy |
|---|---|---|---|---|
| `ollama:qwen2.5:7b` (local, free) | 9/9 | 100% | 0 | 75% |
| `groq:openai/gpt-oss-20b` | 7/9 | 100% | 0 | 69% |
| `groq:qwen/qwen3.8-27b` | 9/9 | 97% | 0 | 97% |
| `groq:openai/gpt-oss-120b` | 6/9 | 79% | 0 | 73% |

No model accepted a decoy in any run. Every miss was over-caution (a supported cause left inconclusive or wrongly refuted); D37 now addresses it with code-worded upgrades. Unverified numbers in summaries: 0 across all completed runs. Pending: re-run the cloud models' broker question (predates a what-if fix) and the five quota-refused runs.

### M8 results so far (2026-11-10): second domain pack

Procure-to-Pay on the same engine, local `qwen2.5:7b`, seeds 42, 7, 1234:

| Investigations | Mean recall | Decoys accepted | Remedy recommended | Q&A grounded | Retrieval hit@5 |
|---|---|---|---|---|---|
| 9/9 completed | 100% (every cause in every run) | 0 / 9 runs | 17/18 causes | 100% (model's own citations 86%) | 100% (all methods) |

The 7B model called a confounded segment "supported" 25 times; the confounder rule refuted all
of them. Insurance results unchanged (all 165 earlier tests pass; 26 new P2P tests).

### M8 platform work (2026-11-11 to 2026-11-12)

Accounts and two-layer RBAC (D43, D44), built-in observability (D45), the policy-answer cache
(D46), a light model tier (D47), the investigation cache with showcase replay (D48) and rate
limits (D49), the Analytics and Knowledge MCP servers (D50), exploratory SQL (D51) and
automatic triage of alerts (D52). 248 backend tests pass.

Remaining M8: public deployment (hosting, HTTPS, GitHub sign-in) and the video. Everything the
deployment needs from the app itself (showcase runs, limits, secure cookies) is in place.

## 10. Open questions

- Free hosting for the public demo (M8): candidates are Oracle Cloud Always Free (ARM VM) or GCP trial credits. Decide at M8.
- Confirm which free-tier models handle multi-step tool calling reliably. Test this in M4 before committing to a default.
- Local GPU (RTX 4050, 6 GB) suits small models only. **2026-11-10 smoke test:** `qwen2.5:7b` via Ollama (100% GPU) produced a correct structured `query_metric` call 3/3 times at ~1.6 s. Good enough for tool selection and argument filling, and the default for development. Whether it can handle planning and synthesis is still open (test in M4).
- Docker → host Ollama: Ollama listens on `127.0.0.1:11434` only. When the backend container needs it (M3/M4), add `host.docker.internal:host-gateway` to the backend service and make Ollama listen on the Docker bridge (`OLLAMA_HOST` in its systemd unit).
