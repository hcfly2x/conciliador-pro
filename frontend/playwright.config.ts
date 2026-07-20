import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'

const root = path.resolve(__dirname, '..')
const e2eData = path.join(root, 'tmp', 'playwright', 'data')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['html', { open: 'never' }], ['github']] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'python ../backend/app.py',
      url: 'http://127.0.0.1:5061/api/v1/health',
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        ADMIN_USERNAME: 'e2e-admin',
        ADMIN_PASSWORD: 'e2e-password-123',
        AUTH_DISABLED: '0',
        CONCILIADOR_DATA_DIR: e2eData,
      },
    },
    {
      command: 'npm run dev -- --hostname 127.0.0.1 --port 3000',
      url: 'http://127.0.0.1:3000/login',
      reuseExistingServer: false,
      timeout: 120_000,
      env: { ...process.env, API_PROXY_TARGET: 'http://127.0.0.1:5061' },
    },
  ],
  outputDir: '../tmp/playwright/results',
})
