import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { api } from '../api/client'
import { watchApi } from '../api/investigation'
import { formatCount, formatDimensionValue, formatMonth } from '../lib/format'
import { authApi } from '../api/auth'
import { Login, signInErrorAtLoad, useAuth } from '../lib/auth'
import { useActiveDomain } from '../lib/domain'
import { listDomains } from '../lib/domainStore'
import { useDomainScope } from '../lib/hooks'
import { monthsBetween } from '../lib/scope'

// Primary work and admin pages; an item shows only if the user's role allows it.
const NAV: { to: string; label: string; permission?: string; adminOnly?: boolean }[] = [
  { to: '/watch', label: 'Watch' },
  { to: '/overview', label: 'Overview' },
  { to: '/process', label: 'Process' },
  { to: '/knowledge', label: 'Knowledge' },
  { to: '/investigate', label: 'Investigate' },
  { to: '/actions', label: 'Actions' },
  { to: '/explore', label: 'Explore', permission: 'explore' },
  { to: '/models', label: 'Models' },
  { to: '/observability', label: 'Observability', permission: 'view_observability' },
  { to: '/users', label: 'Users', adminOnly: true },
]

function OpenAlerts() {
  const q = useQuery({ queryKey: ['watch'], queryFn: watchApi.status, refetchInterval: 60_000 })
  const open = q.data?.alerts.filter((a) => a.status !== 'resolved') ?? []
  if (!open.length) return null
  const critical = open.some((a) => a.severity === 'critical')
  return (
    <span
      className={`ml-1 rounded-full px-1.5 text-[10px] font-semibold ${critical ? 'bg-critical text-white' : 'bg-warning text-ink'}`}
      aria-label={`${open.length} open alerts`}
    >
      {open.length}
    </span>
  )
}

export default function Layout() {
  const { search } = useLocation()
  const { me, can } = useAuth()
  const realAdmin = (me?.real_user ?? me?.user)?.platform_role === 'admin'
  const items = NAV.filter((n) => (n.adminOnly ? realAdmin : !n.permission || can(n.permission)))
  return (
    <div className="min-h-screen">
      <header className="border-b border-hairline bg-surface">
        <div className="mx-auto flex max-w-7xl flex-wrap items-end justify-between gap-x-6 gap-y-2 px-4 pt-3">
          <div className="flex flex-wrap items-end gap-6">
            <div className="pb-1">
              <div className="whitespace-nowrap text-base font-semibold">Intelligence WatchDog</div>
              <div className="whitespace-nowrap text-[11px] text-ink-muted">Watch · Investigate · Recommend · Act</div>
            </div>
            <DomainSwitcher />
          </div>
          <div className="flex flex-wrap items-center gap-4 pb-1">
            <SystemStatus />
            <UserMenu />
          </div>
        </div>
        <nav aria-label="Main" className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pt-2">
          {items.map((n) => (
            <NavLink
              key={n.to}
              to={{ pathname: n.to, search }}
              className={({ isActive }) =>
                `whitespace-nowrap border-b-2 px-3 py-2 text-sm ${
                  isActive ? 'border-series-1 font-semibold text-ink' : 'border-transparent text-ink-2 hover:text-ink'
                }`
              }
            >
              {n.label}
              {n.to === '/watch' && <OpenAlerts />}
            </NavLink>
          ))}
        </nav>
      </header>
      {me?.real_user && (
        <div className="border-b border-hairline bg-warning/15 px-4 py-1.5 text-center text-xs text-ink">
          You ({me.real_user.name}) are acting as <b>{me.user.name}</b>
          {me.business_role ? ` · ${me.business_role}` : ''}. Every action is recorded as theirs, with you named in the audit log.
        </div>
      )}
      <FilterBar />
      <main className="mx-auto max-w-7xl px-4 pb-16 pt-6">
        <Outlet />
      </main>
    </div>
  )
}

function DomainSwitcher() {
  const { domain, setDomain } = useActiveDomain()
  const navigate = useNavigate()
  const q = useQuery({ queryKey: ['domains-list'], queryFn: listDomains, staleTime: 60_000 })
  if (!q.data || q.data.length < 2) return null
  return (
    <label className="flex flex-col gap-0.5" title="Each process is a domain pack: configuration and data on the same engine.">
      <span className="text-[11px] text-ink-muted">Process</span>
      <select
        value={domain ?? ''}
        onChange={(e) => {
          navigate('/watch') // filters belong to one pack: start the new one unfiltered
          setDomain(e.target.value)
        }}
        className="rounded-md border border-hairline bg-surface px-2 py-1 text-sm font-medium text-ink"
      >
        {q.data.map((d) => (
          <option key={d.domain} value={d.domain}>
            {d.display_name}
          </option>
        ))}
      </select>
    </label>
  )
}

