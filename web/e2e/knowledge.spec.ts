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

  await page.getByRole('tab', { name: /Automation · not implemented/ }).click();
  await expect(page.getByText(/Automation is not implemented in this build/)).toBeVisible();
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

  await page.getByRole('tab', { name: /Automation · not implemented/ }).click();
  await expect(page.getByText(/Automation is not implemented in this build/)).toBeVisible();
  await expect(page.getByLabel('Knowledge question')).toHaveCount(0);
});