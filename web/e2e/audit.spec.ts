import { expect, test } from '@playwright/test';

import { DOCUMENT, Workspace } from './support/workspace';

/**
 * Happy path, fixture-backed. Maps to `editor-shell` / "Extraction completed", "Zero findings",
 * "The audited digest is displayed" and `frontend-console` / "Stage reports cannot be omitted".
 */
test('runs parse→extract→normalize→audit and reports 33 of 51 checks assessed', async ({ page }) => {
  const ws = new Workspace(page);
  await ws.open();
  await ws.paste(DOCUMENT);
  await ws.runAudit();

  // Four stage rows come back from the envelope — the panel must not drop or invent one.
  await expect(ws.stageRows()).toHaveCount(4);
  expect(await ws.stages()).toEqual([
    ['parse', 'done'],
    ['extract', 'done'],
    ['normalize', 'done'],
    ['audit', 'done'],
  ]);

  // Candidates came from a recorded fixture, and the UI says so instead of implying a model ran.
  await expect(page.getByRole('heading', { name: 'Fixture-backed run' })).toBeVisible();

  // Recomputable numbers, not a page snapshot.
  await expect(page.getByText('33 of 51 planned checks assessed')).toBeVisible();
  await expect(page.getByText('ratio 0.647')).toBeVisible();

  // An audit decides no operation: "not asked" is a claim of its own, never "allowed".
  await expect(ws.gate()).toHaveAttribute('data-decision', 'not-asked');
  await expect(ws.gate()).toContainText('Not asked');
  await expect(ws.ruleAudit()).toHaveAttribute('data-ran', 'true');

  // Zero findings is not compliance.
  await expect(page.getByText('No findings in the checks that ran')).toBeVisible();
  await expect(
    page.getByText('No findings does not mean the document is compliant.'),
  ).toBeVisible();

  // Exactly three calls, in order: create run → normalize (backfills parse+extract) → audit.
  expect(ws.posts).toHaveLength(3);
  expect(ws.stageCalls()).toEqual(['normalize', 'audit']);
});