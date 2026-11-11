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
/**
 * `python -m uvicorn` works on both layouts (`.venv/bin/` on POSIX, `.venv/Scripts/` on Windows),
 * and `PYTHON` still lets CI point at an interpreter outside the checkout.
 */
const PY = process.env.PYTHON ?? (process.platform === 'win32'
  ? '.venv\\Scripts\\python.exe'
  : '.venv/bin/python');
const FIXTURE = 'fixture:fixtures/llm/extract_sample.json';
/**
 * Local ports are overridable so an occupied 8000 (RAGFlow, another demo, ...) does not force a
 * hand-written config. The defaults match the docs and CI.
 */
const API_PORT = process.env.SMART_EDIT_E2E_API_PORT ?? '8000';
const HONEST_API_PORT = process.env.SMART_EDIT_E2E_HONEST_API_PORT ?? '8010';
const WEB_PORT = process.env.SMART_EDIT_E2E_WEB_PORT ?? '5173';
const HONEST_WEB_PORT = process.env.SMART_EDIT_E2E_HONEST_WEB_PORT ?? '5174';
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
      use: { ...devices['Desktop Chrome'], ...browser, baseURL: `http://localhost:${WEB_PORT}`, viewport: DESKTOP },
      testIgnore: /(honesty|narrow)\.spec\.ts/,
    },
    {
      name: 'honesty',
      use: { ...devices['Desktop Chrome'], ...browser, baseURL: `http://localhost:${HONEST_WEB_PORT}`, viewport: DESKTOP },
      testMatch: /honesty\.spec\.ts/,
    },
    {
      name: 'narrow',
      // Pixel 7 (412×915) is chromium-based, so `PW_CHANNEL=chrome` works; iPhone 13 is webkit.
      use: { ...devices['Pixel 7'], ...browser, baseURL: `http://localhost:${WEB_PORT}` },
      testMatch: /narrow\.spec\.ts/,
    },
  ],

  webServer: [
    {
      command: `${PY} -m uvicorn app.api.main:app --port ${API_PORT} --log-level warning`,
      cwd: '..',
      env: { ...baseEnv, SMART_EDIT_LLM: FIXTURE },
      url: `http://127.0.0.1:${API_PORT}/openapi.json`, // FastAPI docs are on by default → 200 when ready
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `${PY} -m uvicorn app.api.main:app --port ${HONEST_API_PORT} --log-level warning`,
      cwd: '..',
      env: { ...baseEnv, SMART_EDIT_LLM: '' }, // explicit "no provider configured"
      url: `http://127.0.0.1:${HONEST_API_PORT}/openapi.json`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${WEB_PORT} --strictPort`,
      env: { ...baseEnv, VITE_PROXY_TARGET: `http://127.0.0.1:${API_PORT}` },
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${HONEST_WEB_PORT} --strictPort`,
      env: { ...baseEnv, VITE_PROXY_TARGET: `http://127.0.0.1:${HONEST_API_PORT}` },
      url: `http://localhost:${HONEST_WEB_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});