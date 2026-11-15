/** Mock workbench data: the shared fixture, deterministic matching and payload preview (tasks 2.3, 4.2, 4.4). */

import { describe, expect, it } from 'vitest';

import {
  __fixture,
  buildPayload,
  defaultTemplateName,
  downstreamTemplates,
  matchDocument,
  suggestDefinition,
} from './mockWorkbench';
import type { RichDocument } from '../rich/richDocument';
import { plainTextToDocument } from '../rich/richDocument';

const doc = (value: string): RichDocument => plainTextToDocument(value);

const tradeTemplate = downstreamTemplates[0];
const binding = { templateVersion: tradeTemplate.version, documentDigest: 'c'.repeat(64) };

describe('workbench fixture', () => {
  it('is the single source for templates and variable suggestions', () => {
    expect(defaultTemplateName).toBe('Demand guarantee template');
    expect(__fixture.suggestedVariables.map((item) => item.label)).toEqual([
      'amount',
      'beneficiary',
      'expiry date',
    ]);
    expect(tradeTemplate.fields[0].options).toEqual(['guarantee', 'standby_dc']);
    expect(downstreamTemplates).toHaveLength(2);
  });

  it('suggests a known type from the fixture and falls back to an optional string', () => {
    expect(suggestDefinition('Amount')).toMatchObject({
      valueType: 'amount',
      required: true,
    });
    expect(suggestDefinition('Reference number')).toMatchObject({
      label: 'Reference number',
      valueType: 'string',
      required: false,
    });
  });
});

describe('matchDocument', () => {
  it('matches a guarantee with an evidence excerpt', () => {
    const [candidate] = matchDocument(doc('This demand guarantee expires soon.'), tradeTemplate);
    expect(candidate).toMatchObject({ fieldId: 'application_type', status: 'matched', value: 'guarantee' });
    expect(candidate.evidence).toContain('demand guarantee');
  });

  it('matches a standby and a date', () => {
    const candidates = matchDocument(
      doc('Standby facility valid until 2027-01-01.'),
      tradeTemplate,
    );
    expect(candidates[0]).toMatchObject({ status: 'matched', value: 'standby_dc' });
    expect(candidates[1]).toMatchObject({ status: 'matched', value: '2027-01-01' });
  });

  it('reports ambiguity when both wordings appear', () => {
    const [candidate] = matchDocument(doc('Guarantee or standby, unclear.'), tradeTemplate);
    expect(candidate).toMatchObject({ status: 'ambiguous', value: null });
    expect(candidate.evidence).toContain('Guarantee or standby');
  });

  it('reports missing when the document has no supporting wording', () => {
    const [candidate] = matchDocument(doc('Unrelated text.'), tradeTemplate);
    expect(candidate).toMatchObject({ status: 'missing', value: null, evidence: null });
  });

  it('never turns a variable placeholder into a beneficiary value', () => {
    const beneficiary = matchDocument(
      doc('Beneficiary: {{beneficiary}}'),
      downstreamTemplates[1],
    ).find((item) => item.fieldId === 'beneficiary_name');
    expect(beneficiary).toMatchObject({ status: 'missing', value: null });
  });
});

describe('buildPayload', () => {
  it('keeps unconfirmed fields out and marks the preview not ready', () => {
    const preview = buildPayload(tradeTemplate, {}, binding);

    expect(preview.state).toBe('mapping_not_ready');
    expect(preview.ready).toBe(false);
    expect(preview.missing).toEqual(['application_type']);
    expect(preview.payload).toEqual({});
    expect(preview.sent).toBe(false);
  });

  it('is ready once required fields are confirmed, bound to template version and digest', () => {
    const preview = buildPayload(tradeTemplate, { application_type: 'guarantee' }, binding);

    expect(preview.state).toBe('ready');
    expect(preview.payload).toEqual({ application_type: 'guarantee' });
    expect(preview.templateVersion).toBe(tradeTemplate.version);
    expect(preview.documentDigest).toBe(binding.documentDigest);
    expect(preview.missing).toEqual([]);
    expect(preview.sent).toBe(false);
  });

  it('rejects an enum value outside the template options', () => {
    const preview = buildPayload(tradeTemplate, { application_type: 'invented' }, binding);

    expect(preview.state).toBe('mapping_not_ready');
    expect(preview.missing).toEqual(['application_type']);
    expect(preview.payload).toEqual({});
  });

  it('allows optional fields to stay empty', () => {
    const preview = buildPayload(
      tradeTemplate,
      { application_type: 'guarantee', expiry_date: '' },
      binding,
    );

    expect(preview.state).toBe('ready');
    expect(preview.payload).toEqual({ application_type: 'guarantee' });
  });
});