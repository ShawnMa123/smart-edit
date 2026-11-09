/** Tasks 5.1-5.5 — the audit view model: what may and may not be claimed. */

import { describe, expect, it } from 'vitest';

import {
  LABEL_FINDINGS,
  LABEL_NO_FINDINGS,
  LABEL_NOT_RUN,
  LABEL_TEMPLATE_NOT_REQUESTED,
  SCOPE_NOT_RUN,
  SCOPE_RAN,
  buildAuditView,
  stageStatus,
} from './auditView';
import type { Snapshot } from './snapshot';
import {
  NO_PROVIDER_REASON,
  ambiguousTemplateEnvelope,
  auditedEnvelope,
  blockedAuditEnvelope,
  doneEnvelope,
  envelope,
  findingsEnvelope,
  noProviderEnvelope,
  stage,
  templatedEnvelope,
} from './test/fixtures';

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

describe('the rule audit block (agent-audit `verification`)', () => {
  it('reports "did not run" when the envelope carries no report', () => {
    const model = view(doneEnvelope());

    expect(model.audit.ran).toBe(false);
    expect(model.audit.planned).toBeNull();
    expect(model.audit.outcome).toBe('unknown');
    expect(model.audit.gate.decision).toBe('not-asked');
  });

  it('quotes the plan, the assessed count and the coverage ratio verbatim', () => {
    const { audit } = view(auditedEnvelope());

    expect(audit.ran).toBe(true);
    expect(audit.planned).toBe(51);
    expect(audit.assessed).toBe(33);
    expect(audit.ratio).toBe(0.647);
    expect(audit.outcome).toBe('no_findings');
    expect(audit.verdict).toBe('pass');
    expect(audit.counts.not_applicable).toBe(18);
    expect(audit.engineVersion).toBe('1.0.0');
    expect(audit.schemaVersion).toBe('044a959e73af');
    expect(audit.bundleVersions).toEqual({ 'guarantee-core': '1.0.0' });
  });

  it('never treats a missing gate decision as allowed', () => {
    const { audit } = view(auditedEnvelope());

    expect(audit.gate.asked).toBe(false);
    expect(audit.gate.decision).toBe('not-asked');
    expect(audit.gate.decision).not.toBe('allowed');
  });

  it('carries the gate type and the target operations of each finding', () => {
    const { audit } = view(blockedAuditEnvelope());

    expect(audit.outcome).toBe('findings_present');
    expect(audit.hardBlockFindings).toBe(1);
    expect(audit.findings[0].id).toBe('B-001');
    expect(audit.findings[0].gateType).toBe('hard_block');
    expect(audit.findings[0].targetOperations).toContain('start_approval');
    expect(audit.findings[0].rule).toBe('SCHEMA:guarantee_amount:required@schema-1');
    expect(audit.gate).toMatchObject({ asked: true, decision: 'blocked', openGaps: 0 });
    expect(audit.gate.reasonCodes).toEqual(['hard_block']);
    expect(audit.gate.authorizedFindingIds).toEqual(['B-001']);
  });

  it('keeps the server digest separate from the browser digest', () => {
    const model = view(auditedEnvelope(), 'browser-digest', 'browser-digest');

    expect(model.audit.serverDigest).toBe('server-digest-0123456789');
    expect(model.digest).toBe('browser-digest');
    expect(model.stale).toBe(false);
  });
});

describe('the template block (agent-audit `verification.audit.template`)', () => {
  it('says no template was requested when the run never asked for one', () => {
    const { template } = view(doneEnvelope()).audit;

    expect(template.requested).toBe(false);
    expect(template.templateId).toBeNull();
    expect(template.label).toBe(LABEL_TEMPLATE_NOT_REQUESTED);
    expect(template.units).toBe(0);
  });

  it('labels a synthetic pack as synthetic and counts the units it added', () => {
    const { template } = view(templatedEnvelope()).audit;

    expect(template.requested).toBe(true);
    expect(template.templateId).toBe('adidas-guarantee');
    expect(template.version).toBe('1.0.0');
    expect(template.synthetic).toBe(true);
    expect(template.label).toBe('Synthetic template · adidas-guarantee v1.0.0');
    expect(template.units).toBe(2);
    expect(template.counterparty).toBe('Adidas AG');
    expect(template.policyPacks).toEqual(['guarantee-core v1.0.0']);
    expect(template.conflicts).toEqual([]);
  });

  it('reports an unresolvable template with its reason and candidates', () => {
    const { template } = view(ambiguousTemplateEnvelope()).audit;

    expect(template.templateId).toBeNull();
    expect(template.reason).toBe('ambiguous_template');
    expect(template.candidates).toEqual([
      { templateId: 'adidas-guarantee', version: '1.0.0' },
      { templateId: 'adidas-guarantee-second', version: '2.0.0' },
    ]);
    expect(template.requested).toBe(true);
  });
});

describe('stage helper', () => {
  it('reports the latest status per stage, and `absent` when the run never reached it', () => {
    const audited = auditedEnvelope();

    expect(stageStatus(audited, 'normalize')).toBe('done');
    expect(stageStatus(audited, 'audit')).toBe('done');
    expect(stageStatus(audited, 'merge')).toBe('absent');
    expect(stageStatus(noProviderEnvelope(), 'audit')).toBe('absent');
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