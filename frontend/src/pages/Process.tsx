import { useState } from 'react'
import { api, type ActivityStats, type Scope } from '../api/client'
import { ProcessMap, type MapMode } from '../components/ProcessMap'
import { Card, ErrorNote, LowSample, Refetching, Segmented, StatTile, StatusBadge } from '../components/ui'
import { formatCount, formatDays, formatHours, formatPercent } from '../lib/format'
import { useDomainScope, useScoped } from '../lib/hooks'

export default function Process() {
  const { domain, scope } = useDomainScope()
  if (!domain.data) return domain.error ? <ErrorNote error={domain.error} /> : null
  return <ProcessBody scope={scope} />
}

function ProcessBody({ scope }: { scope: Scope }) {
  const [mode, setMode] = useState<MapMode>('frequency')
  const map = useScoped('processMap', scope, () => api.processMap(scope))
  const acts = useScoped('activities', scope, () => api.activities(scope))
  const variants = useScoped('variants', scope, () => api.variants(scope, 10))

  const error = map.error ?? acts.error ?? variants.error
  if (error) return <ErrorNote error={error} />
  if (!map.data || !acts.data || !variants.data) return null
  if (map.data.cases === 0)
    return (
      <Card title="No claims match these filters">
        <p className="text-sm text-ink-2">Widen the period or clear a filter.</p>
      </Card>
    )

  const bottlenecks = acts.data.internal.filter((a) => a.is_bottleneck)
  const fetching = map.isFetching || acts.isFetching || variants.isFetching

  return (
    <Refetching active={fetching}>
      <div className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label="Claims analysed" value={formatCount(map.data.cases)} />
          <StatTile
            label="Process variants"
            value={formatCount(variants.data.distinct_variants)}
            note={`Top ${variants.data.variants.length} cover ${formatPercent(variants.data.top_variants_share, 0)} of claims`}
          />
          <StatTile
            label="Most common path"
            value={formatPercent(variants.data.variants[0]?.share ?? 0, 0)}
            note="of claims follow the single most common sequence"
          />
          <div className="rounded-xl border border-hairline bg-surface p-4">
            <div className="text-xs text-ink-2">Bottlenecks</div>
            <div className="mt-1 text-2xl font-semibold">{bottlenecks.length}</div>
            {bottlenecks.map((b) => (
              <div key={b.activity}>
                <StatusBadge status="critical" label={b.activity} />
              </div>
            ))}
            <div className="mt-1 text-xs text-ink-muted">
              Mean wait ≥ {formatHours(acts.data.bottleneck_threshold_hours)} (2× the typical activity)
            </div>
          </div>
        </div>

        <Card
          title="Process map"
          subtitle="How claims actually flowed. Edge thickness = number of transitions; labels on edges carrying ≥ 5% of claims."
          actions={
            <Segmented
              label="Show"
              value={mode}
              onChange={setMode}
              options={[
                { value: 'frequency', label: 'Frequency' },
                { value: 'time', label: 'Waiting time' },
              ]}
            />
          }
        >
          <ProcessMap data={map.data} activities={acts.data.internal} mode={mode} />
        </Card>

        <ActivityTable
          rows={acts.data.internal}
          customer={acts.data.customer_time}
          definitions={acts.data.definitions}
        />

        <Card
          title="Process variants"
          subtitle="Distinct paths from FNOL to Closed, most common first"
        >
          <ol className="divide-y divide-hairline">
            {variants.data.variants.map((v) => (
              <li key={v.rank} className="grid gap-2 py-3 md:grid-cols-[3rem_9rem_1fr_6rem_7rem] md:items-center">
                <span className="tabular text-xs text-ink-muted">#{v.rank}</span>
                <div>
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-20 rounded-full bg-series-1-wash">
                      <div className="h-2 rounded-full bg-series-1" style={{ width: `${v.share * 100}%` }} />
                    </div>
                    <span className="tabular text-xs font-medium">{formatPercent(v.share)}</span>
                  </div>
                  <div className="tabular mt-0.5 text-[11px] text-ink-muted">
                    {formatCount(v.cases)} claims {v.low_sample && <LowSample n={v.cases} />}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-1 text-[11px]">
                  {v.activities.map((a, i) => (
                    <span key={i} className="flex items-center gap-1">
                      {i > 0 && <span className="text-ink-muted">→</span>}
                      <span
                        className={`rounded border px-1.5 py-0.5 ${
                          bottlenecks.some((b) => b.activity === a)
                            ? 'border-critical text-ink'
                            : 'border-hairline text-ink-2'
                        }`}
                      >
                        {a}
                      </span>
                    </span>
                  ))}
                </div>
                <div className="tabular text-xs">
                  <div className="text-ink-muted">Avg cycle</div>
                  {formatDays(v.mean_cycle_days)}
                </div>
                <div className="tabular text-xs">
                  <div className="text-ink-muted">SLA breach</div>
                  {formatPercent(v.breach_rate, 0)}
                </div>
              </li>
            ))}
          </ol>
        </Card>
      </div>
    </Refetching>
  )
}

