/** Applying a template snapshot to the editor (task 8.1). */

import { describe, expect, it } from 'vitest';

import { applyTemplate } from './templateApply';
import type { TemplateRecord } from './templateStore';
import type { RichDocument } from '../rich/richDocument';
import { projectDocument } from '../rich/projection';

const document: RichDocument = {
  type: 'doc',
  provenance: 'heuristic',
  provenanceNote: 'font_size_1.42x',
  content: [
    {
      type: 'paragraph',
      content: [
        { type: 'text', text: 'Amount: ' },
        {
          type: 'variableReference',
          attrs: {
            variableId: 'var_amount',
            label: 'amount',
            valueType: 'amount',
            required: true,
            displayValue: 'USD 500,000.00',
            occurrenceId: 'occ_1',
          },
        },
      ],
    },
  ],
};

const record = (rich: RichDocument = document): TemplateRecord => ({
  id: 'tpl_1',
  name: 'Guarantee template',
  version: 'v3',
  source: { kind: 'imported', provenance: 'heuristic', note: 'font_size_1.42x' },
  boundRevision: 7,
  charCount: 22,
  variables: [{ label: 'amount', valueType: 'amount', required: true }],
  capturedAt: '2026-11-15T10:00:00.000Z',
  rich,
  persisted: true,
});

describe('applyTemplate', () => {
  it('preserves captured values, provenance and the projected text', () => {
    const applied = applyTemplate(record());

    expect(projectDocument(applied.document).text).toBe('Amount: USD 500,000.00');
    expect(applied.document.provenance).toBe('heuristic');
    expect(applied.document.provenanceNote).toBe('font_size_1.42x');
    expect(applied.variables).toEqual([
      { variableId: 'var_amount', label: 'amount', required: true },
    ]);
  });

  it('returns a deep copy so editor edits cannot mutate the stored snapshot', () => {
    const template = record();
    const before = JSON.stringify(template);

    const applied = applyTemplate(template);
    applied.document.content.push({
      type: 'paragraph',
      content: [{ type: 'text', text: 'edited after apply' }],
    });

    expect(JSON.stringify(template)).toBe(before);
    expect(applied.document.content).toHaveLength(2);
  });

  it('produces the same document when applied twice', () => {
    const template = record();

    expect(applyTemplate(template).document).toEqual(applyTemplate(template).document);
  });
});