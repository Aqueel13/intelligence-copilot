import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { watchApi, type Alert, type Evaluation, type FollowUp, type MonitorStatus } from '../api/investigation'
import { Card, ErrorNote, StatusBadge } from '../components/ui'
import { formatMonth, formatValue } from '../lib/format'
import { useAuth } from '../lib/auth'
import { useLabels } from '../lib/hooks'

const STATUS: Record<MonitorStatus, { status: 'good' | 'warning' | 'critical' | 'serious'; label: string }> = {
  ok: { status: 'good', label: 'OK' },
  warning: { status: 'warning', label: 'Warning' },
  critical: { status: 'critical', label: 'Critical' },
  insufficient_data: { status: 'serious', label: 'Not enough data' },
}

/** Comparisons need one unit on both sides: hours stay hours (no switch to days). */
const fmtSame = (v: number | null, unit: FollowUp['unit']) =>
  unit === 'hours' && v !== null ? `${v.toLocaleString('en-IN', { maximumFractionDigits: 1 })} h` : formatValue(v, unit)

const VERDICT: Record<FollowUp['verdict'], { status: 'good' | 'warning' | 'critical' | 'serious'; label: string }> = {
  on_target: { status: 'good', label: 'Working: on target' },
  improving: { status: 'warning', label: 'Improving' },
  no_change: { status: 'serious', label: 'No clear change' },
  worse: { status: 'critical', label: 'Worse' },
  awaiting_data: { status: 'serious', label: 'Awaiting data' },
}

/** Link to an investigation pre-scoped to the alert's segment. */
function investigateHref(e: Evaluation, alertId?: string): string {
  const p = new URLSearchParams({ q: e.question })
  for (const [k, v] of Object.entries(e.scope)) if (v.length === 1) p.set(k, v[0])
  if (alertId) p.set('alert', alertId)
  return `/investigate?${p}`
}

