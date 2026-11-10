import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import type { Scope } from '../api/client'
import {
  actionsApi,
  investigationsApi,
  watchApi,
  streamInvestigation,
  type Hypothesis,
  type InvestigationState,
  type Recommendation,
  type Verdict,
} from '../api/investigation'
import { Inline, MarkdownLite } from '../components/MarkdownLite'
import { Card, ErrorNote, LowSample, StatTile, StatusBadge } from '../components/ui'
import { formatCount, formatDays, formatDimensionValue, formatPercent, formatValue } from '../lib/format'
import { useAuth } from '../lib/auth'
import { useDomainScope, useLabels } from '../lib/hooks'


const STEPS: { node: string; label: string }[] = [
  { node: 'route', label: 'Understand the question' },
  { node: 'scan', label: 'Scan the data for signals' },
  { node: 'plan', label: 'Form hypotheses' },
  { node: 'gather', label: 'Gather evidence' },
  { node: 'assess', label: 'Judge each hypothesis' },
  { node: 'recommend', label: 'Value corrective actions' },
  { node: 'synthesize', label: 'Write the summary' },
]

type RunStatus = 'idle' | 'running' | 'done' | 'error'

export default function Investigate() {
  const { scope, domain } = useDomainScope()
  const [params, setParams] = useSearchParams()
  const { can } = useAuth()
  const viewer = !can('investigate')
  const [question, setQuestion] = useState('')
  const [state, setState] = useState<InvestigationState>({})
  const [status, setStatus] = useState<RunStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [models, setModels] = useState<Record<string, string>>({})
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const abort = useRef<AbortController | null>(null)
  const qc = useQueryClient()

  const openId = params.get('id')
  const record = useQuery({
    queryKey: ['investigation', openId],
    queryFn: () => investigationsApi.get(openId!),
    enabled: !!openId && status !== 'running',
  })
  const shown: InvestigationState =
    status === 'idle' && record.data?.result ? record.data.result : state
  const shownQuestion = status === 'idle' && record.data ? record.data.question : question
  const shownModels = status === 'idle' && record.data ? record.data.models : models

  const run = async (q: string) => {
    const text = q.trim()
    if (text.length < 5) return
    abort.current?.abort()
    abort.current = new AbortController()
    setQuestion(text)
    setState({})
    setError(null)
    setStatus('running')
    setStartedAt(Date.now())
    try {
      await streamInvestigation(
        text,
        scope,
        (e) => {
          if (e.event === 'start') {
            setModels(e.data.models)
            const alertId = params.get('alert')
            if (alertId) watchApi.link(alertId, e.data.id).catch(() => {})
            setParams((p) => {
              const n = new URLSearchParams(p)
              n.set('id', e.data.id)
              n.delete('q')
              n.delete('alert')
              return n
            }, { replace: true })
          } else if (e.event === 'step') {
            setState((s) => ({ ...s, ...e.data.update }))
          } else if (e.event === 'done') {
            setStatus('done')
          } else if (e.event === 'error') {
            setError(e.data.message)
            setStatus('error')
          }
        },
        abort.current.signal,
      )
      setStatus((s) => (s === 'running' ? 'done' : s))
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setError(err instanceof Error ? err.message : String(err))
        setStatus('error')
      }
    } finally {
      qc.invalidateQueries({ queryKey: ['investigations'] })
    }
  }

  // Arriving from a Watch alert: run its question once, scoped by the URL's filters.
  const started = useRef(false)
  const preset = params.get('q')
  useEffect(() => {
    if (preset && !openId && !started.current && domain.data) {
      started.current = true
      run(preset)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, openId, domain.data])

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    run(question)
  }
  const scopeLabel = describeScope(scope, domain.data?.case_label_plural ?? "cases", domain.data?.sla_start ?? "start")

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
      <div className="grid min-w-0 content-start gap-4">
        <Card
          title="Investigate"
          subtitle="Ask why something is happening. The copilot scans the data, tests hypotheses against evidence, and values corrective actions."
        >
          <form onSubmit={onSubmit} className="flex gap-2">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={`e.g. ${domain.data?.investigate_examples[0] ?? ''}`}
              className="min-w-0 flex-1 rounded-lg border border-hairline bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted"
              aria-label="Question"
              maxLength={500}
            />
            <button
              type="submit"
              disabled={viewer || status === 'running' || question.trim().length < 5}
              title={viewer ? 'Your role can read investigations but not start them' : undefined}
              className="rounded-lg bg-series-1 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {status === 'running' ? 'Investigating…' : 'Investigate'}
            </button>
          </form>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {(domain.data?.investigate_examples ?? []).map((ex) => (
              <button
                key={ex}
                onClick={() => run(ex)}
                disabled={viewer || status === 'running'}
                className="rounded-full border border-hairline px-2.5 py-1 text-left text-xs text-ink-2 hover:bg-ghost disabled:opacity-50"
              >
                {ex}
              </button>
            ))}
          </div>
          <p className="mt-3 text-xs text-ink-muted">
            Scope: <span className="text-ink-2">{scopeLabel}</span> (set with the filters above) ·{' '}
            {domain.data?.display_name}
          </p>
        </Card>

        {error && (
          <Card>
            <ErrorNote error={error} />
          </Card>
        )}

        {(status !== 'idle' || record.data) && (
          <Progress
            state={shown}
            status={status === 'idle' ? 'done' : status}
            models={shownModels}
            question={shownQuestion}
            startedAt={startedAt}
          />
        )}

        {shown.route === 'metric' && shown.metric_answer && <MetricAnswer result={shown.metric_answer} />}
        {shown.route === 'policy' && shown.answer && <PolicyAnswer state={shown} />}
        {shown.summary && <Summary state={shown} />}
        {shown.overview && <OverviewStrip state={shown} />}
        {shown.hypotheses && <Hypotheses hypotheses={shown.hypotheses} />}
        {shown.recommendations && <Recommendations recs={shown.recommendations} hypotheses={shown.hypotheses ?? []} />}
        {shown.signals && <Signals state={shown} />}
      </div>

      <History activeId={openId} onOpen={() => setStatus('idle')} />
    </div>
  )
}

