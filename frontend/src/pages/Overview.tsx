import { useState } from 'react'
import { Link } from 'react-router'
import { api, type DomainInfo, type MetricResult, type OverviewTile, type Scope } from '../api/client'
import { BarList } from '../components/BarList'
import { TrendChart } from '../components/TrendChart'
import { Card, ErrorNote, Refetching, Segmented, StatTile, StatusBadge } from '../components/ui'
import { formatCount, formatDimensionValue, formatMonth, formatPercent, formatValue } from '../lib/format'
import { useDomainScope, useScoped } from '../lib/hooks'

const useMetric = (scope: Scope, metric: string, groupBy: string[] = []) =>
  useScoped(`metric:${metric}`, scope, () => api.metric(scope, metric, groupBy), groupBy)

const single = (r: MetricResult | undefined) => r?.rows[0]

export default function Overview() {
  const { domain, scope } = useDomainScope()
  if (!domain.data) return domain.error ? <ErrorNote error={domain.error} /> : null
  return <OverviewBody scope={scope} domain={domain.data} />
}

function OverviewBody({ scope, domain }: { scope: Scope; domain: DomainInfo }) {
  const slaDays = domain.sla_hours / 24
  const plural = domain.case_label_plural
  const { spotlight, tiles } = domain.overview
  const cases = useMetric(scope, 'case_count')
  const breach = useMetric(scope, 'sla_breach_rate')
  const cycle = useMetric(scope, 'avg_cycle_days')
  const p90 = useMetric(scope, 'p90_cycle_days')
  const activities = useScoped('activities', scope, () => api.activities(scope))

  const fetching = [cases, breach, cycle, activities].some((q) => q.isFetching)
  const firstError = [cases, breach, cycle].find((q) => q.error)?.error
  if (firstError) return <ErrorNote error={firstError} />

  const n = single(cases.data)?.value ?? 0
  const bottlenecks = activities.data?.internal.filter((a) => a.is_bottleneck) ?? []

  if (cases.data && n === 0) {
    return (
      <Card title={`No ${plural} match these filters`}>
        <p className="text-sm text-ink-2">Widen the period or clear a filter.</p>
      </Card>
    )
  }

  return (
    <Refetching active={fetching}>
      <div className="grid gap-4">
        <div className="grid gap-4 md:grid-cols-[minmax(16rem,1.3fr)_repeat(3,minmax(0,1fr))]">
          <StatTile
            hero
            label={`${domain.sla_name} breach rate`}
            value={formatValue(single(breach.data)?.value ?? null, 'ratio')}
            note={`${capitalise(plural)} taking longer than ${slaDays} days from ${domain.sla_start} to ${domain.sla_end} · ${formatCount(n)} ${plural}`}
          />
          <StatTile
            label="Average cycle time"
            value={formatValue(single(cycle.data)?.value ?? null, 'days')}
            note={`90% finish within ${formatValue(single(p90.data)?.value ?? null, 'days')}`}
          />
          <div className="rounded-xl border border-hairline bg-surface p-4">
            <div className="text-xs text-ink-2">Bottlenecks</div>
            <div className="mt-1 text-2xl font-semibold">{activities.data ? bottlenecks.length : '—'}</div>
            <div className="mt-1 space-y-0.5">
              {bottlenecks.map((b) => (
                <div key={b.activity}>
                  <StatusBadge status="critical" label={b.activity} />
                  <span className="ml-1 text-xs text-ink-muted">
                    waits {formatValue(b.mean_wait_hours, 'hours')} on average
                  </span>
                </div>
              ))}
              <Link to={{ pathname: '/process', search: location.search }} className="text-xs text-ink-2 underline underline-offset-2">
                See the process
              </Link>
            </div>
          </div>
          {spotlight && <MetricTile scope={scope} tile={spotlight} />}
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label={capitalise(plural)} value={formatCount(n)} />
          {tiles.map((t) => (
            <MetricTile key={t.metric} scope={scope} tile={t} />
          ))}
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <MonthlyTrend scope={scope} domain={domain} metric="sla_breach_rate" title={`${domain.sla_name} breach rate by month`} />
          <MonthlyTrend
            scope={scope}
            domain={domain}
            metric="avg_cycle_days"
            title="Average cycle time by month"
            reference={{ y: slaDays, label: `SLA ${slaDays} days` }}
          />
        </div>

        <Breakdown scope={scope} domain={domain} />
      </div>
    </Refetching>
  )
}

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** A KPI tile configured by the domain pack. Its note may use {n} and {secondary}. */
function MetricTile({ scope, tile }: { scope: Scope; tile: OverviewTile }) {
  const q = useMetric(scope, tile.metric)
  const secondary = useScoped(`metric:${tile.secondary ?? 'none'}`, scope, () =>
    tile.secondary ? api.metric(scope, tile.secondary, []) : Promise.resolve(null),
  )
  const row = single(q.data)
  const second = secondary.data ? single(secondary.data) : undefined
  const note = tile.note
    ?.replace('{n}', formatCount(row?.n ?? 0))
    .replace('{secondary}', second && secondary.data ? formatValue(second.value, secondary.data.unit) : '—')
  return <StatTile label={tile.label} value={q.data ? formatValue(row?.value ?? null, q.data.unit) : '—'} note={note} />
}

