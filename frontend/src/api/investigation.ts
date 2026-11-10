// Types and streaming client for investigations. Shapes mirror backend/investigation/graph.py.
import type { Answer, MetricResult, Scope } from './client'

export type Verdict = 'supported' | 'refuted' | 'inconclusive'

export interface Signal {
  id: string
  kind: 'segment' | 'bottleneck' | 'weekday' | 'trend'
  statement: string
  strength: number
}

export interface Overview {
  cases: number
  breach_rate: number
  breaches: number
  mean_cycle_days: number
  sla_days: number
  months: number
}

export interface StratifiedComparison {
  control: string
  raw_difference: number
  adjusted_difference: number | null
  explained_by_control: boolean
  note: string
}

export interface PolicyExcerpt {
  doc_key: string
  title: string
  version: string
  section: string
  content: string
}

export interface EvidenceItem {
  check: { type: string; [k: string]: unknown }
  ok: boolean
  summary: string
  confounders: StratifiedComparison[]
  policy: PolicyExcerpt[]
  auto: boolean
}

export interface Hypothesis {
  id: string
  statement: string
  auto: boolean
  evidence: EvidenceItem[]
  dropped_checks: string[]
  verdict: Verdict | null
  confidence: string | null
  reasoning: string | null
  model_verdict: string | null
  override: string | null
}

export interface ActionImpact {
  breaches_now: number
  breaches_avoided: number
  breach_rate_now: number
  breach_rate_after: number
  annual_breaches_avoided: number
  annual_benefit_inr: number
  annual_cost_inr: number
  annual_net_inr: number
  affected_claims: number
  cost_basis: string
  assumptions: Record<string, number>
  method: string
}

export interface PolicyClause {
  ref: string
  doc_key: string
  title: string
  version: string
  section: string
  text: string
}

export interface Recommendation {
  action_id: string
  title: string
  description: string
  effort: string
  hypothesis_ids: string[]
  rationale: string
  impact: ActionImpact
  policy: PolicyClause[]
  recommended: boolean
  cost_effective: boolean
}

export interface Step {
  node: string
  ms: number
  model: string | null
  note: string | null
}

export interface InvestigationState {
  route?: 'investigation' | 'metric' | 'policy'
  overview?: Overview
  signals?: Signal[]
  hypotheses?: Hypothesis[]
  recommendations?: Recommendation[]
  summary?: string
  number_check?: { numbers_found: number; unverified: string[] }
  answer?: Answer | null
  metric_answer?: (MetricResult & { error?: string }) | null
  steps?: Step[]
}

export interface InvestigationSummary {
  investigation_id: string
  question: string
  status: 'running' | 'completed' | 'failed'
  route: string | null
  models: Record<string, string>
  created_at: string
  duration_ms: number | null
  error: string | null
  supported: number
}

export interface InvestigationRecord {
  investigation_id: string
  question: string
  scope: Scope
  status: string
  models: Record<string, string>
  result: InvestigationState | null
  error: string | null
  duration_ms: number | null
  created_at: string
}

export type StreamEvent =
  | { event: 'start'; data: { id: string; models: Record<string, string> } }
  | { event: 'step'; data: { node: string; update: InvestigationState } }
  | { event: 'done'; data: { id: string } }
  | { event: 'error'; data: { id?: string; message: string } }

/** POST + read Server-Sent Events from the response body (EventSource only supports GET). */
export async function streamInvestigation(
  question: string,
  scope: Scope,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch('/api/investigations/stream', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question, scope }),
    signal,
  })
  if (!res.ok || !res.body) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string }
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const event = /^event: (.+)$/m.exec(block)?.[1]
      const data = /^data: (.+)$/m.exec(block)?.[1]
      if (event && data) onEvent({ event, data: JSON.parse(data) } as StreamEvent)
    }
  }
}

export const investigationsApi = {
  recent: async (): Promise<InvestigationSummary[]> => {
    const res = await fetch('/api/investigations')
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json() as Promise<InvestigationSummary[]>
  },
  get: async (id: string): Promise<InvestigationRecord> => {
    const res = await fetch(`/api/investigations/${id}`)
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json() as Promise<InvestigationRecord>
  },
}
