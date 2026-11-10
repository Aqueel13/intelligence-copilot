import type { Unit } from '../api/client'

const enIN = 'en-IN'

export const formatCount = (n: number) => n.toLocaleString(enIN)

export const formatPercent = (ratio: number, digits = 1) =>
  `${(ratio * 100).toLocaleString(enIN, { maximumFractionDigits: digits, minimumFractionDigits: digits })}%`

export const formatDays = (days: number) =>
  `${days.toLocaleString(enIN, { maximumFractionDigits: 1, minimumFractionDigits: 1 })} d`

export function formatHours(hours: number): string {
  if (hours >= 48) return `${(hours / 24).toLocaleString(enIN, { maximumFractionDigits: 1 })} d`
  return `${hours.toLocaleString(enIN, { maximumFractionDigits: 1 })} h`
}

/** Indian notation: ₹45,000 · ₹2.4L · ₹1.2Cr */
export function formatInr(amount: number): string {
  if (amount >= 1e7) return `₹${(amount / 1e7).toLocaleString(enIN, { maximumFractionDigits: 1 })}Cr`
  if (amount >= 1e5) return `₹${(amount / 1e5).toLocaleString(enIN, { maximumFractionDigits: 1 })}L`
  return `₹${Math.round(amount).toLocaleString(enIN)}`
}

export function formatValue(value: number | null, unit: Unit): string {
  if (value === null) return '—'
  switch (unit) {
    case 'ratio':
      return formatPercent(value)
    case 'days':
      return formatDays(value)
    case 'hours':
      return formatHours(value)
    case 'inr':
      return formatInr(value)
    case 'score_1_5':
      return value.toLocaleString(enIN, { maximumFractionDigits: 2, minimumFractionDigits: 2 })
    case 'nps':
      return value.toLocaleString(enIN, { maximumFractionDigits: 0 })
    default:
      return formatCount(value)
  }
}

export function formatMonth(month: string): string {
  const [y, m] = month.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString(enIN, { month: 'short', year: '2-digit' })
}

/** Human labels for dimension values (snake/lower-case values → sentence case). */
export function formatDimensionValue(value: string): string {
  if (value === '(none)') return 'None'
  return /^[a-z_]+$/.test(value) ? value[0].toUpperCase() + value.slice(1).replace(/_/g, ' ') : value
}