function describeScope(scope: Scope, many: string, start: string): string {
  const parts = Object.entries(scope.filters).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v.map(formatDimensionValue).join(', ')}`)
  if (scope.period_from || scope.period_to) parts.push(`${start} ${scope.period_from ?? 'start'} → ${scope.period_to ?? 'latest'}`)
  return parts.length ? parts.join(' · ') : `all ${many}`
}

// ------------------------------------------------------------------------- progress

function Progress({
  state,
  status,
  models,
  question,
  startedAt,
}: {
  state: InvestigationState
  status: RunStatus
  models: Record<string, string>
  question: string
  startedAt: number | null
}) {
  const done = new Map((state.steps ?? []).map((s) => [s.node, s]))
  const route = state.route
  const visible = route && route !== 'investigation' ? STEPS.slice(0, 1).concat({ node: route, label: route === 'metric' ? 'Compute the metric' : 'Answer from policies' }) : STEPS
  const nextIdx = visible.findIndex((s) => !done.has(s.node))
  const total = (state.steps ?? []).reduce((a, s) => a + s.ms, 0)
  return (
    <Card title={question} subtitle={status === 'running' ? 'Investigating…' : status === 'done' ? `Completed in ${(total / 1000).toFixed(0)} s` : undefined}>
      <ol className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
        {visible.map((s, i) => {
          const d = done.get(s.node)
          const running = status === 'running' && i === nextIdx
          return (
            <li key={s.node} className="flex items-start gap-2 text-xs">
              <span aria-hidden className={`mt-0.5 ${d ? 'text-good' : running ? 'animate-pulse text-series-1' : 'text-axis'}`}>
                {d ? '✓' : running ? '●' : '○'}
              </span>
              <span>
                <span className={d || running ? 'text-ink' : 'text-ink-muted'}>{s.label}</span>
                {d && <span className="tabular ml-1 text-ink-muted">{(d.ms / 1000).toFixed(1)} s</span>}
                {d?.note && <span className="block text-[11px] text-ink-muted">{d.note}</span>}
              </span>
            </li>
          )
        })}
      </ol>
      {Object.keys(models).length > 0 && (
        <p className="mt-3 text-[11px] text-ink-muted">
          Models: {[...new Set(Object.values(models))].join(', ')}
          {status === 'running' && startedAt && ' · a local model takes about a minute'}
        </p>
      )}
    </Card>
  )
}

// ------------------------------------------------------------------------- results

function Summary({ state }: { state: InvestigationState }) {
  const check = state.number_check
  return (
    <Card
      title="Executive summary"
      actions={
        check &&
        (check.unverified.length === 0 ? (
          <StatusBadge status="good" label={`All ${check.numbers_found} numbers verified against the analysis`} />
        ) : (
          <StatusBadge status="critical" label={`${check.unverified.length} number(s) not found in the analysis: ${check.unverified.join(', ')}`} />
        ))
      }
    >
      <p className="text-sm leading-relaxed text-ink">
        <Inline text={state.summary ?? ''} />
      </p>
    </Card>
  )
}

function OverviewStrip({ state }: { state: InvestigationState }) {
  const L = useLabels()
  const o = state.overview!
  return (
    <div className="grid gap-4 sm:grid-cols-4">
      <StatTile label={`${L.Many} in scope`} value={formatCount(o.cases)} note={`${o.months.toFixed(0)} months`} />
      <StatTile label="SLA breach rate" value={formatPercent(o.breach_rate)} note={`${formatCount(o.breaches)} breaches`} />
      <StatTile label="Average cycle time" value={formatDays(o.mean_cycle_days)} note={`SLA ${o.sla_days} days`} />
      <StatTile label="Signals found" value={formatCount(state.signals?.length ?? 0)} note="by the statistical scan" />
    </div>
  )
}

const VERDICT: Record<Verdict, { status: 'good' | 'warning' | 'serious'; label: string }> = {
  supported: { status: 'good', label: 'Supported' },
  inconclusive: { status: 'warning', label: 'Inconclusive' },
  refuted: { status: 'serious', label: 'Ruled out' },
}

function Hypotheses({ hypotheses }: { hypotheses: Hypothesis[] }) {
  const order: Record<string, number> = { supported: 0, inconclusive: 1, refuted: 2 }
  const sorted = [...hypotheses].sort((a, b) => (order[a.verdict ?? ''] ?? 3) - (order[b.verdict ?? ''] ?? 3))
  return (
    <Card title="Hypotheses" subtitle="Each tested against computed evidence. Segment effects are automatically re-checked within comparable groups (confounder checks).">
      <ul className="grid gap-3">
        {sorted.map((h) => (
          <HypothesisCard key={h.id} h={h} />
        ))}
      </ul>
    </Card>
  )
}

function HypothesisCard({ h }: { h: Hypothesis }) {
  const [open, setOpen] = useState(false)
  const v = h.verdict ? VERDICT[h.verdict] : null
  return (
    <li className="rounded-lg border border-hairline p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="min-w-0 flex-1 text-sm text-ink">
          <span className="mr-1.5 text-xs font-semibold text-ink-muted">{h.id}</span>
          {h.statement}
        </p>
        <div className="flex items-center gap-2">
          {h.auto && <span className="rounded border border-hairline px-1 text-[10px] uppercase tracking-wide text-ink-muted" title="Added because the planner did not test a strong signal">coverage</span>}
          {v ? <StatusBadge {...v} /> : <span className="text-xs text-ink-muted">gathering evidence…</span>}
          {h.confidence && <span className="text-[11px] text-ink-muted">{h.confidence} confidence</span>}
        </div>
      </div>
      {h.override && (
        <p className="mt-2 rounded-md bg-ghost px-2 py-1.5 text-xs text-ink-2">
          <StatusBadge status="warning" label="Rule override" /> The model said <b>{h.model_verdict}</b>. {h.override}
        </p>
      )}
      {h.reasoning && <p className="mt-2 text-xs leading-relaxed text-ink-2"><Inline text={h.reasoning} /></p>}
      {h.evidence.length > 0 && (
        <button onClick={() => setOpen((o) => !o)} className="mt-2 text-xs text-ink-2 underline underline-offset-2" aria-expanded={open}>
          {open ? 'Hide' : 'Show'} evidence ({h.evidence.length} checks)
        </button>
      )}
      {open && (
        <ul className="mt-2 grid gap-2">
          {h.evidence.map((e, i) => (
            <li key={i} className="rounded-md border border-hairline p-2 text-xs">
              <div className="flex items-center gap-2 font-medium text-ink">
                {e.ok ? <span className="text-good" aria-hidden>✓</span> : <span className="text-critical" aria-hidden>▲</span>}
                {checkLabel(e.check)}
                {e.auto && <span className="text-[10px] text-ink-muted">(added automatically)</span>}
              </div>
              {e.policy.length > 0 ? (
                <ul className="mt-1 grid gap-1.5">
                  {e.policy.map((p, j) => (
                    <li key={j} className="text-ink-2">
                      <span className="font-semibold text-ink">{p.doc_key}</span> v{p.version} § {p.section}
                      <MarkdownLite text={p.content} className="mt-0.5 text-[11px]" />
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-ink-2">{e.summary}</p>
              )}
              {e.confounders.some((c) => c.explained_by_control) && (
                <p className="mt-1">
                  <StatusBadge status="warning" label="Explained by a confounder" />
                </p>
              )}
            </li>
          ))}
          {h.dropped_checks.length > 0 && <li className="text-[11px] text-ink-muted">Invalid checks dropped: {h.dropped_checks.join('; ')}</li>}
        </ul>
      )}
    </li>
  )
}

function checkLabel(c: { type: string; [k: string]: unknown }): string {
  if (c.type === 'segment') return `Compare ${String(c.outcome ?? 'breached').replace('_', ' ')} for ${String(c.dimension).replace(/_/g, ' ')} = ${formatDimensionValue(String(c.value))}`
  if (c.type === 'activity_wait') return `Waiting time before ${String(c.activity)}`
  if (c.type === 'weekday_handoff') return `Waiting after ${String(c.weekday)} handoffs`
  return `Policy search: ${String(c.query)}`
}

const lakh = (inr: number) => `${inr < 0 ? '−' : ''}₹${Math.abs(inr / 1e5).toLocaleString('en-IN', { maximumFractionDigits: 1 })}L`

function Recommendations({ recs, hypotheses }: { recs: Recommendation[]; hypotheses: Hypothesis[] }) {
  const [showAll, setShowAll] = useState(false)
  const chosen = recs.filter((r) => r.recommended)
  const others = recs.filter((r) => !r.recommended)
  const first = recs[0]?.impact
  return (
    <Card
      title="Recommended actions"
      subtitle="Impact from a deterministic what-if on the event log; money uses the illustrative assumptions shown. Actions come from the domain pack's catalogue, each permitted by a policy clause."
    >
      {chosen.length === 0 && <p className="text-sm text-ink-2">No action recommended: no hypothesis was supported.</p>}
      <ul className="grid gap-3">
        {chosen.map((r) => (
          <RecCard key={r.action_id} r={r} hypotheses={hypotheses} />
        ))}
      </ul>
      {others.length > 0 && (
        <>
          <button onClick={() => setShowAll((s) => !s)} className="mt-3 text-xs text-ink-2 underline underline-offset-2" aria-expanded={showAll}>
            {showAll ? 'Hide' : 'Show'} {others.length} other actions evaluated
          </button>
          {showAll && (
            <ul className="mt-2 grid gap-3">
              {others.map((r) => (
                <RecCard key={r.action_id} r={r} hypotheses={hypotheses} />
              ))}
            </ul>
          )}
        </>
      )}
      {first && (
        <p className="mt-3 border-t border-hairline pt-3 text-[11px] text-ink-muted">
          Assumptions: cost per SLA breach ₹{formatCount(first.assumptions.cost_per_breach_inr)}; {first.assumptions.months_of_data} months of data annualised. {first.method}
        </p>
      )}
    </Card>
  )
}

function ProposeButton({ r }: { r: Recommendation }) {
  const { can } = useAuth()
  const [params] = useSearchParams()
  const qc = useQueryClient()
  const propose = useMutation({
    mutationFn: () =>
      actionsApi.propose({
        action_id: r.action_id,
        rationale: r.rationale || undefined,
        investigation_id: params.get('id'),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['actions'] }),
  })
  if (propose.data)
    return (
      <span className="text-xs text-ink-2">
        <StatusBadge status="good" label="Proposed" />{' '}
        <Link to="/actions" className="underline underline-offset-2">
          Open in Action Centre
        </Link>
      </span>
    )
  return (
    <span className="flex flex-wrap items-center gap-2">
      <button
        onClick={() => propose.mutate()}
        disabled={!can('propose_action') || propose.isPending}
        title={can('propose_action') ? undefined : 'Your role cannot propose actions'}
        className="rounded-md border border-hairline px-2.5 py-1 text-xs font-semibold text-ink hover:bg-ghost disabled:opacity-40"
      >
        {propose.isPending ? 'Proposing…' : 'Propose for approval'}
      </button>
      {propose.error && <span className="text-xs text-critical">{(propose.error as Error).message}</span>}
    </span>
  )
}

function RecCard({ r, hypotheses }: { r: Recommendation; hypotheses: Hypothesis[] }) {
  const L = useLabels()
  const i = r.impact
  return (
    <li className="rounded-lg border border-hairline p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-ink">{r.title}</div>
          <div className="mt-0.5 text-xs text-ink-2">{r.description}</div>
        </div>
        <div className="flex items-center gap-2">
          {!r.cost_effective && <StatusBadge status="serious" label="Not cost-effective" />}
          <span className="rounded border border-hairline px-1.5 py-0.5 text-[11px] text-ink-2">{r.effort} effort</span>
          <ProposeButton r={r} />
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Figure label="Breaches avoided" value={formatCount(Math.round(i.annual_breaches_avoided))} note={`a year (${formatCount(Math.round(i.breaches_avoided))} in period)`} />
        <Figure label="Breach rate" value={`${formatPercent(i.breach_rate_now)} → ${formatPercent(i.breach_rate_after)}`} />
        <Figure label="Net value / year" value={lakh(i.annual_net_inr)} note={`${lakh(i.annual_benefit_inr)} benefit − ${lakh(i.annual_cost_inr)} cost`} />
        <Figure label={`${L.Many} affected`} value={formatCount(Math.round(i.affected_claims))} note={i.cost_basis} />
      </div>
      {r.rationale && (
        <p className="mt-2 text-xs text-ink-2">
          <span className="font-medium text-ink">Why: </span>
          {r.rationale}
          {r.hypothesis_ids.length > 0 && <span className="text-ink-muted"> (addresses {r.hypothesis_ids.map((id) => `${id}${hypotheses.find((h) => h.id === id)?.verdict === 'supported' ? '' : '?'}`).join(', ')})</span>}
        </p>
      )}
      {r.policy.length > 0 && (
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer text-ink-2">Policy basis: {r.policy.map((p) => p.ref).join(', ')}</summary>
          <ul className="mt-1 grid gap-1.5">
            {r.policy.map((p) => (
              <li key={p.ref} className="rounded-md bg-ghost p-2 text-ink-2">
                <span className="font-semibold text-ink">{p.ref}</span> · {p.title} v{p.version}
                <MarkdownLite text={p.text} className="mt-1 text-[11px]" />
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  )
}

function Figure({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <div className="text-[11px] text-ink-muted">{label}</div>
      <div className="text-base font-semibold text-ink">{value}</div>
      {note && <div className="text-[11px] text-ink-muted">{note}</div>}
    </div>
  )
}

function Signals({ state }: { state: InvestigationState }) {
  return (
    <Card title="Signals from the statistical scan" subtitle="Computed before any model is involved: significance tests, bottlenecks, weekday effects, trend.">
      <details>
        <summary className="cursor-pointer text-xs text-ink-2">Show {state.signals!.length} signals</summary>
        <ul className="mt-2 grid gap-1.5 text-xs text-ink-2">
          {state.signals!.map((s) => (
            <li key={s.id}>
              <span className="mr-1 rounded border border-hairline px-1 text-[10px] uppercase text-ink-muted">{s.kind}</span>
              {s.statement}
            </li>
          ))}
        </ul>
      </details>
    </Card>
  )
}

function MetricAnswer({ result }: { result: NonNullable<InvestigationState['metric_answer']> }) {
  const L = useLabels()
  if (result.error) return <Card title="Couldn't compute that metric"><ErrorNote error={result.error} /></Card>
  return (
    <Card title={result.label} subtitle={result.description}>
      <table className="tabular w-full text-left text-sm">
        <tbody>
          {result.rows.map((r, i) => (
            <tr key={i} className="border-b border-hairline last:border-0">
              <td className="py-1.5 pr-4 text-ink-2">{Object.values(r.group).map(formatDimensionValue).join(' · ') || `All ${L.many} in scope`}</td>
              <td className="py-1.5 pr-4 font-semibold text-ink">{formatValue(r.value, result.unit)}</td>
              <td className="py-1.5 text-xs text-ink-muted">
                n = {formatCount(r.n)} {r.low_sample && <LowSample n={r.n} />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <details className="mt-3 text-xs">
        <summary className="cursor-pointer text-ink-2">SQL used</summary>
        <pre className="mt-1 overflow-x-auto rounded-md bg-ghost p-2 text-[11px] text-ink-2">{result.sql}</pre>
      </details>
    </Card>
  )
}

function PolicyAnswer({ state }: { state: InvestigationState }) {
  const a = state.answer!
  return (
    <Card title="Answer from the policy library" actions={a.grounded ? <StatusBadge status="good" label="Grounded in sources" /> : <StatusBadge status="critical" label="Partly unsupported" />}>
      <p className="text-sm text-ink"><Inline text={a.answer} /></p>
      <ul className="mt-3 grid gap-1 text-xs text-ink-2">
        {a.citations.map((c) => (
          <li key={c.number}>
            [{c.number}] <span className="font-semibold text-ink">{c.doc_key}</span> v{c.version} § {c.section}
          </li>
        ))}
      </ul>
    </Card>
  )
}

// ------------------------------------------------------------------------- history

function History({ activeId, onOpen }: { activeId: string | null; onOpen: () => void }) {
  const [, setParams] = useSearchParams()
  const recent = useQuery({ queryKey: ['investigations'], queryFn: investigationsApi.recent })
  return (
    <Card title="Recent investigations">
      {recent.error && <ErrorNote error={recent.error} />}
      {recent.data?.length === 0 && <p className="text-xs text-ink-muted">None yet.</p>}
      <ul className="grid gap-1">
        {recent.data?.map((r) => (
          <li key={r.investigation_id}>
            <button
              onClick={() => {
                onOpen()
                setParams((p) => {
                  const n = new URLSearchParams(p)
                  n.set('id', r.investigation_id)
                  return n
                })
              }}
              className={`w-full rounded-md px-2 py-1.5 text-left text-xs hover:bg-ghost ${activeId === r.investigation_id ? 'bg-ghost' : ''}`}
            >
              <div className="line-clamp-2 text-ink">{r.question}</div>
              <div className="mt-0.5 text-[11px] text-ink-muted">
                {r.status === 'completed' ? (r.route === 'investigation' ? `${r.supported} supported` : r.route) : r.status} ·{' '}
                {r.duration_ms ? `${Math.round(r.duration_ms / 1000)} s · ` : ''}
                {new Date(r.created_at).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' })}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}
