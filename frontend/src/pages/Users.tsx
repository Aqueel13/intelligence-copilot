import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { authApi, type UserInfo } from '../api/auth'
import { Card, ErrorNote, StatusBadge } from '../components/ui'
import { useAuth } from '../lib/auth'

const ROLES = ['viewer', 'analyst', 'admin'] as const

export default function Users() {
  const { me } = useAuth()
  const realAdmin = (me?.real_user ?? me?.user)?.platform_role === 'admin'
  const users = useQuery({ queryKey: ['auth-users'], queryFn: authApi.users, enabled: realAdmin })
  const roles = useQuery({ queryKey: ['auth-roles'], queryFn: authApi.roles })
  const packs = useQuery({ queryKey: ['auth-packs'], queryFn: authApi.packs })
  const [editing, setEditing] = useState<string | null>(null)

  if (!realAdmin) return <Card title="Users"><p className="text-sm text-ink-2">Only administrators can manage users.</p></Card>
  if (users.error) return <ErrorNote error={users.error} />
  if (!users.data || !roles.data || !packs.data) return null

  return (
    <div className="grid gap-4">
      <Card
        title="Users and roles"
        subtitle="Two layers: the platform role decides what someone can do in the app; the business role in each process decides which actions they may approve there (per that pack's governance). Every change is recorded in the audit log."
      >
        <div className="grid gap-3 sm:grid-cols-3">
          {ROLES.map((r) => (
            <div key={r} className="rounded-lg border border-hairline p-3 text-xs">
              <div className="mb-1 font-semibold capitalize text-ink">{r}</div>
              <div className="text-ink-2">{roles.data.platform_roles[r]}</div>
            </div>
          ))}
        </div>
        {me?.real_user && (
          <p className="mt-3 text-xs text-serious">You are acting as {me.user.name}: changes are made by you ({me.real_user.name}) and recorded under your name.</p>
        )}
      </Card>

      <Card title={`Accounts (${users.data.length})`}>
        <div className="overflow-x-auto">
          <table className="tabular w-full text-left text-xs">
            <thead>
              <tr className="border-b border-hairline text-ink-2">
                {['User', 'Email', 'GitHub', 'Platform role', ...packs.data.map((p) => p.display_name.split(' (')[0]), 'Status', 'Last sign-in', ''].map((h) => (
                  <th key={h} className="py-1.5 pr-4 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.data.map((u) =>
                editing === u.user_id ? (
                  <EditRow key={u.user_id} user={u} packs={packs.data} businessRoles={roles.data.business_roles} onDone={() => setEditing(null)} />
                ) : (
                  <tr key={u.user_id} className="border-b border-hairline last:border-0">
                    <td className="py-1.5 pr-4 font-medium text-ink">
                      {u.name} <span className="text-ink-muted">({u.user_id})</span>
                    </td>
                    <td className="py-1.5 pr-4 text-ink-2">{u.email}</td>
                    <td className="py-1.5 pr-4 text-ink-2">{u.github_login ?? '–'}</td>
                    <td className="py-1.5 pr-4 capitalize text-ink">{u.platform_role}</td>
                    {packs.data.map((p) => (
                      <td key={p.domain} className="py-1.5 pr-4 text-ink-2">
                        {u.pack_roles[p.domain] ?? '–'}
                      </td>
                    ))}
                    <td className="py-1.5 pr-4">
                      {u.active ? <StatusBadge status="good" label="Active" /> : <StatusBadge status="serious" label="Deactivated" />}
                    </td>
                    <td className="py-1.5 pr-4 text-ink-muted">{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'never'}</td>
                    <td className="py-1.5 pr-4">
                      <button onClick={() => setEditing(u.user_id)} className="text-ink-2 underline underline-offset-2 hover:text-ink">
                        Edit
                      </button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <NewUser packs={packs.data} businessRoles={roles.data.business_roles} />
    </div>
  )
}

function RoleSelects({
  packs,
  businessRoles,
  value,
  onChange,
}: {
  packs: { domain: string; display_name: string }[]
  businessRoles: Record<string, string[]>
  value: Record<string, string>
  onChange: (v: Record<string, string>) => void
}) {
  return (
    <>
      {packs.map((p) => (
        <label key={p.domain} className="flex flex-col gap-0.5 text-[11px] text-ink-muted">
          {p.display_name.split(' (')[0]}
          <select
            value={value[p.domain] ?? ''}
            onChange={(e) => onChange({ ...value, [p.domain]: e.target.value })}
            className="rounded-md border border-hairline bg-surface px-1.5 py-1 text-xs text-ink"
          >
            <option value="">No business role</option>
            {(businessRoles[p.domain] ?? []).map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
      ))}
    </>
  )
}

function EditRow({
  user,
  packs,
  businessRoles,
  onDone,
}: {
  user: UserInfo
  packs: { domain: string; display_name: string }[]
  businessRoles: Record<string, string[]>
  onDone: () => void
}) {
  const qc = useQueryClient()
  const [role, setRole] = useState(user.platform_role)
  const [active, setActive] = useState(user.active)
  const [packRoles, setPackRoles] = useState(user.pack_roles)
  const [password, setPassword] = useState('')
  const [githubLogin, setGithubLogin] = useState(user.github_login ?? '')
  const save = useMutation({
    mutationFn: () =>
      authApi.updateUser(user.user_id, {
        platform_role: role,
        active,
        pack_roles: Object.fromEntries(Object.entries(packRoles).filter(([, v]) => v)),
        github_login: githubLogin.trim(),
        ...(password ? { password } : {}),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['auth-users'] })
      onDone()
    },
  })
  return (
    <tr className="border-b border-hairline bg-ghost/50">
      <td colSpan={6 + packs.length} className="p-3">
        <div className="mb-2 text-xs font-semibold text-ink">
          {user.name} ({user.user_id})
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-0.5 text-[11px] text-ink-muted">
            Platform role
            <select value={role} onChange={(e) => setRole(e.target.value as UserInfo['platform_role'])} className="rounded-md border border-hairline bg-surface px-1.5 py-1 text-xs text-ink">
              {ROLES.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </label>
          <RoleSelects packs={packs} businessRoles={businessRoles} value={packRoles} onChange={setPackRoles} />
          <label className="flex items-center gap-1.5 pb-1 text-xs text-ink-2">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active
          </label>
          <label className="flex flex-col gap-0.5 text-[11px] text-ink-muted">
            GitHub user (optional)
            <input value={githubLogin} onChange={(e) => setGithubLogin(e.target.value)} placeholder="e.g. octocat" className="rounded-md border border-hairline bg-surface px-1.5 py-1 text-xs text-ink" />
          </label>
          <label className="flex flex-col gap-0.5 text-[11px] text-ink-muted">
            New password (optional)
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={10} placeholder="≥ 10 characters" className="rounded-md border border-hairline bg-surface px-1.5 py-1 text-xs text-ink" />
          </label>
          <button onClick={() => save.mutate()} disabled={save.isPending} className="rounded-md bg-series-1 px-3 py-1 text-xs font-semibold text-white disabled:opacity-50">
            Save
          </button>
          <button onClick={onDone} className="text-xs text-ink-2 underline underline-offset-2">
            Cancel
          </button>
        </div>
        <p className="mt-2 text-[11px] text-ink-muted">Deactivating or resetting a password signs the user out everywhere. Changing the GitHub user links the account to whoever signs in with the new name next.</p>
        {save.error && <p className="mt-1 text-xs text-critical">{(save.error as Error).message}</p>}
      </td>
    </tr>
  )
}

function NewUser({ packs, businessRoles }: { packs: { domain: string; display_name: string }[]; businessRoles: Record<string, string[]> }) {
  const qc = useQueryClient()
  const blank = { user_id: '', email: '', name: '', platform_role: 'viewer', password: '', github_login: '' }
  const [f, setF] = useState(blank)
  const [packRoles, setPackRoles] = useState<Record<string, string>>({})
  const create = useMutation({
    mutationFn: () =>
      authApi.createUser({
        ...f,
        password: f.password || undefined,
        github_login: f.github_login.trim() || undefined,
        pack_roles: Object.fromEntries(Object.entries(packRoles).filter(([, v]) => v)),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['auth-users'] })
      setF(blank)
      setPackRoles({})
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }
  const field = (key: keyof typeof blank, label: string, type = 'text', extra: Record<string, unknown> = {}) => (
    <label className="flex flex-col gap-0.5 text-[11px] text-ink-muted">
      {label}
      <input
        type={type}
        value={f[key]}
        onChange={(e) => setF({ ...f, [key]: e.target.value })}
        required={key !== 'password' && key !== 'github_login'}
        className="rounded-md border border-hairline bg-surface px-2 py-1 text-xs text-ink"
        {...extra}
      />
    </label>
  )
  return (
    <Card
      title="Add a user"
      subtitle="Give a GitHub user name, an initial password, or both. With GitHub, the person signs in with GitHub (a verified GitHub email equal to the account's email also works). Nobody can create their own account."
    >
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        {field('user_id', 'Handle (e.g. j.doe)', 'text', { pattern: '[a-z][a-z0-9._-]{1,40}' })}
        {field('name', 'Name')}
        {field('email', 'Email', 'email')}
        {field('github_login', 'GitHub user', 'text', { placeholder: 'e.g. octocat' })}
        {field('password', 'Initial password', 'password', { minLength: 10, placeholder: 'optional with GitHub' })}
        <label className="flex flex-col gap-0.5 text-[11px] text-ink-muted">
          Platform role
          <select value={f.platform_role} onChange={(e) => setF({ ...f, platform_role: e.target.value })} className="rounded-md border border-hairline bg-surface px-1.5 py-1 text-xs text-ink">
            {ROLES.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <RoleSelects packs={packs} businessRoles={businessRoles} value={packRoles} onChange={setPackRoles} />
        <button disabled={create.isPending} className="rounded-md bg-series-1 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
          Create user
        </button>
      </form>
      {create.error && <p className="mt-2 text-xs text-critical">{(create.error as Error).message}</p>}
      {create.data && <p className="mt-2 text-xs text-good">Created {create.data.user_id}.</p>}
    </Card>
  )
}
