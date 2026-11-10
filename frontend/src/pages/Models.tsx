import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { BarList, type BarDatum } from '../components/BarList'
import { Card, ErrorNote, Segmented, StatTile } from '../components/ui'
import { apiFetch } from '../lib/domainStore'
import { useActiveDomain } from '../lib/domain'
import { formatCount, formatPercent } from '../lib/format'

// ---- API shapes (backend/evaluation/summary.py)

interface InvestigationStats {
  runs: number
  completed: number
  rate_limited: number
  failed: number
  mean_recall: number | null
  all_found: number
  decoy_runs: number
  decoys_accepted: number
  remedy_rate: number | null
  downgrades: number
  coverage_added: number
  unverified_numbers: number
  mean_duration_s: number | null
  mean_llm_calls: number | null
  mean_tokens: number | null
  causes: Record<string, { found: number; of: number }>
  seeds: number[]
}

interface QaStats {
  answerable: number
  answered_rate: number | null
  cites_relevant: number | null
  grounded: number | null
  model_citation_accuracy: number | null
  declined: number
  unanswerable: number
  errors: number
  mean_generation_s: number | null
}

interface ModelRow {
  model: string
  provider: string
  investigations: InvestigationStats | null
  qa: QaStats | null
  last_run: string
}

interface Comparison {
  runs: { name: string; started: string; finished?: string; domain: string; models: string[]; seeds: number[]; suites: string[] }[]
  superseded: number
  domains: { domain: string; cause_labels: Record<string, string>; models: ModelRow[]; questions: string[] }[]
}

const getComparison = () =>
  apiFetch('/api/evaluation/comparison').then((r) => {
    if (!r.ok) throw new Error(`comparison: ${r.status}`)
    return r.json() as Promise<Comparison>
  })

