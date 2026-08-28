<script setup lang="ts">
import { onMounted } from 'vue'

import RunTimeline from './components/RunTimeline.vue'
import { useAgentDesk } from './composables/useAgentDesk'

const desk = useAgentDesk()

onMounted(desk.initialize)
</script>

<template>
  <main class="desk-shell">
    <header class="masthead">
      <div>
        <p class="eyebrow">FIELD NOTE / 04</p>
        <h1>Agent Research Desk</h1>
      </div>
      <div class="connection" :data-status="desk.status.value" role="status" aria-live="polite">
        <span></span>
        {{ desk.status.value }}
      </div>
    </header>

    <section class="desk-grid">
      <aside class="control-rail">
        <div class="rail-heading">
          <span>CONTROL</span>
          <span>01</span>
        </div>
        <p class="rail-copy">先让执行过程可见，再判断答案是否可信。</p>

        <dl class="facts">
          <div><dt>SESSION</dt><dd>{{ desk.sessionId.value.slice(0, 8) || 'connecting' }}</dd></div>
          <div><dt>RUN</dt><dd>{{ desk.runId.value.slice(0, 8) || 'not started' }}</dd></div>
          <div><dt>SEQUENCE</dt><dd>{{ desk.sequence.value }}</dd></div>
          <div><dt>EVENTS</dt><dd>{{ desk.events.value.length }}</dd></div>
          <div><dt>SOURCES</dt><dd>{{ desk.evidence.value.length }}</dd></div>
        </dl>

        <button
          class="knowledge-button"
          :disabled="desk.isKnowledgeReady.value || desk.isPreparingKnowledge.value"
          :aria-busy="desk.isPreparingKnowledge.value"
          @click="desk.prepareKnowledge"
        >
          {{ desk.isPreparingKnowledge.value ? '正在装载…' : desk.isKnowledgeReady.value ? '课程资料已装载' : '装载课程资料' }}
        </button>
        <p class="microcopy">Mock 模式 · 不调用真实模型 · 不产生 API 费用</p>
      </aside>

      <section class="paper-panel">
        <div class="panel-index">RESEARCH QUERY / 02</div>
        <label for="question">你想核验什么？</label>
        <textarea
          id="question"
          v-model="desk.question.value"
          rows="4"
          maxlength="4000"
          :disabled="!desk.canRun.value"
        ></textarea>
        <div class="prompt-actions">
          <span>{{ desk.question.value.length }} / 4000</span>
          <button
            v-if="desk.canCancel.value"
            class="button button--ghost"
            :disabled="desk.isCancelling.value"
            @click="desk.cancel"
          >
            {{ desk.isCancelling.value ? '正在停止…' : '停止' }}
          </button>
          <button v-else class="button" :disabled="!desk.canRun.value" @click="desk.run">
            启动研究 <span>↗</span>
          </button>
        </div>

        <p v-if="desk.error.value" class="error-note" role="alert">{{ desk.error.value }}</p>

        <section v-if="desk.approval.value" class="approval-card" aria-live="assertive">
          <div>
            <strong>工具操作等待审批</strong>
            <p>{{ desk.approval.value.toolName }}</p>
          </div>
          <div class="approval-actions">
            <button
              class="button button--ghost"
              :disabled="desk.isResolvingApproval.value"
              @click="desk.decideApproval('reject')"
            >拒绝</button>
            <button
              class="button"
              :disabled="desk.isResolvingApproval.value"
              @click="desk.decideApproval('approve')"
            >批准</button>
          </div>
        </section>

        <article class="answer-block" aria-live="polite">
          <div class="answer-meta">
            <span>AGENT OUTPUT</span>
            <span>{{ desk.critique.value }}</span>
          </div>
          <p v-if="desk.answer.value">{{ desk.answer.value }}</p>
          <p v-else class="answer-placeholder">运行后，经过证据审核的答案会出现在这里。</p>
        </article>

        <section class="evidence-section">
          <div class="section-title"><span>EVIDENCE</span><span>{{ desk.evidence.value.length.toString().padStart(2, '0') }}</span></div>
          <div v-if="desk.evidence.value.length" class="evidence-list">
            <article v-for="item in desk.evidence.value" :key="`${item.source}-${item.score}`" class="evidence-card">
              <div><strong>{{ item.title }}</strong><code>{{ item.score.toFixed(3) }}</code></div>
              <p>{{ item.excerpt }}</p>
              <small>{{ item.source }}</small>
            </article>
          </div>
          <p v-else class="empty-evidence">装载课程资料后运行问题，观察检索来源与相关度。</p>
        </section>

        <section class="usage-section">
          <div class="section-title"><span>MODEL USAGE</span><span>SAME RUN</span></div>
          <dl v-if="desk.usage.value" class="usage-grid">
            <div><dt>INPUT</dt><dd>{{ desk.usage.value.input_tokens }}</dd></div>
            <div><dt>OUTPUT</dt><dd>{{ desk.usage.value.output_tokens }}</dd></div>
            <div><dt>TOTAL</dt><dd>{{ desk.usage.value.total_tokens }}</dd></div>
            <div>
              <dt>COST USD</dt>
              <dd>{{ desk.usage.value.estimated_cost_usd === null ? '未知' : desk.usage.value.estimated_cost_usd.toFixed(6) }}</dd>
            </div>
          </dl>
          <p v-else class="empty-evidence">当前 Run 尚未报告模型用量；未知不代表 0。</p>
        </section>
      </section>

      <aside class="trace-panel">
        <div class="rail-heading"><span>LIVE TRACE</span><span>03</span></div>
        <RunTimeline :events="desk.events.value" />
      </aside>
    </section>
  </main>
</template>
