import type {
  AgentEvent,
  AgentEventEnvelope,
  DurableRun,
  Evidence,
  ModelUsage,
} from '../types/agent'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

export async function addCourseDocument(): Promise<void> {
  await requestJson('/api/knowledge/demo-seed', {
    method: 'POST',
  })
}

export async function createDurableRun(
  message: string,
  sessionId: string,
  capability: string,
  idempotencyKey: string,
): Promise<DurableRun> {
  return requestJson<DurableRun>('/api/durable/runs', {
    method: 'POST',
    headers: durableHeaders(capability, { 'Idempotency-Key': idempotencyKey }),
    body: JSON.stringify({ message, session_id: sessionId || null }),
  })
}

export async function getDurableRun(runId: string, capability: string): Promise<DurableRun> {
  return requestJson<DurableRun>(`/api/durable/runs/${encodeURIComponent(runId)}`, {
    headers: durableHeaders(capability),
  })
}

export async function cancelDurableRun(runId: string, capability: string): Promise<DurableRun> {
  return requestJson<DurableRun>(`/api/durable/runs/${encodeURIComponent(runId)}/cancel`, {
    method: 'POST',
    headers: durableHeaders(capability),
  })
}

export async function resolveDurableApproval(
  runId: string,
  approvalId: string,
  decision: 'approve' | 'reject',
  capability: string,
): Promise<DurableRun> {
  return requestJson<DurableRun>(
    `/api/durable/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}`,
    {
      method: 'POST',
      headers: durableHeaders(capability),
      body: JSON.stringify({ decision }),
    },
  )
}

export async function streamDurableRun(
  runId: string,
  capability: string,
  afterSequence: number,
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<number> {
  const response = await fetch(
    `/api/durable/runs/${encodeURIComponent(runId)}/events?after=${afterSequence}`,
    {
      headers: durableHeaders(capability),
      signal,
    },
  )
  if (!response.ok) {
    throw await toApiError(response)
  }
  if (!response.body) {
    throw new ApiError('浏览器没有返回可读取的事件流', response.status)
  }
  if (!response.headers.get('content-type')?.includes('text/event-stream')) {
    throw new ApiError('服务端没有返回事件流协议', response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let hasTerminalEvent = false
  let lastSequence = afterSequence

  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      buffer = buffer.replaceAll('\r\n', '\n')
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const event = parseFrame(frame)
        if (!event) continue
        lastSequence = event.data.sequence
        if (isTerminalEvent(event)) {
          hasTerminalEvent = true
        }
        onEvent(event)
      }
      if (done) {
        const event = parseFrame(buffer)
        if (event) {
          lastSequence = event.data.sequence
          if (isTerminalEvent(event)) {
            hasTerminalEvent = true
          }
          onEvent(event)
        }
        break
      }
    }
  } catch (reason: unknown) {
    await reader.cancel(reason).catch(() => undefined)
    throw reason
  } finally {
    reader.releaseLock()
  }

  if (!hasTerminalEvent) {
    throw new ApiError('事件流提前结束，未收到终止事件', response.status)
  }
  return lastSequence
}

export function parseFrame(frame: string): AgentEvent | null {
  if (!frame.trim()) return null
  let type = 'message'
  let eventId: number | null = null
  const dataLines: string[] = []
  frame.split('\n').forEach((line) => {
    if (line.startsWith(':')) return
    if (line.startsWith('id:')) {
      const rawId = line.slice(3).trim()
      if (!/^\d+$/.test(rawId)) throw new Error('事件流返回了无效的事件 ID')
      eventId = Number(rawId)
    } else if (line.startsWith('event:')) {
      type = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  })
  if (dataLines.length === 0) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(dataLines.join('\n'))
  } catch {
    throw new Error('事件流返回了无效 JSON')
  }
  const envelope = parseEnvelope(parsed)
  if (eventId === null || eventId !== envelope.sequence) {
    throw new Error('事件 ID 与业务序号不一致')
  }
  return createAgentEvent(type, envelope)
}

export function createIdempotencyKey(): string {
  return crypto.randomUUID()
}

function durableHeaders(
  capability: string,
  extra: Record<string, string> = {},
): Record<string, string> {
  return capability
    ? { ...extra, 'X-Session-Token': capability }
    : extra
}

function parseEnvelope(value: unknown): AgentEventEnvelope<Record<string, unknown>> {
  if (!isRecord(value) || !isRecord(value.data)) {
    throw new Error('事件流返回了无效的数据结构')
  }
  if (
    typeof value.run_id !== 'string'
    || !Number.isInteger(value.sequence)
    || typeof value.sequence !== 'number'
    || value.sequence < 1
    || (value.step !== null && (!Number.isInteger(value.step) || typeof value.step !== 'number'))
    || typeof value.created_at !== 'string'
  ) {
    throw new Error('事件流返回了无效的事件标识')
  }
  return {
    run_id: value.run_id,
    sequence: value.sequence,
    step: value.step,
    created_at: value.created_at,
    data: value.data,
  }
}

