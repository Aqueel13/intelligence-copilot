# Evaluation report

Generated from 3 run(s): `2026-11-10T14:23:19`, `2026-11-10T14:43:04`, `2026-11-10T15:54:20`. Models: `groq:openai/gpt-oss-120b`, `groq:openai/gpt-oss-20b`, `groq:qwen/qwen3.8-27b`, `ollama:qwen2.5:7b`. Generator seeds: [7, 42, 1234].

All results are measured, not targets. Failed runs are reported, not dropped. Every investigation is scored against the generator's planted ground truth (`investigation/scoring.py`): a planted cause counts as found only if a hypothesis that targets it is *supported*; a decoy counts as accepted if a supported hypothesis rests only on it.

## 1. Investigations

Quality columns cover completed runs only. *Rate-limited* runs never reached the model's reasoning (the provider refused the request), so they are counted apart from runs the model itself failed.

| Model | Runs | Completed | Rate-limited | Other failures | Mean recall | All expected causes found | Decoys accepted | Overrides fired | Unverified numbers / run | Mean duration | LLM calls / run | Tokens / run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `groq:openai/gpt-oss-120b` | 9 | 6 | 3 | 0 | 79% | 4/6 | 0/4 runs | 5 | 0.00 | 86 s | 10.0 | 16,340 |
| `groq:openai/gpt-oss-20b` | 9 | 7 | 2 | 0 | 100% | 7/7 | 0/5 runs | 5 | 0.00 | 123 s | 10.9 | 19,349 |
| `groq:qwen/qwen3.8-27b` | 9 | 9 | 0 | 0 | 97% | 8/9 | 0/6 runs | 1 | 0.00 | 189 s | 13.4 | 14,058 |
| `ollama:qwen2.5:7b` | 9 | 9 | 0 | 0 | 100% | 9/9 | 0/6 runs | 14 | 0.00 | 89 s | 11.1 | 10,029 |

### By question

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

### Planted causes found (all questions that expect them)

| Model | RC1 senior approval | RC2 broker documents | RC3 Team B rework | RC4 Friday backlog |
|---|---|---|---|---|
| `groq:openai/gpt-oss-120b` | 3/4 | 3/4 | 2/2 | 2/2 |
| `groq:openai/gpt-oss-20b` | 5/5 | 5/5 | 3/3 | 3/3 |
| `groq:qwen/qwen3.8-27b` | 6/6 | 6/6 | 3/3 | 2/3 |
| `ollama:qwen2.5:7b` | 6/6 | 6/6 | 3/3 | 3/3 |

### Safeguards at work

How often the deterministic safeguards changed the outcome:

| Model | Hypotheses added by coverage rule | Verdicts overridden (confounder / small sample) | Runs whose summary needed a rewrite | Negative-value actions recommended |
|---|---|---|---|---|
| `groq:openai/gpt-oss-120b` | 7 | 5 | 1/6 | 4/6 |
| `groq:openai/gpt-oss-20b` | 20 | 5 | 2/7 | 5/7 |
| `groq:qwen/qwen3.8-27b` | 4 | 1 | 0/9 | 6/9 |
| `ollama:qwen2.5:7b` | 18 | 14 | 1/9 | 5/9 |

*Negative-value actions recommended* counts runs that recommended an action whose estimated net value is negative. The recommender may do so only when no positive action addresses a supported cause (here: the Saturday rota is the only catalogue remedy for the Friday backlog); the UI marks such actions "Not cost-effective".

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

**Not yet re-run (provider quota).** The cloud runs started at 14:43, a minute before fix 2
was applied, so the three Groq models' `broker_channel` results predate it; their low "remedy
recommended" counts on that question reflect the bug, not the models. The local model was
re-run after the fix (3/3). Re-running the cloud models, and the five runs refused by Groq's
200,000-tokens-per-day free-tier quota, needs the rolling quota to recover (about 24 hours).

**Known limitation found by this evaluation.** The deterministic overrides only ever
*downgrade* a verdict (e.g. "supported" → "refuted" when a confounder explains the effect).
Nothing yet catches a model wrongly *refuting* or leaving *inconclusive* a hypothesis the
evidence supports. All model misses above are of that kind (over-caution), never an accepted
decoy: gpt-oss-120b refuted the broker hypothesis as "confounded by claim amounts" although its
confounder checks showed the effect persisting, and left the correct claim-value explanation
"inconclusive" in one health-vs-motor run.

3 earlier result(s) were re-run after a fix and replaced:

| Suite | Model | Seed | Question | Earlier result |
|---|---|---|---|---|
| investigation | `ollama:qwen2.5:7b` | 7 | `broker_channel` | recall 100%, remedy recommended 0/1 |
| investigation | `ollama:qwen2.5:7b` | 42 | `broker_channel` | recall 100%, remedy recommended 0/1 |
| investigation | `ollama:qwen2.5:7b` | 1234 | `broker_channel` | recall 100%, remedy recommended 0/1 |

## 2. Failures and misses (every one)

