import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * The frontend-first Automation workbench (change: automation-workbench-ui, task 5.4).
 *
 * Real browser → real vite → real backend draft. Every workbench action is local mock behaviour, so
 * the assertions focus on the three areas, the honesty labels, variable fill and the payload preview.
 */

const API = 'http://127.0.0.1:8000';
const TEXT = 'Amount: USD 500,000.00\n\nThe guarantee expires on 2027-03-31.';
const headers = { 'X-Demo-User': 'user_demo_01' };

async function resetDocument(request: APIRequestContext) {
  let response = await request.get(`${API}/documents/demo-document`, { headers });
  if (response.status() === 404) {
    const created = await request.post(`${API}/documents`, {
      headers,
      data: { document_id: 'demo-document', title: 'Demand Guarantee', text: TEXT },
    });
    expect(created.status()).toBe(201);
    return;
  }
  expect(response.ok()).toBeTruthy();
  const view = await response.json();
  const locked = await request.post(
    `${API}/documents/${view.document_id}/drafts/${view.draft_id}/lock`,
    { headers, data: { lease_seconds: 120 } },
  );
  expect(locked.ok()).toBeTruthy();
  const lock = await locked.json();
  const saved = await request.put(
    `${API}/documents/${view.document_id}/drafts/${view.draft_id}`,
    {
      headers: { ...headers, 'If-Match': `"draft-${view.revision}"` },
      data: { text: TEXT, lock_id: lock.lock_id, fencing_token: lock.fencing_token },
    },
  );
  expect(saved.ok()).toBeTruthy();
}

async function markAmountVariable(page: Page) {
  await page.evaluate(() => {
    const paragraph = globalThis.document.querySelector(
      '[data-testid="editor-rich"] p',
    ) as HTMLParagraphElement | null;
    const first = paragraph?.firstChild;
    if (!first || first.nodeType !== Node.TEXT_NODE) return;
    const text = first.textContent ?? '';
    const start = text.indexOf('USD');
    const range = globalThis.document.createRange();
    range.setStart(first, start);
    range.setEnd(first, text.length);
    const selection = globalThis.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    globalThis.document.dispatchEvent(new Event('selectionchange'));
  });

  await page.getByRole('tab', { name: /Automation · fixture only/ }).click();
  await page.getByRole('tab', { name: 'Variables & Fill' }).click();
  const variablesPanel = page.getByRole('tabpanel', { name: 'Variables & Fill' });
  await variablesPanel.getByRole('button', { name: 'Mark selection as variable' }).click();
  const dialog = page.getByTestId('variable-dialog');
  await dialog.getByLabel('Variable label').fill('amount');
  await dialog.getByLabel('Variable type').selectOption('amount');
  await dialog.getByRole('button', { name: 'Create variable' }).click();
  await page.getByRole('button', { name: /amount · amount/ }).click();
  await page.getByLabel('Variable value').fill('500000');
  await page.getByRole('button', { name: 'Fill all occurrences' }).click();
}

