import { defineComponent, h } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAgentDesk } from '../../src/composables/useAgentDesk'
import type { AgentEvent, DurableRun } from '../../src/types/agent'

const api = vi.hoisted(() => ({
  addCourseDocument: vi.fn(),
  cancelDurableRun: vi.fn(),
  createDurableRun: vi.fn(),
  createIdempotencyKey: vi.fn(),
  getDurableRun: vi.fn(),
  resolveDurableApproval: vi.fn(),
  streamDurableRun: vi.fn(),
}))

vi.mock('../../src/services/agentApi', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../src/services/agentApi')>(),
  ...api,
}))

const capability = 'capability-unit-test-12345678901234567890'
const runId = 'run-state-1'
const sessionId = 'session-state-1'
const wrappers: VueWrapper[] = []

beforeEach(() => {
  window.sessionStorage.clear()
  api.createIdempotencyKey.mockReturnValue(capability)
})

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  window.sessionStorage.clear()
  vi.useRealTimers()
})

describe('durable Run state machine', () => {
  it('ignores duplicate events while applying the strict next sequence', async () => {
    api.createDurableRun.mockResolvedValue(snapshot('queued'))
    api.getDurableRun.mockResolvedValue(snapshot('completed', { answer: 'done' }))
    api.streamDurableRun.mockImplementation(async (_run, _capability, _after, onEvent) => {
      onEvent(startedEvent(1))
      onEvent(startedEvent(1))
      onEvent(completedEvent(2))
      return 2
    })
    const desk = mountDesk()

    await desk.run()

    expect(desk.sequence.value).toBe(2)
    expect(desk.events.value.map((event) => event.type)).toEqual([
      'run.started',
      'run.completed',
    ])
    expect(desk.status.value).toBe('completed')
  })

  it('fails closed on a sequence gap without applying partial state', async () => {
    api.createDurableRun.mockResolvedValue(snapshot('queued'))
    api.getDurableRun.mockResolvedValue(snapshot('completed'))
    api.streamDurableRun.mockImplementation(async (_run, _capability, _after, onEvent) => {
      onEvent(completedEvent(2))
      return 2
    })
    const desk = mountDesk()

    await desk.run()

    expect(desk.sequence.value).toBe(0)
    expect(desk.events.value).toEqual([])
    expect(desk.error.value).toBe('事件序号不连续，已停止应用不完整状态')
  })

  it('reconnects from the last sequence after a transient disconnect', async () => {
    vi.useFakeTimers()
    api.createDurableRun.mockResolvedValue(snapshot('queued'))
    api.getDurableRun
      .mockResolvedValueOnce(snapshot('running'))
      .mockResolvedValueOnce(snapshot('completed', { answer: 'recovered' }))
    api.streamDurableRun
      .mockRejectedValueOnce(new Error('connection lost'))
      .mockImplementationOnce(async (_run, _capability, after, onEvent) => {
        expect(after).toBe(0)
        onEvent(startedEvent(1))
        onEvent(completedEvent(2))
        return 2
      })
    const desk = mountDesk()

    const runPromise = desk.run()
    await flushPromises()
    expect(desk.critique.value).toContain('正在从事件 #1 续传')
    await vi.advanceTimersByTimeAsync(250)
    await runPromise

    expect(api.streamDurableRun).toHaveBeenCalledTimes(2)
    expect(desk.status.value).toBe('completed')
    expect(desk.answer.value).toBe('recovered')
  })

  it('calls the durable cancel API instead of only aborting the stream', async () => {
    let releaseStream: ((sequence: number) => void) | undefined
    api.createDurableRun.mockResolvedValue(snapshot('queued'))
    api.streamDurableRun.mockImplementation(() => new Promise<number>((resolve) => {
      releaseStream = resolve
    }))
    api.cancelDurableRun.mockResolvedValue(snapshot('cancelled'))
    api.getDurableRun.mockResolvedValue(snapshot('cancelled'))
    const desk = mountDesk()

    const runPromise = desk.run()
    await flushPromises()
    await desk.cancel()

    expect(api.cancelDurableRun).toHaveBeenCalledWith(runId, capability)
    expect(desk.status.value).toBe('cancelled')
    releaseStream?.(0)
    await runPromise
  })

  it('submits only the persisted approval id and decision', async () => {
    let releaseStream: ((sequence: number) => void) | undefined
    api.createDurableRun.mockResolvedValue(snapshot('queued'))
    api.streamDurableRun.mockImplementation(async (_run, _capability, _after, onEvent) => {
      onEvent(waitingApprovalEvent(1))
      return new Promise<number>((resolve) => {
        releaseStream = resolve
      })
    })
    api.resolveDurableApproval.mockResolvedValue(snapshot('running'))
    api.getDurableRun.mockResolvedValue(snapshot('completed'))
    const desk = mountDesk()

    const runPromise = desk.run()
    await flushPromises()
    await desk.decideApproval('reject')

    expect(api.resolveDurableApproval).toHaveBeenCalledWith(
      runId,
      'approval-state-1',
      'reject',
      capability,
    )
    expect(desk.approval.value).toBeNull()
    releaseStream?.(1)
    await runPromise
  })

  it('restores a page from snapshot and resumes after the saved sequence', async () => {
    window.sessionStorage.setItem('ai-agent-demo:durable-run:v1', JSON.stringify({
      version: 1,
      runId,
      sessionId,
      capability,
      sequence: 3,
      status: 'running',
      approval: null,
    }))
    api.getDurableRun.mockResolvedValue(snapshot('completed', { answer: 'restored' }))
    api.streamDurableRun.mockImplementation(async (_run, _capability, after, onEvent) => {
      expect(after).toBe(3)
      onEvent(completedEvent(4))
      return 4
    })
    const desk = mountDesk()

    await desk.initialize()

    expect(api.getDurableRun).toHaveBeenCalledWith(runId, capability)
    expect(api.streamDurableRun).toHaveBeenCalledWith(
      runId,
      capability,
      3,
      expect.any(Function),
      expect.any(AbortSignal),
    )
    expect(desk.sequence.value).toBe(4)
    expect(desk.answer.value).toBe('restored')
    expect(desk.status.value).toBe('completed')
  })
})

