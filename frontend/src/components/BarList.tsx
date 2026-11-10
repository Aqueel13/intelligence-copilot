import { useId, useState } from 'react'
import { LowSample, TableView } from './ui'

export interface BarDatum {
  label: string
  value: number
  display: string
  n: number
  lowSample?: boolean
  note?: string
}

/**
 * Horizontal bars, one series: thin bars (≤ 24px), 4px rounded data-end, square at the
 * baseline, value at the tip, hover/focus tooltip, table twin.
 */
export function BarList({
  data,
  max,
  caption,
  valueLabel,
}: {
  data: BarDatum[]
  max?: number
  caption: string
  valueLabel: string
}) {
  const top = max ?? Math.max(...data.map((d) => d.value), 0)
  const [hover, setHover] = useState<number | null>(null)
  const id = useId()

  return (
    <div>
      <ul className="space-y-2" aria-label={caption}>
        {data.map((d, i) => {
          const pct = top > 0 ? (d.value / top) * 100 : 0
          return (
            <li
              key={d.label}
              className="grid grid-cols-[minmax(6rem,10rem)_1fr] items-center gap-3"
              onPointerEnter={() => setHover(i)}
              onPointerLeave={() => setHover(null)}
            >
              <div className="flex items-center gap-1.5 truncate text-xs text-ink-2" title={d.label}>
                <span className="truncate">{d.label}</span>
                {d.lowSample && <LowSample n={d.n} />}
              </div>
              <div
                className="relative flex h-6 items-center gap-2 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-series-1"
                tabIndex={0}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                aria-describedby={hover === i ? `${id}-tip` : undefined}
                aria-label={`${d.label}: ${d.display}, n = ${d.n.toLocaleString('en-IN')}`}
              >
                <div
                  className={`h-3.5 rounded-r-[4px] bg-series-1 transition-opacity ${
                    d.lowSample ? 'opacity-45' : hover === null || hover === i ? 'opacity-100' : 'opacity-70'
                  }`}
                  style={{ width: `max(${pct}%, 2px)` }}
                />
                <span className="tabular shrink-0 text-xs font-medium text-ink">{d.display}</span>
                {hover === i && (
                  <div
                    id={`${id}-tip`}
                    role="tooltip"
                    className="pointer-events-none absolute left-0 top-7 z-10 rounded-lg border border-hairline bg-surface px-3 py-2 text-xs shadow-md"
                  >
                    <div className="font-semibold text-ink">{d.display}</div>
                    <div className="text-ink-2">
                      {d.label} · n = {d.n.toLocaleString('en-IN')}
                    </div>
                    {d.note && <div className="text-ink-muted">{d.note}</div>}
                  </div>
                )}
              </div>
            </li>
          )
        })}
      </ul>
      <TableView
        caption={caption}
        columns={['Group', valueLabel, 'Records']}
        rows={data.map((d) => [d.label, d.display, d.n.toLocaleString('en-IN')])}
      />
    </div>
  )
}
