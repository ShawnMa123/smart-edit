// @vitest-environment node
/**
 * Acceptance (tasks 8.1 / 8.2 plus the agent-audit transport): drive a real
 * `createRun → normalize → audit` over HTTP and assert what the panel would show.
 *
 * Runs in the node environment on purpose: jsdom ships its own `AbortSignal`, which Node's fetch
 * rejects, so a browser-like environment cannot make real HTTP calls.
 *
 *   SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json \
 *     .venv/bin/uvicorn app.api.main:app --port 8010 &
 *
 *   VITE_E2E=1 VITE_API_BASE=http://127.0.0.1:8010 npm --prefix web run test -- src/e2e.audit.test.ts
 *
 * The document is read from `fixtures/llm/sample_document.txt`, not typed here: the recorded fixture was
 * taken from exactly that text, so sending anything else would exercise the fixture instead of the
 * pipeline. The honesty path (8.2) needs the same backend started **without** `SMART_EDIT_LLM`.
 */

import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { createRun, triggerStage } from './api/client';
import { buildAuditView, fieldChecksRan } from './auditView';
import { createSnapshot } from './snapshot';

const enabled = import.meta.env.VITE_E2E === '1';
const DOCUMENT = readFileSync(
  new URL('../../fixtures/llm/sample_document.txt', import.meta.url),
  'utf8',
);

const audit = async () => {
  const snapshot = await createSnapshot(DOCUMENT, null);
  const created = await createRun(snapshot.text);
  const normalized = await triggerStage(created.thread_id, 'normalize');
  // Same guard as the UI: `normalize` reports `done` even with placeholder fields, so check both
  // `extract` and `normalize` before asking for an audit.
  const report = fieldChecksRan(normalized)
    ? await triggerStage(created.thread_id, 'audit')
    : normalized;
  return { snapshot, report, view: buildAuditView(report, snapshot, snapshot.digest) };
};

describe.skipIf(!enabled)('end-to-end audit over HTTP', () => {
  it('8.1 reports stages, checks, counts and the audited digest', async () => {
    const { view, snapshot } = await audit();

    // eslint-disable-next-line no-console
    console.log(
      'E2E stages:',
      view.stages.map((row) => `${row.stage}:${row.status}`).join(' '),
      '| audit:',
      `${view.audit.assessed}/${view.audit.planned}`,
      view.audit.outcome,
      '| gate:',
      view.audit.gate.decision,
    );

    expect(view.stages.map((row) => row.stage)).toEqual([
      'parse',
      'extract',
      'normalize',
      'audit',
    ]);
    expect(view.stages.every((row) => row.status === 'done')).toBe(true);
    expect(view.digest).toBe(snapshot.digest);
    expect(view.stale).toBe(false);
    expect(view.usedFixture).toBe(true);
    expect(view.fieldChecks).toBe('ran');
    expect(view.checks.length).toBeGreaterThan(0);
    expect(view.statusCounts.extracted).toBeGreaterThan(0);
  });

  it('8.1b reports the rule audit: 51 planned checks, 33 assessed, nothing found', async () => {
    const { view } = await audit();

    expect(view.audit.ran).toBe(true);
    expect(view.audit.planned).toBe(51);
    expect(view.audit.assessed).toBe(33);
    expect(view.audit.ratio).toBe(0.647);
    expect(view.audit.outcome).toBe('no_findings');
    expect(view.audit.counts.not_applicable).toBe(18);
    expect(view.audit.findings).toEqual([]);
    expect(view.audit.engineVersion).toBe('1.0.0');
    expect(view.audit.bundleVersions).toEqual({ 'guarantee-core': '1.0.0' });
    // An audit decides no operation: the gate stays unasked, which is not "allowed".
    expect(view.audit.gate.asked).toBe(false);
    expect(view.audit.gate.decision).toBe('not-asked');
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
    expect(view.audit.ran).toBe(false);
    expect(view.audit.gate.decision).toBe('not-asked');
  });
});