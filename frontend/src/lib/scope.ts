import { useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { Scope } from '../api/client'

/**
 * The shared slice (filters + period) lives in the URL, so every screen agrees and a view
 * can be shared as a link. Params: one per dimension (single value), `from` and `to` as
 * YYYY-MM months.
 */
export function useScope(dimensionNames: string[]) {
  const [params, setParams] = useSearchParams()

  const scope: Scope = useMemo(() => {
    const filters: Record<string, string[]> = {}
    for (const name of dimensionNames) {
      const v = params.get(name)
      if (v) filters[name] = [v]
    }
    const from = params.get('from')
    const to = params.get('to')
    return {
      filters,
      period_from: from ? `${from}-01` : null,
      period_to: to ? lastDayOfMonth(to) : null,
    }
  }, [params, dimensionNames])

  const set = (key: string, value: string | null) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true },
    )
  }

  const clear = () =>
    setParams(
      (prev) => {
        const next = new URLSearchParams()
        // Keep non-scope params (none yet) by copying anything not owned by the scope.
        for (const [k, v] of prev) {
          if (!dimensionNames.includes(k) && k !== 'from' && k !== 'to') next.set(k, v)
        }
        return next
      },
      { replace: true },
    )

  const active =
    Object.keys(scope.filters).length + (params.get('from') ? 1 : 0) + (params.get('to') ? 1 : 0)

  return { scope, params, set, clear, active }
}

function lastDayOfMonth(month: string): string {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(Date.UTC(y, m, 0))
  return d.toISOString().slice(0, 10)
}

/** All YYYY-MM months between two ISO dates, inclusive. */
export function monthsBetween(from: string, to: string): string[] {
  const out: string[] = []
  let [y, m] = from.slice(0, 7).split('-').map(Number)
  const [ty, tm] = to.slice(0, 7).split('-').map(Number)
  while (y < ty || (y === ty && m <= tm)) {
    out.push(`${y}-${String(m).padStart(2, '0')}`)
    m += 1
    if (m > 12) {
      m = 1
      y += 1
    }
  }
  return out
}

/** Stable cache key for a scope. */
export const scopeKey = (s: Scope) => JSON.stringify(s)
