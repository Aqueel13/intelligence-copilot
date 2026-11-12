import { useQuery } from '@tanstack/react-query'
import { createContext, useContext, useState, type FormEvent, type ReactNode } from 'react'
import { authApi, Unauthorized, type Me } from '../api/auth'

/**
 * Sign-in gate and the current user. The session is an HttpOnly cookie (scripts never see
 * it); this only asks the backend who we are. Permissions come from the backend too: the UI
 * hides or disables what a role cannot do, and the backend enforces it regardless.
 */
const Ctx = createContext<{ me: Me | null; can: (permission: string) => boolean }>({
  me: null,
  can: () => false,
})

export function AuthGate({ children }: { children: ReactNode }) {
  const q = useQuery({ queryKey: ['me-gate'], queryFn: authApi.me, retry: false, staleTime: 60_000 })
  if (q.isPending) return null
  if (q.error instanceof Unauthorized) return <Login />
  if (q.error) return <div className="p-8 text-sm text-critical">Cannot reach the backend: {String(q.error.message)}</div>
  return <>{children}</>
}

/** The current user for the active pack (the business role differs per pack). */
export function MeProvider({ children }: { children: ReactNode }) {
  const q = useQuery({ queryKey: ['me'], queryFn: authApi.me, retry: false, staleTime: 60_000 })
  const me = q.data ?? null
  const can = (p: string) => !!me?.permissions.includes(p)
  return <Ctx.Provider value={{ me, can }}>{children}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = () => useContext(Ctx)

/** Sign-in form: the whole page when visitors are not allowed; an overlay with Cancel when a
 * visitor chooses to sign in. Only accounts an admin created can sign in (no sign-up). */
export function Login({ onCancel }: { onCancel?: () => void } = {}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await authApi.login(email, password)
      // A fresh start: every query (and the sign-in gate itself) refetches as the new user.
      window.location.reload()
      return
    } catch (err) {
      setError(err instanceof Unauthorized ? 'Wrong email or password.' : String((err as Error).message))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div
      className={
        onCancel
          ? 'fixed inset-0 z-50 flex items-center justify-center bg-page/90 px-4'
          : 'flex min-h-screen items-center justify-center bg-page px-4'
      }
      role={onCancel ? 'dialog' : undefined}
      aria-modal={onCancel ? true : undefined}
      aria-label={onCancel ? 'Sign in' : undefined}
    >
      <form onSubmit={submit} className="w-full max-w-sm rounded-xl border border-hairline bg-surface p-6">
        <div className="text-lg font-semibold text-ink">Intelligence WatchDog</div>
        <div className="mb-5 text-xs text-ink-muted">Watch · Investigate · Recommend · Act</div>
        <label className="mb-3 block text-xs text-ink-2">
          Email
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg border border-hairline bg-surface px-3 py-2 text-sm text-ink"
            required
          />
        </label>
        <label className="mb-4 block text-xs text-ink-2">
          Password
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-hairline bg-surface px-3 py-2 text-sm text-ink"
            required
          />
        </label>
        {error && <p className="mb-3 text-xs text-critical" role="alert">{error}</p>}
        <button disabled={busy} className="w-full rounded-lg bg-series-1 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} className="mt-2 w-full rounded-lg px-4 py-2 text-sm text-ink-2 hover:bg-ghost">
            Keep browsing as a visitor
          </button>
        )}
        <p className="mt-4 text-[11px] text-ink-muted">
          Local accounts (`make users`). Demo accounts are named after each pack's governance users, e.g. aqueel.kanchwala@demo.watchdog.
        </p>
      </form>
    </div>
  )
}
