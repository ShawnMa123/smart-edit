import { expect, test } from '@playwright/test';

/**
 * Knowledge Q&A through a real browser (task 5.2/6.1): snapshot + session on the first question,
 * 202 + polling, reviewed answer with citations, citation detail, feedback, and the unimplemented
 * tabs still labelled. The corpus is synthetic, so the banner must be visible.
 */
test('answers a product question with citations and keeps the honesty labels', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('tab', { name: 'Knowledge Q&A' })).toBeVisible();

  await page.getByRole('tab', { name: 'Knowledge Q&A' }).click();
  await expect(page.getByText(/Fixture-backed: answers use synthetic demo sources/)).toBeVisible();

  await page.getByLabel('Knowledge question').fill('What documents are required for the application?');
  await page.getByRole('button', { name: 'Ask' }).click();

  await expect(page.getByText('Answer · answered')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Support: (strong|qualified)/)).toBeVisible();
  await expect(page.getByText(/synthetic demo corpus/i)).toBeVisible();
  await expect(page.getByText(/Conversation sess_/)).toBeVisible();

  const citation = page.getByRole('button', { name: /Open citation Synthetic Product Manual/ }).first();
  await citation.click();
  const detail = page.getByRole('region', { name: 'Citation detail' });
  await expect(detail).toBeVisible();
  await expect(detail.getByText(/Locator:/)).toBeVisible();

  await page.getByRole('button', { name: 'Helpful', exact: true }).click();
  await expect(page.getByText(/Feedback saved: helpful/)).toBeVisible();

  await page.getByRole('tab', { name: /Automation · fixture only/ }).click();
  await expect(page.getByTestId('automation-boundary')).toContainText('Fixture-backed workbench');
  await expect(page.getByRole('tab', { name: 'Downstream Mapping' })).toBeVisible();
  await expect(page.getByLabel('Knowledge question')).toHaveCount(0);
});

test('shows onboarding, fills a suggestion without running, and answers a capability question', async ({
  page,
}) => {
  const assistantRuns: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (
      request.method() === 'POST' &&
      /^\/api\/assistant\/sessions\/[^/]+\/runs$/.test(url.pathname)
    ) {
      assistantRuns.push(url.pathname);
    }
  });

  await page.goto('/');
  await page.getByRole('tab', { name: 'Knowledge Q&A' }).click();

  await expect(page.getByText('What can I ask?')).toBeVisible();
  await expect(page.getByText('Can:')).toBeVisible();
  await expect(page.getByText('Cannot:')).toBeVisible();
  await expect(page.getByText('How:')).toBeVisible();
  await expect(page.getByText(/No edits/)).toBeVisible();

  const input = page.getByLabel('Knowledge question');
  await page.getByRole('button', { name: 'What can you do?' }).click();
  await expect(input).toHaveValue('What can you do?');
  expect(assistantRuns).toHaveLength(0);

  await page.getByRole('button', { name: 'Ask' }).click();
  await expect(page.getByText('Answer · answered')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Support: (strong|qualified)/)).toBeVisible();
  await expect(
    page.getByRole('button', { name: /Open citation Knowledge Assistant Guide/ }).first(),
  ).toBeVisible();
  expect(assistantRuns).toHaveLength(1);

  await page.getByRole('button', { name: /Open citation Knowledge Assistant Guide/ }).first().click();
  const detail = page.getByRole('region', { name: 'Citation detail' });
  await expect(detail).toBeVisible();
  await expect(detail.getByText(/Locator:/)).toBeVisible();

  await expect(page.getByRole('button', { name: 'What can you do?' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Show examples' }).click();
  await expect(page.getByRole('button', { name: 'What can you do?' })).toBeVisible();

  await page.getByRole('button', { name: 'Helpful', exact: true }).click();
  await expect(page.getByText(/Feedback saved: helpful/)).toBeVisible();

  await page.getByRole('tab', { name: /Automation · fixture only/ }).click();
  await expect(page.getByTestId('automation-boundary')).toContainText('Fixture-backed workbench');
  await expect(page.getByRole('tab', { name: 'Downstream Mapping' })).toBeVisible();
  await expect(page.getByLabel('Knowledge question')).toHaveCount(0);
});

/**
 * `knowledge-retrieval-layers` / `knowledge-egress-policy`: the web layer is opt-in and the panel
 * states exactly what would leave the service before anything is sent.
 */
test('the web toggle is opt-in and previews the outbound payload', async ({ page }) => {
  const external: string[] = [];
  page.on('request', (request) => {
    const { hostname } = new URL(request.url());
    if (!['127.0.0.1', 'localhost'].includes(hostname)) external.push(request.url());
  });
  // The dev backend has no provider; stub the capability view so the toggle is exercisable.
  await page.route('**/api/assistant/capabilities', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        model: { configured: true, label: 'doubao:seed-1', approved_processor: true },
        layers: { local: true, approved_web: true, general_web: false },
        egress: { policy_version: 'test', allowed_domains: 2, loaded: true },
        web: { provider: 'fixture' },
      }),
    });
  });

  await page.goto('/');
  await page.getByRole('tab', { name: 'Knowledge Q&A' }).click();

  const toggle = page.getByRole('checkbox', { name: /Search the web for the latest/i });
  await expect(toggle).not.toBeChecked();
  await expect(page.getByText(/Off: only published sources/i)).toBeVisible();

  await toggle.check();
  await expect(page.getByText(/Will send: the screened question only/i)).toBeVisible();
  await expect(page.getByText(/Will not send: document text/i)).toBeVisible();

  // Merely enabling the toggle must not call anything outside the app.
  expect(external).toEqual([]);
});

