import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { actionsApi, type ActionRequest, type ActionStatus, type AuditEntry } from '../api/investigation'
import { Card, ErrorNote, StatusBadge } from '../components/ui'
import { formatCount, formatPercent } from '../lib/format'
import { useAuth } from '../lib/auth'
import { useDomain } from '../lib/hooks'

const STATUS: Record<ActionStatus, { status: 'good' | 'warning' | 'serious' | 'critical'; label: string }> = {
  proposed: { status: 'warning', label: 'Awaiting approval' },
  approved: { status: 'good', label: 'Approved' },
  rejected: { status: 'serious', label: 'Rejected' },
  executing: { status: 'warning', label: 'Executing' },
  executed: { status: 'good', label: 'Executed' },
  failed: { status: 'critical', label: 'Execution failed' },
}

const GROUPS: { title: string; statuses: ActionStatus[]; empty: string }[] = [
  { title: 'Awaiting approval', statuses: ['proposed'], empty: 'Nothing waiting for a decision.' },
  { title: 'Approved, ready to execute', statuses: ['approved', 'executing'], empty: 'Nothing approved and waiting.' },
  { title: 'Done', statuses: ['executed', 'failed', 'rejected'], empty: 'No completed actions yet.' },
]

const lakh = (inr: number) => `${inr < 0 ? '−' : ''}₹${Math.abs(inr / 1e5).toLocaleString('en-IN', { maximumFractionDigits: 1 })}L`

export default function Actions() {
  const list = useQuery({ queryKey: ['actions'], queryFn: actionsApi.list, refetchInterval: 15_000 })
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="grid min-w-0 content-start gap-4">
        <Card
          title="Action Centre"
          subtitle="Corrective actions move from proposal to human approval to execution. Rules are enforced by the backend and the Operations MCP server, not by these buttons."
        >
          <p className="text-xs text-ink-2">
            Propose actions from an <Link to="/investigate" className="underline underline-offset-2">investigation</Link>, or from any MCP
            client connected to the Operations MCP server. Agents and MCP clients can propose and execute approved actions, but only a
            person with the required role can approve.
          </p>
        </Card>
        {list.error && <ErrorNote error={list.error} />}
        {GROUPS.map((g) => {
          const items = (list.data ?? []).filter((r) => g.statuses.includes(r.status))
          return (
            <Card key={g.title} title={`${g.title}${items.length ? ` (${items.length})` : ''}`}>
              {items.length === 0 ? (
                <p className="text-xs text-ink-muted">{g.empty}</p>
              ) : (
                <ul className="grid gap-3">
                  {items.map((r) => (
                    <RequestCard key={r.request_id} r={r} />
                  ))}
                </ul>
              )}
            </Card>
          )
        })}
      </div>
      <AuditPanel />
    </div>
  )
}

