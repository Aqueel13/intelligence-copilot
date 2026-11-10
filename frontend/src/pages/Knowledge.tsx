import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, type Answer, type RetrievedChunk, type SentenceCheck } from '../api/client'
import { MarkdownLite } from '../components/MarkdownLite'
import { Card, ErrorNote, Segmented, StatusBadge } from '../components/ui'
import { formatPercent } from '../lib/format'

const EXAMPLES = [
  'Who approves a claim of ₹3,00,000, and how fast?',
  'Can senior approvals be delegated? Under what conditions?',
  'What happens to work handed over late on a Friday?',
  'What QA rejection rate is acceptable for a verification team?',
  'Why do broker claims arrive without complete documents?',
]

type Mode = 'ask' | 'search'

export default function Knowledge() {
  const [question, setQuestion] = useState('')
  const [mode, setMode] = useState<Mode>('ask')
  const [history, setHistory] = useState(false)
  const [active, setActive] = useState<number | null>(null)

  const ask = useMutation({ mutationFn: (q: string) => api.ask(q, history) })
  const search = useMutation({ mutationFn: (q: string) => api.search(q, history) })

  const submit = (q: string) => {
    const text = q.trim()
    if (text.length < 3) return
    setQuestion(text)
    setActive(null)
    if (mode === 'ask') ask.mutate(text)
    else search.mutate(text)
  }
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    submit(question)
  }

  const busy = ask.isPending || search.isPending
  const sources = mode === 'ask' ? ask.data?.sources : search.data

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="grid content-start gap-4">
        <Card
          title="Ask the policy library"
          subtitle="Answers use only the Company's policies and procedures, with every sentence checked against its source."
          actions={
            <Segmented
              label="Mode"
              value={mode}
              onChange={setMode}
              options={[
                { value: 'ask', label: 'Ask' },
                { value: 'search', label: 'Search only' },
              ]}
            />
          }
        >
          <form onSubmit={onSubmit} className="flex gap-2">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. Who approves a claim of ₹3,00,000?"
              className="min-w-0 flex-1 rounded-lg border border-hairline bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted"
              aria-label="Question"
              maxLength={500}
            />
            <button
              type="submit"
              disabled={busy || question.trim().length < 3}
              className="rounded-lg bg-series-1 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {busy ? 'Working…' : mode === 'ask' ? 'Ask' : 'Search'}
            </button>
          </form>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => submit(ex)}
                disabled={busy}
                className="rounded-full border border-hairline px-2.5 py-1 text-xs text-ink-2 hover:bg-ghost disabled:opacity-50"
              >
                {ex}
              </button>
            ))}
          </div>
          <label className="mt-3 flex items-center gap-2 text-xs text-ink-2">
            <input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} />
            Include superseded document versions
          </label>
        </Card>

        {mode === 'ask' && ask.isPending && (
          <Card>
            <p className="text-sm text-ink-2">Retrieving sources and generating an answer… (a local model can take a few seconds)</p>
          </Card>
        )}
        {mode === 'ask' && ask.error && (
          <Card>
            <ErrorNote error={ask.error} />
          </Card>
        )}
        {mode === 'ask' && ask.data && !ask.isPending && (
          <AnswerCard answer={ask.data} onCite={setActive} />
        )}
        {mode === 'search' && search.error && (
          <Card>
            <ErrorNote error={search.error} />
          </Card>
        )}

        {sources && sources.length > 0 && !busy && (
          <Card title={mode === 'ask' ? 'Sources given to the model' : 'Search results'} subtitle="Hybrid retrieval: meaning (vector) and keywords (full-text), fused by rank">
            <ol className="grid gap-2">
              {sources.map((s, i) => (
                <SourceCard key={s.chunk_id} n={i + 1} chunk={s} highlighted={active === i + 1} />
              ))}
            </ol>
          </Card>
        )}
      </div>

      <Library />
    </div>
  )
}

const CHECK_LABEL: Record<SentenceCheck['status'], { status: 'good' | 'warning' | 'critical'; label: string }> = {
  supported: { status: 'good', label: 'Citation verified' },
  corrected: { status: 'warning', label: 'Citation corrected by verifier' },
  unsupported: { status: 'critical', label: 'Not supported by sources' },
}

