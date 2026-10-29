export type DurableRunStatus =
  | 'queued'
  | 'running'
  | 'waiting_approval'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type RunStatus = 'idle' | 'connecting' | DurableRunStatus

export interface Evidence {
  title: string
  source: string
  excerpt: string
  score: number
}

export interface ModelUsage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  estimated_cost_usd: number | null
}

export interface DurableRunError {
  code: string
  category: string
  retryable: boolean
}

export interface ReviewRunRequest {
  review_id: string
  expected_revision: number
  image_asset_id: string
  policy_topic: string
  page_fixture_id: string
  requested_decision: 'approve' | 'reject' | 'needs_review'
}

export interface ReviewEvidence {
  source_kind: 'image' | 'policy' | 'page'
  source_ref: string
  content_sha256: string
  content_bytes: number
  trust: string
  status: 'verified' | 'degraded'
  citation_refs: string[]
}

export interface ReviewSnapshot {
  scenario_version: 'multisource-review-v1'
  review_id: string
  outcome: 'in_progress' | 'waiting_approval' | 'published' | 'needs_attention' | 'failed'
  evidence: ReviewEvidence[]
  evidence_bundle_digest: string | null
  publication: { publication_id: string; revision: number; status: 'published' } | null
  usage: { provider: null; total_tokens: null; estimated_cost: null; currency: null; cost_source: 'unknown' }
}

export interface DurableRun {
  id: string
  run_id: string
  session_id: string
  status: DurableRunStatus
  answer: string | null
  citations: Evidence[]
  usage: ModelUsage | null
  review?: ReviewSnapshot | null
  error: DurableRunError | null
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
  session_capability: string | null
}

export interface PendingApproval {
  approvalId: string
  toolName: string
  expiresAt: string | null
}

export interface AgentEventEnvelope<TData> {
  run_id: string
  sequence: number
  step: number | null
  created_at: string
  data: TData
}

interface AgentEventBase<TType extends string, TData> {
  type: TType
  data: AgentEventEnvelope<TData>
  receivedAt: string
}

export type AgentEvent =
  | AgentEventBase<'run.started', { status: 'running'; runtime: string }>
  | AgentEventBase<'run.resumed', {
      status: 'running'
      approval_id: string
      decision: 'approved' | 'rejected' | 'expired'
    }>
  | AgentEventBase<'run.waiting_approval', {
      status: 'waiting_approval'
      approval_id: string
      tool_call_id: string
      tool_name: string
      expires_at: string | null
    }>
  | AgentEventBase<'run.completed', { status: 'completed'; answer?: string }>
  | AgentEventBase<'run.failed', {
      status: 'failed'
      failure_code?: string
      failure_category?: string
      retryable?: boolean
    }>
  | AgentEventBase<'run.cancelled', {
      status: 'cancelled'
      failure_code?: string
      failure_category?: string
      retryable?: boolean
    }>
  | AgentEventBase<'context.failed', { code: string }>
  | AgentEventBase<'rag.citations', { citations: Evidence[] }>
  | AgentEventBase<'review.evidence.recorded', ReviewEvidence & { review_id: string }>
  | AgentEventBase<'model.output.delta', { delta: string; segment?: number }>
  | AgentEventBase<'model.usage', ModelUsage>
  | AgentEventBase<'tool.started', { id: string; name: string }>
  | AgentEventBase<'tool.completed', { id: string; name: string; ok: boolean }>
  | AgentEventBase<'tool.failed', { id: string; name: string; ok: boolean; error_code?: string }>
  | AgentEventBase<'unknown', Record<string, unknown>> & { eventType: string }

export function isTerminalRunStatus(status: DurableRunStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'cancelled'
}
