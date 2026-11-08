import { defineConfig, devices } from '@playwright/test';

/**
 * UI end-to-end: real browser → real vite dev server → real uvicorn.
 *
 * Two backends on purpose:
 *   8000  fixture-backed (`SMART_EDIT_LLM=fixture:...`) — deterministic happy path
 *   8010  no provider (`SMART_EDIT_LLM=''` → `resolve_llm` returns None) — the honesty path
 *
 * The second vite (5174) exists because `app/api/main.py` ships **no** CORS middleware: the browser can
 * only reach 8010 through a dev proxy, so `VITE_PROXY_TARGET` (vite.config.ts) points it there.
 */
const PY = '.venv/bin/uvicorn';
const FIXTURE = 'fixture:fixtures/llm/extract_sample.json';
/** `useViewport.ts` switches to one-pane + tabs at ≤1365px, so the desktop project must be wider. */
const DESKTOP = { width: 1440, height: 900 };
const baseEnv = process.env as Record<string, string>;
/**
 * Browser resolution order (offline / restricted CI friendly — never downloads):
 *   1. `PW_CHANNEL=chrome`            → the installed Google Chrome (`channel`)
 *   2. `PW_EXECUTABLE_PATH=/path/bin` → a pre-baked Chrome/Chromium binary from the image
 *   3. neither                        → Playwright's bundled build (needs `playwright install`)
 */
const browser = process.env.PW_CHANNEL
  ? { channel: process.env.PW_CHANNEL }
  : process.env.PW_EXECUTABLE_PATH
    ? { launchOptions: { executablePath: process.env.PW_EXECUTABLE_PATH } }
    : {};

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000, // `web/src/api/client.ts` DEFAULT_TIMEOUT_MS
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1, // backend run state is process-scoped + SQLite; parallel runs interfere
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    trace: 'retain-on-failure',
    // Video needs Playwright's ffmpeg build; keep it opt-in so a fresh clone can run the suite.
    video: process.env.PW_VIDEO ? 'retain-on-failure' : 'off',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], ...browser, baseURL: 'http://127.0.0.1:5173', viewport: DESKTOP },
      testIgnore: /(honesty|narrow)\.spec\.ts/,
    },
    {
      name: 'honesty',
      use: { ...devices['Desktop Chrome'], ...browser, baseURL: 'http://127.0.0.1:5174', viewport: DESKTOP },
      testMatch: /honesty\.spec\.ts/,
    },
    {
      name: 'narrow',
      // Pixel 7 (412×915) is chromium-based, so `PW_CHANNEL=chrome` works; iPhone 13 is webkit.
      use: { ...devices['Pixel 7'], ...browser, baseURL: 'http://127.0.0.1:5173' },
      testMatch: /narrow\.spec\.ts/,
    },
  ],

  webServer: [
    {
      command: `${PY} app.api.main:app --port 8000 --log-level warning`,
      cwd: '..',
      env: { ...baseEnv, SMART_EDIT_LLM: FIXTURE },
      url: 'http://127.0.0.1:8000/openapi.json', // FastAPI docs are on by default → 200 when ready
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `${PY} app.api.main:app --port 8010 --log-level warning`,
      cwd: '..',
      env: { ...baseEnv, SMART_EDIT_LLM: '' }, // explicit "no provider configured"
      url: 'http://127.0.0.1:8010/openapi.json',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: 'npm run dev -- --port 5173 --strictPort',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: 'npm run dev -- --port 5174 --strictPort',
      env: { ...baseEnv, VITE_PROXY_TARGET: 'http://127.0.0.1:8010' },
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});