const pct = (x: number | null | undefined) => (x == null ? '–' : formatPercent(x, 0))
const shortName = (m: string) => m.replace(/^(ollama|groq|gemini):/, '').replace(/^openai\//, '').replace(/^qwen\//, '')
const where = (m: ModelRow) => (m.provider === 'ollama' ? 'local' : `${m.provider} free tier`)

const PACK_LABELS: Record<string, string> = {
  insurance_claims: 'Insurance claims',
  procure_to_pay: 'Procure-to-pay',
}

export default function Models() {
  const q = useQuery({ queryKey: ['evaluation-comparison'], queryFn: getComparison, staleTime: 60_000 })
  const { domain } = useActiveDomain()
  const [picked, setPicked] = useState<string | null>(null)
  if (q.error) return <ErrorNote error={q.error} />
  if (!q.data) return null
  const c = q.data
  if (!c.domains.length)
    return (
      <Card title="Model comparison">
        <p className="text-sm text-ink-2">No saved evaluation runs yet. Run `make eval`.</p>
      </Card>
    )
  const available = c.domains.map((d) => d.domain)
  const active = picked ?? (domain && available.includes(domain) ? domain : available[0])
  const d = c.domains.find((x) => x.domain === active)!
  const lastRun = c.runs.at(-1)

  return (
    <div className="grid gap-4">
      <Card
        title="Model comparison"
        subtitle="Every model on the same benchmark: investigations scored against planted ground truth, grounded policy answers, speed and token use. Read live from the saved evaluation runs, so it updates as new runs are added."
        actions={
          <Segmented
            label="Process"
            value={active}
            onChange={setPicked}
            options={available.map((x) => ({ value: x, label: PACK_LABELS[x] ?? x }))}
          />
        }
      >
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-2">
          <span>
            <b className="text-ink">{c.runs.length}</b> runs merged
          </span>
          <span>
            <b className="text-ink">{c.superseded}</b> earlier results replaced by re-runs after fixes
          </span>
          {lastRun && (
            <span>
              Latest run <b className="text-ink">{lastRun.name}</b> ({lastRun.domain})
            </span>
          )}
        </div>
      </Card>

      <Leaders rows={d.models} />
      <ComparisonTable rows={d.models} />

      <div className="grid gap-4 lg:grid-cols-2">
        <MetricBars
          title="Planted causes found (mean recall)"
          subtitle="Completed investigations; a cause counts only if a supported hypothesis targets it"
          rows={d.models}
          value={(m) => m.investigations?.mean_recall ?? null}
          display={(v) => pct(v)}
          n={(m) => m.investigations?.completed ?? 0}
          max={1}
        />
        <MetricBars
          title="Model's own citation accuracy (Q&A)"
          subtitle="Share of answer sentences cited correctly before the verifier corrects anything"
          rows={d.models}
          value={(m) => m.qa?.model_citation_accuracy ?? null}
          display={(v) => pct(v)}
          n={(m) => m.qa?.answerable ?? 0}
          max={1}
        />
        <MetricBars
          title="Mean investigation time"
          subtitle="Seconds per completed investigation (local GPU vs free-tier cloud, including rate-limit waits)"
          rows={d.models}
          value={(m) => m.investigations?.mean_duration_s ?? null}
          display={(v) => `${v.toFixed(0)} s`}
          n={(m) => m.investigations?.completed ?? 0}
        />
        <MetricBars
          title="Tokens per investigation"
          subtitle="Input + output tokens; on a free tier this is what the daily quota is spent on"
          rows={d.models}
          value={(m) => m.investigations?.mean_tokens ?? null}
          display={(v) => formatCount(Math.round(v))}
          n={(m) => m.investigations?.completed ?? 0}
        />
      </div>

      <CauseMatrix rows={d.models} labels={d.cause_labels} />

      <Card title="Runs included" subtitle="Later runs replace earlier results for the same pack, model, seed and question.">
        <table className="tabular w-full text-left text-xs">
          <thead>
            <tr className="border-b border-hairline text-ink-2">
              {['Run', 'Pack', 'Started', 'Models', 'Seeds', 'Suites'].map((h) => (
                <th key={h} className="py-1.5 pr-4 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {c.runs.map((r) => (
              <tr key={r.name} className="border-b border-hairline last:border-0">
                <td className="py-1.5 pr-4 font-medium text-ink">{r.name}</td>
                <td className="py-1.5 pr-4 text-ink-2">{PACK_LABELS[r.domain] ?? r.domain}</td>
                <td className="py-1.5 pr-4 text-ink-2">{r.started?.replace('T', ' ')}</td>
                <td className="py-1.5 pr-4 text-ink-2">{r.models.map(shortName).join(', ')}</td>
                <td className="py-1.5 pr-4 text-ink-2">{r.seeds.join(', ')}</td>
                <td className="py-1.5 pr-4 text-ink-2">{r.suites.join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-xs text-ink-muted">
          Synthetic data, author-written benchmarks, few seeds: differences of one or two runs are not significant. Full detail and every failure in{' '}
          <code>docs/evaluation_report.md</code>.
        </p>
      </Card>
    </div>
  )
}

/** Headline tiles: the best model on each axis, so the trade-off is visible at a glance. */
function Leaders({ rows }: { rows: ModelRow[] }) {
  // Ties go to the model with more completed runs (more evidence behind the same score).
  const best = (f: (m: ModelRow) => number | null | undefined, low = false) => {
    const scored = rows.filter((m) => f(m) != null)
    if (!scored.length) return null
    const n = (m: ModelRow) => m.investigations?.completed ?? m.qa?.answerable ?? 0
    return scored.reduce((a, b) => {
      const fa = f(a)!, fb = f(b)!
      if (fa === fb) return n(b) > n(a) ? b : a
      return (low ? fb < fa : fb > fa) ? b : a
    })
  }
  const recall = best((m) => m.investigations?.mean_recall)
  const cite = best((m) => m.qa?.model_citation_accuracy)
  const fast = best((m) => m.investigations?.mean_duration_s, true)
  const decoys = rows.reduce((s, m) => s + (m.investigations?.decoys_accepted ?? 0), 0)
  const decoyRuns = rows.reduce((s, m) => s + (m.investigations?.decoy_runs ?? 0), 0)
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <StatTile
        label="Decoys accepted, all models"
        value={`${decoys} / ${decoyRuns}`}
        note="Runs whose question had a decoy; confounder rules catch what models miss"
      />
      <StatTile
        label="Highest recall"
        value={recall ? pct(recall.investigations?.mean_recall) : '–'}
        note={recall ? `${shortName(recall.model)} · ${where(recall)}` : undefined}
      />
      <StatTile
        label="Best own citations"
        value={cite ? pct(cite.qa?.model_citation_accuracy) : '–'}
        note={cite ? `${shortName(cite.model)} · ${where(cite)}` : undefined}
      />
      <StatTile
        label="Fastest investigation"
        value={fast?.investigations?.mean_duration_s != null ? `${fast.investigations.mean_duration_s.toFixed(0)} s` : '–'}
        note={fast ? `${shortName(fast.model)} · ${where(fast)}` : undefined}
      />
    </div>
  )
}

function ComparisonTable({ rows }: { rows: ModelRow[] }) {
  const head = [
    'Model',
    'Where',
    'Completed',
    'Rate-limited',
    'Failed',
    'Mean recall',
    'All causes found',
    'Decoys accepted',
    'Remedy recommended',
    'Q&A grounded',
    'Own citations',
    'Unanswerable declined',
  ]
  return (
    <Card title="All models" subtitle="Completed = the run reached the model's reasoning. Rate-limited runs were refused by a free-tier quota and are not counted against quality.">
      <div className="overflow-x-auto">
        <table className="tabular w-full text-left text-xs">
          <thead>
            <tr className="border-b border-hairline text-ink-2">
              {head.map((h) => (
                <th key={h} scope="col" className="py-1.5 pr-4 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => {
              const i = m.investigations
              const qa = m.qa
              return (
                <tr key={m.model} className="border-b border-hairline last:border-0">
                  <td className="py-1.5 pr-4 font-medium text-ink">{shortName(m.model)}</td>
                  <td className="py-1.5 pr-4 text-ink-2">{where(m)}</td>
                  <td className="py-1.5 pr-4">{i ? `${i.completed}/${i.runs}` : '–'}</td>
                  <td className="py-1.5 pr-4">{i?.rate_limited ?? '–'}</td>
                  <td className="py-1.5 pr-4">{i?.failed ?? '–'}</td>
                  <td className="py-1.5 pr-4 font-semibold">{pct(i?.mean_recall)}</td>
                  <td className="py-1.5 pr-4">{i ? `${i.all_found}/${i.completed}` : '–'}</td>
                  <td className="py-1.5 pr-4">{i ? `${i.decoys_accepted}/${i.decoy_runs}` : '–'}</td>
                  <td className="py-1.5 pr-4">{pct(i?.remedy_rate)}</td>
                  <td className="py-1.5 pr-4">{pct(qa?.grounded)}</td>
                  <td className="py-1.5 pr-4">{pct(qa?.model_citation_accuracy)}</td>
                  <td className="py-1.5 pr-4">{qa ? `${qa.declined}/${qa.unanswerable}` : '–'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function MetricBars({
  title,
  subtitle,
  rows,
  value,
  display,
  n,
  max,
}: {
  title: string
  subtitle: string
  rows: ModelRow[]
  value: (m: ModelRow) => number | null
  display: (v: number) => string
  n: (m: ModelRow) => number
  max?: number
}) {
  const data: BarDatum[] = rows
    .filter((m) => value(m) != null)
    .map((m) => ({ label: shortName(m.model), value: value(m)!, display: display(value(m)!), n: n(m), note: where(m) }))
  return (
    <Card title={title} subtitle={subtitle}>
      {data.length ? <BarList data={data} max={max} caption={title} valueLabel={title} /> : <p className="text-xs text-ink-muted">No data yet.</p>}
    </Card>
  )
}

function CauseMatrix({ rows, labels }: { rows: ModelRow[]; labels: Record<string, string> }) {
  const causes = Object.keys(labels)
  return (
    <Card title="Each planted cause, by model" subtitle="Found / runs whose question expects it. A miss is a real cause left inconclusive or refuted.">
      <div className="overflow-x-auto">
        <table className="tabular w-full text-left text-xs">
          <thead>
            <tr className="border-b border-hairline text-ink-2">
              <th className="py-1.5 pr-4 font-medium">Model</th>
              {causes.map((rc) => (
                <th key={rc} className="py-1.5 pr-4 font-medium">
                  {rc} · {labels[rc]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.model} className="border-b border-hairline last:border-0">
                <td className="py-1.5 pr-4 font-medium text-ink">{shortName(m.model)}</td>
                {causes.map((rc) => {
                  const cell = m.investigations?.causes[rc]
                  const full = cell && cell.found === cell.of
                  return (
                    <td key={rc} className={`py-1.5 pr-4 ${cell && !full ? 'font-semibold text-serious' : 'text-ink'}`}>
                      {cell ? `${cell.found}/${cell.of}` : '–'}
                      {cell && !full && <span className="sr-only"> (missed in some runs)</span>}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
