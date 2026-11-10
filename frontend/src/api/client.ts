export interface DatabaseHealth {
  ok: boolean
  pgvector_version: string | null
  missing_schemas: string[]
  error: string | null
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  app: string
  version: string
  environment: string
  database: DatabaseHealth
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const res = await fetch('/api/health', { signal })
  // 503 still carries a useful body describing what is degraded.
  if (!res.ok && res.status !== 503) {
    throw new Error(`Backend returned ${res.status}`)
  }
  return res.json() as Promise<HealthResponse>
}
