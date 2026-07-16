import { computed, onUnmounted, ref, shallowRef } from 'vue'

import {
  addCourseDocument,
  ApiError,
  createSession,
  research,
  streamRun,
} from '../services/agentApi'
import type { AgentEvent, Evidence, RunStatus } from '../types/agent'

export function useAgentDesk() {
  const sessionId = shallowRef('')
  const sessionToken = shallowRef('')
  const question = ref('MCP 如何帮助 Agent 连接工具？')
  const answer = ref('')
  const critique = ref('等待运行')
  const status = ref<RunStatus>('idle')
  const error = ref('')
  const events = shallowRef<AgentEvent[]>([])
  const evidence = shallowRef<Evidence[]>([])
  const isKnowledgeReady = ref(false)
  const isPreparingKnowledge = ref(false)
  let controller: AbortController | null = null

  const canRun = computed(
    () => question.value.trim().length > 0 && !['connecting', 'running'].includes(status.value),
  )

  async function initialize(): Promise<void> {
    if (sessionId.value) return
    status.value = 'connecting'
    try {
      const session = await createSession()
      sessionId.value = session.id
      sessionToken.value = session.access_token ?? ''
      if (!sessionToken.value) {
        throw new Error('匿名会话没有返回访问令牌')
      }
      status.value = 'idle'
    } catch (reason: unknown) {
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
      if (status.value === 'failed') status.value = 'idle'
    } catch (reason: unknown) {
      fail(reason)
    } finally {
      isPreparingKnowledge.value = false
    }
  }

  async function run(): Promise<void> {
    if (!canRun.value) return
    if (!sessionId.value) await initialize()
    if (!sessionId.value) return

    controller = new AbortController()
    const activeQuestion = question.value.trim()
    status.value = 'running'
    error.value = ''
    answer.value = ''
    critique.value = '正在建立证据链'
    events.value = []
    evidence.value = []

    try {
      await streamRun(
        sessionId.value,
        sessionToken.value,
        activeQuestion,
        (event) => {
          events.value = [...events.value, event]
          if (event.type === 'run.completed') answer.value = event.data.answer ?? ''
          if (event.type === 'run.failed') throw new Error(event.data.error ?? '运行失败')
        },
        controller.signal,
      )
      const result = await research(activeQuestion, controller.signal)
      evidence.value = result.evidence
      critique.value = result.critique
      answer.value = result.answer
      status.value = 'completed'
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === 'AbortError') {
        status.value = 'idle'
        critique.value = '运行已由用户停止'
      } else {
        fail(reason)
      }
    } finally {
      controller = null
    }
  }

  function cancel(): void {
    controller?.abort()
  }

  function fail(reason: unknown): void {
    status.value = 'failed'
    error.value = reason instanceof ApiError || reason instanceof Error ? reason.message : '未知错误'
  }

  onUnmounted(cancel)

  return {
    answer,
    canRun,
    cancel,
    critique,
    error,
    events,
    evidence,
    initialize,
    isKnowledgeReady,
    isPreparingKnowledge,
    prepareKnowledge,
    question,
    run,
    sessionId,
    status,
  }
}
