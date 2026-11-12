// Exploratory SQL. Shapes mirror backend/api/explore.py.
import { apiFetch } from '../lib/domainStore'

export interface ExploreResult {
  sql: string
  columns: string[]
  rows: unknown[][]
  row_count: number
  truncated: boolean
  duration_ms: number
  label: string
}

export interface Draft {
  sql: string
  explanation: string
  model: string
}

export interface SchemaInfo {
  doc: string
  tables: Record<string, [string, string][]>
  max_rows: number
  timeout_seconds: number
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown }
    throw new Error(typeof body.detail === 'string' ? body.detail : `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

const post = (url: string, body: unknown) =>
  apiFetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })

export const exploreApi = {
  schema: () => apiFetch('/api/explore/schema').then((r) => json<SchemaInfo>(r)),
  run: (sql: string) => post('/api/explore/run', { sql }).then((r) => json<ExploreResult>(r)),
  draft: (question: string) => post('/api/explore/draft', { question }).then((r) => json<Draft>(r)),
}