test('template capture/reload/rename/delete and the fixture-backed flows', async ({
  page,
  request,
}) => {
  await resetDocument(request);
  await page.goto('/');
  // Start from an empty browser-local template list, then reload so the component mounts cleanly.
  await page.evaluate(() =>
    globalThis.localStorage.removeItem('smart-edit:automation-templates'),
  );
  await page.reload();
  await expect(page.getByText(/server draft rev/)).toBeVisible();

  await page.getByRole('tab', { name: /Automation · fixture only/ }).click();
  await expect(page.getByTestId('automation-boundary')).toContainText('Fixture-backed workbench');
  await expect(page.getByTestId('automation-boundary')).toContainText('Not implemented');
  await expect(page.getByRole('tab', { name: 'Template' })).toBeVisible();

  // Template: preview the source/summary before the explicit save.
  await expect(page.getByTestId('template-boundary')).toContainText(
    'Saved in this browser — not on the server',
  );
  await expect(page.getByTestId('template-empty')).toBeVisible();

  const templateName = `E2E template ${Date.now()}`;
  const capture = page.getByTestId('template-capture');
  await capture.getByLabel('Template name').fill(templateName);
  const capturePreview = page.getByTestId('capture-preview');
  await expect(capturePreview).toContainText('Edited in this browser');
  await expect(capturePreview).toContainText('Revision');
  await expect(capturePreview).toContainText('characters');
  await expect(capturePreview).toContainText('v1');

  await capture.getByRole('button', { name: 'Save as template' }).click();
  await expect(page.getByTestId('template-detail')).toContainText('Captured content');
  await expect(page.getByTestId('template-item')).toContainText(templateName);

  // Browser-local persistence: the card survives a reload, still not a server save.
  await page.reload();
  await page.getByRole('tab', { name: /Automation · fixture only/ }).click();
  const card = page.getByRole('button', { name: `${templateName} · v1` });
  await expect(card).toBeVisible();
  await expect(page.getByTestId('template-boundary')).toContainText('not on the server');

  // Rename, then delete only after explicit confirmation.
  await card.click();
  await page.getByRole('button', { name: 'Rename' }).click();
  await page.getByLabel('Rename template').fill(`${templateName} renamed`);
  await page.getByRole('button', { name: 'Save name' }).click();
  await expect(page.getByTestId('template-item')).toContainText('renamed');

  const detail = page.getByTestId('template-detail');
  await detail.getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByText(/from this browser\?/)).toBeVisible();
  await expect(page.getByTestId('template-item')).toBeVisible();
  await detail.getByRole('button', { name: 'Confirm delete' }).click();
  await expect(page.getByTestId('template-empty')).toBeVisible();
  await expect(page.getByTestId('workbench-status')).toContainText('Deleted');

  // Variables: select a word in the first paragraph, mark it, then fill every occurrence.
  const editor = page.getByTestId('editor-rich');
  await page.evaluate(() => {
    const paragraph = globalThis.document.querySelector(
      '[data-testid="editor-rich"] p',
    ) as HTMLParagraphElement | null;
    const first = paragraph?.firstChild;
    if (!first || first.nodeType !== Node.TEXT_NODE) return;
    const range = globalThis.document.createRange();
    range.setStart(first, 0);
    range.setEnd(first, 'Amount'.length);
    const selection = globalThis.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    globalThis.document.dispatchEvent(new Event('selectionchange'));
  });
  const variablesPanel = page.getByRole('tabpanel', { name: 'Variables & Fill' });
  await page.getByRole('tab', { name: 'Variables & Fill' }).click();
  const markButton = variablesPanel.getByRole('button', { name: 'Mark selection as variable' });
  await expect(markButton).toBeEnabled();
  await markButton.click();

  const dialog = page.getByTestId('variable-dialog');
  await dialog.getByLabel('Variable label').fill('amount');
  await dialog.getByLabel('Variable type').selectOption('amount');
  await dialog.getByRole('checkbox').check();
  await dialog.getByRole('button', { name: 'Create variable' }).click();

  const variableList = page.getByTestId('variable-list');
  await expect(variableList).toContainText('amount');
  await expect(variableList).toContainText('1 occurrence(s)');

  await page.getByRole('button', { name: /amount · amount/ }).click();
  await page.getByLabel('Variable value').fill('USD 750,000.00');
  await page.getByRole('button', { name: 'Fill all occurrences' }).click();
  await expect(editor.locator('.variable-chip').first()).toContainText('USD 750,000.00');

  // Downstream mapping: candidate + evidence, explicit confirmation, payload preview, never sent.
  await page.getByRole('tab', { name: 'Downstream Mapping' }).click();
  await page.getByRole('button', { name: 'Match document' }).click();
  await expect(page.getByTestId('mapping-fields')).toContainText('status: matched');
  await expect(page.getByTestId('mapping-fields')).toContainText('evidence:');

  const preview = page.getByTestId('payload-preview');
  await expect(preview).toHaveAttribute('data-state', 'mapping_not_ready');
  await expect(preview).toContainText('Not sent');

  await page.getByRole('button', { name: 'Confirm guarantee' }).click();
  await expect(preview).toHaveAttribute('data-state', 'ready');
  await expect(preview).toContainText('"application_type": "guarantee"');
  await expect(preview).toContainText('document digest');
  await expect(page.getByRole('button', { name: /send/i })).toHaveCount(0);
});

