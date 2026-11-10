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

// ------------------------------------------------------------------ actions & governance

export interface DemoUser {
  id: string
  name: string
  role: string
}

export type ActionStatus = 'proposed' | 'approved' | 'rejected' | 'executing' | 'executed' | 'failed'

export interface ActionRequest {
  request_id: string
  action_id: string
  title: string
  operation: { type: string; params: Record<string, unknown> }
  impact: (ActionImpact & { scope?: Scope }) | null
  policy_refs: string[]
  approver_roles: string[]
  approval_basis: string | null
  investigation_id: string | null
  rationale: string | null
  status: ActionStatus
  requested_by: string
  requested_via: string
  created_at: string
  decision: string | null
  decided_by: string | null
  decided_role: string | null
  decision_note: string | null
  decided_at: string | null
  executed_by: string | null
  executed_at: string | null
  result: Record<string, unknown> | null
  error: string | null
}

export interface AuditEntry {
  entry_id: number
  at: string
  actor: string
  actor_type: 'user' | 'agent' | 'mcp_client' | 'system'
  event: string
  request_id: string | null
  details: Record<string, unknown>
  prev_hash: string
  hash: string
}

export interface AuditVerification {
  ok: boolean
  entries: number
  first_broken_entry: number | null
  reason: string | null
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown }
    throw new Error(typeof body.detail === 'string' ? body.detail : `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

const send = (url: string, body: unknown) =>
  fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })

export const actionsApi = {
  users: () => fetch('/api/governance/users').then((r) => json<DemoUser[]>(r)),
  list: () => fetch('/api/actions').then((r) => json<ActionRequest[]>(r)),
  get: (id: string) => fetch(`/api/actions/${id}`).then((r) => json<ActionRequest & { audit: AuditEntry[] }>(r)),
  propose: (b: { action_id: string; user_id: string; rationale?: string; investigation_id?: string | null }) =>
    send('/api/actions', b).then((r) => json<ActionRequest>(r)),
  decide: (id: string, b: { user_id: string; decision: 'approved' | 'rejected'; note?: string }) =>
    send(`/api/actions/${id}/decision`, b).then((r) => json<ActionRequest>(r)),
  execute: (id: string, user_id: string) => send(`/api/actions/${id}/execute`, { user_id }).then((r) => json<ActionRequest>(r)),
  audit: () => fetch('/api/audit').then((r) => json<AuditEntry[]>(r)),
  verify: () => fetch('/api/audit/verify').then((r) => json<AuditVerification>(r)),
}
