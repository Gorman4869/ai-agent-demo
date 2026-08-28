import { computed, onUnmounted, ref, shallowRef } from 'vue'

import {
  addCourseDocument,
  ApiError,
  cancelDurableRun,
  createDurableRun,
  createIdempotencyKey,
  getDurableRun,
  resolveDurableApproval,
  streamDurableRun,
} from '../services/agentApi'
import {
  isTerminalRunStatus,
  type AgentEvent,
  type DurableRun,
  type DurableRunStatus,
  type Evidence,
  type ModelUsage,
  type PendingApproval,
  type RunStatus,
} from '../types/agent'

const recoveryStorageKey = 'ai-agent-demo:durable-run:v1'
const maxReconnectAttempts = 3

interface RecoveryState {
  version: 1
  runId: string
  sessionId: string
  capability: string
  sequence: number
  status: DurableRunStatus
  approval: PendingApproval | null
}

export function useAgentDesk() {
  const runId = shallowRef('')
  const sessionId = shallowRef('')
  const capability = shallowRef('')
  const sequence = ref(0)
  const question = ref('MCP 如何帮助 Agent 连接工具？')
  const answer = ref('')
  const critique = ref('等待运行')
  const status = ref<RunStatus>('idle')
  const error = ref('')
  const events = shallowRef<AgentEvent[]>([])
  const evidence = shallowRef<Evidence[]>([])
  const usage = shallowRef<ModelUsage | null>(null)
  const approval = shallowRef<PendingApproval | null>(null)
  const isKnowledgeReady = ref(false)
  const isPreparingKnowledge = ref(false)
  const isResolvingApproval = ref(false)
  const isCancelling = ref(false)
  let streamController: AbortController | null = null
  let outputSegment: number | null = null

  const canRun = computed(
    () => question.value.trim().length > 0
      && !['connecting', 'queued', 'running', 'waiting_approval'].includes(status.value),
  )
  const canCancel = computed(
    () => ['queued', 'running', 'waiting_approval'].includes(status.value) && !isCancelling.value,
  )

  async function initialize(): Promise<void> {
    const recovered = loadRecovery()
    if (!recovered) return
    restoreRecovery(recovered)
    const recoveredStatus = recovered.status
    const hadTerminalEvent = isTerminalRunStatus(recovered.status)
    status.value = 'connecting'
    critique.value = '正在恢复上次运行'
    try {
      const snapshot = await getDurableRun(runId.value, capability.value)
      applySnapshot(snapshot)
      if (!isTerminalRunStatus(snapshot.status) || !hadTerminalEvent) {
        await followRun()
      }
    } catch (reason: unknown) {
      if (reason instanceof ApiError && (reason.status === 401 || reason.status === 404)) {
        clearRecovery()
        resetRunState()
        return
      }
      status.value = recoveredStatus
      fail(reason)
    }
  }

  async function prepareKnowledge(): Promise<void> {
    if (isPreparingKnowledge.value || isKnowledgeReady.value) return
    isPreparingKnowledge.value = true
    error.value = ''
    try {
      await addCourseDocument()
      isKnowledgeReady.value = true
      if (status.value === 'failed' && !runId.value) status.value = 'idle'
    } catch (reason: unknown) {
      fail(reason)
    } finally {
      isPreparingKnowledge.value = false
    }
  }

  async function run(): Promise<void> {
    if (!canRun.value) return
    disconnectStream()
    resetPresentation()
    status.value = 'connecting'
    critique.value = '正在创建持久 Run'
    const activeQuestion = question.value.trim()
    const idempotencyKey = createIdempotencyKey()
    runId.value = ''
    sequence.value = 0

    try {
      const snapshot = await createDurableRun(
        activeQuestion,
        sessionId.value,
        capability.value,
        idempotencyKey,
      )
      runId.value = snapshot.run_id
      sessionId.value = snapshot.session_id
      capability.value = snapshot.session_capability ?? (capability.value || idempotencyKey)
      sequence.value = 0
      applySnapshot(snapshot)
      saveRecovery()
      await followRun()
    } catch (reason: unknown) {
      if (!isAbortError(reason)) fail(reason)
    }
  }

  async function followRun(): Promise<void> {
    if (!runId.value || !capability.value) return
    disconnectStream()
    streamController = new AbortController()
    const signal = streamController.signal
    let reconnectAttempts = 0

    try {
      while (!signal.aborted) {
        try {
          await streamDurableRun(
            runId.value,
            capability.value,
            sequence.value,
            applyEvent,
            signal,
          )
          const snapshot = await getDurableRun(runId.value, capability.value)
          applySnapshot(snapshot)
          return
        } catch (reason: unknown) {
          if (isAbortError(reason)) return
          const snapshot = await getDurableRun(runId.value, capability.value)
          applySnapshot(snapshot)
          if (isTerminalRunStatus(snapshot.status)) {
            await streamDurableRun(
              runId.value,
              capability.value,
              sequence.value,
              applyEvent,
              signal,
            )
            applySnapshot(await getDurableRun(runId.value, capability.value))
            return
          }
          reconnectAttempts += 1
          if (reconnectAttempts > maxReconnectAttempts) throw reason
          critique.value = `连接中断，正在从事件 #${sequence.value + 1} 续传`
          await waitForReconnect(reconnectAttempts, signal)
        }
      }
    } catch (reason: unknown) {
      if (!isAbortError(reason)) fail(reason)
    } finally {
      if (streamController?.signal === signal) streamController = null
    }
  }

  async function cancel(): Promise<void> {
    if (!canCancel.value || !runId.value || !capability.value) return
    isCancelling.value = true
    error.value = ''
    try {
      const hadActiveStream = Boolean(streamController)
      const snapshot = await cancelDurableRun(runId.value, capability.value)
      applySnapshot(snapshot)
      if (!hadActiveStream) await followRun()
    } catch (reason: unknown) {
      fail(reason)
    } finally {
      isCancelling.value = false
    }
  }

  async function decideApproval(decision: 'approve' | 'reject'): Promise<void> {
    const pending = approval.value
    if (!pending || !runId.value || !capability.value || isResolvingApproval.value) return
    isResolvingApproval.value = true
    error.value = ''
    try {
      const snapshot = await resolveDurableApproval(
        runId.value,
        pending.approvalId,
        decision,
        capability.value,
      )
      approval.value = null
      applySnapshot(snapshot)
      saveRecovery()
      if (!streamController && !isTerminalRunStatus(snapshot.status)) {
        await followRun()
      }
    } catch (reason: unknown) {
      fail(reason)
    } finally {
      isResolvingApproval.value = false
    }
  }

  function applyEvent(event: AgentEvent): void {
    if (event.data.run_id !== runId.value || event.data.sequence <= sequence.value) return
    if (event.data.sequence !== sequence.value + 1) {
      throw new Error('事件序号不连续，已停止应用不完整状态')
    }
    sequence.value = event.data.sequence
    events.value = [...events.value, event]
    if (event.type === 'run.started' || event.type === 'run.resumed') {
      status.value = 'running'
      approval.value = null
      critique.value = '正在执行同一持久 Run'
    } else if (event.type === 'run.waiting_approval') {
      status.value = 'waiting_approval'
      approval.value = {
        approvalId: event.data.data.approval_id,
        toolName: event.data.data.tool_name,
        expiresAt: event.data.data.expires_at,
      }
      critique.value = `工具 ${event.data.data.tool_name} 等待审批`
    } else if (event.type === 'model.output.delta') {
      applyOutputDelta(event.data.data.delta, event.data.data.segment)
    } else if (event.type === 'rag.citations') {
      evidence.value = event.data.data.citations
    } else if (event.type === 'model.usage') {
      usage.value = event.data.data
    } else if (event.type === 'run.completed') {
      status.value = 'completed'
      critique.value = '回答、引用与用量来自同一 Run'
    } else if (event.type === 'run.failed') {
      status.value = 'failed'
      error.value = event.data.data.failure_code ?? '运行失败'
      critique.value = '运行已安全终止'
    } else if (event.type === 'run.cancelled') {
      status.value = 'cancelled'
      critique.value = '运行已取消'
    }
    saveRecovery()
  }

  function applySnapshot(snapshot: DurableRun): void {
    if (runId.value && snapshot.run_id !== runId.value) {
      throw new Error('Run 快照与当前恢复记录不一致')
    }
    runId.value = snapshot.run_id
    sessionId.value = snapshot.session_id
    status.value = snapshot.status
    answer.value = snapshot.answer ?? answer.value
    evidence.value = snapshot.citations
    usage.value = snapshot.usage
    error.value = snapshot.error?.code ?? ''
    if (snapshot.status !== 'waiting_approval') approval.value = null
    if (snapshot.status === 'queued') critique.value = 'Run 已创建，等待执行'
    if (snapshot.status === 'running') critique.value = '正在执行同一持久 Run'
    if (snapshot.status === 'waiting_approval') {
      critique.value = approval.value
        ? `工具 ${approval.value.toolName} 等待审批`
        : '正在恢复待审批工具信息'
    }
    if (snapshot.status === 'completed') critique.value = '回答、引用与用量来自同一 Run'
    if (snapshot.status === 'failed') critique.value = '运行已安全终止'
    if (snapshot.status === 'cancelled') critique.value = '运行已取消'
    saveRecovery()
  }

  function applyOutputDelta(delta: string, segment?: number): void {
    if (segment !== undefined && segment !== outputSegment) {
      outputSegment = segment
      answer.value = delta
      return
    }
    answer.value += delta
  }

  function resetPresentation(): void {
    error.value = ''
    answer.value = ''
    critique.value = '正在建立证据链'
    events.value = []
    evidence.value = []
    usage.value = null
    approval.value = null
    outputSegment = null
  }

  function resetRunState(): void {
    disconnectStream()
    runId.value = ''
    sessionId.value = ''
    capability.value = ''
    sequence.value = 0
    status.value = 'idle'
    resetPresentation()
    critique.value = '等待运行'
  }

  function restoreRecovery(recovered: RecoveryState): void {
    runId.value = recovered.runId
    sessionId.value = recovered.sessionId
    capability.value = recovered.capability
    sequence.value = recovered.sequence
    approval.value = recovered.approval
    status.value = recovered.status
  }

  function saveRecovery(): void {
    if (
      !runId.value
      || !sessionId.value
      || !capability.value
      || status.value === 'idle'
      || status.value === 'connecting'
    ) return
    const recovery: RecoveryState = {
      version: 1,
      runId: runId.value,
      sessionId: sessionId.value,
      capability: capability.value,
      sequence: sequence.value,
      status: status.value,
      approval: approval.value,
    }
    try {
      window.sessionStorage.setItem(recoveryStorageKey, JSON.stringify(recovery))
    } catch {
      error.value = '浏览器无法保存刷新恢复状态；当前 Run 仍会继续执行'
    }
  }

  function loadRecovery(): RecoveryState | null {
    try {
      const raw = window.sessionStorage.getItem(recoveryStorageKey)
      if (!raw) return null
      const value: unknown = JSON.parse(raw)
      if (!isRecoveryState(value)) throw new Error('invalid recovery state')
      return value
    } catch {
      clearRecovery()
      return null
    }
  }

  function clearRecovery(): void {
    try {
      window.sessionStorage.removeItem(recoveryStorageKey)
    } catch {
      return
    }
  }

  function disconnectStream(): void {
    streamController?.abort()
    streamController = null
  }

  function fail(reason: unknown): void {
    if (!runId.value) status.value = 'failed'
    error.value = reason instanceof ApiError || reason instanceof Error ? reason.message : '未知错误'
  }

  onUnmounted(disconnectStream)

  return {
    answer,
    approval,
    canCancel,
    canRun,
    cancel,
    critique,
    decideApproval,
    error,
    events,
    evidence,
    initialize,
    isCancelling,
    isKnowledgeReady,
    isPreparingKnowledge,
    isResolvingApproval,
    prepareKnowledge,
    question,
    run,
    runId,
    sequence,
    sessionId,
    status,
    usage,
  }
}

