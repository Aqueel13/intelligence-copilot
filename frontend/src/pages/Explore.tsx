import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { exploreApi, type Draft, type ExploreResult } from '../api/explore'
import { Card, ErrorNote, StatusBadge } from '../components/ui'
import { useAuth } from '../lib/auth'
import { useDomain } from '../lib/hooks'

const EXAMPLES: Record<string, string> = {
  'Cases and breach rate by month':
    "select to_char(opened_at, 'YYYY-MM') as month, count(*) as cases,\n       round(avg(breached::int), 3) as breach_rate\nfrom cases\ngroup by 1\norder by 1",
  'Slowest activities by mean wait':
    'select activity, count(*) as events, round(avg(wait_hours), 1) as mean_wait_h\nfrom events\ngroup by 1\norder by 3 desc nulls last',
  'CSAT of breached vs on-time cases':
    'select c.breached, count(*) as responses, round(avg(f.csat), 2) as csat\nfrom feedback f join cases c using (case_id)\nwhere f.responded\ngroup by 1',
}

export default function Explore() {
  const { can } = useAuth()
  const domain = useDomain().data
  const allowed = can('explore')
  const [question, setQuestion] = useState('')
  const [sql, setSql] = useState(Object.values(EXAMPLES)[0])
  const [draftInfo, setDraftInfo] = useState<Draft | null>(null)
  const schema = useQuery({ queryKey: ['explore-schema'], queryFn: exploreApi.schema, enabled: allowed })
  const run = useMutation({ mutationFn: exploreApi.run })
  const draft = useMutation({
    mutationFn: exploreApi.draft,
    onSuccess: (d) => {
      setDraftInfo(d)
      setSql(d.sql)
      run.mutate(d.sql)
    },
  })

  if (!allowed)
    return (
      <Card title="Explore">
        <p className="text-sm text-ink-2">Exploratory SQL is available to analysts and admins. Your role can use the governed metrics on Overview and Process.</p>
      </Card>
    )

  const onDraft = (e: FormEvent) => {
    e.preventDefault()
    if (question.trim().length >= 5) draft.mutate(question.trim())
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="grid min-w-0 content-start gap-4">
        <Card
          title="Explore with SQL"
          subtitle={`Read-only queries over ${domain?.display_name ?? 'this pack'}'s cases, events and survey feedback, for questions the governed metrics do not cover.`}
          actions={<StatusBadge status="warning" label="Exploratory: not a verified metric" />}
        >
          <form onSubmit={onDraft} className="flex gap-2">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Describe what you want to see; a model drafts the SQL for you to check"
              className="min-w-0 flex-1 rounded-lg border border-hairline bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted"
              aria-label="Question for the SQL draft"
              maxLength={500}
            />
            <button
              type="submit"
              disabled={draft.isPending || question.trim().length < 5}
              className="rounded-lg border border-hairline px-4 py-2 text-sm font-semibold text-ink hover:bg-ghost disabled:opacity-50"
            >
              {draft.isPending ? 'Drafting…' : 'Draft SQL'}
            </button>
          </form>
          {draft.error && <div className="mt-2"><ErrorNote error={draft.error} /></div>}
          {draftInfo && (
            <p className="mt-2 text-xs text-ink-2">
              <span className="font-semibold">Drafted by {draftInfo.model}:</span> {draftInfo.explanation} Read the SQL before relying on the result.
            </p>
          )}

          <label className="mt-4 block text-xs font-medium text-ink-2" htmlFor="sql">
            SQL (one SELECT; tables: cases, events, feedback)
          </label>
          <textarea
            id="sql"
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            rows={8}
            spellCheck={false}
            className="mt-1 w-full rounded-lg border border-hairline bg-surface p-3 font-mono text-xs text-ink"
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              onClick={() => run.mutate(sql)}
              disabled={run.isPending || !sql.trim()}
              className="rounded-lg bg-series-1 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {run.isPending ? 'Running…' : 'Run'}
            </button>
            {Object.entries(EXAMPLES).map(([label, q]) => (
              <button key={label} onClick={() => setSql(q)} className="rounded-full border border-hairline px-2.5 py-1 text-xs text-ink-2 hover:bg-ghost">
                {label}
              </button>
            ))}
          </div>
        </Card>

        {run.error && (
          <Card>
            <ErrorNote error={run.error} />
          </Card>
        )}
        {run.data && <Result result={run.data} maxRows={schema.data?.max_rows ?? 500} />}
      </div>

      <Card title="Tables" subtitle={schema.data ? `At most ${schema.data.max_rows} rows; queries stop after ${schema.data.timeout_seconds} s. Nothing else in the database is readable.` : undefined}>
        {schema.error && <ErrorNote error={schema.error} />}
        {schema.data && <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-ink-2">{schema.data.doc}</pre>}
      </Card>
    </div>
  )
}

function Result({ result, maxRows }: { result: ExploreResult; maxRows: number }) {
  return (
    <Card
      title={`${result.row_count} row${result.row_count === 1 ? '' : 's'}${result.truncated ? ` (first ${maxRows} shown)` : ''}`}
      subtitle={`${result.label} · ${result.duration_ms} ms`}
    >
      <div className="max-h-[32rem] overflow-auto">
        <table className="tabular w-full text-left text-xs">
          <thead className="sticky top-0 bg-surface">
            <tr className="border-b border-hairline text-ink-2">
              {result.columns.map((c, i) => (
                <th key={i} scope="col" className="py-1.5 pr-4 font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((r, i) => (
              <tr key={i} className="border-b border-hairline last:border-0">
                {r.map((cell, j) => (
                  <td key={j} className="py-1.5 pr-4 align-top text-ink">
                    {cell === null ? <span className="text-ink-muted">null</span> : typeof cell === 'object' ? JSON.stringify(cell) : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