function AnswerCard({ answer, onCite }: { answer: Answer; onCite: (n: number) => void }) {
  if (!answer.found) {
    return (
      <Card title="Answer">
        <p className="text-sm text-ink">{answer.answer}</p>
        <p className="mt-2 text-xs text-ink-muted">
          The model found nothing relevant in the retrieved sources, so it declined to answer rather than guess.
        </p>
        <Meta answer={answer} />
      </Card>
    )
  }
  return (
    <Card
      title="Answer"
      actions={
        answer.grounded ? (
          <StatusBadge status="good" label="Grounded in sources" />
        ) : (
          <StatusBadge status="critical" label="Partly unsupported" />
        )
      }
    >
      <div className="grid gap-3">
        {answer.checks.map((c, i) => (
          <div key={i} className="grid gap-1">
            <p className="text-sm leading-relaxed text-ink">
              {c.sentence.replace(/[.!?]$/, '')}
              {c.cited.map((n) => (
                <button
                  key={n}
                  onClick={() => onCite(n)}
                  className="ml-1 rounded bg-series-1-wash px-1 align-baseline text-xs font-semibold text-ink hover:bg-ghost"
                  aria-label={`Source ${n}`}
                >
                  {n}
                </button>
              ))}
              {c.sentence.match(/[.!?]$/)?.[0]}
            </p>
            <div className="flex items-center gap-2">
              <StatusBadge {...CHECK_LABEL[c.status]} />
              {c.status === 'corrected' && (
                <span className="text-[11px] text-ink-muted">
                  model cited {c.model_cited.length ? `[${c.model_cited.join(', ')}]` : 'nothing'}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
      <Meta answer={answer} />
    </Card>
  )
}

function Meta({ answer }: { answer: Answer }) {
  return (
    <p className="mt-4 border-t border-hairline pt-3 text-[11px] text-ink-muted">
      {answer.model} · retrieval {Math.round(answer.retrieval_ms)} ms · generation{' '}
      {(answer.generation_ms / 1000).toFixed(1)} s
      {answer.model_citation_accuracy !== null && (
        <> · model cited correctly in {formatPercent(answer.model_citation_accuracy, 0)} of sentences</>
      )}
    </p>
  )
}

function SourceCard({ n, chunk, highlighted }: { n: number; chunk: RetrievedChunk; highlighted: boolean }) {
  const ref = useRef<HTMLLIElement>(null)
  useEffect(() => {
    if (highlighted) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [highlighted])
  return (
    <li
      ref={ref}
      className={`rounded-lg border p-3 text-xs ${highlighted ? 'border-series-1' : 'border-hairline'}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <span className="mr-2 rounded bg-series-1-wash px-1 font-semibold text-ink">{n}</span>
          <span className="font-semibold text-ink">{chunk.doc_key}</span>
          <span className="text-ink-2"> · {chunk.title} v{chunk.version}</span>
          {chunk.status !== 'current' && <span className="ml-1 text-ink-muted">({chunk.status})</span>}
        </div>
        <span className="tabular text-ink-muted">
          vector #{chunk.vector_rank ?? '—'} · keyword #{chunk.keyword_rank ?? '—'}
        </span>
      </div>
      <div className="mt-1 font-medium text-ink-2">§ {chunk.section}</div>
      <MarkdownLite text={chunk.content} className="mt-1 text-ink-2" />
    </li>
  )
}

function Library() {
  const docs = useQuery({ queryKey: ['documents'], queryFn: api.documents })
  return (
    <div className="grid content-start gap-4">
      <Card title="Policy library" subtitle={docs.data ? `${docs.data.length} documents` : undefined}>
        {docs.error && <ErrorNote error={docs.error} />}
        <ul className="divide-y divide-hairline">
          {docs.data?.map((d) => (
            <li key={d.document_id} className="py-2 text-xs">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-semibold text-ink">{d.doc_key}</span>
                <span className="tabular text-ink-muted">
                  v{d.version} · {d.chunks} chunks
                </span>
              </div>
              <div className={d.status === 'current' ? 'text-ink-2' : 'text-ink-muted line-through'}>{d.title}</div>
              {d.status !== 'current' && <div className="text-ink-muted">{d.status}, kept for history</div>}
            </li>
          ))}
        </ul>
      </Card>
      <Upload />
    </div>
  )
}

function Upload() {
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [fields, setFields] = useState({ doc_key: '', title: '', doc_type: 'other', version: '', status: 'current' })
  const upload = useMutation({
    mutationFn: () => api.upload(file!, fields),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents'] }),
  })
  const set = (k: keyof typeof fields) => (e: { target: { value: string } }) =>
    setFields((f) => ({ ...f, [k]: e.target.value }))
  const input = 'w-full rounded-md border border-hairline bg-surface px-2 py-1 text-xs text-ink'

  return (
    <Card title="Add a document" subtitle="Markdown, text, Word (.docx) or PDF, up to 10 MB">
      <form
        className="grid gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (file) upload.mutate()
        }}
      >
        <input
          type="file"
          accept=".md,.markdown,.txt,.docx,.pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-xs text-ink-2"
          aria-label="Document file"
        />
        <div className="grid grid-cols-2 gap-2">
          <input className={input} placeholder="Document key (e.g. POL-010)" value={fields.doc_key} onChange={set('doc_key')} />
          <input className={input} placeholder="Version (e.g. 1.0)" value={fields.version} onChange={set('version')} />
        </div>
        <input className={input} placeholder="Title (optional)" value={fields.title} onChange={set('title')} />
        <div className="grid grid-cols-2 gap-2">
          <select className={input} value={fields.doc_type} onChange={set('doc_type')} aria-label="Type">
            {['policy', 'sop', 'reference', 'plan', 'other'].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <select className={input} value={fields.status} onChange={set('status')} aria-label="Status">
            {['current', 'superseded', 'draft'].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          disabled={!file || upload.isPending}
          className="rounded-md border border-hairline px-3 py-1.5 text-xs font-semibold text-ink hover:bg-ghost disabled:opacity-50"
        >
          {upload.isPending ? 'Ingesting…' : 'Upload and index'}
        </button>
        {upload.error && <ErrorNote error={upload.error} />}
        {upload.data && (
          <p className="text-xs text-ink-2">
            <StatusBadge status="good" label={upload.data.status} /> {upload.data.doc_key} v{upload.data.version} ·{' '}
            {upload.data.chunks} chunks
          </p>
        )}
      </form>
    </Card>
  )
}