- **`groq:openai/gpt-oss-120b` · `broker_channel` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_<redacted>` service tier `on_demand` on tokens per day (TPD): Limit 200`
- **`groq:openai/gpt-oss-120b` · `health_vs_motor` · seed 42**: missed RC1. Hypotheses: H1 [inconclusive] Health claims have longer cycle times because they are routed through Senior Approval more frequently, and the; H2 [inconclusive] The higher breach rate for health claims is actually driven by larger claim amounts, which require senior appr; H3 [refuted] Claims submitted via brokers generate more document requests, leading to delays; if health claims are dispropo; H4 [inconclusive] Friday handoffs add extra waiting time, and health claims tend to be handed over later in the week, causing hi; H5 [inconclusive] Team B has higher verification rework and breach rates; if health claims are assigned more often to Team B, th
- **`groq:openai/gpt-oss-120b` · `health_vs_motor` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_<redacted>` service tier `on_demand` on tokens per day (TPD): Limit 200`
- **`groq:openai/gpt-oss-120b` · `sla_root_causes` · seed 7**: missed RC2. Hypotheses: H1 [refuted] The prolonged waiting time before Senior Approval is the primary driver of SLA breaches.; H2 [supported] Claims in the ₹2L–₹5L and >₹5L amount bands experience higher breach rates due to additional documentation and; H3 [supported] Friday handoffs cause a 24‑hour (or 54‑hour) delay that pushes many claims past the 5‑day SLA.; H4 [supported] Team B’s higher verification rework rate leads to longer cycle times and SLA breaches.; H5 [refuted] Broker channel’s higher breach rate appears significant, but it may be confounded by the higher claim amounts 
- **`groq:openai/gpt-oss-120b` · `sla_root_causes` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization `org_<redacted>` service tier `on_demand` on tokens per day (TPD): Limit 200`
- **`groq:openai/gpt-oss-20b` · `broker_channel` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-20b` in organization `org_<redacted>` service tier `on_demand` on tokens per day (TPD): Limit 2000`
- **`groq:openai/gpt-oss-20b` · `health_vs_motor` · seed 1234**: **rate limit (provider quota)**: `RateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-20b` in organization `org_<redacted>` service tier `on_demand` on tokens per day (TPD): Limit 2000`
- **`groq:qwen/qwen3.8-27b` · `sla_root_causes` · seed 7**: missed RC4. Hypotheses: H1 [supported] Claims in the ₹2L–₹5L and >₹5L bands are systematically routed to Senior Approval, creating a bottleneck that ; H2 [supported] Broker-originated claims have a significantly higher rate of additional document requests, causing delays in t; H3 [supported] Team B has a high rework rate in Verification, indicating process inefficiencies or skill gaps that lead to de; H4 [refuted] Health claims have a higher breach rate due to the complexity and time-consuming nature of Medical Adjudicatio; H5 [inconclusive] Claims handed over on Fridays, particularly in the afternoon, experience significant delays due to weekend gap; H6 [refuted] The higher breach and document request rates in Pune may be misleading due to a small sample size and could be

## 3. Grounded answers (policy Q&A)

| Model | Answerable questions | Answered (not refused) | Cited a relevant passage | Grounded after verification | Model's own citation accuracy | Unanswerable correctly declined | Errors | Mean generation |
|---|---|---|---|---|---|---|---|---|
| `groq:openai/gpt-oss-120b` | 28 | 96% | 96% | 96% | 73% | 5/5 | 0 | 2.9 s |
| `groq:openai/gpt-oss-20b` | 28 | 96% | 96% | 85% | 69% | 5/5 | 0 | 2.7 s |
| `groq:qwen/qwen3.8-27b` | 28 | 100% | 96% | 89% | 97% | 5/5 | 0 | 1.9 s |
| `ollama:qwen2.5:7b` | 28 | 96% | 96% | 89% | 75% | 5/5 | 0 | 2.2 s |

*Model's own citation accuracy* = share of answer sentences whose citation the model got right before the verifier corrected anything (M3, decision D20).

## 4. Retrieval (no LLM)

| Method | Hit@1 | Hit@3 | Hit@5 | MRR@10 |
|---|---|---|---|---|
| vector | 0.79 | 0.93 | 1.00 | 0.87 |
| keyword | 0.61 | 0.86 | 0.89 | 0.72 |
| hybrid | 0.75 | 1.00 | 1.00 | 0.86 |
| hybrid_rerank | 0.75 | 1.00 | 1.00 | 0.87 |

## 5. What-if engine vs exact counterfactuals (no LLM)

| Action | seed 7: estimate / truth | seed 42: estimate / truth | seed 1234: estimate / truth | Mean ratio |
|---|---|---|---|---|
| `delegate_mid_value_approvals` | 442 / 522 | 426 / 514 | 455 / 523 | 0.85 |
| `add_senior_adjuster_capacity` | 563 / 645 | 516 / 625 | 557 / 648 | 0.85 |
| `enforce_broker_checklist` | 112 / 137 | 106 / 124 | 127 / 124 | 0.90 |
| `retrain_team_b` | 92 / 96 | 79 / 76 | 97 / 99 | 0.99 |
| `saturday_rota` | 53 / 101 | 51 / 99 | 44 / 91 | 0.51 |

A ratio below 1 means the what-if understates the benefit (it does not re-run the working calendar); it never overstates by more than the ratio shown.

## 6. Method and limitations

- **Synthetic data.** Ground truth is known because the generator planted it. Results show the system recovers planted patterns and resists planted decoys; they do not prove performance on real operational data.
- **Author-written benchmarks.** The documents, retrieval questions and investigation questions were written by the same author, which flatters retrieval in particular.
- **Small samples.** A few seeds and questions per model: differences of one or two runs are not significant.
- **Free tiers.** Cloud models ran on free tiers; rate limits can cause failed runs, which are reported as failures.
- **Scoring is structural.** A cause counts as found from the evidence a supported hypothesis targets, not from reading its prose.