export default function Watch() {
  const L = useLabels()
  const { can } = useAuth()
  const qc = useQueryClient()
  const status = useQuery({ queryKey: ['watch'], queryFn: watchApi.status, refetchInterval: 30_000 })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['watch'] })
    qc.invalidateQueries({ queryKey: ['domain'] })
    qc.invalidateQueries({ queryKey: ['metric'] })
  }
  const run = useMutation({ mutationFn: watchApi.run, onSettled: refresh })
  const simulate = useMutation({ mutationFn: watchApi.simulate, onSettled: () => qc.invalidateQueries() })
  const [confirmSim, setConfirmSim] = useState(false)

  if (status.error) return <ErrorNote error={status.error} />
  if (!status.data) return null
  const s = status.data
  const evaluations = s.summary.evaluations
  const bad = evaluations.filter((e) => e.status === 'warning' || e.status === 'critical')
  const alertFor = (e: Evaluation) =>
    s.alerts.find((a) => a.monitor_id === e.monitor_id && a.segment === e.segment && a.status !== 'resolved')

  return (
    <div className="grid gap-4">
      <Card
        title="Watch"
        subtitle={`KPI monitors from the domain pack, evaluated on ${s.summary.period ? formatMonth(s.summary.period) : '—'} (latest month of data), using the same metrics engine as every other screen.`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => run.mutate()}
              disabled={run.isPending || !can('run_monitors')}
              title={can('run_monitors') ? undefined : 'Your role cannot run monitors'}
              className="rounded-md border border-hairline px-3 py-1.5 text-xs font-semibold text-ink hover:bg-ghost disabled:opacity-50"
            >
              {run.isPending ? 'Checking…' : 'Run checks now'}
            </button>
            <button
              onClick={() => setConfirmSim(true)}
              disabled={simulate.isPending || !can('simulate_month')}
              title={can('simulate_month') ? undefined : 'Admins only: it changes the data everyone sees'}
              className="rounded-md border border-hairline px-3 py-1.5 text-xs font-semibold text-ink hover:bg-ghost disabled:opacity-50"
            >
              {simulate.isPending ? 'Generating…' : 'Simulate next month'}
            </button>
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-ink-2">
          <span>
            <b className="text-ink">{bad.length}</b> of {evaluations.length} monitored segments need attention
          </span>
          <span>
            <b className="text-ink">{s.alerts.filter((a) => a.status !== 'resolved').length}</b> open alerts
          </span>
          {s.last_run && (
            <span className="text-ink-muted">
              Last run {new Date(s.last_run.started_at).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' })} ({s.last_run.trigger})
            </span>
          )}
          {s.simulated_months.length > 0 && (
            <span className="text-ink-muted">
              Synthetic months:{' '}
              {s.simulated_months.map((m) => `${formatMonth(m.month)}${m.applied_actions.length ? ` (${m.applied_actions.length} actions applied)` : ''}`).join(', ')}
            </span>
          )}
        </div>
        {confirmSim && (
          <div className="mt-3 rounded-md border border-hairline bg-ghost p-3 text-xs text-ink-2">
            <p>
              <b className="text-ink">Demo only.</b> This appends one more month of <b>synthetic</b> {L.many} from the same generator. Trends continue
              (an untreated queue keeps getting worse) and every action executed so far is applied, so you can see whether it works. It changes
              the data every screen shows; <code>make seed</code> resets it.
            </p>
            <div className="mt-2 flex gap-2">
              <button
                onClick={() => {
                  setConfirmSim(false)
                  simulate.mutate()
                }}
                className="rounded-md bg-series-1 px-3 py-1 font-semibold text-white"
              >
                Generate next month
              </button>
              <button onClick={() => setConfirmSim(false)} className="rounded-md border border-hairline px-3 py-1 font-semibold text-ink">
                Cancel
              </button>
            </div>
          </div>
        )}
        {(run.error || simulate.error) && <ErrorNote error={run.error ?? simulate.error} />}
        {run.data && (
          <p className="mt-2 text-xs text-ink-2">
            Checked {run.data.evaluated} segments in {run.data.duration_ms} ms: {run.data.opened} alerts opened, {run.data.updated} updated,{' '}
            {run.data.resolved} resolved.
          </p>
        )}
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {evaluations.map((e) => (
          <MonitorTile key={`${e.monitor_id}|${e.segment}`} e={e} alert={alertFor(e)} />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Alerts alerts={s.alerts} evaluations={evaluations} />
        <FollowUps items={s.follow_ups} />
      </div>
    </div>
  )
}

function MonitorTile({ e, alert }: { e: Evaluation; alert?: Alert }) {
  const st = STATUS[e.status]
  const fmt = (v: number | null) => formatValue(v, e.unit)
  return (
    <section className="rounded-xl border border-hairline bg-surface p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink">{e.title}</h3>
          {e.segment && <div className="text-xs text-ink-2">{e.segment.replace('=', ': ').replace(/_/g, ' ')}</div>}
        </div>
        <StatusBadge {...st} />
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-2xl font-semibold text-ink">{fmt(e.value)}</span>
        <span className="text-xs text-ink-muted">
          {e.direction === 'above' ? '≤' : '≥'} {fmt(e.warning)} expected
          {e.critical !== e.warning && <> · critical {e.direction === 'above' ? '>' : '<'} {fmt(e.critical)}</>}
          {e.critical_months > 1 && <> for {e.critical_months} months</>}
        </span>
      </div>
      <Sparkline e={e} />
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-ink-muted">
        <span>
          {formatMonth(e.period)} · n = {e.n.toLocaleString('en-IN')}
          {e.policy_ref && <> · {e.policy_ref}</>}
        </span>
        {(e.status === 'warning' || e.status === 'critical') && (
          <Link to={investigateHref(e, alert?.alert_id)} className="font-semibold text-ink underline underline-offset-2">
            Investigate
          </Link>
        )}
      </div>
    </section>
  )
}

/** Monthly values with the warning threshold as a hairline; the latest point is labelled. */
function Sparkline({ e }: { e: Evaluation }) {
  const pts = e.series.filter((p) => p.value !== null) as { period: string; value: number; status: MonitorStatus }[]
  if (pts.length < 2) return null
  const W = 280
  const H = 56
  const pad = 6
  const values = [...pts.map((p) => p.value), e.warning, e.critical]
  const lo = Math.min(0, ...values)
  const hi = Math.max(...values) * 1.1
  const x = (i: number) => pad + (i * (W - 2 * pad)) / (pts.length - 1)
  const y = (v: number) => H - pad - ((v - lo) / (hi - lo || 1)) * (H - 2 * pad)
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 h-14 w-full" role="img" aria-label={`${e.title} by month: ${pts.map((p) => `${formatMonth(p.period)} ${formatValue(p.value, e.unit)}`).join(', ')}`}>
      <line x1={pad} x2={W - pad} y1={y(e.warning)} y2={y(e.warning)} stroke="var(--ink-muted)" strokeWidth={1} opacity={0.6} />
      <path d={d} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      {pts.map((p, i) => (
        <circle key={p.period} cx={x(i)} cy={y(p.value)} r={i === pts.length - 1 ? 4 : 2.5} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={1.5}>
          <title>{`${formatMonth(p.period)}: ${formatValue(p.value, e.unit)} (${STATUS[p.status].label})`}</title>
        </circle>
      ))}
    </svg>
  )
}

function Alerts({ alerts, evaluations }: { alerts: Alert[]; evaluations: Evaluation[] }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const ack = useMutation({
    mutationFn: (id: string) => watchApi.acknowledge(id),
    onSettled: () => qc.invalidateQueries({ queryKey: ['watch'] }),
  })
  const [showResolved, setShowResolved] = useState(false)
  const visible = alerts.filter((a) => showResolved || a.status !== 'resolved')
  return (
    <Card
      title="Alerts"
      subtitle="One alert per monitor and segment, kept open while the condition holds and resolved automatically when it clears."
      actions={
        <label className="flex items-center gap-1.5 text-xs text-ink-2">
          <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} /> Show resolved
        </label>
      }
    >
      {visible.length === 0 && <p className="text-xs text-ink-muted">No open alerts.</p>}
      <ul className="grid gap-2">
        {visible.map((a) => {
          const e = evaluations.find((x) => x.monitor_id === a.monitor_id && x.segment === a.segment)
          return (
            <li key={a.alert_id} className="rounded-lg border border-hairline p-3 text-xs">
              <div className="flex flex-wrap items-center justify-between gap-2">
                {a.status === 'resolved' ? (
                  <StatusBadge status="good" label="Resolved" />
                ) : (
                  <StatusBadge status={a.severity === 'critical' ? 'critical' : 'warning'} label={a.severity === 'critical' ? 'Critical' : 'Warning'} />
                )}
                <span className="text-ink-muted">
                  since {formatMonth(a.first_period)}
                  {a.status === 'acknowledged' && a.acknowledged_by && <> · acknowledged by {a.acknowledged_by}</>}
                </span>
              </div>
              <p className="mt-1 text-ink">{a.message}</p>
              {a.status !== 'resolved' && (
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  {a.investigation_id ? (
                    <Link to={`/investigate?id=${a.investigation_id}`} className="font-semibold text-ink underline underline-offset-2">
                      Open investigation
                    </Link>
                  ) : (
                    e && (
                      <Link to={investigateHref(e, a.alert_id)} className="font-semibold text-ink underline underline-offset-2">
                        Investigate
                      </Link>
                    )
                  )}
                  {a.status === 'open' && (
                    <button onClick={() => ack.mutate(a.alert_id)} disabled={!can('acknowledge_alert') || ack.isPending} title={can('acknowledge_alert') ? undefined : 'Your role cannot acknowledge alerts'} className="text-ink-2 underline underline-offset-2 disabled:opacity-50">
                      Acknowledge
                    </button>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {ack.error && <ErrorNote error={ack.error} />}
    </Card>
  )
}

function FollowUps({ items }: { items: FollowUp[] }) {
  return (
    <Card title="Are executed actions working?" subtitle="Each executed action's follow-up metric, before vs after the action took effect, against its target.">
      {items.length === 0 && (
        <p className="text-xs text-ink-muted">
          No executed actions yet. Approve and execute one in the <Link to="/actions" className="underline underline-offset-2">Action Centre</Link>.
        </p>
      )}
      <ul className="grid gap-2">
        {items.map((f) => (
          <li key={f.request_id} className="rounded-lg border border-hairline p-3 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-semibold text-ink">{f.title}</span>
              <StatusBadge {...VERDICT[f.verdict]} />
            </div>
            {f.before !== null && f.after !== null ? (
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-ink-muted">{fmtSame(f.before, f.unit)}</span>
                <span className="text-ink-muted">→</span>
                <span className="text-base font-semibold text-ink">{fmtSame(f.after, f.unit)}</span>
                <span className="text-ink-muted">
                  target {f.expect === 'below' ? '≤' : '≥'} {fmtSame(f.target, f.unit)}
                </span>
              </div>
            ) : null}
            <p className="mt-1 text-ink-2">{f.message}</p>
          </li>
        ))}
      </ul>
    </Card>
  )
}
