import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { BarList, type BarDatum } from '../components/BarList'
import { TrendChart } from '../components/TrendChart'
import { Card, ErrorNote, Refetching, Segmented, StatTile, StatusBadge } from '../components/ui'
import { apiFetch } from '../lib/domainStore'
import { formatCount, formatPercent } from '../lib/format'

// ---- API shapes (backend/observability/queries.py)

interface LlmAgg {
  calls: number
  errors: number
  cache_hits: number
  input_tokens: number
  output_tokens: number
  tokens_saved: number
  light_calls: number
  p50_ms: number | null
  p95_ms: number | null
}
type Keyed = LlmAgg & { key: string | null }

interface Summary {
  hours: number
  bucket: 'hour' | 'day'
  llm: LlmAgg
  by: Record<'model' | 'role' | 'purpose' | 'domain' | 'tier', Keyed[]>
  series: { bucket: string; calls: number; errors: number; cache_hits: number; tokens: number }[]
  api: { key: string; requests: number; server_errors: number; client_errors: number; p50_ms: number; p95_ms: number }[]
  errors: { at: string; domain: string; role: string; model: string; purpose: string | null; investigation_id: string | null; error: string }[]
  quota: { model: string; tokens: number; limit: number; share: number | null }[]
  mcp: {
    tools: (McpAgg & { server: string; tool: string })[]
    clients: (McpAgg & { key: string })[]
    errors: { at: string; server: string; tool: string; client: string; domain: string | null; error: string | null }[]
  }
}

interface McpAgg {
  calls: number
  errors: number
  p50_ms: number | null
  p95_ms: number | null
  last_at: string
}

interface InvestigationRow {
  investigation_id: string
  domain: string
  question: string
  status: string
  created_at: string
  duration_ms: number | null
  llm_calls: number
  tokens: number
  errors: number
}

interface Trace {
  question: string
  duration_ms: number | null
  steps: { node: string; ms: number; model: string | null; note: string | null }[]
  calls: { at: string; role: string; model: string; tier: string; duration_ms: number; input_tokens: number; output_tokens: number; status: string; error: string | null }[]
}

const get = <T,>(url: string) =>
  apiFetch(url).then((r) => {
    if (!r.ok) throw new Error(`${url}: ${r.status}`)
    return r.json() as Promise<T>
  })

