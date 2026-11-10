import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from 'recharts'
import { TableView } from './ui'

/** Round axis ticks: 0 and ~4 clean steps (1, 2, 2.5 or 5 × 10^k) covering `max`. */
function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1]
  const raw = max / count
  const pow = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? 10 * pow
  const top = Math.ceil(max / step) * step
  return Array.from({ length: Math.round(top / step) + 1 }, (_, i) => +(i * step).toFixed(10))
}

export interface TrendPoint {
  x: string // category (e.g. month)
  xLabel: string
  y: number
  n: number
}

/** Single-series trend: 2px line, ≥ 8px end dot with surface ring, hairline grid,
 *  crosshair tooltip, value labelled at the end only, table twin. */
export function TrendChart({
  data,
  format,
  caption,
  valueLabel,
  reference,
  height = 200,
  axisFormat,
}: {
  data: TrendPoint[]
  format: (v: number) => string
  caption: string
  valueLabel: string
  reference?: { y: number; label: string }
  height?: number
  /** Format for axis ticks (e.g. no decimals); defaults to `format`. */
  axisFormat?: (v: number) => string
}) {
  const last = data.length - 1
  const ticks = niceTicks(Math.max(...data.map((d) => d.y), reference?.y ?? 0) * 1.08)
  return (
    <div>
      <div style={{ height }} role="img" aria-label={caption}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 12, right: 56, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
            <XAxis
              dataKey="xLabel"
              tickLine={false}
              axisLine={{ stroke: 'var(--axis)' }}
              tick={{ fill: 'var(--ink-muted)', fontSize: 11 }}
              className="tabular"
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={48}
              tick={{ fill: 'var(--ink-muted)', fontSize: 11 }}
              tickFormatter={(v: number) => (axisFormat ?? format)(v)}
              ticks={ticks}
              domain={[0, ticks[ticks.length - 1]]}
            />
            {reference && (
              <ReferenceLine
                y={reference.y}
                stroke="var(--ink-muted)"
                strokeWidth={1}
                label={(p: { viewBox?: { x?: number; y?: number } }) => (
                  // Above the line at the left edge, so it never sits on the data line.
                  <text x={(p.viewBox?.x ?? 0) + 4} y={(p.viewBox?.y ?? 0) - 6} fontSize={11} fill="var(--ink-2)">
                    {reference.label}
                  </text>
                )}
              />
            )}
            <Tooltip
              cursor={{ stroke: 'var(--axis)', strokeWidth: 1 }}
              content={(props: TooltipContentProps) => <Tip {...props} format={format} />}
              isAnimationActive={false}
            />
            <Line
              type="linear"
              dataKey="y"
              stroke="var(--series-1)"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              isAnimationActive={false}
              dot={(p: { cx?: number; cy?: number; index?: number }) =>
                p.index === last && p.cx !== undefined && p.cy !== undefined ? (
                  <g key="end">
                    <circle cx={p.cx} cy={p.cy} r={6} fill="var(--surface)" />
                    <circle cx={p.cx} cy={p.cy} r={4} fill="var(--series-1)" />
                    <text x={p.cx + 10} y={p.cy + 4} fontSize={12} fontWeight={600} fill="var(--ink)">
                      {format(data[last].y)}
                    </text>
                  </g>
                ) : (
                  <g key={p.index} />
                )
              }
              activeDot={{ r: 4, stroke: 'var(--surface)', strokeWidth: 2, fill: 'var(--series-1)' }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <TableView
        caption={caption}
        columns={['Period', valueLabel, 'Records']}
        rows={data.map((d) => [d.xLabel, format(d.y), d.n.toLocaleString('en-IN')])}
      />
    </div>
  )
}

function Tip({
  active,
  payload,
  format,
}: TooltipContentProps & { format: (v: number) => string }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload as TrendPoint
  return (
    <div className="rounded-lg border border-hairline bg-surface px-3 py-2 text-xs shadow-md">
      <div className="flex items-center gap-2">
        <span aria-hidden className="h-0.5 w-3 rounded bg-series-1" />
        <span className="font-semibold text-ink">{format(p.y)}</span>
      </div>
      <div className="text-ink-2">
        {p.xLabel} · n = {p.n.toLocaleString('en-IN')}
      </div>
    </div>
  )
}
