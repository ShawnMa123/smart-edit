/** The structural guard accepts the documented shapes and rejects malformed inline/block payloads. */

import { describe, expect, it } from 'vitest';

import { isRichDocument, plainTextToDocument } from './richDocument';

const validVariable = {
  type: 'variableReference',
  attrs: {
    variableId: 'var_1',
    label: 'amount',
    valueType: 'amount',
    required: true,
    displayValue: 'USD 1.00',
    occurrenceId: 'occ_1',
  },
};

describe('isRichDocument', () => {
  it('accepts paragraphs, headings, lists, tables, gaps, page breaks and variables', () => {
    expect(isRichDocument(plainTextToDocument('Amount'))).toBe(true);
    expect(
      isRichDocument({
        type: 'doc',
        content: [
          { type: 'heading', attrs: { level: 2, fontSize: 12 }, content: [{ type: 'text', text: 'Parties' }] },
          { type: 'pageBreak' },
          {
            type: 'paragraph',
            content: [
              { type: 'text', text: 'Amount: ' },
              validVariable,
              { type: 'pdfGap', attrs: { rule: true, grow: 1 }, content: [{ type: 'text', text: 'x' }] },
            ],
          },
          {
            type: 'bulletList',
            content: [
              { type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'one' }] }] },
            ],
          },
          {
            type: 'table',
            content: [
              {
                type: 'tableRow',
                content: [
                  {
                    type: 'tableCell',
                    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'a' }] }],
                  },
                ],
              },
            ],
          },
        ],
      }),
    ).toBe(true);
  });

  it('rejects an unknown inline node instead of silently dropping it', () => {
    expect(
      isRichDocument({
        type: 'doc',
        content: [{ type: 'paragraph', content: [{ type: 'mystery', text: 'x' }] }],
      }),
    ).toBe(false);
  });

  it('rejects a variable without a stable id or with an unknown type', () => {
    expect(
      isRichDocument({
        type: 'doc',
        content: [
          {
            type: 'paragraph',
            content: [
              { type: 'variableReference', attrs: { ...validVariable.attrs, variableId: '' } },
            ],
          },
        ],
      }),
    ).toBe(false);

    expect(
      isRichDocument({
        type: 'doc',
        content: [
          {
            type: 'paragraph',
            content: [
              { type: 'variableReference', attrs: { ...validVariable.attrs, valueType: 'money' } },
            ],
          },
        ],
      }),
    ).toBe(false);
  });

  it('rejects malformed blocks and nested children', () => {
    expect(isRichDocument({ type: 'doc', content: [{ type: 'quote' }] })).toBe(false);
    expect(
      isRichDocument({ type: 'doc', content: [{ type: 'heading', attrs: { level: 9 } }] }),
    ).toBe(false);
    expect(
      isRichDocument({
        type: 'doc',
        content: [{ type: 'table', content: [{ type: 'tableRow', content: [{ type: 'text', text: 'x' }] }] }],
      }),
    ).toBe(false);
  });
});