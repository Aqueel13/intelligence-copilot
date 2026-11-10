# Adding a domain pack

A domain pack is one business process on the shared engine. Insurance Claims and Procure-to-Pay
run side by side. The engine (tables, metrics engine, process mining, investigation graph,
safeguards, what-if, governance, monitors, UI) is the same code for both. This guide is what
it took to add Procure-to-Pay, written as a recipe for the next pack.

## What a pack contains

```
domain_packs/<pack>/
  pack.yaml          the process: case label, SLA, calendar, dimensions, activities,
                     what the investigation analyses (analysis:), UI wording (ui:)
  metrics.yaml       metric catalogue: SQL aggregates over the shared fact views
  actions.yaml       corrective actions: policy basis, what-if lever, cost, follow-up metric,
                     the operation executed on approval
  governance.yaml    demo users and roles; who may approve each action
  monitors.yaml      KPI monitors with policy-based thresholds
  documents/*.md     policies and procedures (front matter + numbered sections)
  evaluation/
    investigations.yaml   benchmark questions, planted-truth targets, remedies, what-if truth
    retrieval.yaml        retrieval benchmark (question → relevant sections)
backend/src/watchdog_backend/generator/<pack>.py   synthetic data with planted causes
```

Only the generator is code. Real data would replace it: a loader that fills
`operational.cases` / `operational.events` (one row per case, one per activity occurrence).

## Steps

1. **Define the case and its SLA** (`pack.yaml`: `case`, `sla`, `calendar`). One case is one
   unit of work with a start and an end activity: a claim, an invoice, a ticket.
2. **Choose dimensions** the analysis may filter and group by. Attribute dimensions live in the
   case's JSONB `attributes`; `amount_band` and `opened_month` are derived. Names are
   validated identifiers, because they end up in SQL.
3. **Tell the investigation what to look at** (`analysis:`):
   - `dimensions`: scanned for segment effects;
   - `controls`: confounders checked for every segment effect. Pick the dimensions that most
     plausibly explain others (in P2P: PO type, AP team, amount band);
   - `outcomes`: loops and detours compared across segments besides `breached`, each read from
     per-case activity counts (`when: present` or `when: repeated`);
   - `wait_targets`: activities with a waiting-time target from policy.
4. **Write the metric catalogue.** Every metric is one SQL aggregate over `cases`, `events` or
   `feedback`. The LLM picks metrics by name; it never writes SQL.
5. **Write the policy documents.** Number the sections (`## 3. Posting target`, `3.1 …`): actions
   and monitors cite clauses as `WH-201 §3.1`, and citations are verified against them.
6. **Write the action catalogue.** Each action needs a lever the what-if engine understands
   (`cap_wait`, `remove_repeats` with an `outcome` for excess-only valuation,
   `cap_handoff_wait`), an annual cost, a follow-up metric and the operation to execute. If the
   operation type is new, map it in `governance/executor.py` (`ROUTES`) and the mock system.
7. **Governance and monitors:** roles that approve each action (with the clause that says so),
   and monitors with thresholds taken from the policies. The `users:` listed in
   `governance.yaml` become demo accounts (`make users`), each with that business role in this
   pack; real users get their business role per pack on the Users page.
8. **Build a generator with planted truth** (for a demo pack). Plant causes that exercise
   different checks, and decoys that look like causes until a control is applied. Draw every
   random number up front so each cause can be switched off for an exact counterfactual.
   Calibrate until every cause carries a real share of breaches and every decoy appears raw
   and vanishes within its confounder (see `tests/test_procure_to_pay.py`).
9. **Register** the generator in `generator/registry.py` (and how executed actions change its
   world, for "Simulate next month"), and enable the pack in `DOMAIN_PACKS`.
10. **Benchmark:** investigation questions with planted-truth targets, a retrieval set, and
    unanswerable questions. Then `make data knowledge` and
    `make eval DOMAIN=<pack>`.

## What adding Procure-to-Pay changed in the engine

Most of the work was moving insurance assumptions out of the engine into `pack.yaml`. The
insurance results did not change (all earlier tests still pass):

- the investigation's scanned dimensions, confounder controls, loop outcomes and wait targets
  were constants in code → `analysis:`;
- LLM prompts said "insurance claims" → worded from the pack's `subject`;
- the evaluation's map from planted causes to evidence was code → `ground_truth:` in the
  benchmark file;
- the Overview page's tiles and the example questions → `ui:`;
- the generator, the simulator and the evaluation loader called the insurance generator
  directly → a registry;
- the active pack was a process-wide setting → per request (`X-Domain` header), per job (the
  watcher evaluates every pack) and per thread (context variables follow the work into the
  parallel LLM calls).

One genuinely new capability was needed. P2P's weekly payment run is a queue every invoice
passes through, so "breach rate with vs without it" cannot exist. The activity check now also
reports waiting time **month by month** and whether the breach rate moved with it. The scan
raises such a queue as a signal, and the strict evidence rule accepts it: a material queue
whose wait rose 30%+ and correlated with the breach rate (r ≥ 0.8, p < 0.05). This is generic:
it would also catch an insurance queue that worsened over time.
