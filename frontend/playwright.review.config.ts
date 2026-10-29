import { fileURLToPath } from 'node:url'

import { defineConfig } from '@playwright/test'
import base from './playwright.config'

const repositoryRoot = fileURLToPath(new URL('../', import.meta.url))
const frontendRoot = fileURLToPath(new URL('.', import.meta.url))
const python = fileURLToPath(new URL('../.venv/Scripts/python.exe', import.meta.url))

export default defineConfig({
  ...base,
  testMatch: 'review-run.spec.ts',
  timeout: 60_000,
  outputDir: 'test-results/review',
  use: { ...base.use, baseURL: 'http://127.0.0.1:5174' },
  webServer: [
    {
      command: `"${python}" -B -m uvicorn backend.app.review_demo:create_demo_review_app --factory --host 127.0.0.1 --port 18081`,
      cwd: repositoryRoot, url: 'http://127.0.0.1:18081/health', reuseExistingServer: false, timeout: 120_000,
    },
    {
      command: 'npm.cmd run dev -- --host 127.0.0.1 --port 5174',
      cwd: frontendRoot, url: 'http://127.0.0.1:5174', reuseExistingServer: false, timeout: 120_000,
      env: { ...process.env, AI_AGENT_DEV_API_TARGET: 'http://127.0.0.1:18081' },
    },
  ],
})
