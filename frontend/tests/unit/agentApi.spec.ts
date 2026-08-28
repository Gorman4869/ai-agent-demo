import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, parseFrame, streamDurableRun } from '../../src/services/agentApi'

const runId = 'run-unit-1'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('durable SSE parser', () => {
  it('parses one typed event and ignores comment-only frames', () => {
    expect(parseFrame(': keep-alive')).toBeNull()

    const event = parseFrame(frame('run.started', 1, {
      status: 'running',
      runtime: 'manual',
    }))

    expect(event).toMatchObject({
      type: 'run.started',
      data: {
        run_id: runId,
        sequence: 1,
        data: { status: 'running', runtime: 'manual' },
      },
    })
  })

  it('rejects invalid JSON and a mismatched SSE id', () => {
    expect(() => parseFrame('id: 1\nevent: run.started\ndata: {broken}'))
      .toThrow('事件流返回了无效 JSON')
    expect(() => parseFrame(frame('run.started', 1, {
      status: 'running',
      runtime: 'manual',
    }, 2))).toThrow('事件 ID 与业务序号不一致')
  })

  it('reassembles split CRLF chunks and multiple frames', async () => {
    const first = frame('run.started', 1, {
      status: 'running',
      runtime: 'manual',
    }).replaceAll('\n', '\r\n')
    const second = frame('run.completed', 2, {
      status: 'completed',
      answer: 'done',
    }).replaceAll('\n', '\r\n')
    const payload = `${first}\r\n\r\n${second}\r\n\r\n`
    const events: string[] = []
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
      payload.slice(0, 17),
      payload.slice(17, 71),
      payload.slice(71),
    ])))

    const lastSequence = await streamDurableRun(
      runId,
      'capability-unit-test-12345678901234567890',
      0,
      (event) => events.push(event.type),
    )

    expect(lastSequence).toBe(2)
    expect(events).toEqual(['run.started', 'run.completed'])
  })

  it('preserves AbortError when the caller disconnects', async () => {
    const controller = new AbortController()
    const body = new ReadableStream<Uint8Array>({
      start(streamController) {
        controller.signal.addEventListener('abort', () => {
          streamController.error(new DOMException('Aborted', 'AbortError'))
        }, { once: true })
      },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, {
      headers: { 'Content-Type': 'text/event-stream' },
    })))

    const result = streamDurableRun(runId, 'capability', 0, () => undefined, controller.signal)
    controller.abort()

    await expect(result).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('fails closed when a stream ends without a terminal event', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamResponse([
      `${frame('run.started', 1, { status: 'running', runtime: 'manual' })}\n\n`,
    ])))

    await expect(streamDurableRun(runId, 'capability', 0, () => undefined))
      .rejects.toEqual(expect.objectContaining<ApiError>({
        message: '事件流提前结束，未收到终止事件',
        status: 200,
      }))
  })

  it('rejects invalid business payloads instead of guessing usage', () => {
    expect(() => parseFrame(frame('model.usage', 1, {
      input_tokens: 2,
      output_tokens: 3,
      total_tokens: 6,
      estimated_cost_usd: null,
    }))).toThrow('事件流返回了无效的业务数据')
  })
})

function frame(
  type: string,
  sequence: number,
  data: Record<string, unknown>,
  eventId = sequence,
): string {
  return [
    `id: ${eventId}`,
    `event: ${type}`,
    `data: ${JSON.stringify({
      run_id: runId,
      sequence,
      step: sequence,
      created_at: '2026-08-28T00:00:00Z',
      data,
    })}`,
  ].join('\n')
}

function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
      controller.close()
    },
  }), {
    headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
  })
}