function isRecoveryState(value: unknown): value is RecoveryState {
  if (typeof value !== 'object' || value === null) return false
  const record = value as Record<string, unknown>
  return record.version === 1
    && typeof record.runId === 'string'
    && Boolean(record.runId)
    && typeof record.sessionId === 'string'
    && Boolean(record.sessionId)
    && typeof record.capability === 'string'
    && record.capability.length >= 32
    && typeof record.sequence === 'number'
    && Number.isInteger(record.sequence)
    && record.sequence >= 0
    && isDurableStatus(record.status)
    && isPendingApproval(record.approval)
}

function isDurableStatus(value: unknown): value is DurableRunStatus {
  return value === 'queued'
    || value === 'running'
    || value === 'waiting_approval'
    || value === 'completed'
    || value === 'failed'
    || value === 'cancelled'
}

function isPendingApproval(value: unknown): value is PendingApproval | null {
  if (value === null) return true
  if (typeof value !== 'object' || value === null) return false
  const record = value as Record<string, unknown>
  return typeof record.approvalId === 'string'
    && Boolean(record.approvalId)
    && typeof record.toolName === 'string'
    && Boolean(record.toolName)
    && (record.expiresAt === null || typeof record.expiresAt === 'string')
}

function isAbortError(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === 'AbortError'
}

async function waitForReconnect(attempt: number, signal: AbortSignal): Promise<void> {
  const delayMs = Math.min(250 * 2 ** (attempt - 1), 1_000)
  await new Promise<void>((resolve, reject) => {
    const handleAbort = () => {
      window.clearTimeout(timeoutId)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    const timeoutId = window.setTimeout(() => {
      signal.removeEventListener('abort', handleAbort)
      resolve()
    }, delayMs)
    signal.addEventListener('abort', handleAbort, { once: true })
  })
}