test('applies a captured template to the editor, cancels safely and survives reload', async ({
  page,
  request,
}) => {
  await resetDocument(request);
  await page.goto('/');
  await expect(page.getByText(/server draft rev/)).toBeVisible();

  await page.getByRole('tab', { name: /Automation · fixture only/ }).click();
  await page.getByRole('button', { name: 'Save as template' }).click();
  await expect(page.getByTestId('template-item')).toContainText('Demand guarantee template');

  const editor = page.getByTestId('editor-rich');
  await editor.locator('p').last().click();
  await page.keyboard.press('End');
  await page.keyboard.type(' EDITED');
  await expect(editor).toContainText('EDITED');

  // Cancel keeps the edited document.
  await page.getByRole('button', { name: 'Apply to editor' }).click();
  await expect(page.getByText(/Replace the current document/)).toBeVisible();
  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(editor).toContainText('EDITED');

  // Confirm replaces it with the captured snapshot.
  await page.getByRole('button', { name: 'Apply to editor' }).click();
  await page.getByRole('button', { name: 'Replace document' }).click();
  await expect(editor).not.toContainText('EDITED');
  await expect(editor).toContainText('Amount: USD 500,000.00');

  await expect(page.getByTestId('save-state')).toHaveText('Saved to server', { timeout: 10_000 });
  await page.reload();
  await expect(page.getByTestId('editor-rich')).toContainText('Amount: USD 500,000.00');
  await expect(page.getByTestId('editor-rich')).not.toContainText('EDITED');
});

test('updates an existing template and applies the new snapshot', async ({ page, request }) => {
  await resetDocument(request);
  await page.goto('/');
  await expect(page.getByText(/server draft rev/)).toBeVisible();

  await page.getByRole('tab', { name: /Automation · fixture only/ }).click();
  await page.getByRole('button', { name: 'Save as template' }).click();
  await expect(page.getByTestId('template-item')).toContainText('v1');

  const editor = page.getByTestId('editor-rich');
  await editor.locator('p').last().click();
  await page.keyboard.press('End');
  await page.keyboard.type(' UPDATED');
  await expect(editor).toContainText('UPDATED');

  await page.getByRole('tab', { name: 'Variables & Fill' }).click();
  await page.getByRole('button', { name: 'Save to template' }).click();
  await expect(page.getByText(/previous snapshot will be replaced/)).toBeVisible();
  await page.getByRole('button', { name: 'Update template' }).click();
  await page.getByRole('tab', { name: 'Template' }).click();
  await expect(page.getByTestId('template-item')).toContainText('v2');

  await page.reload();
  await page.getByRole('tab', { name: /Automation · fixture only/ }).click();
  await expect(page.getByTestId('template-item')).toContainText('v2');

  await page.getByTestId('template-item').click();
  await page.getByRole('button', { name: 'Apply to editor' }).click();
  await page.getByRole('button', { name: 'Replace document' }).click();
  await expect(page.getByTestId('editor-rich')).toContainText('UPDATED');
});
test('downloads JSON from the preset system and mock sends', async ({ page, request }) => {
  await resetDocument(request);
  await page.goto('/');
  await expect(page.getByText(/server draft rev/)).toBeVisible();

  await markAmountVariable(page);

  await page.getByRole('tab', { name: 'Downstream Mapping' }).click();
  await page.getByLabel('Downstream source').selectOption('openapi');
  await expect(page.getByTestId('openapi-title')).toContainText('Trade Intake API');
  await page.getByLabel('OpenAPI operation').selectOption('POST /trade/preview');

  const payload = page.getByTestId('openapi-payload');
  await expect(payload).toHaveAttribute('data-state', 'ready');
  await expect(payload).toContainText('"amount": 500000');
  await expect(payload).toContainText('Not sent');

  await page.getByRole('button', { name: 'Send (mock)' }).click();
  const receipt = page.getByTestId('mock-receipt');
  await expect(receipt).toHaveAttribute('data-status', '200');
  await expect(receipt).toContainText('mock_success');
  await expect(receipt).toContainText('Simulated — no network request');
  await expect(receipt).toContainText('https://sandbox.trade.example/api/trade/preview');

  await page.getByLabel('Simulate failure').check();
  await page.getByRole('button', { name: 'Send (mock)' }).click();
  await expect(receipt).toHaveAttribute('data-status', '500');
  await expect(receipt).toContainText('MOCK_DOWNSTREAM_ERROR');

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download JSON' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^previewTradeApplication-\d{8}-\d{6}\.json$/);

  const downloadedPath = await download.path();
  expect(downloadedPath).not.toBeNull();
  expect(readFileSync(downloadedPath!, 'utf8')).toContain('"amount": 500000');
});

