# Intelligence WatchDog: case study

**An AI operations analyst that watches process KPIs, investigates why they drift, recommends
fixes with evidence and ROI, and acts only with human approval. One engine, two business
processes, evaluated against planted ground truth.**

Built end to end on a zero budget (local and free-tier LLMs) as an independent project, after
consulting at EY (procurement transformation) and building production process-intelligence AI
at SkanAI.

---

## 1. The problem

Operations leaders run on KPIs: claim turnaround, invoice-to-pay time, first-time-right rates.
When one drifts, the usual path is slow and manual. Someone notices weeks late, an analyst
spends days slicing data, and the findings are often wrong in a predictable way. The obvious
segment ("health claims are slower", "small suppliers get paid late") turns out to be a
symptom of something else.

GenAI copilots promise to shortcut this, but the generic version fails where it matters most to
an enterprise buyer:

- **Numbers.** A language model asked "why is the breach rate up?" will happily produce a
  plausible percentage that no query ever returned.
- **Rigour.** Models take correlations at face value. Confounded segments are exactly what a
  plausible-sounding analysis gets wrong.
- **Control.** An agent that can change systems needs approvals, separation of duties and an
  audit trail that the agent itself cannot bypass.
- **Proof.** "It looked good in the demo" is not evidence. Buyers need to know how often it is
  right, and how it fails.

## 2. What I built

```
 WATCH ──────────▶ INVESTIGATE ──────────▶ RECOMMEND ──────────▶ ACT
 KPI monitors       scan → hypotheses →      catalogue actions,     propose → human
 from policy        evidence → verdicts      valued by a what-if    approval → execute
 thresholds         (with safeguards)        engine, with policy    via MCP → audit →
                                             citations and ROI      follow-up metric
```

- **Watch.** Monitors defined in configuration, with thresholds taken from the client's own
  policies ("critical if above 24 hours for two consecutive months"). Alerts open, update and
  resolve themselves. New critical alerts are triaged automatically: ranked, and the top one
  investigated within a daily budget (an identical earlier run is linked instead). Any alert
  can also be investigated with one click, scoped to the alert.
- **Investigate.** A LangGraph workflow. Code scans the data for every significant pattern,
  the LLM turns patterns into hypotheses and picks checks from a fixed menu, code runs every
  check (segment comparisons, confounder controls, queue analysis, policy retrieval), and the
  LLM judges each hypothesis on that evidence alone.
- **Recommend.** The LLM chooses only from the client's action catalogue. A deterministic
  what-if engine values every action on the actual event log (breaches avoided, annual net
  value), with the policy clause that permits it.
- **Act.** Proposed actions need a human with the right role. Execution goes through an
  Operations MCP server that re-checks governance, calls the system of record, and writes a
  hash-chained audit entry. After execution the monitor tracks the action's follow-up metric.

Two processes run side by side on the same engine: **insurance claims** (motor and health,
5,000 claims) and **procure-to-pay** (invoice-to-pay at a five-plant manufacturer, 6,000
invoices). A switcher in the UI moves between them.

## 3. Design decisions that matter to a buyer

**1. The model never calculates.** Every number comes from SQL or code: a metrics catalogue of
parameterised aggregates, process mining in SQL, statistics in Python. The LLM picks metrics by
name and reads results. The executive summary is checked number by number against the facts it
was given. Unverified numbers trigger one rewrite, and anything still unverified is flagged in
the UI. In the insurance evaluation, 0 unverified numbers reached a final summary; in procure-to-pay, 3 across 9 summaries, all flagged.

**2. Safeguards in both directions, without re-judging the model's words.** A segment effect
explained by a confounder cannot be "supported", whatever the model says. That stops decoys.
The evaluation showed the opposite failure was more common: cautious models leaving real causes
"inconclusive". So there is a symmetric rule that only ever acts on hypotheses worded by code
from evidence that meets strict criteria (significant, material, not a small sample, not
explained by any control). It never flips a verdict on a sentence the model wrote, because that
sentence might claim something the evidence does not.

