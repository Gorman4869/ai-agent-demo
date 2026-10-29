<script setup lang="ts">
import { reactive } from 'vue'

import type { ReviewRunRequest, ReviewSnapshot } from '../types/agent'

defineProps<{ disabled: boolean; review: ReviewSnapshot | null }>()
const emit = defineEmits<{ create: [request: ReviewRunRequest] }>()
const request = reactive<ReviewRunRequest>({
  review_id: 'demo-review', expected_revision: 1, image_asset_id: 'demo-image',
  policy_topic: 'review disclosure', page_fixture_id: 'demo-page', requested_decision: 'approve',
})
const outcomes = {
  in_progress: '正在收集证据', waiting_approval: '等待人工审批', published: '审查已发布',
  needs_attention: '需要人工处理', failed: '审查失败',
}
const sources = { image: '图片观察', policy: '内部规则', page: '网页事实' }
</script>

<template>
  <section class="review-workspace" aria-label="多源证据审查">
    <h2>多源证据审查</h2>
    <p>核对图片、内部规则和网页事实，再由你确认是否发布。使用本地审查演示入口运行。</p>
    <form @submit.prevent="emit('create', { ...request })">
      <fieldset :disabled="disabled" class="review-fields">
        <label>审查单 ID<input v-model="request.review_id" required maxlength="128"></label>
        <label>预期版本<input v-model.number="request.expected_revision" type="number" min="1" step="1" required></label>
        <label>图片资产 ID<input v-model="request.image_asset_id" required maxlength="64"></label>
        <label>规则主题<input v-model="request.policy_topic" required maxlength="512"></label>
        <label>网页资料 ID<input v-model="request.page_fixture_id" required maxlength="64"></label>
        <label>拟定结论<select v-model="request.requested_decision">
          <option value="approve">通过</option><option value="reject">拒绝</option><option value="needs_review">需复核</option>
        </select></label>
        <button class="button" type="submit">启动审查 ↗</button>
      </fieldset>
    </form>
    <section v-if="review" class="review-result" aria-live="polite">
      <h3>{{ outcomes[review.outcome] }}</h3>
      <div class="evidence-list">
        <article v-for="item in review.evidence" :key="item.source_kind" class="evidence-card">
          <strong>{{ sources[item.source_kind] }}</strong>
          <p>{{ item.status === 'verified' ? '证据已记录' : '证据已降级' }} · {{ item.content_bytes }} bytes</p>
          <small>{{ item.source_ref }}</small>
          <details><summary>证据摘要</summary><code>{{ item.content_sha256 }}</code><p>{{ item.trust }}</p></details>
        </article>
      </div>
      <p v-if="review.publication" class="publication-result">
        发布编号：{{ review.publication.publication_id }} · 版本 {{ review.publication.revision }}
      </p>
      <p v-else>尚无已确认的发布记录。</p>
      <details v-if="review.evidence_bundle_digest"><summary>完整证据包摘要</summary><code>{{ review.evidence_bundle_digest }}</code></details>
      <p class="empty-evidence">模型用量与费用未知；离线观察不能替代真实视觉质量验证。</p>
    </section>
    <p v-else class="empty-evidence">提交后，三类证据将按图片 → 规则 → 网页的顺序记录。</p>
  </section>
</template>

<style scoped>
.review-workspace h2 { font: 400 2rem var(--font-display); margin: 24px 0 12px; }
.review-workspace > p { line-height: 1.7; }
.review-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 24px 0; padding: 0; border: 0; }
.review-fields label { display: grid; gap: 8px; font-size: .82rem; }
.review-fields input, .review-fields select { width: 100%; min-width: 0; padding: 11px; border: 1px solid var(--line); background: rgb(255 255 255 / 28%); color: var(--ink); font: inherit; }
.review-fields input:focus-visible, .review-fields select:focus-visible { outline: 3px solid var(--signal); outline-offset: 2px; }
.review-fields button { grid-column: 1 / -1; }
.review-result { border-top: 2px solid var(--ink); padding-top: 12px; }
.review-result code, .publication-result { overflow-wrap: anywhere; }
.review-result details { margin-top: 12px; font-size: .78rem; }
@media (max-width: 720px) { .review-fields { grid-template-columns: 1fr; } }
</style>