test('creates a downstream system with a bound spec, persists it, mock sends and deletes it', async ({
  page,
  request,
}) => {
  await resetDocument(request);
  await page.goto('/');
  await expect(page.getByText(/server draft rev/)).toBeVisible();

  await markAmountVariable(page);

  await page.getByRole('tab', { name: 'Downstream Mapping' }).click();
  await page.getByLabel('Downstream source').selectOption('openapi');
  await page.getByRole('button', { name: 'Manage systems' }).click();
  await page.getByRole('button', { name: 'New system' }).click();
  await page.getByLabel('System name').fill('E2E system');
  await page.getByLabel('Base URL').fill('https://e2e.example/api');
  await page
    .getByLabel('System OpenAPI file')
    .setInputFiles(join(process.cwd(), '../fixtures/automation/openapi_sample.json'));
  await expect(page.getByLabel('System OpenAPI JSON')).toHaveValue(/Trade Intake API/);
  await page.getByRole('button', { name: 'Save system' }).click();

  await expect(page.getByLabel('Downstream system').locator('option:checked')).toContainText(
    'E2E system',
  );
  await page.getByLabel('OpenAPI operation').selectOption('POST /trade/preview');
  await expect(page.getByTestId('openapi-payload')).toHaveAttribute('data-state', 'ready');
  await page.getByRole('button', { name: 'Send (mock)' }).click();
  await expect(page.getByTestId('mock-receipt')).toHaveAttribute('data-status', '200');

  await page.reload();
  await page.getByRole('tab', { name: /Automation · fixture only/ }).click();
  await page.getByRole('tab', { name: 'Downstream Mapping' }).click();
  await page.getByLabel('Downstream source').selectOption('openapi');
  await page.getByRole('button', { name: 'Manage systems' }).click();
  await expect(page.getByTestId('system-list')).toContainText('E2E system');

  const option = page.getByRole('option', { name: /E2E system/ });
  await page.getByLabel('Downstream system').selectOption((await option.getAttribute('value')) ?? '');
  await expect(page.getByTestId('system-detail')).toContainText('https://e2e.example/api');

  const item = page.getByTestId('system-list').locator('li', { hasText: 'E2E system' });
  await item.getByRole('button', { name: 'Delete' }).click();
  await item.getByRole('button', { name: 'Confirm delete' }).click();
  await expect(page.getByTestId('system-list')).not.toContainText('E2E system');
});