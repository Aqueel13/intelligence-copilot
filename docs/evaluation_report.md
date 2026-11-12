# Evaluation report

Generated from 16 run(s) over 2 domain pack(s): `2026-11-10T14:43:04` (insurance_claims), `2026-11-10T14:23:19` (insurance_claims), `2026-11-10T15:54:20` (insurance_claims), `2026-11-10T19:27:50` (insurance_claims), `2026-11-10T20:28:49` (procure_to_pay), `2026-11-12T10:49:06` (insurance_claims), `2026-11-12T11:08:03` (insurance_claims), `2026-11-12T11:32:20` (insurance_claims), `2026-11-12T13:01:35` (insurance_claims), `2026-11-12T13:40:47` (insurance_claims), `2026-11-12T15:01:44` (insurance_claims), `2026-11-12T15:41:55` (insurance_claims), `2026-11-12T13:18:51` (procure_to_pay), `2026-11-12T13:45:42` (procure_to_pay), `2026-11-12T15:20:06` (procure_to_pay), `2026-11-12T15:49:01` (procure_to_pay). Models: `groq:openai/gpt-oss-120b`, `groq:openai/gpt-oss-20b`, `groq:qwen/qwen3.8-27b`, `ollama:qwen2.5:7b`.

All results are measured, not targets. Failed runs are reported, not dropped. Every investigation is scored against the generator's planted ground truth, declared per pack in `domain_packs/<pack>/evaluation/investigations.yaml`: a planted cause counts as found only if a hypothesis that targets it is *supported*; a decoy counts as accepted if a supported hypothesis rests only on it. Both packs run on the same engine code: only configuration and the synthetic-data generator differ.

