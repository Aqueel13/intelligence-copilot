import { useState } from 'react'
import { Link } from 'react-router'
import { api, type MetricResult, type Scope } from '../api/client'
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
  return <OverviewBody scope={scope} slaDays={domain.data.sla_hours / 24} />
}

function OverviewBody({ scope, slaDays }: { scope: Scope; slaDays: number }) {
  const cases = useMetric(scope, 'case_count')
  const breach = useMetric(scope, 'sla_breach_rate')
  const cycle = useMetric(scope, 'avg_cycle_days')
  const p90 = useMetric(scope, 'p90_cycle_days')
  const rework = useMetric(scope, 'rework_rate')
  const docs = useMetric(scope, 'doc_request_rate')
  const csat = useMetric(scope, 'avg_csat')
  const response = useMetric(scope, 'survey_response_rate')
  const activities = useScoped('activities', scope, () => api.activities(scope))

  const fetching = [cases, breach, cycle, rework, docs, csat, activities].some((q) => q.isFetching)
  const firstError = [cases, breach, cycle].find((q) => q.error)?.error
  if (firstError) return <ErrorNote error={firstError} />

  const n = single(cases.data)?.value ?? 0
  const bottlenecks = activities.data?.internal.filter((a) => a.is_bottleneck) ?? []

  if (cases.data && n === 0) {
    return (
      <Card title="No claims match these filters">
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
            label="SLA breach rate"
            value={formatValue(single(breach.data)?.value ?? null, 'ratio')}
            note={`Claims taking longer than ${slaDays} days from FNOL to Closed · ${formatCount(n)} claims`}
          />
          <StatTile
            label="Average cycle time"
            value={formatValue(single(cycle.data)?.value ?? null, 'days')}
            note={`90% close within ${formatValue(single(p90.data)?.value ?? null, 'days')}`}
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
          <StatTile
            label="Customer satisfaction (CSAT)"
            value={formatValue(single(csat.data)?.value ?? null, 'score_1_5')}
            note={
              <>
                Out of 5 · {formatCount(single(csat.data)?.n ?? 0)} responses (
                {formatValue(single(response.data)?.value ?? null, 'ratio')} response rate). Respondents only;
                unhappy customers respond more often.
              </>
            }
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label="Claims" value={formatCount(n)} />
          <StatTile
            label="Verification rework"
            value={formatValue(single(rework.data)?.value ?? null, 'ratio')}
            note="Claims sent back by QA at least once"
          />
          <StatTile
            label="Additional documents requested"
            value={formatValue(single(docs.data)?.value ?? null, 'ratio')}
            note="Customer asked for more documents at least once"
          />
          <StatTile
            label="Need senior approval"
            value={activities.data ? formatPercent(seniorShare(activities.data.internal, n)) : '—'}
            note="Claims above ₹2,00,000"
          />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <MonthlyTrend scope={scope} metric="sla_breach_rate" title="SLA breach rate by month" />
          <MonthlyTrend
            scope={scope}
            metric="avg_cycle_days"
            title="Average cycle time by month"
            reference={{ y: slaDays, label: `SLA ${slaDays} days` }}
          />
        </div>

        <Breakdown scope={scope} />
      </div>
    </Refetching>
  )
}

function seniorShare(activities: { activity: string; cases: number }[], total: number) {
  const senior = activities.find((a) => a.activity === 'Senior Approval')
  return senior && total ? senior.cases / total : 0
}

function MonthlyTrend({
  scope,
  metric,
  title,
  reference,
}: {
  scope: Scope
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
    <Card title={title} subtitle="By month the claim was opened (FNOL)">
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

const BREAKDOWNS = [
  { value: 'amount_band', label: 'Amount' },
  { value: 'channel', label: 'Channel' },
  { value: 'line_of_business', label: 'Line of business' },
  { value: 'team', label: 'Team' },
  { value: 'region', label: 'Region' },
] as const
type BreakdownDim = (typeof BREAKDOWNS)[number]['value']

const BREAKDOWN_METRICS = [
  { value: 'sla_breach_rate', label: 'SLA breach rate' },
  { value: 'avg_cycle_days', label: 'Cycle time' },
  { value: 'rework_rate', label: 'Rework' },
  { value: 'doc_request_rate', label: 'Documents requested' },
] as const
type BreakdownMetric = (typeof BREAKDOWN_METRICS)[number]['value']

function Breakdown({ scope }: { scope: Scope }) {
  const [dim, setDim] = useState<BreakdownDim>('amount_band')
  const [metric, setMetric] = useState<BreakdownMetric>('sla_breach_rate')
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
  const metricLabel = BREAKDOWN_METRICS.find((m) => m.value === metric)!.label
  const dimLabel = BREAKDOWNS.find((b) => b.value === dim)!.label

  return (
    <Card
      title={`${metricLabel} by ${dimLabel.toLowerCase()}`}
      subtitle="Groups with fewer than 100 claims are marked low sample and drawn lighter"
      actions={
        <div className="flex flex-wrap gap-2">
          <Segmented label="Metric" value={metric} onChange={setMetric} options={[...BREAKDOWN_METRICS]} />
          <Segmented label="Group by" value={dim} onChange={setDim} options={[...BREAKDOWNS]} />
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