function mountDesk(): ReturnType<typeof useAgentDesk> {
  let desk: ReturnType<typeof useAgentDesk> | undefined
  const wrapper = mount(defineComponent({
    setup() {
      desk = useAgentDesk()
      return () => h('div')
    },
  }))
  wrappers.push(wrapper)
  if (!desk) throw new Error('desk was not mounted')
  return desk
}

function snapshot(
  status: DurableRun['status'],
  overrides: Partial<DurableRun> = {},
): DurableRun {
  return {
    id: runId,
    run_id: runId,
    session_id: sessionId,
    status,
    answer: null,
    citations: [],
    usage: null,
    error: null,
    created_at: '2026-08-28T00:00:00Z',
    updated_at: '2026-08-28T00:00:00Z',
    started_at: null,
    finished_at: null,
    session_capability: capability,
    ...overrides,
  }
}

function startedEvent(sequence: number): AgentEvent {
  return event('run.started', sequence, { status: 'running', runtime: 'manual' })
}

function completedEvent(sequence: number): AgentEvent {
  return event('run.completed', sequence, { status: 'completed', answer: 'done' })
}

function waitingApprovalEvent(sequence: number): AgentEvent {
  return event('run.waiting_approval', sequence, {
    status: 'waiting_approval',
    approval_id: 'approval-state-1',
    tool_call_id: 'tool-call-state-1',
    tool_name: 'publish_report',
    expires_at: null,
  })
}

function event<TEvent extends AgentEvent['type']>(
  type: TEvent,
  sequence: number,
  data: Extract<AgentEvent, { type: TEvent }>['data']['data'],
): Extract<AgentEvent, { type: TEvent }> {
  return {
    type,
    data: {
      run_id: runId,
      sequence,
      step: sequence,
      created_at: '2026-08-28T00:00:00Z',
      data,
    },
    receivedAt: '2026-08-28T00:00:00Z',
  } as Extract<AgentEvent, { type: TEvent }>
}
