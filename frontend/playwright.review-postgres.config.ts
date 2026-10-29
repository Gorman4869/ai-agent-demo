import { fileURLToPath } from 'node:url'

import { defineConfig } from '@playwright/test'
import base from './playwright.config'

if (!process.env.AI_AGENT_REVIEW_DEMO_DSN_FILE) {
  throw new Error('Run scripts/verify-review-deployment.ps1 to provide an isolated local database')
}

const frontendPort = process.env.REVIEW_FRONTEND_PORT ?? '15174'
const backendPort = process.env.REVIEW_BACKEND_PORT ?? '18082'

export default defineConfig({
  ...base,
  testMatch: 'review-postgres.spec.ts',
  timeout: 120_000,
  outputDir: 'test-results/review-postgres',
  // Synthetic session recovery must never be retained in a Playwright trace archive.
  use: { ...base.use, baseURL: `http://127.0.0.1:${frontendPort}`, trace: 'off' },
  webServer: {
    command: `npm.cmd run preview -- --host 127.0.0.1 --port ${frontendPort} --strictPort`,
    cwd: fileURLToPath(new URL('.', import.meta.url)),
    url: `http://127.0.0.1:${frontendPort}`,
    reuseExistingServer: false,
    timeout: 30_000,
    env: { ...process.env, AI_AGENT_DEV_API_TARGET: `http://127.0.0.1:${backendPort}` },
  },
})