function RequestCard({ r }: { r: ActionRequest }) {
  const system = useDomain().data?.system_of_record ?? 'the system of record'
  const { me, can } = useAuth()
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const [showTrail, setShowTrail] = useState(false)
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['actions'] })
    qc.invalidateQueries({ queryKey: ['audit'] })
    qc.invalidateQueries({ queryKey: ['action', r.request_id] })
  }
  const decide = useMutation({
    mutationFn: (decision: 'approved' | 'rejected') => actionsApi.decide(r.request_id, { decision, note: note || undefined }),
    onSettled: refresh,
  })
  const execute = useMutation({ mutationFn: () => actionsApi.execute(r.request_id), onSettled: refresh })

  // The UI only explains the rules; the backend enforces them (a forced click is still refused).
  const role = me?.business_role ?? null
  const canDecideReason = !me
    ? 'Sign in first.'
    : !can('decide_action')
      ? `Your platform role (${me.user.platform_role}) cannot approve actions.`
      : !role || !r.approver_roles.includes(role)
        ? `Needs ${r.approver_roles.join(' or ')}; your role here is ${role ?? 'none'}.`
        : me.user.user_id === r.requested_by
          ? 'Separation of duties: you proposed this action.'
          : null
  const i = r.impact
  const s = STATUS[r.status]

  return (
    <li className="rounded-lg border border-hairline p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-ink">{r.title}</div>
          <div className="mt-0.5 text-[11px] text-ink-muted">
            Proposed by {r.requested_by} via {r.requested_via} · {new Date(r.created_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}
            {r.investigation_id && (
              <>
                {' · '}
                <Link to={`/investigate?id=${r.investigation_id}`} className="underline underline-offset-2">
                  from investigation
                </Link>
              </>
            )}
          </div>
        </div>
        <StatusBadge {...s} />
      </div>

      {r.rationale && <p className="mt-2 text-xs text-ink-2">“{r.rationale}”</p>}

      {i && (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Fig label="Breaches avoided / year" value={formatCount(Math.round(i.annual_breaches_avoided))} />
          <Fig label="Breach rate" value={`${formatPercent(i.breach_rate_now)} → ${formatPercent(i.breach_rate_after)}`} />
          <Fig label="Net value / year (illustrative)" value={lakh(i.annual_net_inr)} />
        </div>
      )}

      <p className="mt-2 text-[11px] text-ink-muted">
        Approval: {r.approver_roles.join(' or ')}
        {r.approval_basis && <> · {r.approval_basis}</>}
        {r.policy_refs.length > 0 && <> · Policy basis: {r.policy_refs.join(', ')}</>}
      </p>

      {r.decided_by && (
        <p className="mt-2 text-xs text-ink-2">
          {r.decision === 'approved' ? 'Approved' : 'Rejected'} by <b className="text-ink">{r.decided_by}</b> ({r.decided_role})
          {r.decision_note && <> · “{r.decision_note}”</>}
        </p>
      )}
      {r.status === 'executed' && r.result && (
        <p className="mt-2 rounded-md bg-ghost px-2 py-1.5 text-xs text-ink-2">
          <StatusBadge status="good" label="Applied" /> in {String(r.result.system)}: {String(r.result.resource)} record{' '}
          <code className="text-[11px]">{String(r.result.record_id).slice(0, 8)}</code> (executed by {r.executed_by} through the Operations
          MCP server)
        </p>
      )}
      {r.status === 'failed' && r.error && <ErrorNote error={r.error} />}

      {r.status === 'proposed' && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-hairline pt-3">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Decision note (optional)"
            className="min-w-0 flex-1 rounded-md border border-hairline bg-surface px-2 py-1 text-xs text-ink"
            aria-label="Decision note"
            maxLength={1000}
          />
          <button
            onClick={() => decide.mutate('approved')}
            disabled={!!canDecideReason || decide.isPending}
            className="rounded-md bg-series-1 px-3 py-1 text-xs font-semibold text-white disabled:opacity-40"
          >
            Approve
          </button>
          <button
            onClick={() => decide.mutate('rejected')}
            disabled={!!canDecideReason || decide.isPending}
            className="rounded-md border border-hairline px-3 py-1 text-xs font-semibold text-ink hover:bg-ghost disabled:opacity-40"
          >
            Reject
          </button>
          {canDecideReason && <p className="w-full text-[11px] text-ink-muted">{canDecideReason}</p>}
        </div>
      )}
      {r.status === 'approved' && (
        <div className="mt-3 flex items-center gap-2 border-t border-hairline pt-3">
          <button
            onClick={() => execute.mutate()}
            disabled={!can('execute_action') || execute.isPending}
            className="rounded-md bg-series-1 px-3 py-1 text-xs font-semibold text-white disabled:opacity-40"
          >
            {execute.isPending ? 'Executing…' : 'Execute via Operations MCP'}
          </button>
          <span className="text-[11px] text-ink-muted">Changes {system}.</span>
        </div>
      )}
      {(decide.error || execute.error) && (
        <div className="mt-2">
          <ErrorNote error={decide.error ?? execute.error} />
        </div>
      )}

      <button onClick={() => setShowTrail((v) => !v)} className="mt-2 text-xs text-ink-2 underline underline-offset-2" aria-expanded={showTrail}>
        {showTrail ? 'Hide' : 'Show'} audit trail
      </button>
      {showTrail && <Trail id={r.request_id} />}
    </li>
  )
}

function Trail({ id }: { id: string }) {
  const q = useQuery({ queryKey: ['action', id], queryFn: () => actionsApi.get(id) })
  if (q.error) return <ErrorNote error={q.error} />
  return (
    <ol className="mt-2 grid gap-1 border-l border-hairline pl-3">
      {q.data?.audit.map((e) => (
        <AuditRow key={e.entry_id} e={e} />
      ))}
    </ol>
  )
}

const DENIED = /denied/

function AuditRow({ e, showRequest = false }: { e: AuditEntry; showRequest?: boolean }) {
  const reason = typeof e.details.reason === 'string' ? e.details.reason : null
  return (
    <li className="text-[11px]">
      <span className="tabular text-ink-muted">{new Date(e.at).toLocaleTimeString('en-IN')}</span>{' '}
      <span className={DENIED.test(e.event) ? 'font-semibold text-ink' : 'text-ink'}>
        {DENIED.test(e.event) && (
          <span className="text-critical" aria-hidden>
            ▲{' '}
          </span>
        )}
        {e.event}
      </span>{' '}
      <span className="text-ink-2">
        by {e.actor} ({e.actor_type.replace('_', ' ')})
      </span>
      {showRequest && e.request_id && <span className="text-ink-muted"> · {e.request_id.slice(0, 8)}</span>}
      {reason && <div className="text-ink-muted">{reason}</div>}
    </li>
  )
}

function AuditPanel() {
  const verify = useQuery({ queryKey: ['audit', 'verify'], queryFn: actionsApi.verify, refetchInterval: 15_000 })
  const log = useQuery({ queryKey: ['audit', 'log'], queryFn: actionsApi.audit, refetchInterval: 15_000 })
  return (
    <Card title="Audit log" subtitle="Append-only and hash-chained: editing, inserting or deleting any entry breaks verification.">
      {verify.data &&
        (verify.data.ok ? (
          <StatusBadge status="good" label={`Chain verified · ${formatCount(verify.data.entries)} entries`} />
        ) : (
          <StatusBadge status="critical" label={`Chain broken at entry ${verify.data.first_broken_entry}: ${verify.data.reason}`} />
        ))}
      {verify.error && <ErrorNote error={verify.error} />}
      <ol className="mt-3 grid max-h-[40rem] gap-1.5 overflow-y-auto">
        {log.data?.map((e) => (
          <AuditRow key={e.entry_id} e={e} showRequest />
        ))}
      </ol>
    </Card>
  )
}

function Fig({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-ink-muted">{label}</div>
      <div className="text-sm font-semibold text-ink">{value}</div>
    </div>
  )
}