**3. Governance is enforced in the backend, not the prompt.** Agents and MCP clients can
propose and execute, never approve. The person who proposed an action cannot approve it.
Denials are recorded durably, and the audit log is a SHA-256 hash chain whose integrity can be
verified. Any MCP client (Claude Desktop, another agent) gets exactly the same rules as the web
app. Two more MCP servers are read-only: Analytics gives clients the app's own numbers
(metrics, process mining, investigations) and Knowledge gives them the policy passages to cite.

**4. Every capability is measured against ground truth.** Synthetic generators plant root
causes and decoys, and keep an exact counterfactual for every case: the same case re-simulated
with one cause switched off. That makes "did it find the real causes, and did it fall for the
decoys?" a number, not an opinion.

**5. A new process is configuration.** Dimensions, controls, loops, wait targets, metrics,
monitors, actions, governance, documents and benchmark live in a domain pack. The second pack
proved it, and showed where it wasn't yet true (section 6).

**6. Run like an enterprise system.** Accounts and role-based access in two layers: a
platform role (viewer, analyst, admin) for what someone can do, and a business role per process
for what they can approve. Observability records every LLM call and API request, with
per-investigation traces and the free-tier quota per model. Repeated or near-identical policy
questions are served from a cache that any document change invalidates, and an identical
investigation replays its recorded run instead of calling a model again. Admins choose showcase
runs that read-only visitors can watch, and rate limits apply only to requests that spend
tokens, so a free model tier can carry a public demo. A cheaper model tier takes simple
requests, with the routing reason shown. The observability page paid for itself
on day one: it showed the parallel assessor's calls arriving without context, which turned
out to be a real bug (and it had been quietly using the wrong pack's wording).

**7. Provider-agnostic and zero-cost.** Local Ollama (`qwen2.5:7b` on a 6 GB laptop GPU) and
Groq/Gemini free tiers are configuration. The evaluation compares them on the same benchmark.

## 4. Results

All numbers come from [`evaluation_report.md`](evaluation_report.md), which also lists every
failure.

**Insurance claims** (36 scored investigations: 4 models × 3 data seeds × 3 questions, plus
12 earlier runs repeated after fixes; Q&A, retrieval and what-if suites)

| Model | Runs completed | Mean recall of planted causes | Decoys accepted | Model's own citation accuracy |
|---|---|---|---|---|
| `qwen2.5:7b`, local, free | 9/9 | 100% | 0 | 75% |
| `qwen3.8-27b`, Groq free tier | 9/9 | 97% | 0 | 97% |
| `gpt-oss-20b`, Groq free tier | 7/9 | 100% | 0 | 69% |
| `gpt-oss-120b`, Groq free tier | 6/9 | 79% | 0 | 73% |

No model accepted a decoy in any run. The failed runs were refused by Groq's free daily quota,
and are reported as such. Citation accuracy is measured *before* the verifier corrects
anything. With the verifier, 96% of answers cite a relevant passage for every model, and all
models declined 5/5 unanswerable questions.

**Procure-to-pay** (local model; 9 investigations: 3 seeds × 3 questions)

| Model | Runs completed | Mean recall | Decoys accepted | Remedy recommended per cause found | Q&A: model's own citation accuracy |
|---|---|---|---|---|---|
| `qwen2.5:7b`, local, free | 9/9 | 100% | 0/9 runs | 17/18 | 86% (100% grounded after verification) |

The safeguards did real work here. The 7B model called a confounded effect "supported" 25
times across the nine runs (services, MSME suppliers). The confounder rule refuted every one,
and the coverage and evidence rules added the causes it left out. Three numbers across nine
executive summaries could not be verified against the facts; they are flagged in the UI and
listed in the report.

**What-if engine vs the exact counterfactuals:** estimates fall between 0.5 and 1.0 of the true
breaches avoided. The engine understates by design: it removes waiting time but does not
re-simulate the calendar. The biggest gap is weekend effects, and that is stated next to every
estimate.

**Closed loop (demo):** after approving two actions (delegating mid-value approvals and
retraining one team) and simulating the next month, the breach rate fell from 34% to 19%. Both
follow-up metrics hit target, and the monitors resolved their own alerts. The monitors also
showed what was *not* fixed: claims above ₹5 lakh still queued, and broker document requests
were untouched.

## 5. What the evaluation broke, and what changed

Building the evaluation found more product defects than any demo did. Each was fixed in the
product, covered by a test and re-measured:

- **Scoped questions were blind to their own cause.** Asked "why are *broker* claims
  breaching?", every claim in scope was a broker claim, so nothing showed the broker effect
  (recall 0). Scoped investigations now also compare the scope with the rest of the business.
  The what-if engine had the same blind spot: `max(0, NaN)` silently valued the right action
  at zero.
- **Tool calling was unreliable on two cloud models.** Tested directly, JSON-schema output
  worked 3/3 where tool calling failed. Structured output now defaults to JSON schema, with the
  error fed back on retry.
- **I misdiagnosed a hang first.** Local runs stalled. I blamed concurrency and serialised the
  calls, and the stall came back. The real cause was unbounded generation: with constrained
  JSON output a small model can loop inside a string forever, and the abandoned request keeps
  the single-GPU server busy. Output caps fixed it. The notes keep the wrong diagnosis on
  record.
- **Over-caution, not gullibility, was the dominant failure.** Every miss was a real cause
  left inconclusive or wrongly refuted, never a decoy accepted. That led to the symmetric
  safeguard in decision 2.

## 6. The second process: what it took

Procure-to-pay was chosen to be close to my procurement-transformation work, and different
enough to hurt. Its planted causes exercise different checks from insurance:

- a plant whose stores post goods receipts late (a queue within one segment);
- free-text purchase orders causing price exceptions (a loop driven by PO type);
- an outsourced capture team's errors (a loop driven by team);
- a payment run cut from twice to once a week in July (a change over time).

Its decoys are confounded by different controls. Services "look slow" because of PO type. MSME
suppliers "get paid late" because their paper invoices go to the outsourced team.

Most of the work was removing assumptions I had not noticed I'd made. The scanned dimensions,
confounder controls, loop definitions, wait targets, prompt wording, dashboard tiles and the
evaluation's truth mapping had all been insurance-shaped constants in code. They are now pack
configuration, and the insurance results are unchanged (all 165 earlier tests pass).

One capability was genuinely missing. Every invoice passes through the payment run, so the
existing evidence ("cases with this step breach X% vs Y% without") had no "without" group, and
the weekly payment run could not be confirmed. The queue check now also compares waiting time
month by month against the breach rate. That is generic, and it would catch any queue that
worsened over time in either process. The full recipe for a third pack is in
[`ADDING_A_DOMAIN_PACK.md`](ADDING_A_DOMAIN_PACK.md).

## 7. With a real client

The synthetic data is a stand-in for a client's event log. A real engagement would replace the
generator with a loader and spend its effort where it usually goes:

1. **Data mapping (2–4 weeks).** Case and activity definitions from the ERP or claims system,
   timestamp quality, and which attributes exist. Most process-mining projects are won or lost
   here.
2. **Pack authoring with the process owner.** Which dimensions plausibly confound which, what
   the policies actually say, which actions are in scope and who approves them.
3. **Calibrating trust.** Replay past incidents where the cause is known, and use the same
   evaluation harness with those incidents as ground truth.
4. **A watch-only pilot,** then recommendations, then approvals. Act last, because that is
   where the change management is.

## 8. Limitations

- Results are on **synthetic data** with author-written policies and benchmarks. They show the
  system recovers planted patterns and resists planted decoys, not that it would on a messy
  real event log.
- **Small samples:** three seeds and three questions per pack and model.
- **Number verification checks numbers, not claims.** Every figure in a summary must appear in
  the computed facts, but a small model can still attach a correct number to the wrong claim
  (one P2P summary called the payment run's 31% breach rate "31% of breaches"). The hypotheses
  and evidence beneath the summary are the record; the summary is a reading of it.
- The what-if engine **understates** some effects (calendar, and mechanisms beyond waiting
  time).
- Accounts are **local** (no single sign-on yet), and the app runs on a laptop: public
  hosting and GitHub sign-in come with the deployment.

## Stack

FastAPI · LangGraph · PostgreSQL 17 + pgvector · SQL-native process mining · hybrid retrieval
(BGE embeddings + full-text, cross-encoder verification) · MCP (Analytics, Knowledge and
Operations servers; client) ·
React + TypeScript + Tailwind · Docker Compose · local Ollama and free-tier Groq/Gemini.
220+ backend tests, CI on every push.