function ActivityTable({
  rows,
  customer,
  definitions,
}: {
  rows: ActivityStats[]
  customer: ActivityStats[]
  definitions: Record<string, string>
}) {
  return (
    <Card title="Where claims wait" subtitle={definitions.waiting_time}>
      <div className="overflow-x-auto">
        <table className="tabular w-full text-left text-xs">
          <thead>
            <tr className="border-b border-hairline text-ink-2">
              <th className="py-2 pr-4 font-medium">Activity</th>
              <th className="py-2 pr-4 text-right font-medium">Mean wait</th>
              <th className="py-2 pr-4 text-right font-medium">Median</th>
              <th className="py-2 pr-4 text-right font-medium">90th pct</th>
              <th className="py-2 pr-4 font-medium">Share of all internal waiting</th>
              <th className="py-2 pr-4 text-right font-medium">Repeated</th>
              <th className="py-2 pr-4 text-right font-medium">Breach rate with / without</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.activity} className="border-b border-hairline last:border-0">
                <td className="py-2 pr-4">
                  <div className="font-medium text-ink">{a.activity}</div>
                  {a.is_bottleneck && <StatusBadge status="critical" label="Bottleneck" />}
                </td>
                <td className="py-2 pr-4 text-right">{formatHours(a.mean_wait_hours)}</td>
                <td className="py-2 pr-4 text-right text-ink-2">{formatHours(a.median_wait_hours)}</td>
                <td className="py-2 pr-4 text-right text-ink-2">{formatHours(a.p90_wait_hours)}</td>
                <td className="py-2 pr-4">
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-28 rounded-sm bg-series-1-wash">
                      <div
                        className="h-2 rounded-r-[4px] bg-series-1"
                        style={{ width: `${a.share_of_internal_wait * 100}%` }}
                      />
                    </div>
                    {formatPercent(a.share_of_internal_wait, 0)}
                  </div>
                </td>
                <td className="py-2 pr-4 text-right">{a.repeat_rate > 0 ? formatPercent(a.repeat_rate) : '—'}</td>
                <td className="py-2 pr-4 text-right">
                  {formatPercent(a.breach_rate_with, 0)}
                  <span className="text-ink-muted">
                    {' / '}
                    {a.breach_rate_without === null ? 'all claims' : formatPercent(a.breach_rate_without, 0)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {customer.map((c) => (
        <p key={c.activity} className="mt-3 border-t border-hairline pt-3 text-xs text-ink-2">
          <b className="text-ink">Customer time:</b> {c.activity} took {formatHours(c.mean_wait_hours)} on average
          (median {formatHours(c.median_wait_hours)}) in {formatCount(c.cases)} claims. Not counted as an internal
          queue.
        </p>
      ))}
      <p className="mt-3 text-[11px] text-ink-muted">{definitions.bottleneck}</p>
    </Card>
  )
}
