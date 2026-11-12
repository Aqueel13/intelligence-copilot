// Types and streaming client for investigations. Shapes mirror backend/investigation/graph.py.
import type { Answer, MetricResult, Scope, Unit } from './client'
import { apiFetch } from '../lib/domainStore'

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
  showcase: boolean
  replayable: boolean // recorded step by step, so it can be played back
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
  showcase: boolean
  replayable: boolean
}

export interface StartInfo {
  id: string
  models: Record<string, string>
  replay?: boolean // played back from a recording: no model calls
  cached?: boolean // …because an identical request was made before
  recorded_at?: string
}

export type StreamEvent =
  | { event: 'start'; data: StartInfo }
  | { event: 'step'; data: { node: string; update: InvestigationState } }
  | { event: 'done'; data: { id: string } }
  | { event: 'error'; data: { id?: string; message: string } }

/** Start an investigation (or get an identical earlier one replayed from the cache, unless
 * `fresh`) and read its Server-Sent Events. */
export function streamInvestigation(
  question: string,
  scope: Scope,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
  fresh = false,
): Promise<void> {
  return readEvents(
    apiFetch('/api/investigations/stream', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question, scope, fresh }),
      signal,
    }),
    onEvent,
  )
}

/** Play a recorded run back at a watchable pace (no model calls; open to every role). */
export function replayInvestigation(id: string, onEvent: (e: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
  return readEvents(apiFetch(`/api/investigations/${id}/replay`, { signal }), onEvent)
}

/** Read Server-Sent Events from a fetch response body (EventSource only supports GET). */
async function readEvents(request: Promise<Response>, onEvent: (e: StreamEvent) => void): Promise<void> {
  const res = await request
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
    const res = await apiFetch('/api/investigations')
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json() as Promise<InvestigationSummary[]>
  },
  showcase: async (): Promise<InvestigationSummary[]> => {
    const res = await apiFetch('/api/investigations?showcase=true')
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json() as Promise<InvestigationSummary[]>
  },
  setShowcase: async (id: string, showcase: boolean): Promise<void> => {
    const res = await apiFetch(`/api/investigations/${id}/showcase`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ showcase }),
    })
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string }
      throw new Error(body.detail ?? `${res.status} ${res.statusText}`)
    }
  },
  get: async (id: string): Promise<InvestigationRecord> => {
    const res = await apiFetch(`/api/investigations/${id}`)
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json() as Promise<InvestigationRecord>
  },
}

// ------------------------------------------------------------------ actions & governance

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
  apiFetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })

export const actionsApi = {
  list: () => apiFetch('/api/actions').then((r) => json<ActionRequest[]>(r)),
  get: (id: string) => apiFetch(`/api/actions/${id}`).then((r) => json<ActionRequest & { audit: AuditEntry[] }>(r)),
  propose: (b: { action_id: string; rationale?: string; investigation_id?: string | null }) =>
    send('/api/actions', b).then((r) => json<ActionRequest>(r)),
  decide: (id: string, b: { decision: 'approved' | 'rejected'; note?: string }) =>
    send(`/api/actions/${id}/decision`, b).then((r) => json<ActionRequest>(r)),
  execute: (id: string) => send(`/api/actions/${id}/execute`, {}).then((r) => json<ActionRequest>(r)),
  audit: () => apiFetch('/api/audit').then((r) => json<AuditEntry[]>(r)),
  verify: () => apiFetch('/api/audit/verify').then((r) => json<AuditVerification>(r)),
}

// ------------------------------------------------------------------ watch

export type MonitorStatus = 'ok' | 'warning' | 'critical' | 'insufficient_data'

export interface Evaluation {
  monitor_id: string
  title: string
  metric: string
  unit: Unit
  segment: string
  segment_label: string
  period: string
  value: number | null
  n: number
  status: MonitorStatus
  threshold: number | null
  warning: number
  critical: number
  direction: 'above' | 'below'
  critical_months: number
  message: string
  policy_ref: string | null
  question: string
  scope: Record<string, string[]>
  series: { period: string; value: number | null; n: number; status: MonitorStatus }[]
}

export interface Alert {
  alert_id: string
  monitor_id: string
  segment: string
  severity: 'warning' | 'critical'
  status: 'open' | 'acknowledged' | 'resolved'
  value: number
  threshold: number
  first_period: string
  last_period: string
  message: string
  opened_at: string
  updated_at: string
  acknowledged_by: string | null
  resolved_at: string | null
  investigation_id: string | null
  triage_status: 'running' | 'investigated' | 'reused' | 'skipped' | 'failed' | null
  triage_note: string | null
  triaged_at: string | null
}

export interface FollowUp {
  request_id: string
  action_id: string
  title: string
  metric: string
  unit: Unit
  target: number
  expect: 'below' | 'above'
  effective_month: string | null
  before: number | null
  after: number | null
  verdict: 'awaiting_data' | 'on_target' | 'improving' | 'no_change' | 'worse'
  message: string
}

export interface RunSummary {
  period: string | null
  evaluated: number
  opened: number
  updated: number
  resolved: number
  duration_ms: number
  evaluations: Evaluation[]
}

export interface WatchStatus {
  summary: RunSummary
  alerts: Alert[]
  follow_ups: FollowUp[]
  simulated_months: { month: string; claims: number; applied_actions: string[] }[]
  last_run: { started_at: string; trigger: string; period: string } | null
}

export const watchApi = {
  status: () => apiFetch('/api/watch').then((r) => json<WatchStatus>(r)),
  run: () => apiFetch('/api/watch/run', { method: 'POST' }).then((r) => json<RunSummary>(r)),
  simulate: () => apiFetch('/api/watch/simulate-month', { method: 'POST' }).then((r) => json<{ month: { month: string } }>(r)),
  acknowledge: (id: string) => send(`/api/watch/alerts/${id}/acknowledge`, {}).then((r) => json<Alert>(r)),
  link: (id: string, investigation_id: string) =>
    send(`/api/watch/alerts/${id}/investigation`, { investigation_id }).then((r) => json<Alert>(r)),
}