const ms = (v: number | null | undefined) => (v == null ? '–' : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`)
const short = (m: string | null) => (m ?? '–').replace(/^(ollama|groq|gemini):/, '').replace(/^openai\//, '').replace(/^qwen\//, '')
const PERIODS = [
  { value: '24', label: '24 hours' },
  { value: '168', label: '7 days' },
  { value: '720', label: '30 days' },
]

export default function Observability() {
  const [hours, setHours] = useState('24')
  const q = useQuery({
    queryKey: ['observability', hours],
    queryFn: () => get<Summary>(`/api/observability/summary?hours=${hours}`),
    refetchInterval: 30_000,
  })
  if (q.error) return <ErrorNote error={q.error} />
  if (!q.data) return null
  const s = q.data
  const l = s.llm
  const tokens = l.input_tokens + l.output_tokens
  const answered = l.calls + l.cache_hits

  return (
    <Refetching active={q.isFetching}>
      <div className="grid gap-4">
        <Card
          title="Observability"
          subtitle="Every LLM call and API request, recorded in Postgres: latency, tokens, errors, cache hits and which model tier served it. All packs; refreshes every 30 seconds."
          actions={<Segmented label="Period" value={hours} onChange={setHours} options={PERIODS} />}
        >
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <StatTile label="LLM calls" value={formatCount(l.calls)} note={`${formatCount(l.errors)} errors (${formatPercent(l.calls ? l.errors / l.calls : 0, 1)})`} />
            <StatTile label="Tokens" value={formatCount(tokens)} note={`${formatCount(l.input_tokens)} in · ${formatCount(l.output_tokens)} out`} />
            <StatTile label="Latency per call" value={ms(l.p50_ms)} note={`median · 95th percentile ${ms(l.p95_ms)}`} />
            <StatTile
              label="Knowledge cache"
              value={formatPercent(answered ? l.cache_hits / answered : 0, 0)}
              note={`${formatCount(l.cache_hits)} hits · ${formatCount(l.tokens_saved)} tokens saved`}
            />
            <StatTile label="Served by the light model" value={formatPercent(l.calls ? l.light_calls / l.calls : 0, 0)} note={`${formatCount(l.light_calls)} simple requests routed to the cheaper tier`} />
          </div>
        </Card>

        <div className="grid gap-4 lg:grid-cols-2">
          <Series s={s} metric="calls" title="LLM calls" />
          <Series s={s} metric="tokens" title="Tokens" />
        </div>

        {s.quota.length > 0 && (
          <Card title="Free-tier quota, rolling 24 hours" subtitle="Groq's free tier allows a daily token budget per model; investigations spend it fastest">
            <BarList
              data={s.quota.map((x) => ({
                label: short(x.model),
                value: x.tokens,
                display: `${formatCount(x.tokens)} of ${formatCount(x.limit)} (${formatPercent(x.share ?? 0, 0)})`,
                n: x.tokens,
              }))}
              max={Math.max(...s.quota.map((x) => x.limit))}
              caption="Tokens used per Groq model in the last 24 hours"
              valueLabel="Tokens"
            />
          </Card>
        )}

        <div className="grid gap-4 lg:grid-cols-2">
          <Breakdown title="Tokens by model" rows={s.by.model} value={(r) => r.input_tokens + r.output_tokens} display={(v) => formatCount(v)} />
          <Breakdown title="95th percentile latency by model" rows={s.by.model} value={(r) => r.p95_ms ?? 0} display={ms} />
          <Breakdown title="Calls by role" rows={s.by.role} value={(r) => r.calls} display={(v) => formatCount(v)} />
          <Breakdown title="Calls by purpose" rows={s.by.purpose} value={(r) => r.calls + r.cache_hits} display={(v) => formatCount(v)} />
        </div>

        <Investigations />

        <Card title="API" subtitle="Requests by route (health and observability polling excluded)">
          <Table
            head={['Route', 'Requests', '5xx', '4xx', 'Median', '95th pct']}
            rows={s.api.map((a) => [a.key, formatCount(a.requests), a.server_errors, a.client_errors, ms(a.p50_ms), ms(a.p95_ms)])}
          />
        </Card>

        <Mcp m={s.mcp} />

        <Card title="Recent LLM errors" subtitle="Provider failures, timeouts and malformed output that could not be repaired">
          {s.errors.length ? (
            <ul className="space-y-2 text-xs">
              {s.errors.map((e, i) => (
                <li key={i} className="rounded-md border border-hairline p-2">
                  <StatusBadge status="critical" label={`${short(e.model)} · ${e.role}`} />
                  <span className="ml-2 text-ink-muted">
                    {new Date(e.at).toLocaleString()} · {e.domain} · {e.purpose ?? '–'}
                  </span>
                  <div className="mt-1 break-words text-ink-2">{e.error}</div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-ink-muted">None in this period.</p>
          )}
        </Card>
      </div>
    </Refetching>
  )
}

function Mcp({ m }: { m: Summary['mcp'] }) {
  const when = (at: string) => new Date(at).toLocaleString()
  return (
    <Card
      title="MCP tool calls"
      subtitle="Calls from external MCP clients to the Analytics, Knowledge and Operations servers, by the client name their token maps to. Arguments are not recorded."
    >
      {m.tools.length ? (
        <div className="grid gap-4">
          <Table
            head={['Server · tool', 'Calls', 'Errors', 'Median', '95th pct', 'Last call']}
            rows={m.tools.map((t) => [`${t.server} · ${t.tool}`, formatCount(t.calls), t.errors, ms(t.p50_ms), ms(t.p95_ms), when(t.last_at)])}
          />
          <Table
            head={['Client', 'Calls', 'Errors', 'Median', '95th pct', 'Last call']}
            rows={m.clients.map((c) => [c.key, formatCount(c.calls), c.errors, ms(c.p50_ms), ms(c.p95_ms), when(c.last_at)])}
          />
          {m.errors.length > 0 && (
            <ul className="space-y-2 text-xs">
              {m.errors.map((e, i) => (
                <li key={i} className="rounded-md border border-hairline p-2">
                  <StatusBadge status="critical" label={`${e.server} · ${e.tool}`} />
                  <span className="ml-2 text-ink-muted">
                    {when(e.at)} · {e.client}
                    {e.domain ? ` · ${e.domain}` : ''}
                  </span>
                  <div className="mt-1 break-words text-ink-2">{e.error}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="text-xs text-ink-muted">No MCP calls in this period.</p>
      )}
    </Card>
  )
}

function Series({ s, metric, title }: { s: Summary; metric: 'calls' | 'tokens'; title: string }) {
  const data = s.series.map((p) => {
    const d = new Date(p.bucket)
    return {
      x: p.bucket,
      xLabel: s.bucket === 'hour' ? d.toLocaleTimeString([], { hour: '2-digit' }) : d.toLocaleDateString([], { day: 'numeric', month: 'short' }),
      y: p[metric],
      n: p.calls,
    }
  })
  return (
    <Card title={`${title} per ${s.bucket}`}>
      {data.length ? (
        <TrendChart data={data} format={(v) => formatCount(v)} axisFormat={(v) => formatCount(v)} caption={`${title} per ${s.bucket}`} valueLabel={title} />
      ) : (
        <p className="text-xs text-ink-muted">No calls in this period.</p>
      )}
    </Card>
  )
}

function Breakdown({ title, rows, value, display }: { title: string; rows: Keyed[]; value: (r: Keyed) => number; display: (v: number) => string }) {
  const data: BarDatum[] = rows.map((r) => ({ label: r.key === null ? '(unattributed)' : short(r.key), value: value(r), display: display(value(r)), n: r.calls }))
  return <Card title={title}>{data.length ? <BarList data={data} caption={title} valueLabel={title} /> : <p className="text-xs text-ink-muted">No data.</p>}</Card>
}

function Table({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="tabular w-full text-left text-xs">
        <thead>
          <tr className="border-b border-hairline text-ink-2">
            {head.map((h) => (
              <th key={h} className="py-1.5 pr-4 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-hairline last:border-0">
              {r.map((c, j) => (
                <td key={j} className={`py-1.5 pr-4 ${j === 0 ? 'font-medium text-ink' : 'text-ink-2'}`}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Recent investigations, each opening into a trace: graph steps and every LLM call on a timeline. */
function Investigations() {
  const q = useQuery({ queryKey: ['obs-investigations'], queryFn: () => get<InvestigationRow[]>('/api/observability/investigations') })
  const [open, setOpen] = useState<string | null>(null)
  return (
    <Card title="Investigation traces" subtitle="Every LLM call an investigation made, with its role, model, latency and tokens">
      {!q.data?.length ? (
        <p className="text-xs text-ink-muted">No investigations yet.</p>
      ) : (
        <ul className="divide-y divide-hairline">
          {q.data.map((r) => (
            <li key={r.investigation_id} className="py-2">
              <button
                className="flex w-full flex-wrap items-baseline justify-between gap-2 text-left"
                onClick={() => setOpen(open === r.investigation_id ? null : r.investigation_id)}
                aria-expanded={open === r.investigation_id}
              >
                <span className="text-sm text-ink">{r.question}</span>
                <span className="text-xs text-ink-muted">
                  {r.domain} · {new Date(r.created_at).toLocaleString()} · {ms(r.duration_ms)} · {r.llm_calls} calls · {formatCount(r.tokens)} tokens
                  {r.errors > 0 && <span className="ml-1 text-critical">· {r.errors} errors</span>}
                </span>
              </button>
              {open === r.investigation_id && <TraceView id={r.investigation_id} />}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function TraceView({ id }: { id: string }) {
  const q = useQuery({ queryKey: ['trace', id], queryFn: () => get<Trace>(`/api/observability/investigations/${id}`) })
  if (!q.data) return <p className="mt-2 text-xs text-ink-muted">Loading…</p>
  const t = q.data
  if (!t.calls.length)
    return <p className="mt-2 text-xs text-ink-muted">No LLM calls recorded (this run predates observability).</p>
  const t0 = new Date(t.calls[0].at).getTime() - t.calls[0].duration_ms
  const end = Math.max(...t.calls.map((c) => new Date(c.at).getTime())) - t0 || 1
  return (
    <div className="mt-3 space-y-1">
      <div className="mb-2 text-xs text-ink-2">
        Steps: {t.steps.map((s) => `${s.node} ${ms(s.ms)}`).join(' → ')}
      </div>
      {t.calls.map((c, i) => {
        const finish = new Date(c.at).getTime() - t0
        const start = finish - c.duration_ms
        return (
          <div key={i} className="grid grid-cols-[9rem_1fr_9rem] items-center gap-2 text-[11px]">
            <span className="truncate text-ink-2" title={c.model}>
              {c.role} · {short(c.model)}
            </span>
            <div className="relative h-3 rounded bg-ghost" aria-hidden>
              <div
                className={`absolute h-3 rounded ${c.status === 'error' ? 'bg-critical' : 'bg-series-1'}`}
                style={{ left: `${(start / end) * 100}%`, width: `${Math.max((c.duration_ms / end) * 100, 0.5)}%` }}
              />
            </div>
            <span className="text-ink-muted">
              {ms(c.duration_ms)} · {formatCount(c.input_tokens + c.output_tokens)} tok{c.status === 'error' ? ' · error' : ''}
            </span>
          </div>
        )
      })}
    </div>
  )
}