/** Who is signed in, their roles here, sign out; admins can act as another user (audited). */
function UserMenu() {
  const { me } = useAuth()
  // Back from a refused GitHub sign-in: reopen the form with the reason.
  const [signInError, setSignInError] = useState(signInErrorAtLoad)
  const [signIn, setSignIn] = useState(signInErrorAtLoad !== null)
  const realAdmin = (me?.real_user ?? me?.user)?.platform_role === 'admin'
  const users = useQuery({ queryKey: ['auth-users'], queryFn: authApi.users, enabled: realAdmin, staleTime: 60_000 })
  if (!me) return null
  if (me.user.platform_role === 'visitor')
    return (
      <div className="flex items-center gap-3 text-xs text-ink-2">
        <span className="rounded border border-hairline px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-muted" title="Not signed in: you can read every screen and replay showcase runs.">
          Visitor · read-only
        </span>
        <button onClick={() => setSignIn(true)} className="rounded-md bg-series-1 px-2.5 py-1 font-semibold text-white">
          Sign in to run things
        </button>
        {signIn && (
          <Login
            onCancel={() => {
              setSignIn(false)
              setSignInError(null)
            }}
            initialError={signInError}
          />
        )}
      </div>
    )
  const switchTo = async (id: string) => {
    await authApi.actAs(id === (me.real_user ?? me.user).user_id ? null : id)
    window.location.reload() // every screen re-renders as the new identity
  }
  const logout = async () => {
    await authApi.logout()
    window.location.assign('/')
  }
  return (
    <div className="flex items-center gap-3 text-xs text-ink-2">
      {realAdmin && users.data ? (
        <label className="flex items-center gap-1.5" title="Admins can act as another user for demos and support. Recorded in the audit log.">
          Act as
          <select
            value={me.user.user_id}
            onChange={(e) => switchTo(e.target.value)}
            className="max-w-[16rem] rounded-md border border-hairline bg-surface px-1.5 py-0.5 text-xs font-medium text-ink"
          >
            {users.data
              .filter((u) => u.active)
              .map((u) => (
                <option key={u.user_id} value={u.user_id}>
                  {u.name} · {u.platform_role}
                  {Object.keys(u.pack_roles).length ? ` · ${Object.values(u.pack_roles).join(' / ')}` : ''}
                </option>
              ))}
          </select>
        </label>
      ) : (
        <span>
          <b className="text-ink">{me.user.name}</b>
        </span>
      )}
      <span className="rounded border border-hairline px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-muted" title={`Business role here: ${me.business_role ?? 'none'}`}>
        {me.user.platform_role}
        {me.business_role ? ` · ${me.business_role}` : ''}
      </span>
      <button onClick={logout} className="underline underline-offset-2 hover:text-ink">
        Sign out
      </button>
    </div>
  )
}

function SystemStatus() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30_000 })
  const ok = health.data?.status === 'ok'
  const label = health.isPending ? 'Checking…' : ok ? 'All systems normal' : 'Degraded'
  return (
    <div className="flex items-center gap-2 text-xs text-ink-2" title={health.data?.database.error ?? ''}>
      <span
        aria-hidden
        className={`h-2 w-2 rounded-full ${health.isPending ? 'bg-axis' : ok ? 'bg-good' : 'bg-critical'}`}
      />
      {label}
      {health.data && <span className="text-ink-muted">v{health.data.version}</span>}
    </div>
  )
}

/** One filter row, above everything it scopes. Period first. */
function FilterBar() {
  const { domain, params, set, clear, active } = useDomainScope()
  const d = domain.data
  if (!d) return <div className="h-12 border-b border-hairline bg-surface" />
  const months = d.data_from && d.data_to ? monthsBetween(d.data_from, d.data_to) : []

  return (
    <div className="border-b border-hairline bg-surface">
      <div className="mx-auto flex max-w-7xl flex-wrap items-end gap-3 px-4 py-2.5">
        <Select
          label="From"
          value={params.get('from') ?? ''}
          onChange={(v) => set('from', v)}
          options={months.map((m) => ({ value: m, label: formatMonth(m) }))}
          allLabel="Start"
        />
        <Select
          label="To"
          value={params.get('to') ?? ''}
          onChange={(v) => set('to', v)}
          options={months.map((m) => ({ value: m, label: formatMonth(m) }))}
          allLabel="Latest"
        />
        <span className="mx-1 h-8 w-px bg-hairline" aria-hidden />
        {d.filters.map((f) => (
          <Select
            key={f.name}
            label={f.label}
            value={params.get(f.name) ?? ''}
            onChange={(v) => set(f.name, v)}
            options={(f.values ?? []).map((v) => ({ value: v, label: formatDimensionValue(v) }))}
            allLabel="All"
          />
        ))}
        {active > 0 && (
          <button onClick={clear} className="pb-1.5 text-xs text-ink-2 underline underline-offset-2 hover:text-ink">
            Clear filters
          </button>
        )}
        <div className="ml-auto pb-1.5 text-xs text-ink-muted">
          {formatCount(d.cases)} {d.case_label_plural} · {d.sla_name} SLA {d.sla_hours / 24} days
        </div>
      </div>
    </div>
  )
}

function Select({
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  label: string
  value: string
  onChange: (v: string | null) => void
  options: { value: string; label: string }[]
  allLabel: string
}) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-[11px] text-ink-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value || null)}
        className={`rounded-md border border-hairline bg-surface px-2 py-1 text-xs ${
          value ? 'font-semibold text-ink' : 'text-ink-2'
        }`}
      >
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}
