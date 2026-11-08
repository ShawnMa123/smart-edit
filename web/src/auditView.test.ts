/** Tasks 5.1-5.5 — the audit view model: what may and may not be claimed. */

import { describe, expect, it } from 'vitest';

import {
  LABEL_FINDINGS,
  LABEL_NO_FINDINGS,
  LABEL_NOT_RUN,
  SCOPE_NOT_RUN,
  SCOPE_RAN,
  buildAuditView,
} from './auditView';
import type { Snapshot } from './snapshot';
import { NO_PROVIDER_REASON, doneEnvelope, envelope, findingsEnvelope, noProviderEnvelope, stage } from './test/fixtures';

const snapshot = (digest = 'digest-1'): Snapshot => ({
  text: 'document',
  digest,
  versionId: null,
  capturedAt: '2026-11-08T09:00:00.000Z',
});

const view = (
  envelopeValue = doneEnvelope(),
  snapshotDigest = 'digest-1',
  currentDigest = snapshotDigest,
) => buildAuditView(envelopeValue, snapshot(snapshotDigest), currentDigest);

describe('when extraction did not complete (task 5.2)', () => {
  it('reports that the field checks did not run, with the stage reason', () => {
    const model = view(noProviderEnvelope());

    expect(model.fieldChecks).toBe('did-not-run');
    expect(model.blockedReason).toContain('no model provider configured');
    expect(model.blockedReason).toBe(NO_PROVIDER_REASON);
    expect(model.resultLabel).toBe(LABEL_NOT_RUN);
  });

  it('lists no checks at all — placeholders are not document defects', () => {
    const model = view(noProviderEnvelope());

    expect(model.checks).toEqual([]);
    expect(model.statusCounts).toEqual({ extracted: 0, inferred: 0, missing: 0, unknown: 0 });
  });

  it('treats a partial extraction the same way', () => {
    const partial = envelope({
      fields: doneEnvelope().fields,
      stages: [
        stage({ stage: 'parse' }),
        stage({ stage: 'extract', status: 'partial', reason: '1 batch(es) failed' }),
        stage({ stage: 'normalize' }),
      ],
    });

    const model = view(partial);

    expect(model.fieldChecks).toBe('did-not-run');
    expect(model.checks).toEqual([]);
    expect(model.blockedReason).toBe('1 batch(es) failed');
  });
});

describe('when extraction completed (task 5.1)', () => {
  it('reports the field checks, worst status first', () => {
    const model = view(doneEnvelope());

    expect(model.fieldChecks).toBe('ran');
    expect(model.blockedReason).toBeNull();
    expect(model.checks.map((check) => check.status)).toEqual(['missing', 'inferred', 'extracted']);
    expect(model.statusCounts).toEqual({ extracted: 1, inferred: 1, missing: 1, unknown: 0 });
  });

  it('carries status label, notes, original text and source for each field', () => {
    const model = view(doneEnvelope());
    const byKey = Object.fromEntries(model.checks.map((check) => [check.key, check]));

    expect(byKey.expiry_date.statusLabel).toBe('Not found in source');
    expect(byKey.expiry_date.notes).toEqual(['not_in_source']);
    expect(byKey.applicant_name.notes).toEqual(['value_truncated']);
    expect(byKey.guarantee_amount.value).toBe('500000.00');
    expect(byKey.guarantee_amount.normalizedFrom).toBe('USD 500,000.00');
    expect(byKey.guarantee_amount.source).toEqual({
      fileId: 'F-1',
      page: null,
      span: 'USD 500,000.00',
    });
  });

  it('exposes the stage strip with labels and reasons', () => {
    const model = view(doneEnvelope());

    expect(model.stages.map((row) => [row.stage, row.statusLabel])).toEqual([
      ['parse', 'Done'],
      ['extract', 'Done'],
      ['normalize', 'Done'],
    ]);
    expect(model.stages[1].reason).toContain('fixture:');
  });
});

describe('scope disclosure (task 5.3)', () => {
  it('names the checks that ran', () => {
    for (const step of SCOPE_RAN) {
      expect(step.toLowerCase()).toMatch(/required|format|length/);
    }
    expect(view().stepsRan).toEqual(SCOPE_RAN);
  });

  it('names every check family this build does not run', () => {
    const joined = SCOPE_NOT_RUN.join(' ').toLowerCase();

    expect(joined).toContain('semantic');
    expect(joined).toContain('template');
    expect(joined).toContain('regulatory');
    expect(view().stepsNotRun).toEqual(SCOPE_NOT_RUN);
  });
});

describe('result labelling (task 5.4)', () => {
  it('never calls a clean run a pass', () => {
    const model = view(doneEnvelope());

    expect(model.resultLabel).toBe(LABEL_NO_FINDINGS);
    expect(model.resultLabel.toLowerCase()).not.toMatch(/\bpass\b|compliant/);
  });

  it('reports findings as needing review, with severity and evidence', () => {
    const model = view(findingsEnvelope());

    expect(model.resultLabel).toBe(LABEL_FINDINGS);
    expect(model.severityCounts).toEqual({ critical: 1, warn: 1, info: 0 });
    expect(model.findings[0].severityLabel).toBe('Warning');
    expect(model.findings[0].evidence).toBeTruthy();
    expect(model.findings[1].fieldKeys).toEqual(['guarantee_amount']);
  });
});

describe('fixture labelling (task 5.5)', () => {
  it('flags a fixture-backed run', () => {
    expect(view(doneEnvelope()).usedFixture).toBe(true);
  });

  it('does not flag a provider-backed run', () => {
    const provider = envelope({
      fields: doneEnvelope().fields,
      stages: [stage({ stage: 'parse' }), stage({ stage: 'extract' }), stage({ stage: 'normalize' })],
    });

    expect(view(provider).usedFixture).toBe(false);
  });
});

describe('snapshot binding', () => {
  it('is not stale while the document matches', () => {
    expect(view(doneEnvelope(), 'same', 'same').stale).toBe(false);
  });

  it('is stale after an edit, while the report keeps its digest', () => {
    const model = view(doneEnvelope(), 'digest-1', 'after-edit');

    expect(model.stale).toBe(true);
    expect(model.digest).toBe('digest-1');
    expect(model.capturedAt).toBe('2026-11-08T09:00:00.000Z');
    expect(model.checks).not.toHaveLength(0);
  });
});