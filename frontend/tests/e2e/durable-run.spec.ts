import { expect, test, type Page } from '@playwright/test'

test('recovers a real durable Run after one SSE disconnect and page refresh', async ({ page }) => {
  const durableEventUrls: string[] = []
  let interrupted = false
  await page.route('**/api/durable/runs/*/events?after=*', async (route) => {
    durableEventUrls.push(route.request().url())
    if (!interrupted) {
      interrupted = true
      await route.abort('connectionfailed')
      return
    }
    await route.continue()
  })
  const legacyRequests: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/research') || request.url().includes('/runs/stream')) {
      legacyRequests.push(request.url())
    }
  })

  await page.goto('/')
  await page.locator('#question').fill('2 + 3')
  await page.getByRole('button', { name: /启动研究/ }).click()

  await expect(page.locator('.connection')).toHaveText('completed')
  await expect(page.locator('.answer-block')).toContainText('计算结果是 5')
  expect(durableEventUrls.length).toBeGreaterThanOrEqual(2)
  expect(legacyRequests).toEqual([])
  const runBeforeRefresh = await runValue(page)
  expect(runBeforeRefresh).not.toBe('not started')

  await page.reload()

  await expect(page.locator('.connection')).toHaveText('completed')
  await expect(page.locator('.answer-block')).toContainText('计算结果是 5')
  await expect(runLocator(page)).toHaveText(runBeforeRefresh)
  expect(legacyRequests).toEqual([])
})

test('restores a waiting approval and rejects it through the real API', async ({ page }) => {
  await page.goto('/')
  await page.locator('#question').fill('发布报告 e2e-report')
  await page.getByRole('button', { name: /启动研究/ }).click()

  await expect(page.locator('.connection')).toHaveText('waiting_approval')
  await expect(page.locator('.approval-card')).toContainText('publish_report')
  const runBeforeRefresh = await runValue(page)

  await page.reload()

  await expect(page.locator('.connection')).toHaveText('waiting_approval')
  await expect(page.locator('.approval-card')).toContainText('publish_report')
  await expect(runLocator(page)).toHaveText(runBeforeRefresh)

  const approvalRequest = page.waitForRequest((request) => (
    request.method() === 'POST'
    && request.url().includes('/api/durable/runs/')
    && request.url().includes('/approvals/')
  ))
  await page.getByRole('button', { name: '拒绝' }).click()
  const request = await approvalRequest

  expect(request.postDataJSON()).toEqual({ decision: 'reject' })
  expect(request.headers()['x-session-token']).toBeTruthy()
  await expect(page.locator('.connection')).toHaveText('failed')
  await expect(page.locator('.approval-card')).toHaveCount(0)
  await expect(page.getByRole('alert')).toContainText('approval_rejected')
})

function runLocator(page: Page) {
  return page.locator('.facts div').filter({ hasText: 'RUN' }).locator('dd')
}

async function runValue(page: Page): Promise<string> {
  return (await runLocator(page).textContent())?.trim() ?? ''
}
