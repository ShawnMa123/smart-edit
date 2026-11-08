// @vitest-environment node
/**
 * Acceptance (tasks 8.1 / 8.2): drive a real audit over HTTP and assert what the panel would show.
 *
 * Runs in the node environment on purpose: jsdom ships its own `AbortSignal`, which Node's fetch
 * rejects, so a browser-like environment cannot make real HTTP calls.
 *
 *   VITE_E2E=1 VITE_API_BASE=http://127.0.0.1:8010 npm --prefix web run test -- src/e2e.audit.test.ts
 *
 * The backend runs with `SMART_EDIT_LLM=fixture:...` for 8.1 and without it for 8.2.
 */

import { describe, expect, it } from 'vitest';

import { createRun, triggerStage } from './api/client';
import { buildAuditView } from './auditView';
import { createSnapshot } from './snapshot';

const enabled = import.meta.env.VITE_E2E === '1';
const DOCUMENT = `DEMAND GUARANTEE
Guarantee No: BG-2026-00417
Amount: USD 500,000.00
Applicant: Alpha Tech Pte Ltd
Issue Date: 12/03/26
Governing Rules: URDG 758
`;

const audit = async () => {
  const snapshot = await createSnapshot(DOCUMENT, null);
  const created = await createRun(snapshot.text);
  const report = await triggerStage(created.thread_id, 'normalize');
  return { snapshot, report, view: buildAuditView(report, snapshot, snapshot.digest) };
};

describe.skipIf(!enabled)('end-to-end audit over HTTP', () => {
  it('8.1 reports stages, checks, counts and the audited digest', async () => {
    const { view, snapshot } = await audit();

    // eslint-disable-next-line no-console
    console.log(
      'E2E digest:',
      snapshot.digest.slice(0, 12),
      '| stages:',
      view.stages.map((row) => `${row.stage}:${row.status}`).join(' '),
    );

    expect(view.stages.map((row) => row.stage)).toEqual(['parse', 'extract', 'normalize']);
    expect(view.digest).toBe(snapshot.digest);
    expect(view.stale).toBe(false);
    expect(view.usedFixture).toBe(true);
    expect(view.fieldChecks).toBe('ran');
    expect(view.checks.length).toBeGreaterThan(0);
    expect(view.statusCounts.extracted).toBeGreaterThan(0);
    expect(view.resultLabel).toBe('No findings in the checks that ran');
  });
});

const honestyEnabled = import.meta.env.VITE_E2E_HONESTY === '1';

describe.skipIf(!honestyEnabled)('end-to-end honesty path over HTTP', () => {
  it('8.2 reports that field checks did not run when no provider is configured', async () => {
    const { view } = await audit();

    // eslint-disable-next-line no-console
    console.log('Honesty path:', view.fieldChecks, '|', view.blockedReason, '|', view.resultLabel);

    expect(view.fieldChecks).toBe('did-not-run');
    expect(view.blockedReason).toContain('no model provider configured');
    expect(view.checks).toEqual([]);
    expect(view.resultLabel).toBe('Field checks did not run');
  });
});