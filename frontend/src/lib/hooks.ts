import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api, type DomainInfo, type Scope } from '../api/client'
import { scopeKey, useScope } from './scope'

export function useDomain() {
  return useQuery({ queryKey: ['domain'], queryFn: api.domain, staleTime: 60_000 })
}

/** What one case is called in the active pack ("claim" / "invoice"), and its SLA ends. */
export function useLabels() {
  const d = useDomain().data
  const many = d?.case_label_plural ?? 'cases'
  return {
    one: d?.case_label ?? 'case',
    many,
    Many: many.charAt(0).toUpperCase() + many.slice(1),
    start: d?.sla_start ?? 'start',
    end: d?.sla_end ?? 'end',
  }
}

/** Domain info + the URL-backed scope for its filter dimensions. */
export function useDomainScope() {
  const domain = useDomain()
  const names = useMemo(() => domain.data?.filters.map((f) => f.name) ?? [], [domain.data])
  return { domain, ...useScope(names) }
}

/** Queries scoped to the shared slice keep the previous data while refetching. */
export function useScoped<T>(name: string, scope: Scope, fn: () => Promise<T>, extra: unknown[] = []) {
  return useQuery({
    queryKey: [name, scopeKey(scope), ...extra],
    queryFn: fn,
    placeholderData: keepPreviousData,
  })
}

export type { DomainInfo }
