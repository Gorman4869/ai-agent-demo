import type { AgentEvent, ResearchResult } from '../types/agent'

interface SessionResponse {
  id: string
  created_at: string
  access_token: string | null
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

export async function createSession(): Promise<SessionResponse> {
  return requestJson<SessionResponse>('/api/sessions', { method: 'POST' })
}

export async function addCourseDocument(): Promise<void> {
  await requestJson('/api/knowledge/demo-seed', {
    method: 'POST',
  })
}

export async function research(question: string, signal?: AbortSignal): Promise<ResearchResult> {
  return requestJson<ResearchResult>('/api/research', {
    method: 'POST',
    body: JSON.stringify({ question }),
    signal,
  })
}

export async function streamRun(
  sessionId: string,
  sessionToken: string,
  message: string,
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/sessions/${sessionId}/runs/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Session-Token': sessionToken,
    },
    body: JSON.stringify({ message }),
    signal,
  })
  if (!response.ok) {
    throw await toApiError(response)
  }
  if (!response.body) {
    throw new ApiError('浏览器没有返回可读取的事件流', response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let hasTerminalEvent = false

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
        if (event.type === 'run.completed' || event.type === 'run.failed') {
          hasTerminalEvent = true
        }
        onEvent(event)
      }
      if (done) {
        const event = parseFrame(buffer)
        if (event) {
          if (event.type === 'run.completed' || event.type === 'run.failed') {
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
}

function parseFrame(frame: string): AgentEvent | null {
  if (!frame.trim()) return null
  let type = 'message'
  const dataLines: string[] = []
  frame.split('\n').forEach((line) => {
    if (line.startsWith(':')) return
    if (line.startsWith('event:')) {
      type = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  })
  if (dataLines.length === 0) return null
  const data = JSON.parse(dataLines.join('\n')) as AgentEvent['data']
  return { type, data, receivedAt: new Date().toISOString() }
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