function MonthlyTrend({
  scope,
  domain,
  metric,
  title,
  reference,
}: {
  scope: Scope
  domain: DomainInfo
  metric: string
  title: string
  reference?: { y: number; label: string }
}) {
  const q = useMetric(scope, metric, ['month'])
  if (q.error) return <Card title={title}><ErrorNote error={q.error} /></Card>
  const unit = q.data?.unit ?? 'ratio'
  const data = (q.data?.rows ?? []).map((r) => ({
    x: r.group.month,
    xLabel: formatMonth(r.group.month),
    y: r.value ?? 0,
    n: r.n,
  }))
  return (
    <Card title={title} subtitle={`By month the ${domain.case_label} was opened (${domain.sla_start})`}>
      <TrendChart
        data={data}
        format={(v) => formatValue(v, unit)}
        axisFormat={(v) => (unit === 'ratio' ? formatPercent(v, 0) : unit === 'days' ? `${v} d` : formatValue(v, unit))}
        caption={title}
        valueLabel={q.data?.label ?? ''}
        reference={reference}
      />
    </Card>
  )
}

function Breakdown({ scope, domain }: { scope: Scope; domain: DomainInfo }) {
  const dims = Object.entries(domain.overview.breakdown_dimensions).map(([value, label]) => ({ value, label }))
  const metrics = Object.entries(domain.overview.breakdown_metrics).map(([value, label]) => ({ value, label }))
  const [dim, setDim] = useState(dims[0]?.value ?? 'month')
  const [metric, setMetric] = useState(metrics[0]?.value ?? 'sla_breach_rate')
  const q = useMetric(scope, metric, [dim])
  const unit = q.data?.unit ?? 'ratio'
  const rows = q.data?.rows ?? []
  const data = rows.map((r) => ({
    label: formatDimensionValue(r.group[dim]),
    value: r.value ?? 0,
    display: formatValue(r.value, unit),
    n: r.n,
    lowSample: r.low_sample,
  }))
  const metricLabel = metrics.find((m) => m.value === metric)?.label ?? metric
  const dimLabel = dims.find((b) => b.value === dim)?.label ?? dim

  return (
    <Card
      title={`${metricLabel} by ${dimLabel.toLowerCase()}`}
      subtitle={`Groups with fewer than 100 ${domain.case_label_plural} are marked low sample and drawn lighter`}
      actions={
        <div className="flex flex-wrap gap-2">
          <Segmented label="Metric" value={metric} onChange={setMetric} options={metrics} />
          <Segmented label="Group by" value={dim} onChange={setDim} options={dims} />
        </div>
      }
    >
      {q.error ? (
        <ErrorNote error={q.error} />
      ) : (
        <Refetching active={q.isFetching}>
          <BarList data={data} caption={`${metricLabel} by ${dimLabel}`} valueLabel={metricLabel} />
        </Refetching>
      )}
    </Card>
  )
}
