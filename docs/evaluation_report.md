# Evaluation report

Generated from 5 run(s) over 2 domain pack(s): `2026-11-10T14:43:04` (insurance_claims), `2026-11-10T14:23:19` (insurance_claims), `2026-11-10T15:54:20` (insurance_claims), `2026-11-10T19:27:50` (insurance_claims), `2026-11-10T20:28:49` (procure_to_pay). Models: `groq:openai/gpt-oss-120b`, `groq:openai/gpt-oss-20b`, `groq:qwen/qwen3.8-27b`, `ollama:qwen2.5:7b`.

All results are measured, not targets. Failed runs are reported, not dropped. Every investigation is scored against the generator's planted ground truth, declared per pack in `domain_packs/<pack>/evaluation/investigations.yaml`: a planted cause counts as found only if a hypothesis that targets it is *supported*; a decoy counts as accepted if a supported hypothesis rests only on it. Both packs run on the same engine code: only configuration and the synthetic-data generator differ.

Contents: [Insurance Claims (Motor & Health, reimbursement)](#insurance-claims-motor--health-reimbursement) · [Procure-to-Pay (invoice-to-pay, manufacturing)](#procure-to-pay-invoice-to-pay-manufacturing)

## Insurance Claims (Motor & Health, reimbursement)

Pack `insurance_claims`. Models: `groq:openai/gpt-oss-120b`, `groq:openai/gpt-oss-20b`, `groq:qwen/qwen3.8-27b`, `ollama:qwen2.5:7b`. Seeds: [7, 42, 1234].

### 1. Investigations

Quality columns cover completed runs only. *Rate-limited* runs never reached the model's reasoning (the provider refused the request), so they are counted apart from runs the model itself failed.

| Model | Runs | Completed | Rate-limited | Other failures | Mean recall | All expected causes found | Decoys accepted | Overrides fired | Unverified numbers / run | Mean duration | LLM calls / run | Tokens / run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `groq:openai/gpt-oss-120b` | 9 | 6 | 3 | 0 | 79% | 4/6 | 0/4 runs | 5 | 0.00 | 86 s | 10.0 | 16,340 |
| `groq:openai/gpt-oss-20b` | 9 | 7 | 2 | 0 | 100% | 7/7 | 0/5 runs | 5 | 0.00 | 123 s | 10.9 | 19,349 |
| `groq:qwen/qwen3.8-27b` | 9 | 9 | 0 | 0 | 97% | 8/9 | 0/6 runs | 1 | 0.00 | 189 s | 13.4 | 14,058 |
| `ollama:qwen2.5:7b` | 9 | 9 | 0 | 0 | 100% | 9/9 | 0/6 runs | 22 | 0.00 | 101 s | 12.1 | 11,575 |

#### By question

| Question | Model | Recall by seed | Decoys accepted | Remedy recommended for each cause found |
|---|---|---|---|---|
| `broker_channel` | `groq:openai/gpt-oss-120b` | 7: 100%, 42: 100%, 1234: error | 0/2 | 2/2 |
| `broker_channel` | `groq:openai/gpt-oss-20b` | 7: 100%, 42: 100%, 1234: error | 0/2 | 1/2 |
| `broker_channel` | `groq:qwen/qwen3.8-27b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 1/3 |
| `broker_channel` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |
| `health_vs_motor` | `groq:openai/gpt-oss-120b` | 7: 100%, 42: 0%, 1234: error | 0/2 | 1/1 |
| `health_vs_motor` | `groq:openai/gpt-oss-20b` | 7: 100%, 42: 100%, 1234: error | 0/2 | 2/2 |
| `health_vs_motor` | `groq:qwen/qwen3.8-27b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |
| `health_vs_motor` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |
| `sla_root_causes` | `groq:openai/gpt-oss-120b` | 7: 75%, 42: 100%, 1234: error | 0/2 | 7/7 |
| `sla_root_causes` | `groq:openai/gpt-oss-20b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 10/12 |
| `sla_root_causes` | `groq:qwen/qwen3.8-27b` | 7: 75%, 42: 100%, 1234: 100% | 0/3 | 11/11 |
| `sla_root_causes` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 10/12 |

#### Planted causes found (all questions that expect them)

| Model | RC1 Senior approval queue | RC2 Broker documents | RC3 Team B rework | RC4 Friday backlog |
|---|---|---|---|---|
| `groq:openai/gpt-oss-120b` | 3/4 | 3/4 | 2/2 | 2/2 |
| `groq:openai/gpt-oss-20b` | 5/5 | 5/5 | 3/3 | 3/3 |
| `groq:qwen/qwen3.8-27b` | 6/6 | 6/6 | 3/3 | 2/3 |
| `ollama:qwen2.5:7b` | 6/6 | 6/6 | 3/3 | 3/3 |

#### Safeguards at work

How often the deterministic safeguards changed the outcome:

| Model | Hypotheses added by coverage rule | Downgraded (model said supported; confounded or small sample) | Upgraded (code-worded hypothesis, strong evidence) | Findings confirmed by evidence rule | Runs whose summary needed a rewrite | Negative-value actions recommended |
|---|---|---|---|---|---|---|
| `groq:openai/gpt-oss-120b` | 7 | 5 | 0 | 0 | 1/6 | 4/6 |
| `groq:openai/gpt-oss-20b` | 20 | 5 | 0 | 0 | 2/7 | 5/7 |
| `groq:qwen/qwen3.8-27b` | 4 | 1 | 0 | 0 | 0/9 | 6/9 |
| `ollama:qwen2.5:7b` | 34 | 15 | 0 | 7 | 1/9 | 3/9 |

Downgrades stop decoys (a model calling a confounded effect a cause). Upgrades and confirmed findings stop over-caution: the evidence rule only ever adds or upgrades hypotheses worded by code from evidence that is significant, large enough, not a small sample and not explained by any confounder; a sentence the model wrote is never re-judged. Runs made before the upgrade rules existed could only downgrade. *Negative-value actions recommended* counts runs that recommended an action whose estimated net value is negative; the recommender may do so only when no positive action addresses a supported cause, and the UI marks it "Not cost-effective".

#### Failures and misses (every one)

- **`groq:openai/gpt-oss-120b` · `broker_channel` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_<redacted>` service tier `on_demand` on tokens per day (TPD): Limit 200`
- **`groq:openai/gpt-oss-120b` · `health_vs_motor` · seed 42**: missed RC1. Hypotheses: H1 [inconclusive] Health claims have longer cycle times because they are routed through Senior Approval more frequently, and the; H2 [inconclusive] The higher breach rate for health claims is actually driven by larger claim amounts, which require senior appr; H3 [refuted] Claims submitted via brokers generate more document requests, leading to delays; if health claims are dispropo; H4 [inconclusive] Friday handoffs add extra waiting time, and health claims tend to be handed over later in the week, causing hi; H5 [inconclusive] Team B has higher verification rework and breach rates; if health claims are assigned more often to Team B, th
- **`groq:openai/gpt-oss-120b` · `health_vs_motor` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_<redacted>` service tier `on_demand` on tokens per day (TPD): Limit 200`
- **`groq:openai/gpt-oss-120b` · `sla_root_causes` · seed 7**: missed RC2. Hypotheses: H1 [refuted] The prolonged waiting time before Senior Approval is the primary driver of SLA breaches.; H2 [supported] Claims in the ₹2L–₹5L and >₹5L amount bands experience higher breach rates due to additional documentation and; H3 [supported] Friday handoffs cause a 24‑hour (or 54‑hour) delay that pushes many claims past the 5‑day SLA.; H4 [supported] Team B’s higher verification rework rate leads to longer cycle times and SLA breaches.; H5 [refuted] Broker channel’s higher breach rate appears significant, but it may be confounded by the higher claim amounts 
- **`groq:openai/gpt-oss-120b` · `sla_root_causes` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_<redacted>` service tier `on_demand` on tokens per day (TPD): Limit 200`
- **`groq:openai/gpt-oss-20b` · `broker_channel` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-20b` in organization `org_<redacted>` service tier `on_demand` on tokens per day (TPD): Limit 2000`
- **`groq:openai/gpt-oss-20b` · `health_vs_motor` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-20b` in organization `org_<redacted>` service tier `on_demand` on tokens per day (TPD): Limit 2000`
- **`groq:qwen/qwen3.8-27b` · `sla_root_causes` · seed 7**: missed RC4. Hypotheses: H1 [supported] Claims in the ₹2L–₹5L and >₹5L bands are systematically routed to Senior Approval, creating a bottleneck that ; H2 [supported] Broker-originated claims have a significantly higher rate of additional document requests, causing delays in t; H3 [supported] Team B has a high rework rate in Verification, indicating process inefficiencies or skill gaps that lead to de; H4 [refuted] Health claims have a higher breach rate due to the complexity and time-consuming nature of Medical Adjudicatio; H5 [inconclusive] Claims handed over on Fridays, particularly in the afternoon, experience significant delays due to weekend gap; H6 [refuted] The higher breach and document request rates in Pune may be misleading due to a small sample size and could be

### 2. Grounded answers (policy Q&A)

| Model | Answerable questions | Answered (not refused) | Cited a relevant passage | Grounded after verification | Model's own citation accuracy | Unanswerable correctly declined | Errors | Mean generation |
|---|---|---|---|---|---|---|---|---|
| `groq:openai/gpt-oss-120b` | 28 | 96% | 96% | 96% | 73% | 5/5 | 0 | 2.9 s |
| `groq:openai/gpt-oss-20b` | 28 | 96% | 96% | 85% | 69% | 5/5 | 0 | 2.7 s |
| `groq:qwen/qwen3.8-27b` | 28 | 100% | 96% | 89% | 97% | 5/5 | 0 | 1.9 s |
| `ollama:qwen2.5:7b` | 28 | 96% | 96% | 89% | 75% | 5/5 | 0 | 2.2 s |

*Model's own citation accuracy* = share of answer sentences whose citation the model got right before the verifier corrected anything (decision D20).

### 3. Retrieval (no LLM)

| Method | Hit@1 | Hit@3 | Hit@5 | MRR@10 |
|---|---|---|---|---|
| vector | 0.79 | 0.93 | 1.00 | 0.87 |
| keyword | 0.61 | 0.86 | 0.89 | 0.72 |
| hybrid | 0.75 | 1.00 | 1.00 | 0.86 |
| hybrid_rerank | 0.75 | 1.00 | 1.00 | 0.87 |

### 4. What-if engine vs exact counterfactuals (no LLM)

| Action | seed 7: estimate / truth | seed 42: estimate / truth | seed 1234: estimate / truth | Mean ratio |
|---|---|---|---|---|
| `delegate_mid_value_approvals` | 442 / 522 | 426 / 514 | 455 / 523 | 0.85 |
| `add_senior_adjuster_capacity` | 563 / 645 | 516 / 625 | 557 / 648 | 0.85 |
| `enforce_broker_checklist` | 112 / 137 | 106 / 124 | 127 / 124 | 0.90 |
| `retrain_team_b` | 92 / 96 | 79 / 76 | 97 / 99 | 0.99 |
| `saturday_rota` | 53 / 101 | 51 / 99 | 44 / 91 | 0.51 |

A ratio below 1 means the what-if understates the benefit (it removes waiting time but does not re-run the working calendar or the planted mechanism, e.g. a capped goods-receipt wait still leaves the extra GRN-pending invoices).

## Procure-to-Pay (invoice-to-pay, manufacturing)

Pack `procure_to_pay`. Models: `ollama:qwen2.5:7b`. Seeds: [7, 42, 1234].

### 1. Investigations

Quality columns cover completed runs only. *Rate-limited* runs never reached the model's reasoning (the provider refused the request), so they are counted apart from runs the model itself failed.

| Model | Runs | Completed | Rate-limited | Other failures | Mean recall | All expected causes found | Decoys accepted | Overrides fired | Unverified numbers / run | Mean duration | LLM calls / run | Tokens / run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ollama:qwen2.5:7b` | 9 | 9 | 0 | 0 | 100% | 9/9 | 0/9 runs | 33 | 0.33 | 90 s | 13.2 | 13,506 |

#### By question

| Question | Model | Recall by seed | Decoys accepted | Remedy recommended for each cause found |
|---|---|---|---|---|
| `msme_late` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |
| `p2p_root_causes` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 11/12 |
| `services_slow` | `ollama:qwen2.5:7b` | 7: 100%, 42: 100%, 1234: 100% | 0/3 | 3/3 |

#### Planted causes found (all questions that expect them)

| Model | RC1 Chakan goods receipts | RC2 Free-text PO price exceptions | RC3 BPO capture errors | RC4 Weekly payment run |
|---|---|---|---|---|
| `ollama:qwen2.5:7b` | 3/3 | 6/6 | 6/6 | 3/3 |

#### Safeguards at work

How often the deterministic safeguards changed the outcome:

| Model | Hypotheses added by coverage rule | Downgraded (model said supported; confounded or small sample) | Upgraded (code-worded hypothesis, strong evidence) | Findings confirmed by evidence rule | Runs whose summary needed a rewrite | Negative-value actions recommended |
|---|---|---|---|---|---|---|
| `ollama:qwen2.5:7b` | 44 | 25 | 0 | 8 | 2/9 | 1/9 |

Downgrades stop decoys (a model calling a confounded effect a cause). Upgrades and confirmed findings stop over-caution: the evidence rule only ever adds or upgrades hypotheses worded by code from evidence that is significant, large enough, not a small sample and not explained by any confounder; a sentence the model wrote is never re-judged. Runs made before the upgrade rules existed could only downgrade. *Negative-value actions recommended* counts runs that recommended an action whose estimated net value is negative; the recommender may do so only when no positive action addresses a supported cause, and the UI marks it "Not cost-effective".

#### Failures and misses (every one)

None.


### 2. Grounded answers (policy Q&A)

| Model | Answerable questions | Answered (not refused) | Cited a relevant passage | Grounded after verification | Model's own citation accuracy | Unanswerable correctly declined | Errors | Mean generation |
|---|---|---|---|---|---|---|---|---|
| `ollama:qwen2.5:7b` | 25 | 100% | 100% | 100% | 86% | 5/5 | 0 | 1.7 s |

*Model's own citation accuracy* = share of answer sentences whose citation the model got right before the verifier corrected anything (decision D20).

### 3. Retrieval (no LLM)

| Method | Hit@1 | Hit@3 | Hit@5 | MRR@10 |
|---|---|---|---|---|
| vector | 0.88 | 0.96 | 1.00 | 0.93 |
| keyword | 0.40 | 0.84 | 0.96 | 0.64 |
| hybrid | 0.68 | 1.00 | 1.00 | 0.83 |
| hybrid_rerank | 0.76 | 0.92 | 1.00 | 0.86 |

### 4. What-if engine vs exact counterfactuals (no LLM)

| Action | seed 7: estimate / truth | seed 42: estimate / truth | seed 1234: estimate / truth | Mean ratio |
|---|---|---|---|---|
| `chakan_grn_discipline` | 163 / 184 | 185 / 219 | 173 / 207 | 0.86 |
| `add_chakan_stores_clerk` | 163 / 184 | 185 / 219 | 173 / 207 | 0.86 |
| `enforce_catalogue_buying` | 415 / 417 | 399 / 417 | 440 / 437 | 0.99 |
| `retrain_bpo_capture` | 331 / 392 | 303 / 370 | 293 / 370 | 0.82 |
| `restore_twice_weekly_runs` | 209 / 341 | 222 / 335 | 210 / 337 | 0.63 |

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

12 earlier result(s) were re-run after a fix and replaced:

| Pack | Model | Seed | Question | Earlier result |
|---|---|---|---|---|
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `broker_channel` | recall 100%, remedy recommended 0/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `sla_root_causes` | recall 100%, remedy recommended 4/4 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 7 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `broker_channel` | recall 100%, remedy recommended 0/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `sla_root_causes` | recall 100%, remedy recommended 3/4 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 42 | `broker_channel` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `broker_channel` | recall 100%, remedy recommended 0/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `sla_root_causes` | recall 100%, remedy recommended 3/4 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `health_vs_motor` | recall 100%, remedy recommended 1/1 |
| insurance_claims | `ollama:qwen2.5:7b` | 1234 | `broker_channel` | recall 100%, remedy recommended 1/1 |

## Method and limitations

- **Synthetic data.** Ground truth is known because the generators planted it. Results show the system recovers planted patterns and resists planted decoys; they do not prove performance on real operational data.
- **Author-written benchmarks.** The documents, retrieval questions and investigation questions were written by the same author, which flatters retrieval in particular.
- **Small samples.** A few seeds and questions per model: differences of one or two runs are not significant.
- **Free tiers.** Cloud models ran on free tiers; rate limits can cause failed runs, which are reported as failures.
- **Scoring is structural.** A cause counts as found from the evidence a supported hypothesis targets, not from reading its prose.
