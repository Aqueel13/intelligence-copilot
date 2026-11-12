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
  if (q.error instanceof Unauthorized) return <Login initialError={signInErrorAtLoad} />
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

/** Why a GitHub sign-in sent the browser back without a session (?signin_error=...). */
const GITHUB_ERRORS: Record<string, string> = {
  no_account: 'There is no account for this GitHub user. Accounts are created by an administrator; ask for one, or keep browsing as a visitor.',
  conflict: 'This account is linked to a different GitHub user.',
  inactive: 'This account is deactivated.',
  denied: 'GitHub sign-in was cancelled.',
  state: 'The sign-in link expired or was not started here. Please try again.',
  github: 'GitHub could not be reached. Please try again, or sign in with a password.',
}

/** The sign-in error GitHub's redirect left in the address, if any. Read once, when the app
 * loads (render functions may run twice), and removed from the address bar. */
function takeSignInError(): string | null {
  const params = new URLSearchParams(window.location.search)
  const code = params.get('signin_error')
  if (!code) return null
  params.delete('signin_error')
  const rest = params.toString()
  window.history.replaceState(null, '', window.location.pathname + (rest ? `?${rest}` : '') + window.location.hash)
  return GITHUB_ERRORS[code] ?? 'Sign-in failed.'
}
// eslint-disable-next-line react-refresh/only-export-components
export const signInErrorAtLoad = takeSignInError()

/** Sign-in form: the whole page when visitors are not allowed; an overlay with Cancel when a
 * visitor chooses to sign in. Only accounts an admin created can sign in (no sign-up). */
export function Login({ onCancel, initialError = null }: { onCancel?: () => void; initialError?: string | null } = {}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(initialError)
  const [busy, setBusy] = useState(false)
  const providers = useQuery({ queryKey: ['auth-providers'], queryFn: authApi.providers, staleTime: Infinity })
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
        {providers.data?.github && (
          <>
            <a
              href="/api/auth/github/login"
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-hairline bg-ink px-4 py-2 text-sm font-semibold text-page hover:opacity-90"
            >
              <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="currentColor">
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
              </svg>
              Sign in with GitHub
            </a>
            <div className="my-4 flex items-center gap-3 text-[11px] text-ink-muted">
              <span className="h-px flex-1 bg-hairline" />
              or with a password
              <span className="h-px flex-1 bg-hairline" />
            </div>
          </>
        )}
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
          Accounts are created by an administrator; there is no sign-up. Demo accounts are named after each pack's governance users, e.g. aqueel.kanchwala@demo.watchdog.
        </p>
      </form>
    </div>
  )
}
