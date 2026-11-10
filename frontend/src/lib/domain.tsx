import { useQuery } from '@tanstack/react-query'
import { createContext, useContext, useState, type ReactNode } from 'react'
import { getDomain, listDomains, setActiveDomain } from './domainStore'

const Ctx = createContext<{ domain: string | null; setDomain: (d: string) => void }>({
  domain: null,
  setDomain: () => {},
})

/** Renders `children(domain)` once the active pack is known; the caller keys the app on it,
 * so switching packs remounts every screen cleanly. */
export function DomainProvider({ children }: { children: (domain: string) => ReactNode }) {
  const [chosen, setChosen] = useState<string | null>(getDomain)
  const domains = useQuery({ queryKey: ['domains-list'], queryFn: listDomains, staleTime: 60_000 })
  const known = domains.data?.map((d) => d.domain) ?? []
  // A stored pack that is no longer enabled (or none yet) falls back to the default, listed first.
  const domain = chosen && known.includes(chosen) ? chosen : (known[0] ?? null)
  // Idempotent sync of the request header source, before any child renders or fetches.
  if (domain && domain !== getDomain()) setActiveDomain(domain)

  const setDomain = (next: string) => {
    setActiveDomain(next)
    setChosen(next)
  }
  if (!domain) return null
  return <Ctx.Provider value={{ domain, setDomain }}>{children(domain)}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export const useActiveDomain = () => useContext(Ctx)