/**
 * `assistant-capabilities`: with no provider wired, the toggle must be disabled and say why.
 */
test('disables the web toggle when the server has no web layer', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('tab', { name: 'Knowledge Q&A' }).click();

  const toggle = page.getByRole('checkbox', { name: /Search the web for the latest/i });
  await expect(toggle).toBeDisabled({ timeout: 20_000 });
  await expect(page.getByText(/Web is not available on this server/i)).toBeVisible();
});

/**
 * `knowledge-general-web`: an answer that came from the general channel is grouped separately and
 * carries an unverified banner. The run response is stubbed so the check does not need a live model.
 */
test('renders general web citations with an unverified banner', async ({ page }) => {
  const result = {
    schema_version: '1.0',
    outcome: 'answered',
    language: 'en',
    support_level: 'qualified',
    claims: [
      { id: 'c1', text: 'Markets published an update today.', kind: 'fact', citation_ids: ['web_1'] },
    ],
    citations: [
      {
        id: 'web_1',
        source_type: 'general_web',
        title: 'Market update',
        source_version: '2026-11-16T00:00:00Z',
        locator: {
          url: 'https://iccwbo.org/news/1',
          domain: 'iccwbo.org',
          retrieved_at: '2026-11-16T00:00:00Z',
        },
      },
    ],
    limitations: ['This answer comes from general web search: unverified third-party content.'],
    clarification_questions: [],
    context_stale: false,
    handoff_target: null,
    retrieval: [
      { layer: 'web', status: 'ok', detail: 'general_web', retrieved_at: '2026-11-16T00:00:00Z' },
    ],
    processor: 'doubao:seed-1',
    route: 'general_web',
    web: { requested: true, status: 'ok', reason: null, hint: null },
  };
  const run = {
    id: 'run_mock',
    session_id: 'sess_mock',
    user_message_id: 'msg_user',
    status: 'succeeded',
    stage: 'completed',
    attempt: 1,
    created_at: '2026-11-16T00:00:00Z',
    deadline_at: '2026-11-16T00:02:00Z',
    started_at: '2026-11-16T00:00:00Z',
    finished_at: '2026-11-16T00:00:10Z',
    assistant_message_id: 'msg_assistant',
    result,
    error: null,
  };

  await page.route('**/api/assistant/runs/**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(run),
    });
  });

  await page.goto('/');
  await page.getByRole('tab', { name: 'Knowledge Q&A' }).click();
  await page.getByLabel('Knowledge question').fill('What happened in the market today?');
  await page.getByRole('button', { name: 'Ask' }).click();

  await expect(page.getByText('General web (1)')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/General web answer — unverified/)).toBeVisible();
  await expect(page.getByText(/^Web \(\d+\)$/)).toHaveCount(0);
});

/**
 * `assistant-answer-provenance`: a skipped web search must be explained in the answer, not only in
 * the limitations list. The run response is stubbed so no live provider is needed.
 */
test('explains a skipped web search from the answer summary', async ({ page }) => {
  const result = {
    schema_version: '1.0',
    outcome: 'answered',
    language: 'en',
    support_level: 'qualified',
    claims: [
      { id: 'c1', text: 'The assistant answers product questions.', kind: 'fact', citation_ids: ['cite_1'] },
    ],
    citations: [
      {
        id: 'cite_1',
        source_type: 'product_manual',
        title: 'Knowledge Assistant Guide',
        source_version: 'demo-1',
        locator: {},
      },
    ],
    limitations: [],
    clarification_questions: [],
    context_stale: false,
    handoff_target: null,
    retrieval: [{ layer: 'web', status: 'skipped', detail: 'web_unavailable', retrieved_at: null }],
    processor: 'fixture',
    route: 'published',
    web: {
      requested: true,
      status: 'skipped',
      reason: 'web_unavailable',
      hint: 'This server has no web provider configured.',
    },
  };
  const run = {
    id: 'run_mock',
    session_id: 'sess_mock',
    user_message_id: 'msg_user',
    status: 'succeeded',
    stage: 'completed',
    attempt: 1,
    created_at: '2026-11-16T00:00:00Z',
    deadline_at: '2026-11-16T00:02:00Z',
    started_at: '2026-11-16T00:00:00Z',
    finished_at: '2026-11-16T00:00:10Z',
    assistant_message_id: 'msg_assistant',
    result,
    error: null,
  };

  await page.route('**/api/assistant/runs/**', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(run) });
  });

  await page.goto('/');
  await page.getByRole('tab', { name: 'Knowledge Q&A' }).click();
  await page.getByLabel('Knowledge question').fill('What can you do?');
  await page.getByRole('button', { name: 'Ask' }).click();

  await expect(page.getByText(/Web search skipped \(web_unavailable\)/)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/This server has no web provider configured/i)).toBeVisible();
  await expect(page.getByText(/Answered from published sources · web not needed/i)).toBeVisible();
});