function createAgentEvent(
  type: string,
  envelope: AgentEventEnvelope<Record<string, unknown>>,
): AgentEvent {
  const receivedAt = new Date().toISOString()
  const data = envelope.data
  const withData = <TData>(nextData: TData): AgentEventEnvelope<TData> => ({
    ...envelope,
    data: nextData,
  })

  switch (type) {
    case 'run.started':
      return { type, data: withData({ status: 'running', runtime: requiredString(data.runtime) }), receivedAt }
    case 'run.resumed': {
      const decision = data.decision
      if (decision !== 'approved' && decision !== 'rejected' && decision !== 'expired') {
        throw invalidEvent()
      }
      return {
        type,
        data: withData({ status: 'running', approval_id: requiredString(data.approval_id), decision }),
        receivedAt,
      }
    }
    case 'run.waiting_approval':
      return {
        type,
        data: withData({
          status: 'waiting_approval',
          approval_id: requiredString(data.approval_id),
          tool_call_id: requiredString(data.tool_call_id),
          tool_name: requiredString(data.tool_name),
          expires_at: nullableString(data.expires_at),
        }),
        receivedAt,
      }
    case 'run.completed':
      return {
        type,
        data: withData({ status: 'completed', ...optionalStringField(data, 'answer') }),
        receivedAt,
      }
    case 'run.failed':
      return {
        type,
        data: withData({
          status: 'failed',
          ...optionalStringField(data, 'failure_code'),
          ...optionalStringField(data, 'failure_category'),
          ...optionalBooleanField(data, 'retryable'),
        }),
        receivedAt,
      }
    case 'run.cancelled':
      return {
        type,
        data: withData({
          status: 'cancelled',
          ...optionalStringField(data, 'failure_code'),
          ...optionalStringField(data, 'failure_category'),
          ...optionalBooleanField(data, 'retryable'),
        }),
        receivedAt,
      }
    case 'context.failed':
      return { type, data: withData({ code: requiredString(data.code) }), receivedAt }
    case 'rag.citations':
      return { type, data: withData({ citations: parseEvidence(data.citations) }), receivedAt }
    case 'model.output.delta': {
      const segment = data.segment
      if (segment !== undefined && (!Number.isInteger(segment) || typeof segment !== 'number')) {
        throw invalidEvent()
      }
      return {
        type,
        data: withData({ delta: requiredString(data.delta), ...(segment === undefined ? {} : { segment }) }),
        receivedAt,
      }
    }
    case 'model.usage':
      return { type, data: withData(parseUsage(data)), receivedAt }
    case 'tool.started':
      return {
        type,
        data: withData({ id: requiredString(data.id), name: requiredString(data.name) }),
        receivedAt,
      }
    case 'tool.completed':
    case 'tool.failed':
      return {
        type,
        data: withData({
          id: requiredString(data.id),
          name: requiredString(data.name),
          ok: requiredBoolean(data.ok),
          ...(type === 'tool.failed' ? optionalStringField(data, 'error_code') : {}),
        }),
        receivedAt,
      }
    default:
      return { type: 'unknown', eventType: type, data: envelope, receivedAt }
  }
}

function parseEvidence(value: unknown): Evidence[] {
  if (!Array.isArray(value)) throw invalidEvent()
  return value.map((item) => {
    if (!isRecord(item) || typeof item.score !== 'number' || !Number.isFinite(item.score)) {
      throw invalidEvent()
    }
    return {
      title: requiredString(item.title),
      source: requiredString(item.source),
      excerpt: requiredString(item.excerpt),
      score: item.score,
    }
  })
}

function parseUsage(value: Record<string, unknown>): ModelUsage {
  const inputTokens = requiredNonNegativeInteger(value.input_tokens)
  const outputTokens = requiredNonNegativeInteger(value.output_tokens)
  const totalTokens = requiredNonNegativeInteger(value.total_tokens)
  if (totalTokens === 0 || totalTokens !== inputTokens + outputTokens) throw invalidEvent()
  const rawCost = value.estimated_cost_usd
  if (rawCost !== null && rawCost !== undefined && (typeof rawCost !== 'number' || !Number.isFinite(rawCost) || rawCost < 0)) {
    throw invalidEvent()
  }
  return {
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    total_tokens: totalTokens,
    estimated_cost_usd: typeof rawCost === 'number' ? rawCost : null,
  }
}

function isTerminalEvent(event: AgentEvent): boolean {
  return event.type === 'run.completed' || event.type === 'run.failed' || event.type === 'run.cancelled'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function requiredString(value: unknown): string {
  if (typeof value !== 'string' || !value) throw invalidEvent()
  return value
}

function nullableString(value: unknown): string | null {
  if (value === null) return null
  return requiredString(value)
}

function requiredBoolean(value: unknown): boolean {
  if (typeof value !== 'boolean') throw invalidEvent()
  return value
}

function requiredNonNegativeInteger(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) throw invalidEvent()
  return value
}

function optionalStringField<TName extends string>(
  record: Record<string, unknown>,
  name: TName,
): Partial<Record<TName, string>> {
  const value = record[name]
  return value === undefined ? {} : { [name]: requiredString(value) } as Record<TName, string>
}

function optionalBooleanField<TName extends string>(
  record: Record<string, unknown>,
  name: TName,
): Partial<Record<TName, boolean>> {
  const value = record[name]
  return value === undefined ? {} : { [name]: requiredBoolean(value) } as Record<TName, boolean>
}

function invalidEvent(): Error {
  return new Error('事件流返回了无效的业务数据')
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    throw await toApiError(response)
  }
  return response.json() as Promise<T>
}

async function toApiError(response: Response): Promise<ApiError> {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null
  return new ApiError(formatDetail(body?.detail) ?? `请求失败：${response.status}`, response.status)
}

function formatDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (!Array.isArray(detail)) return null
  const messages = detail.flatMap((item) => {
    if (typeof item !== 'object' || item === null || !('msg' in item)) return []
    return typeof item.msg === 'string' ? [item.msg] : []
  })
  return messages.length > 0 ? messages.join('；') : null
}
