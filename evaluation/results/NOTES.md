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
