import { spawn, type ChildProcess } from 'node:child_process'
import { once } from 'node:events'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

const repositoryRoot = fileURLToPath(new URL('../../../', import.meta.url))
const python = fileURLToPath(new URL('../../../.venv/Scripts/python.exe', import.meta.url))
const backendPort = process.env.REVIEW_BACKEND_PORT ?? '18082'
const backendUrl = `http://127.0.0.1:${backendPort}`
let backend: ChildProcess | undefined
let backendErrors = ''

async function startBackend() {
  backendErrors = ''
  backend = spawn(python, [
    '-B', '-m', 'uvicorn', 'backend.app.review_demo:create_postgres_demo_review_app',
    '--factory', '--host', '127.0.0.1', '--port', backendPort, '--no-proxy-headers', '--no-access-log',
    // Psycopg async connections require SelectorEventLoop on Windows.
    '--loop', 'asyncio:SelectorEventLoop',
  ], { cwd: repositoryRoot, env: process.env, stdio: ['ignore', 'ignore', 'pipe'], windowsHide: true })
  backend.stderr?.on('data', (chunk: Buffer) => {
    backendErrors = (backendErrors + chunk.toString()).slice(-8_000)
  })
  await expect.poll(async () => {
    if (backend?.exitCode !== null) {
      const codes = backendErrors.match(/\b[A-Za-z][A-Za-z0-9]*(?:Error|Exception)\b/g) ?? []
      throw new Error(`Owned PostgreSQL demo backend exited before health (${[...new Set(codes)].join(',')})`)
    }
    try {
      return (await fetch(`${backendUrl}/health`, { signal: AbortSignal.timeout(1_000) })).ok
    } catch {
      return false
    }
  }, { timeout: 30_000, message: 'Owned PostgreSQL demo backend health' }).toBe(true)
}

async function stopBackend() {
  if (backend && backend.exitCode === null) {
    const exited = once(backend, 'exit')
    backend.kill()
    await exited
  }
  backend = undefined
}

test.afterAll(stopBackend)

test('built Vue preserves PostgreSQL approval and publication across two backend restarts', async ({ page }) => {
  await startBackend()
  await page.goto('/')
  await page.getByRole('button', { name: '审查', exact: true }).click()
  const createdResponse = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/api/durable/reviews'))
  await page.getByRole('button', { name: /启动审查/ }).click()
  const created = await (await createdResponse).json()
  await expect(page.locator('.connection')).toHaveText('waiting_approval', { timeout: 40_000 })
  await expect(page.locator('.review-result .evidence-card')).toHaveCount(3)
  const waiting = await (await page.request.get(`/api/durable/runs/${created.id}`)).json()
  expect(waiting.review.outcome).toBe('waiting_approval')

  await stopBackend()
  await startBackend()
  await page.reload()
  await expect(page.locator('.approval-card')).toContainText('publish_review')
  await expect(page.locator('.review-result .evidence-card')).toHaveCount(3)
  await expect(page.locator('.facts div').filter({ hasText: 'RUN' }).locator('dd')).toHaveText(created.id.slice(0, 8))
  const restored = await (await page.request.get(`/api/durable/runs/${created.id}`)).json()
  expect(restored.id).toBe(created.id)
  expect(restored.review).toEqual(waiting.review)
  const approvalRequest = page.waitForRequest((request) => request.method() === 'POST' && request.url().includes('/approvals/'))
  await page.getByRole('button', { name: '批准', exact: true }).click()
  const approval = await approvalRequest
  expect(approval.postDataJSON()).toEqual({ decision: 'approve' })
  const approvalPath = new URL(approval.url()).pathname
  await expect(page.locator('.publication-result')).toContainText('版本 2')
  const published = await (await page.request.get(`/api/durable/runs/${created.id}`)).json()

  await stopBackend()
  await startBackend()
  await page.reload()
  await expect(page.locator('.review-result')).toContainText('审查已发布')
  const final = await (await page.request.get(`/api/durable/runs/${created.id}`)).json()
  expect(final.review).toEqual(published.review)
  expect(final.id).toBe(created.id)
  const duplicateApproval = await page.request.post(approvalPath, { data: { decision: 'approve' } })
  expect(duplicateApproval.status()).toBe(409)
  const stream = await (await page.request.get(`/api/durable/runs/${created.id}/events?after=0`)).text()
  expect(stream.match(/^event: review.evidence.recorded$/gm)).toHaveLength(3)
  expect(stream).toContain('event: review.result')
  expect(stream).toContain('event: run.completed')
  const sequences = [...stream.matchAll(/^id: (\d+)$/gm)].map((match) => Number(match[1]))
  expect(sequences).toEqual(Array.from({ length: sequences.length }, (_, index) => index + 1))
  await page.screenshot({ path: 'test-results/review-postgres/published-after-restart.png', fullPage: true })

  // A second Run uses the current revision but a rejected human approval writes no publication.
  await page.getByLabel('预期版本').fill('2')
  await page.getByRole('button', { name: /启动审查/ }).click()
  await expect(page.locator('.approval-card')).toContainText('publish_review')
  await page.getByRole('button', { name: '拒绝', exact: true }).click()
  await expect(page.locator('.review-result')).toContainText('需要人工处理')
  await expect(page.locator('.publication-result')).toHaveCount(0)
  await page.reload()
  await expect(page.locator('.review-result')).toContainText('需要人工处理')
})
