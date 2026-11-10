import { hashKey } from '@tanstack/react-query'

/**
 * The active domain pack, outside React: every API call carries it in the X-Domain header,
 * and every query cache key includes it, so switching never shows one pack's numbers under
 * another's labels. lib/domain.tsx owns switching.
 */
const KEY = 'watchdog.domain'

export interface DomainSummary {
  domain: string
  display_name: string
  case_label_plural: string
  cases: number
}

function stored(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

/** A link can pick the pack (`?domain=procure_to_pay`); otherwise the last one used. */
function fromUrl(): string | null {
  try {
    return new URLSearchParams(window.location.search).get('domain')
  } catch {
    return null
  }
}

let current: string | null = fromUrl() ?? stored()

export const getDomain = () => current

export function setActiveDomain(domain: string): void {
  current = domain
  try {
    localStorage.setItem(KEY, domain)
  } catch {
    /* storage unavailable: keep in memory */
  }
}

/** fetch() with the active domain pack attached. */
export function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers)
  if (current) headers.set('X-Domain', current)
  return fetch(input, { ...init, headers })
}

/** Query keys are hashed together with the active pack. */
export const domainQueryKeyHash = (key: readonly unknown[]) => hashKey([current, ...key])

export async function listDomains(): Promise<DomainSummary[]> {
  const res = await fetch('/api/domains') // no header: must work even if the stored pack is gone
  if (!res.ok) throw new Error(`domains: ${res.status}`)
  return res.json()
}
