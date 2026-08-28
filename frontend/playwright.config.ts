import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

const frontendRoot = fileURLToPath(new URL('.', import.meta.url))
const repositoryRoot = fileURLToPath(new URL('../', import.meta.url))
const pythonExecutable = fileURLToPath(new URL('../.venv/Scripts/python.exe', import.meta.url))

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  reporter: 'list',
  outputDir: 'test-results/playwright',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: `"${pythonExecutable}" -B -m uvicorn backend.tests.m12_frontend_e2e_server:app --host 127.0.0.1 --port 18080`,
      cwd: repositoryRoot,
      env: {
        ...process.env,
        AI_AGENT_EMBEDDING_PROVIDER: 'offline',
        AI_AGENT_MODEL_PROVIDER: 'mock',
        AI_AGENT_ONLINE_ENABLED: 'false',
        AI_AGENT_PERSISTENCE: 'memory',
        AI_AGENT_RUNTIME: 'manual',
      },
      reuseExistingServer: false,
      timeout: 120_000,
      url: 'http://127.0.0.1:18080/health',
    },
    {
      command: 'npm.cmd run dev -- --host 127.0.0.1 --port 5173',
      cwd: frontendRoot,
      env: {
        ...process.env,
        AI_AGENT_DEV_API_TARGET: 'http://127.0.0.1:18080',
      },
      reuseExistingServer: false,
      timeout: 120_000,
      url: 'http://127.0.0.1:5173',
    },
  ],
})
