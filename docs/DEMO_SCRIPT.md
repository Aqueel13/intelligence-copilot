# Demo video script (about 4½ minutes)

Record at 1440×900, browser zoom 90%, light theme. Before recording: `make up && make seed`,
pick a fast model (`groq:qwen/qwen3.8-27b`, or the local 7B and cut the waiting), and run one
investigation per pack beforehand so a finished one can be opened if a live run is slow.
Reset between takes with `make seed` (it clears simulated months; actions stay in the audit
log by design).

Narration is written to be spoken. Keep it plain; let the screen carry the detail.

---

### 0:00 – 0:25 · The problem (title card, then Watch)

**Screen:** title card "Intelligence WatchDog: Watch → Investigate → Recommend → Act", then the
Watch page (Insurance Claims).

> "Operations teams run on KPIs, and when one drifts, finding out why takes days of analysis.
> Often the answer is wrong in a predictable way: the obvious segment is a symptom of
> something else. This is an AI operations analyst that watches the KPIs, investigates, and
> recommends fixes, and it acts only with a human's approval."

### 0:25 – 0:50 · Watch

**Screen:** the monitor tiles. Hover the critical "Waiting time before Senior Approval" tile;
point at "critical > 24 h for 2 months" and the policy reference.

> "These monitors come from the client's own policies. This one is critical because senior
> approvals waited over 24 hours two months running, which is exactly what the policy
> escalates on. Every number here comes from SQL, not from a language model."

**Click** Investigate on the SLA breach alert.

### 0:50 – 2:05 · Investigate

**Screen:** the investigation streaming: steps on the left, signals, hypotheses filling in.

> "The investigation starts with code: it scans every segment, queue and weekday for
> statistically significant patterns. The model turns those into hypotheses and picks checks
> from a fixed menu. Code runs every check, including confounder controls."

**Scroll** to the hypothesis "Health claims take longer". Open its evidence and point at
"within the same amount band … it is mostly explained by amount_band". If this take shows a
**Rule override** badge (the model said "supported"), point at it too.

> "Here's the decoy. Health claims look slower. But within the same claim amount the
> difference disappears: health claims are simply bigger, and big claims wait for senior
> approval. Whatever the model concludes, a code rule makes sure a confounded effect is never
> reported as a root cause."

**Scroll** to the supported causes (senior approval queue, broker documents, Team B rework,
Friday backlog).

> "What survives are the four real causes. Each links to the numbers and the policy clause
> behind it."

### 2:05 – 2:40 · Recommend

**Screen:** recommendations. Point at "breaches avoided", "net value ₹ lakh a year", the policy
citation, and the "Not cost-effective" marker on the Saturday rota.

> "The model can only choose from the client's action catalogue. Each action is valued by a
> deterministic what-if on the actual event log, with its cost assumptions shown. One is
> marked not cost-effective, and the system says so instead of hiding it."

### 2:40 – 3:25 · Act

**Screen:** signed in as the admin and acting as the Operations Analyst (M. Khan), click
Propose on "Delegate ₹2L–₹5L approvals". Switch **Act as** to the Head of Claims (A. Rao); the
banner shows who is really acting. Approve. Execute. Open the audit trail and click
**Verify chain**.

> "Proposing does nothing on its own. Only someone with the right role can approve, the
> proposer can't approve their own request, and an AI agent can't approve at all. Execution
> goes through an MCP server, so any agent, Claude Desktop included, gets exactly these rules.
> Every step lands in a tamper-evident audit log."

**Screen:** Watch → **Simulate next month** → the breach-rate tile drops, the follow-up shows
"on target".

> "In this demo I can simulate the next month: the approval queue clears for that band, and
> the monitor checks the action actually worked."

### 3:25 – 4:05 · Same engine, different process

**Screen:** switch the Process selector to **Procure-to-Pay**. Show Watch (payment run and
Chakan GRN alerts), then open a finished P2P investigation. Point at "MSME suppliers paid late
… explained by AP team".

> "The same engine on a different process: invoice-to-pay at a manufacturer. Same code,
> different configuration. It finds the late goods receipts at one plant, price exceptions from
> free-text purchase orders, an outsourced team's capture errors, and the July change to weekly
> payment runs. And it doesn't fall for 'small suppliers get paid late': their paper invoices
> go to the outsourced team, and that is the real cause."

### 4:05 – 4:30 · Proof

**Screen:** `docs/evaluation_report.md` on GitHub, the investigations table for both packs.

> "Every claim here is measured. The data has planted causes and decoys with exact ground
> truth, and four models were scored on it, including a free local one. No model accepted a
> decoy, and every failure is in the report. The repo has the code, the evaluation and a case
> study."

**End card:** GitHub URL · "Built on a zero budget with local and free-tier models".
