/** Capture preview: source rules, summary and duplicate-name warning (task 7.2). */

import { describe, expect, it } from 'vitest';

import { describeCapture, sourceLabel } from './templateCapture';
import type { TemplateRecord } from './templateStore';
import type { InlineNode, RichDocument } from '../rich/richDocument';
import { plainTextToDocument } from '../rich/richDocument';

const imported = (note?: string): RichDocument => ({
  ...plainTextToDocument('Amount: USD 500,000.00'),
  provenance: 'heuristic',
  ...(note ? { provenanceNote: note } : {}),
});

const variableNode = (): InlineNode => ({
  type: 'variableReference',
  attrs: {
    variableId: 'var_amount',
    label: 'amount',
    valueType: 'amount',
    required: true,
    displayValue: 'USD 500,000.00',
    occurrenceId: 'occ_1',
  },
});

const withVariable = (): RichDocument => ({
  type: 'doc',
  content: [
    {
      type: 'paragraph',
      content: [{ type: 'text', text: 'Amount: ' }, variableNode()],
    },
  ],
});

const template = (name: string): TemplateRecord => ({
  id: `tpl_${name}`,
  name,
  version: 'v1',
  source: { kind: 'edited' },
  boundRevision: 1,
  charCount: 10,
  variables: [],
  capturedAt: '2026-11-15T10:00:00.000Z',
  rich: plainTextToDocument('Captured'),
  persisted: true,
});

const buildPreview = (over: Partial<Parameters<typeof describeCapture>[0]> = {}) =>
  describeCapture({
    document: plainTextToDocument('Amount: USD 500,000.00'),
    draftRevision: 3,
    name: 'Demand guarantee template',
    templates: [],
    nextVersion: 'v1',
    ...over,
  });

describe('describeCapture source', () => {
  it('labels an imported document with its stored provenance and note', () => {
    const preview = buildPreview({ document: imported('font_size_1.42x') });

    expect(preview.source).toEqual({
      kind: 'imported',
      provenance: 'heuristic',
      note: 'font_size_1.42x',
    });
    expect(preview.sourceLabel).toBe('Imported · heuristic');
    expect(preview.provenanceNote).toBe('font_size_1.42x');
  });

  it('labels a document without provenance as edited in this browser', () => {
    const preview = buildPreview();

    expect(preview.source).toEqual({ kind: 'edited' });
    expect(preview.sourceLabel).toBe('Edited in this browser');
    expect(preview.provenanceNote).toBeNull();
  });

  it('never invents an origin for a bare provenance level', () => {
    expect(sourceLabel({ kind: 'imported', provenance: 'fallback' })).toBe('Imported · fallback');
    expect(sourceLabel({ kind: 'edited' })).toBe('Edited in this browser');
  });
});

describe('describeCapture summary', () => {
  it('reports the bound revision, character count and next version', () => {
    const preview = buildPreview({ nextVersion: 'v4' });

    expect(preview.boundRevision).toBe(3);
    expect(preview.revisionLabel).toBe('Revision 3');
    expect(preview.charCount).toBe('Amount: USD 500,000.00'.length);
    expect(preview.nextVersion).toBe('v4');
    expect(preview.canCapture).toBe(true);
  });

  it('keeps capture available for local content without a server draft', () => {
    const preview = buildPreview({ draftRevision: null });

    expect(preview.boundRevision).toBeNull();
    expect(preview.revisionLabel).toBe('No server draft');
    expect(preview.canCapture).toBe(true);
  });

  it('lists the variable summary without writing anything', () => {
    const preview = buildPreview({ document: withVariable() });

    expect(preview.variables).toEqual([
      { label: 'amount', valueType: 'amount', required: true },
    ]);
    expect(preview.charCount).toBe('Amount: USD 500,000.00'.length);
  });

  it('warns about a duplicate name case-insensitively', () => {
    const preview = buildPreview({ templates: [template('demand guarantee TEMPLATE')] });

    expect(preview.duplicate?.name).toBe('demand guarantee TEMPLATE');
  });

  it('trims the name and rejects a blank one', () => {
    expect(buildPreview({ name: '  Reviewed  ' }).name).toBe('Reviewed');
    const blank = buildPreview({ name: '   ' });

    expect(blank.nameError).toBe('Enter a template name before saving.');
    expect(blank.canCapture).toBe(false);
  });

  it('disables capture for an empty document and explains nothing to capture', () => {
    const preview = buildPreview({ document: plainTextToDocument('') });

    expect(preview.empty).toBe(true);
    expect(preview.canCapture).toBe(false);
    expect(preview.charCount).toBe(0);
  });
});