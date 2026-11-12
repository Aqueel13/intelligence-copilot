// Accounts and sessions. Shapes mirror backend/api/auth.py.
import { apiFetch } from '../lib/domainStore'

export interface UserInfo {
  user_id: string
  email: string
  name: string
  platform_role: 'visitor' | 'viewer' | 'analyst' | 'admin' // visitor = not signed in (read-only)
  active: boolean
  pack_roles: Record<string, string>
  last_login_at: string | null
}

export interface Me {
  user: UserInfo
  real_user: UserInfo | null // set while an admin acts as someone else
  business_role: string | null // in the active pack
  permissions: string[]
}

export interface RoleInfo {
  platform_roles: Record<string, string>
  permissions: Record<string, string[]>
  business_roles: Record<string, string[]>
}

export interface UsageWindow {
  scope: 'user' | 'everyone' // rolling hour per person | rolling day for everyone
  limit: number // 0 = no limit
  used: number
  resets_in: number
}

export interface Usage {
  exempt: boolean
  limits: Record<'investigate' | 'ask', UsageWindow[]>
}

export class Unauthorized extends Error {}

async function json<T>(res: Response): Promise<T> {
  if (res.status === 401) throw new Unauthorized('Sign in required')
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* not JSON */
    }
    throw new Error(detail)
  }
  return res.status === 204 ? (undefined as T) : (res.json() as Promise<T>)
}

const send = (url: string, method: string, body?: unknown) =>
  apiFetch(url, { method, headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })

export const authApi = {
  me: () => apiFetch('/api/auth/me').then((r) => json<Me>(r)),
  login: (email: string, password: string) => send('/api/auth/login', 'POST', { email, password }).then((r) => json<Me>(r)),
  logout: () => send('/api/auth/logout', 'POST').then((r) => json<void>(r)),
  actAs: (user_id: string | null) => send('/api/auth/act-as', 'POST', { user_id }).then((r) => json<Me>(r)),
  users: () => apiFetch('/api/auth/users').then((r) => json<UserInfo[]>(r)),
  roles: () => apiFetch('/api/auth/roles').then((r) => json<RoleInfo>(r)),
  usage: () => apiFetch('/api/auth/usage').then((r) => json<Usage>(r)),
  packs: () => apiFetch('/api/auth/packs').then((r) => json<{ domain: string; display_name: string }[]>(r)),
  createUser: (b: { user_id: string; email: string; name: string; platform_role: string; password: string; pack_roles: Record<string, string> }) =>
    send('/api/auth/users', 'POST', b).then((r) => json<UserInfo>(r)),
  updateUser: (id: string, b: Partial<{ name: string; platform_role: string; active: boolean; password: string; pack_roles: Record<string, string> }>) =>
    send(`/api/auth/users/${id}`, 'PATCH', b).then((r) => json<UserInfo>(r)),
}
