// Typed API client. Shapes mirror the backend's Pydantic models.

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

export interface FilterDimension {
  name: string
  label: string
  values: string[] | null
}

export interface DomainInfo {
  domain: string
  display_name: string
  case_label: string
  currency: string
  timezone: string
  sla_name: string
  sla_hours: number
  senior_threshold: number
  filters: FilterDimension[]
  activities: { name: string; label: string; kind: string }[]
  data_from: string | null
  data_to: string | null
  cases: number
}

/** The shared slice every screen is scoped to. */
export interface Scope {
  filters: Record<string, string[]>
  period_from: string | null
  period_to: string | null
}

export type Unit = 'count' | 'ratio' | 'days' | 'hours' | 'inr' | 'score_1_5' | 'nps'

export interface MetricRow {
  group: Record<string, string>
  value: number | null
  n: number
  low_sample: boolean
}

export interface MetricResult {
  metric: string
  label: string
  unit: Unit
  description: string
  group_by: string[]
  rows: MetricRow[]
  sql: string
}

export interface ProcessNode {
  activity: string
  kind: string
  instances: number
  cases: number
  mean_wait_hours: number
  mean_work_hours: number
}

export interface ProcessEdge {
  source: string
  target: string
  transitions: number
  cases: number
  mean_hours: number
  median_hours: number
}

export interface ProcessMap {
  cases: number
  start_activities: Record<string, number>
  end_activities: Record<string, number>
  nodes: ProcessNode[]
  edges: ProcessEdge[]
}

export interface Variant {
  rank: number
  activities: string[]
  cases: number
  share: number
  mean_cycle_days: number
  breach_rate: number
  low_sample: boolean
}

export interface VariantSummary {
  cases: number
  distinct_variants: number
  top_variants_share: number
  variants: Variant[]
}

export interface ActivityStats {
  activity: string
  kind: string
  instances: number
  cases: number
  mean_wait_hours: number
  median_wait_hours: number
  p90_wait_hours: number
  total_wait_hours: number
  share_of_internal_wait: number
  mean_work_hours: number
  repeat_rate: number
  breach_rate_with: number
  breach_rate_without: number | null
  is_bottleneck: boolean
}

export interface ActivityAnalysis {
  cases: number
  bottleneck_threshold_hours: number
  internal: ActivityStats[]
  customer_time: ActivityStats[]
  definitions: Record<string, string>
}

export interface KnowledgeDocument {
  document_id: number
  doc_key: string
  title: string
  doc_type: string
  version: string
  status: 'current' | 'superseded' | 'draft'
  effective_date: string | null
  owner: string | null
  source_name: string
  chunks: number
}

export interface RetrievedChunk {
  chunk_id: number
  doc_key: string
  title: string
  version: string
  status: string
  doc_type: string
  section: string
  content: string
  score: number
  vector_rank: number | null
  keyword_rank: number | null
  vector_similarity: number | null
  rerank_score: number | null
}

export interface Citation {
  number: number
  chunk_id: number
  doc_key: string
  title: string
  version: string
  section: string
  content: string
}

export interface SentenceCheck {
  sentence: string
  model_cited: number[]
  cited: number[]
  status: 'supported' | 'corrected' | 'unsupported'
  best_source: number
  best_score: number
  cited_score: number | null
}

export interface Answer {
  question: string
  answer: string
  found: boolean
  grounded: boolean
  citations: Citation[]
  invalid_citations: number[]
  checks: SentenceCheck[]
  model_citation_accuracy: number | null
  sources: RetrievedChunk[]
  model: string
  retrieval_ms: number
  generation_ms: number
}

export interface IngestResult {
  doc_key: string
  version: string
  title: string
  chunks: number
  status: 'ingested' | 'unchanged' | 'replaced'
}

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail)
  }
  return res.json() as Promise<T>
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const api = {
  health: async (): Promise<HealthResponse> => {
    // 503 still carries a body describing what is degraded.
    const res = await fetch('/api/health')
    if (!res.ok && res.status !== 503) throw new ApiError(`Backend returned ${res.status}`)
    return res.json() as Promise<HealthResponse>
  },
  domain: () => request<DomainInfo>('/domain'),
  metric: (scope: Scope, metric: string, groupBy: string[] = []) =>
    post<MetricResult>('/metrics/query', { ...scope, metric, group_by: groupBy }),
  processMap: (scope: Scope) => post<ProcessMap>('/process/map', scope),
  variants: (scope: Scope, top = 10) => post<VariantSummary>(`/process/variants?top=${top}`, scope),
  activities: (scope: Scope) => post<ActivityAnalysis>('/process/activities', scope),
  documents: () => request<KnowledgeDocument[]>('/knowledge/documents'),
  search: (query: string, includeSuperseded = false) =>
    post<RetrievedChunk[]>('/knowledge/search', {
      query,
      k: 5,
      filters: { include_superseded: includeSuperseded },
    }),
  ask: (question: string, includeSuperseded = false) =>
    post<Answer>('/knowledge/ask', { question, filters: { include_superseded: includeSuperseded } }),
  upload: async (file: File, fields: Record<string, string>): Promise<IngestResult> => {
    const form = new FormData()
    form.append('file', file)
    for (const [k, v] of Object.entries(fields)) if (v) form.append(k, v)
    const res = await fetch('/api/knowledge/documents', { method: 'POST', body: form })
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string }
      throw new ApiError(body.detail ?? `${res.status} ${res.statusText}`)
    }
    return res.json() as Promise<IngestResult>
  },
}