Contents: [Insurance Claims (Motor & Health, reimbursement)](#insurance-claims-motor--health-reimbursement) · [Procure-to-Pay (invoice-to-pay, manufacturing)](#procure-to-pay-invoice-to-pay-manufacturing)

## Insurance Claims (Motor & Health, reimbursement)

Pack `insurance_claims`. Models: `groq:openai/gpt-oss-120b`, `groq:openai/gpt-oss-20b`, `groq:qwen/qwen3.8-27b`, `ollama:qwen2.5:7b`. Seeds: [7, 42, 1234].

### 1. Investigations

Quality columns cover completed runs only. *Rate-limited* runs never reached the model's reasoning (the provider refused the request), so they are counted apart from runs the model itself failed.

| Model | Data | Runs | Completed | Rate-limited | Other failures | Mean recall | All expected causes found | Decoys accepted | Overrides fired | Unverified numbers / run | Mean duration | LLM calls / run | Tokens / run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `groq:openai/gpt-oss-120b` | 6 months (earlier datasets) | 9 | 9 | 0 | 0 | 100% | 9/9 | 0/6 runs | 31 | 0.00 | 105 s | 9.8 | 18,126 |
| `groq:openai/gpt-oss-20b` | 6 months (earlier datasets) | 9 | 8 | 1 | 0 | 100% | 8/8 | 0/6 runs | 26 | 0.00 | 140 s | 10.5 | 23,104 |
| `groq:qwen/qwen3.8-27b` | 6 months (earlier datasets) | 9 | 4 | 5 | 0 | 100% | 4/4 | 0/3 runs | 1 | 0.00 | 201 s | 12.5 | 14,369 |
| `ollama:qwen2.5:7b` | 18 months, 18,000 cases | 15 | 15 | 0 | 0 | 100% | 15/15 | 0/9 runs | 29 | 0.13 | 76 s | 11.2 | 12,727 |

#### By question

| Question | Model | Recall by seed | Decoys accepted | Remedy recommended for each cause found |
|---|---|---|---|---|
| `broker_channel` | `groq:openai/gpt-oss-120b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |
| `broker_channel` | `groq:openai/gpt-oss-20b` | 7: 100%, 42: 100%, 1234: error | 0/2 | 2/2 |
| `broker_channel` | `groq:qwen/qwen3.8-27b` | 7: error, 42: 100%, 1234: error | 0/1 | 1/1 |
| `broker_channel` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |
| `health_vs_motor` | `groq:openai/gpt-oss-120b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |
| `health_vs_motor` | `groq:openai/gpt-oss-20b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |
| `health_vs_motor` | `groq:qwen/qwen3.8-27b` | 7: error, 42: 100%, 1234: error | 0/1 | 1/1 |
| `health_vs_motor` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 2/3 |
| `kolkata_region` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |
| `monsoon_motor` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |
| `sla_root_causes` | `groq:openai/gpt-oss-120b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 12/12 |
| `sla_root_causes` | `groq:openai/gpt-oss-20b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 11/12 |
| `sla_root_causes` | `groq:qwen/qwen3.8-27b` | 7: 100%, 42: 100%, 1234: error | 0/2 | 8/8 |
| `sla_root_causes` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 9/15 |

#### Planted causes found (all questions that expect them)

| Model | RC1 Senior approval queue | RC2 Broker documents | RC3 Team B rework | RC4 Friday backlog | RC5 Monsoon surveyor backlog |
|---|---|---|---|---|---|
| `groq:openai/gpt-oss-120b` | 6/6 | 6/6 | 3/3 | 3/3 | – |
| `groq:openai/gpt-oss-20b` | 6/6 | 5/5 | 3/3 | 3/3 | – |
| `groq:qwen/qwen3.8-27b` | 3/3 | 3/3 | 2/2 | 2/2 | – |
| `ollama:qwen2.5:7b` | 6/6 | 6/6 | 6/6 | 3/3 | 6/6 |

#### Safeguards at work

How often the deterministic safeguards changed the outcome:

| Model | Hypotheses added by coverage rule | Downgraded (model said supported; confounded or small sample) | Upgraded (code-worded hypothesis, strong evidence) | Findings confirmed by evidence rule | Runs whose summary needed a rewrite | Negative-value actions recommended |
|---|---|---|---|---|---|---|
| `groq:openai/gpt-oss-120b` | 34 | 6 | 0 | 25 | 0/9 | 9/9 |
| `groq:openai/gpt-oss-20b` | 34 | 6 | 0 | 20 | 1/8 | 8/8 |
| `groq:qwen/qwen3.8-27b` | 2 | 1 | 0 | 0 | 1/4 | 4/4 |
| `ollama:qwen2.5:7b` | 41 | 14 | 0 | 15 | 4/15 | 7/15 |

Downgrades stop decoys (a model calling a confounded effect a cause). Upgrades and confirmed findings stop over-caution: the evidence rule only ever adds or upgrades hypotheses worded by code from evidence that is significant, large enough, not a small sample and not explained by any confounder; a sentence the model wrote is never re-judged. Runs made before the upgrade rules existed could only downgrade. *Negative-value actions recommended* counts runs that recommended an action whose estimated net value is negative; the recommender may do so only when no positive action addresses a supported cause, and the UI marks it "Not cost-effective".

#### Failures and misses (every one)

- **`groq:openai/gpt-oss-20b` · `broker_channel` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-20b` in organization `org_<redacted>` service tier `on_demand` on tokens per day (TPD): Limit 2000`
- **`groq:qwen/qwen3.8-27b` · `broker_channel` · seed 7**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': "Request too large for model `qwen/qwen3.8-27b` in organization `org_<redacted>` service tier `on_demand` on output tokens per minute (OTPM): Li`
- **`groq:qwen/qwen3.8-27b` · `broker_channel` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': "Request too large for model `qwen/qwen3.8-27b` in organization `org_<redacted>` service tier `on_demand` on output tokens per minute (OTPM): Li`
- **`groq:qwen/qwen3.8-27b` · `health_vs_motor` · seed 7**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': "Request too large for model `qwen/qwen3.8-27b` in organization `org_<redacted>` service tier `on_demand` on output tokens per minute (OTPM): Li`
- **`groq:qwen/qwen3.8-27b` · `health_vs_motor` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': "Request too large for model `qwen/qwen3.8-27b` in organization `org_<redacted>` service tier `on_demand` on output tokens per minute (OTPM): Li`
- **`groq:qwen/qwen3.8-27b` · `sla_root_causes` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': "Request too large for model `qwen/qwen3.8-27b` in organization `org_<redacted>` service tier `on_demand` on output tokens per minute (OTPM): Li`

### 2. Grounded answers (policy Q&A)

| Model | Answerable questions | Answered (not refused) | Cited a relevant passage | Grounded after verification | Model's own citation accuracy | Unanswerable correctly declined | Errors | Mean generation |
|---|---|---|---|---|---|---|---|---|
| `groq:openai/gpt-oss-120b` | 28 | 96% | 96% | 96% | 73% | 5/5 | 0 | 2.9 s |
| `groq:openai/gpt-oss-20b` | 28 | 96% | 96% | 85% | 69% | 5/5 | 0 | 2.7 s |
| `groq:qwen/qwen3.8-27b` | 28 | 100% | 96% | 89% | 97% | 5/5 | 0 | 1.9 s |
| `ollama:qwen2.5:7b` | 38 | 97% | 95% | 89% | 78% | 5/5 | 0 | 1.4 s |

*Model's own citation accuracy* = share of answer sentences whose citation the model got right before the verifier corrected anything (decision D20).

### 3. Retrieval (no LLM)

| Method | Hit@1 | Hit@3 | Hit@5 | MRR@10 |
|---|---|---|---|---|
| vector | 0.71 | 0.87 | 1.00 | 0.82 |
| keyword | 0.50 | 0.76 | 0.87 | 0.64 |
| hybrid | 0.66 | 0.95 | 0.97 | 0.80 |
| hybrid_rerank | 0.71 | 0.92 | 0.97 | 0.83 |

### 4. What-if engine vs exact counterfactuals (no LLM)

| Action | seed 7: estimate / truth | seed 42: estimate / truth | seed 1234: estimate / truth | Mean ratio |
|---|---|---|---|---|
| `delegate_mid_value_approvals` | 499 / 607 | 530 / 629 | 560 / 691 | 0.82 |
| `add_senior_adjuster_capacity` | 650 / 765 | 676 / 779 | 695 / 848 | 0.85 |
| `enforce_broker_checklist` | 481 / 529 | 494 / 543 | 476 / 526 | 0.91 |
| `retrain_team_b` | 413 / 435 | 367 / 376 | 401 / 406 | 0.97 |
| `saturday_rota` | 247 / 428 | 280 / 515 | 244 / 463 | 0.55 |
| `activate_monsoon_survey_panel` | 669 / 912 | 701 / 975 | 633 / 887 | 0.72 |

A ratio below 1 means the what-if understates the benefit (it removes waiting time but does not re-run the working calendar or the planted mechanism, e.g. a capped goods-receipt wait still leaves the extra GRN-pending invoices).

## Procure-to-Pay (invoice-to-pay, manufacturing)

Pack `procure_to_pay`. Models: `ollama:qwen2.5:7b`. Seeds: [7, 42, 1234].

### 1. Investigations

Quality columns cover completed runs only. *Rate-limited* runs never reached the model's reasoning (the provider refused the request), so they are counted apart from runs the model itself failed.

| Model | Data | Runs | Completed | Rate-limited | Other failures | Mean recall | All expected causes found | Decoys accepted | Overrides fired | Unverified numbers / run | Mean duration | LLM calls / run | Tokens / run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ollama:qwen2.5:7b` | 18 months, 18,000 cases | 12 | 12 | 0 | 0 | 100% | 12/12 | 0/12 runs | 52 | 0.00 | 103 s | 14.9 | 18,752 |

#### By question

| Question | Model | Recall by seed | Decoys accepted | Remedy recommended for each cause found |
|---|---|---|---|---|
| `msme_late` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |
| `p2p_root_causes` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 14/15 |
| `sanand_late` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |
| `services_slow` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |

#### Planted causes found (all questions that expect them)

| Model | RC1 Chakan goods receipts | RC2 Free-text PO price exceptions | RC3 BPO capture errors | RC4 Weekly payment run | RC5 Paper invoices wait for capture |
|---|---|---|---|---|---|
| `ollama:qwen2.5:7b` | 3/3 | 6/6 | 6/6 | 3/3 | 6/6 |

#### Safeguards at work

How often the deterministic safeguards changed the outcome:

| Model | Hypotheses added by coverage rule | Downgraded (model said supported; confounded or small sample) | Upgraded (code-worded hypothesis, strong evidence) | Findings confirmed by evidence rule | Runs whose summary needed a rewrite | Negative-value actions recommended |
|---|---|---|---|---|---|---|
| `ollama:qwen2.5:7b` | 73 | 48 | 0 | 4 | 2/12 | 0/12 |

Downgrades stop decoys (a model calling a confounded effect a cause). Upgrades and confirmed findings stop over-caution: the evidence rule only ever adds or upgrades hypotheses worded by code from evidence that is significant, large enough, not a small sample and not explained by any confounder; a sentence the model wrote is never re-judged. Runs made before the upgrade rules existed could only downgrade. *Negative-value actions recommended* counts runs that recommended an action whose estimated net value is negative; the recommender may do so only when no positive action addresses a supported cause, and the UI marks it "Not cost-effective".

#### Failures and misses (every one)

None.


### 2. Grounded answers (policy Q&A)

| Model | Answerable questions | Answered (not refused) | Cited a relevant passage | Grounded after verification | Model's own citation accuracy | Unanswerable correctly declined | Errors | Mean generation |
|---|---|---|---|---|---|---|---|---|
| `ollama:qwen2.5:7b` | 34 | 100% | 100% | 100% | 79% | 5/5 | 0 | 1.6 s |

*Model's own citation accuracy* = share of answer sentences whose citation the model got right before the verifier corrected anything (decision D20).

### 3. Retrieval (no LLM)

| Method | Hit@1 | Hit@3 | Hit@5 | MRR@10 |
|---|---|---|---|---|
| vector | 0.79 | 0.94 | 0.97 | 0.86 |
| keyword | 0.32 | 0.74 | 0.85 | 0.55 |
| hybrid | 0.65 | 0.94 | 1.00 | 0.78 |
| hybrid_rerank | 0.71 | 0.91 | 1.00 | 0.82 |

### 4. What-if engine vs exact counterfactuals (no LLM)

| Action | seed 7: estimate / truth | seed 42: estimate / truth | seed 1234: estimate / truth | Mean ratio |
|---|---|---|---|---|
| `chakan_grn_discipline` | 503 / 590 | 514 / 607 | 457 / 576 | 0.83 |
| `add_chakan_stores_clerk` | 503 / 590 | 514 / 607 | 457 / 576 | 0.83 |
| `enforce_catalogue_buying` | 1208 / 1127 | 1202 / 1195 | 1225 / 1179 | 1.04 |
| `retrain_bpo_capture` | 945 / 1086 | 899 / 1053 | 902 / 1046 | 0.86 |
| `restore_twice_weekly_runs` | 231 / 351 | 207 / 343 | 227 / 342 | 0.64 |
| `enforce_e_invoicing` | 1436 / 1234 | 1462 / 1238 | 1406 / 1220 | 1.17 |
| `scan_paper_invoices_at_plants` | 1436 / 1234 | 1462 / 1238 | 1406 / 1220 | 1.17 |

A ratio below 1 means the what-if understates the benefit (it removes waiting time but does not re-run the working calendar or the planted mechanism, e.g. a capped goods-receipt wait still leaves the extra GRN-pending invoices).

## Changes made during the evaluation

Building and running this evaluation exposed real defects. Each was fixed in the product (not
only in the harness), covered by a regression test, and the affected runs were repeated under
the fixed code:

1. **Scoped investigations could not see the scope's own cause.** Asked "why are *broker*
   claims breaching?", every claim in scope was a broker claim, so there was nothing to compare
   against and RC2 (broker documents) was invisible (recall 0 on the first smoke run). Scoped
   investigations now also compare the scope with the rest of the business, in the scan and in
   segment checks, with the same confounder checks.
2. **The what-if engine had the same blind spot.** In a broker-only scope the broker
   checklist's baseline (other channels) was undefined; `max(0, NaN)` silently returned 0, so
   the action was valued at zero breaches avoided and never recommended. Scoped what-ifs now
   take the baseline from the population; with no population the excess is reported as
   unknown (0), not guessed.
3. **A degraded model server could stall an investigation for many minutes.** Provider
   timeouts are per read and reset with every streamed token, so a server producing a token a
   minute never tripped them (an Ollama hang held one run for 8+ minutes). Every LLM call now
   has a wall-clock deadline (180 s) and fails with a clear "did not finish within …" error.
4. **Structured output used tool calling for cloud models, which two models could not do
   reliably.** gpt-oss-20b sometimes answered without calling the tool and qwen3.8-27b sent
   tool arguments that failed the schema; Groq rejected both with HTTP 400 and the run failed.
   Tested directly, JSON-schema output succeeded 3/3 for all three Groq models while tool
   calling did not. JSON-schema output is now the default for every provider; a malformed
   answer is retried with the error fed back, and the last attempt falls back to tool calling.
   Authentication and other non-output errors are never retried.
5. **Free-tier rate limits** (gpt-oss-20b: 8,000 tokens per minute) exhausted the default two
   provider retries. Provider retries are now configurable (`LLM_MAX_RETRIES`); the evaluation
   used 8, and the SDK waits for the Retry-After the provider sends.

**Improvements made after reading the results** (same day; local runs repeated as `2026-11-10-local-v2`):

6. **Over-caution is now corrected, safely.** All model misses were causes the model would not
   commit to. Code cannot safely re-judge a sentence the model wrote (refuting "the broker effect
   is confounded" was *correct* when the check showed it persisting), so two rules act only on
   code-worded hypotheses: (A) a coverage hypothesis whose own evidence meets strict criteria
   (significant, ≥5 points for breach rates / ≥10 for loops, not a small sample, not explained
   by any confounder, and a significant mechanism for loops and handoffs) is upgraded to
   supported; (B) strong evidence inside a hypothesis the model did not support, and that no
   supported hypothesis covers, becomes a separate "Evidence-confirmed" finding. Tests show a
   model that calls everything inconclusive, or refutes everything, still surfaces the strong
   planted causes, and the health decoy is never confirmed.
7. **Assessment runs in parallel for cloud models** (`LLM_PARALLEL_CALLS`, default 4). A local
   single-GPU Ollama serves one request at a time, so it gets one call at a time
   (`OLLAMA_PARALLEL_CALLS`, default 1; parallelism gained only ≈12% there). Every call also
   runs on its own thread, so its deadline never includes time queued behind other calls on
   our side.
8. **A coverage bug:** a breach-trend signal ended the coverage loop (`break` instead of
   `continue`), so weaker signals after it were never considered; and the 7-hypothesis cap could
   crowd out a strong signal. Fixed, cap raised to 9, rule extracted and tested directly.

9. **The real cause of the Ollama hangs was unbounded generation, not concurrency.** I first
   blamed concurrent requests (item 7); after making calls sequential, the broker run still
   timed out and every later request failed. Ollama's default output limit is unlimited, and
   with JSON-schema constrained output the 7B model occasionally falls into a repetition loop
   inside a string field and generates forever. Tokens keep streaming, so per-read timeouts
   never fire; the wall-clock deadline fires, but the abandoned request keeps the connection
   open, Ollama keeps generating, and because it serves one request at a time every later
   request queues behind it. Every provider now has an output cap (Ollama 1,536 tokens, cloud
   4,096 because reasoning models count hidden reasoning against it); the largest legitimate
   structured output measured was 551 tokens.

10. **Found by the new observability page (M8): parallel assessment lost its context.** The
   assessor's worker threads copied their context inside the worker (an empty context), not
   from the investigation's thread. Every assessor call was therefore unattributed in the
   traces, and in a non-default pack the assessor's evidence descriptions and upgrade reasons
   used the default pack's wording ("claims" instead of "invoices", outcome ids instead of
   labels). Scoring is structural, so the procure-to-pay results above are unaffected; the
   wording in those runs' assessor prompts was. Context is now copied at submit time, with a
   regression test.

**Not yet re-run (provider quota).** The cloud runs started at 14:43, a minute before fix 2
was applied, so the three Groq models' `broker_channel` results predate it; their low "remedy
recommended" counts on that question reflect the bug, not the models. The local model was
re-run after the fix (3/3). Re-running the cloud models, and the five runs refused by Groq's
200,000-tokens-per-day free-tier quota, needs the rolling quota to recover (about 24 hours).

**Limitation found by this evaluation (addressed by 6 above).** The deterministic overrides
used to only *downgrade* a verdict (e.g. "supported" → "refuted" when a confounder explains the effect).
Nothing yet catches a model wrongly *refuting* or leaving *inconclusive* a hypothesis the
evidence supports. All model misses above are of that kind (over-caution), never an accepted
decoy: gpt-oss-120b refuted the broker hypothesis as "confounded by claim amounts" although its
confounder checks showed the effect persisting, and left the correct claim-value explanation
"inconclusive" in one health-vs-motor run. Rules A and B now surface such causes as
separate, code-worded findings; the model's own sentences are still never re-judged.

94 earlier result(s) were re-run after a fix and replaced:

| Pack | Model | Seed | Question | Earlier result |
|---|---|---|---|---|
| insurance_claims | `groq:openai/gpt-oss-120b` | 7 | `sla_root_causes` | recall 75%, remedy recommended 3/3 |
| insurance_claims | `groq:openai/gpt-oss-120b` | 7 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `groq:openai/gpt-oss-120b` | 7 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `groq:openai/gpt-oss-120b` | 42 | `sla_root_causes` | recall 100%, remedy recommended 4/4 |
| insurance_claims | `groq:openai/gpt-oss-120b` | 42 | `health_vs_motor` | recall 0%, remedy recommended 0/0 |
| insurance_claims | `groq:openai/gpt-oss-120b` | 42 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `groq:openai/gpt-oss-120b` | 1234 | `sla_root_causes` | failed: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for  |
| insurance_claims | `groq:openai/gpt-oss-120b` | 1234 | `health_vs_motor` | failed: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for  |
| insurance_claims | `groq:openai/gpt-oss-120b` | 1234 | `broker_channel` | failed: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for  |
| insurance_claims | `groq:openai/gpt-oss-20b` | 7 | `sla_root_causes` | recall 100%, remedy recommended 4/4 |
| insurance_claims | `groq:openai/gpt-oss-20b` | 7 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `groq:openai/gpt-oss-20b` | 7 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `groq:openai/gpt-oss-20b` | 42 | `sla_root_causes` | recall 100%, remedy recommended 4/4 |
| insurance_claims | `groq:openai/gpt-oss-20b` | 42 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `groq:openai/gpt-oss-20b` | 42 | `broker_channel` | recall 100%, remedy recommended 0/1 |
| insurance_claims | `groq:openai/gpt-oss-20b` | 1234 | `sla_root_causes` | recall 100%, remedy recommended 2/4 |
| insurance_claims | `groq:openai/gpt-oss-20b` | 1234 | `health_vs_motor` | failed: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for  |
| insurance_claims | `groq:openai/gpt-oss-20b` | 1234 | `broker_channel` | failed: RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for  |
| insurance_claims | `groq:qwen/qwen3.8-27b` | 7 | `sla_root_causes` | recall 75%, remedy recommended 3/3 |
| insurance_claims | `groq:qwen/qwen3.8-27b` | 7 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `groq:qwen/qwen3.8-27b` | 7 | `broker_channel` | recall 100%, remedy recommended 0/1 |
| insurance_claims | `groq:qwen/qwen3.8-27b` | 42 | `sla_root_causes` | recall 100%, remedy recommended 4/4 |
| insurance_claims | `groq:qwen/qwen3.8-27b` | 42 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `groq:qwen/qwen3.8-27b` | 42 | `broker_channel` | recall 100%, remedy recommended 0/1 |
| insurance_claims | `groq:qwen/qwen3.8-27b` | 1234 | `sla_root_causes` | recall 100%, remedy recommended 4/4 |
| insurance_claims | `groq:qwen/qwen3.8-27b` | 1234 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `groq:qwen/qwen3.8-27b` | 1234 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `broker_channel` | recall 100%, remedy recommended 0/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `sla_root_causes` | recall 100%, remedy recommended 4/4 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `sla_root_causes` | recall 100%, remedy recommended 4/4 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `sla_root_causes` | recall 100%, remedy recommended 3/5 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `monsoon_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `kolkata_region` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `broker_channel` | recall 100%, remedy recommended 0/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `sla_root_causes` | recall 100%, remedy recommended 3/4 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `sla_root_causes` | recall 100%, remedy recommended 3/4 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `sla_root_causes` | recall 100%, remedy recommended 4/5 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `monsoon_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `kolkata_region` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `broker_channel` | recall 100%, remedy recommended 0/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `sla_root_causes` | recall 100%, remedy recommended 3/4 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `sla_root_causes` | recall 100%, remedy recommended 3/4 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `broker_channel` | failed: RemoteProtocolError: Server disconnected without sending a response. |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `monsoon_motor` | failed: ConnectError: [Errno 111] Connection refused |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `kolkata_region` | failed: ConnectError: [Errno 111] Connection refused |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `sla_root_causes` | recall 100%, remedy recommended 4/5 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `monsoon_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `kolkata_region` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `sla_root_causes` | failed: TimeoutError: model did not finish within 180 s |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `health_vs_motor` | failed: RemoteProtocolError: Server disconnected without sending a response. |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `broker_channel` | failed: ConnectError: [Errno 111] Connection refused |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `monsoon_motor` | failed: ConnectError: [Errno 111] Connection refused |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `kolkata_region` | failed: ConnectError: [Errno 111] Connection refused |
| procure_to_pay | `ollama:qwen2.5:7b` | 7 | `p2p_root_causes` | recall 100%, remedy recommended 4/4 |
| procure_to_pay | `ollama:qwen2.5:7b` | 7 | `services_slow` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 7 | `msme_late` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 7 | `p2p_root_causes` | recall 100%, remedy recommended 5/5 |
| procure_to_pay | `ollama:qwen2.5:7b` | 7 | `services_slow` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 7 | `msme_late` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 7 | `sanand_late` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 7 | `sanand_late` | failed: RemoteProtocolError: Server disconnected without sending a response. |
| procure_to_pay | `ollama:qwen2.5:7b` | 42 | `p2p_root_causes` | recall 100%, remedy recommended 4/4 |
| procure_to_pay | `ollama:qwen2.5:7b` | 42 | `services_slow` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 42 | `msme_late` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 42 | `p2p_root_causes` | recall 100%, remedy recommended 4/5 |
| procure_to_pay | `ollama:qwen2.5:7b` | 42 | `services_slow` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 42 | `msme_late` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 42 | `sanand_late` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 1234 | `p2p_root_causes` | recall 100%, remedy recommended 3/4 |
| procure_to_pay | `ollama:qwen2.5:7b` | 1234 | `services_slow` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 1234 | `msme_late` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 1234 | `sanand_late` | failed: RemoteProtocolError: peer closed connection without sending complete message bod |
| procure_to_pay | `ollama:qwen2.5:7b` | 1234 | `p2p_root_causes` | recall 100%, remedy recommended 5/5 |
| procure_to_pay | `ollama:qwen2.5:7b` | 1234 | `services_slow` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 1234 | `msme_late` | recall 100%, remedy recommended 1/1 |
| procure_to_pay | `ollama:qwen2.5:7b` | 1234 | `sanand_late` | recall 100%, remedy recommended 1/1 |

## Method and limitations

- **Synthetic data.** Ground truth is known because the generators planted it. Results show the system recovers planted patterns and resists planted decoys; they do not prove performance on real operational data.
- **Author-written benchmarks.** The documents, retrieval questions and investigation questions were written by the same author, which flatters retrieval in particular.
- **Small samples.** A few seeds and questions per model: differences of one or two runs are not significant.
- **Free tiers.** Cloud models ran on free tiers; rate limits can cause failed runs, which are reported as failures.
- **Scoring is structural.** A cause counts as found from the evidence a supported hypothesis targets, not from reading its prose.
