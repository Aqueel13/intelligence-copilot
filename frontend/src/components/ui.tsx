import { useState, type ReactNode } from 'react'

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = '',
}: {
  title?: string
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`rounded-xl border border-hairline bg-surface p-5 ${className}`}>
      {(title || actions) && (
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-2">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  )
}

/** Stat tile: label · value · optional note. Proportional figures for the value. */
export function StatTile({
  label,
  value,
  note,
  hero = false,
}: {
  label: string
  value: string
  note?: ReactNode
  hero?: boolean
}) {
  return (
    <div className="rounded-xl border border-hairline bg-surface p-4">
      <div className="text-xs text-ink-2">{label}</div>
      <div className={`mt-1 font-semibold text-ink ${hero ? 'text-5xl' : 'text-2xl'}`}>{value}</div>
      {note && <div className="mt-1 text-xs text-ink-muted">{note}</div>}
    </div>
  )
}

type Status = 'critical' | 'serious' | 'warning' | 'good'
const STATUS_ICON: Record<Status, string> = {
  critical: '▲',
  serious: '◆',
  warning: '●',
  good: '✓',
}
const STATUS_COLOR: Record<Status, string> = {
  critical: 'text-critical',
  serious: 'text-serious',
  warning: 'text-warning',
  good: 'text-good',
}

/** Status is never colour alone: icon + label, label in ink. */
export function StatusBadge({ status, label }: { status: Status; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-ink">
      <span aria-hidden className={STATUS_COLOR[status]}>
        {STATUS_ICON[status]}
      </span>
      {label}
    </span>
  )
}

export function LowSample({ n }: { n: number }) {
  return (
    <span
      className="rounded border border-hairline px-1 py-px text-[10px] font-medium uppercase tracking-wide text-ink-muted"
      title={`Based on only ${n} records. Treat with caution.`}
    >
      low sample
    </span>
  )
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-hairline p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
            o.value === value ? 'bg-ghost font-semibold text-ink' : 'text-ink-2 hover:bg-ghost'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** Every chart has a table twin. Collapsed by default. */
export function TableView({
  columns,
  rows,
  caption,
}: {
  columns: string[]
  rows: (string | number)[][]
  caption: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-3">
      <button
        className="text-xs text-ink-2 underline decoration-hairline underline-offset-2 hover:text-ink"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        {open ? 'Hide table' : 'Show table'}
      </button>
      {open && (
        <div className="mt-2 overflow-x-auto">
          <table className="tabular w-full text-left text-xs">
            <caption className="sr-only">{caption}</caption>
            <thead>
              <tr className="border-b border-hairline text-ink-2">
                {columns.map((c) => (
                  <th key={c} scope="col" className="py-1.5 pr-4 font-medium">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-b border-hairline last:border-0">
                  {r.map((cell, j) => (
                    <td key={j} className="py-1.5 pr-4 text-ink">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  return (
    <p role="alert" className="text-sm text-ink-2">
      <StatusBadge status="critical" label="Couldn't load" />{' '}
      {error instanceof Error ? error.message : String(error)}
    </p>
  )
}

/** Hold the previous render at reduced opacity while refetching (no skeleton flash). */
export function Refetching({ active, children }: { active: boolean; children: ReactNode }) {
  return (
    <div className={`transition-opacity ${active ? 'opacity-50' : 'opacity-100'}`} aria-busy={active}>
      {children}
    </div>
  )
}
