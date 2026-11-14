import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * Document host through a real browser (document-host-foundation):
 * autosave, 412 conflict that keeps local content, and the fixture apply/undo chain.
 */

const API = 'http://127.0.0.1:8000';
const BASE_TEXT = 'Amount: USD 500,000.00\n\nThe guarantee expires on 2027-03-31.';
const headers = { 'X-Demo-User': 'user_demo_01' };

async function documentView(request: APIRequestContext) {
  const response = await request.get(`${API}/documents/demo-document`, { headers });
  return response;
}

async function lockDraft(request: APIRequestContext, view: { document_id: string; draft_id: string }) {
  const response = await request.post(
    `${API}/documents/${view.document_id}/drafts/${view.draft_id}/lock`,
    { headers, data: { lease_seconds: 120 } },
  );
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function resetDocument(request: APIRequestContext) {
  let response = await documentView(request);
  if (response.status() === 404) {
    const created = await request.post(`${API}/documents`, {
      headers,
      data: { document_id: 'demo-document', title: 'Demand Guarantee', text: BASE_TEXT },
    });
    expect(created.status()).toBe(201);
    return;
  }
  expect(response.ok()).toBeTruthy();
  const view = await response.json();
  const lock = await lockDraft(request, view);
  const saved = await request.put(
    `${API}/documents/${view.document_id}/drafts/${view.draft_id}`,
    {
      headers: { ...headers, 'If-Match': `"draft-${view.revision}"` },
      data: {
        text: BASE_TEXT,
        lock_id: lock.lock_id,
        fencing_token: lock.fencing_token,
      },
    },
  );
  expect(saved.ok()).toBeTruthy();
}

async function moveHead(request: APIRequestContext) {
  const response = await documentView(request);
  const view = await response.json();
  const lock = await lockDraft(request, view);
  const saved = await request.put(
    `${API}/documents/${view.document_id}/drafts/${view.draft_id}`,
    {
      headers: { ...headers, 'If-Match': `"draft-${view.revision}"` },
      data: {
        text: `${BASE_TEXT}\n\nServer moved this passage.`,
        lock_id: lock.lock_id,
        fencing_token: lock.fencing_token,
      },
    },
  );
  expect(saved.status()).toBe(200);
}

async function typeIntoEditor(page: Page, value: string) {
  const editor = page.getByLabel('Document text');
  await editor.click();
  await page.keyboard.press('End');
  await page.keyboard.type(value);
}

test('autosaves to the server draft', async ({ page, request }) => {
  await resetDocument(request);
  await page.goto('/');
  await expect(page.getByText(/server draft rev/)).toBeVisible();

  await typeIntoEditor(page, ' [autosave]');
  await expect(page.getByTestId('save-state')).toHaveText('Saving…', { timeout: 5_000 });
  await expect(page.getByTestId('save-state')).toHaveText('Saved to server', { timeout: 10_000 });
});

test('keeps local content and shows the conflict panel on 412', async ({ page, request }) => {
  await resetDocument(request);
  await page.goto('/');
  await expect(page.getByText(/server draft rev/)).toBeVisible();

  await moveHead(request);
  await typeIntoEditor(page, ' [local-only]');

  await expect(page.getByTestId('draft-conflict')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('save-state')).toHaveText(
    'Save conflict — local content is not saved to the server',
  );
  const recovery = await page.evaluate(() =>
    globalThis.localStorage.getItem('smart-edit:recovery:demo-document'),
  );
  expect(recovery).toContain('[local-only]');
});

test('runs the fixture proposal through accept, apply and undo', async ({ page, request }) => {
  await resetDocument(request);
  await page.goto('/');

  await page.getByRole('button', { name: 'Create fixture proposal' }).click();
  await expect(page.getByText(/replace_text/).first()).toBeVisible();
  await page.getByRole('button', { name: 'Accept proposal' }).click();
  await expect(page.getByText(/accepted/).first()).toBeVisible();

  await page.getByRole('button', { name: 'Apply proposal' }).click();
  await expect(page.getByTestId('automation-receipt')).toContainText('Receipt');
  await expect(page.getByTestId('automation-receipt')).not.toContainText('reversed');

  await page.getByRole('button', { name: 'Undo application' }).click();
  await expect(page.getByTestId('automation-receipt')).toContainText('reversed');
});