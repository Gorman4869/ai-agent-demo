<script setup lang="ts">
import type { AgentEvent } from '../types/agent'

defineProps<{ events: AgentEvent[] }>()

const eventLabels: Record<string, string> = {
  'run.started': '运行已启动',
  'tool.started': '工具开始执行',
  'tool.completed': '工具执行完成',
  'tool.failed': '工具执行失败',
  'run.completed': '答案已完成',
  'run.failed': '运行失败',
}
</script>

<template>
  <ol class="timeline" aria-label="Agent 运行事件" aria-live="polite">
    <li v-if="events.length === 0" class="timeline__empty">事件流将在这里留下可审计足迹。</li>
    <li v-for="event in events" :key="`${event.data.run_id}-${event.data.index}`" class="timeline__item">
      <span class="timeline__marker" aria-hidden="true"></span>
      <div>
        <strong>{{ eventLabels[event.type] ?? event.type }}</strong>
        <small>#{{ event.data.index + 1 }} · {{ new Date(event.receivedAt).toLocaleTimeString() }}</small>
      </div>
    </li>
  </ol>
</template>

<style scoped>
.timeline { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }
.timeline__item { position: relative; display: grid; grid-template-columns: 20px 1fr; gap: 10px; min-height: 58px; color: var(--ink-soft); }
.timeline__item:not(:last-child)::before { content: ''; position: absolute; left: 6px; top: 17px; bottom: -2px; width: 1px; background: var(--line-dark); }
.timeline__marker { width: 13px; height: 13px; margin-top: 3px; border: 3px solid var(--signal); border-radius: 50%; background: var(--night); box-shadow: 0 0 0 4px rgb(255 111 41 / 10%); }
.timeline strong { display: block; color: var(--paper); font-size: .88rem; font-weight: 650; }
.timeline small { display: block; margin-top: 4px; color: var(--muted); font: .7rem var(--font-mono); }
.timeline__empty { padding: 18px; border: 1px dashed var(--line-dark); color: var(--muted); font-size: .85rem; line-height: 1.6; }
</style>
