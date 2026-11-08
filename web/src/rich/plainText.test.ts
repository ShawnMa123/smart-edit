// @vitest-environment node
/** Tasks 0.1-0.3 — the rich model and the one projection the audit reads. */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { richToPlainText } from './plainText';
import {
  emptyDocument,
  isRichDocument,
  plainTextToDocument,
  type RichDocument,
} from './richDocument';

const doc = (content: RichDocument['content']): RichDocument => ({ type: 'doc', content });
const text = (value: string) => ({ type: 'text' as const, text: value });
const heading = (level: 1 | 2 | 3, value: string) =>
  ({ type: 'heading' as const, attrs: { level }, content: [text(value)] });
const paragraph = (value: string) =>
  ({ type: 'paragraph' as const, content: value ? [text(value)] : [] });

describe('the document model (0.1)', () => {
  it('accepts an empty document and rejects unknown blocks', () => {
    expect(isRichDocument(emptyDocument())).toBe(true);
    expect(isRichDocument({ type: 'doc', content: [{ ...paragraph('x'), type: 'video' }] })).toBe(
      false,
    );
    expect(isRichDocument({ type: 'paragraph' })).toBe(false);
    expect(isRichDocument(null)).toBe(false);
    expect(isRichDocument('doc')).toBe(false);
  });

  it('round-trips plain text through paragraphs', () => {
    const source = 'DEMAND GUARANTEE\nGuarantee No: BG-2026-00417';

    const restored = richToPlainText(plainTextToDocument(source));

    expect(restored).toBe(source);
  });
});

describe('the projection (0.2)', () => {
  it('marks headings with the matching number of hashes', () => {
    expect(richToPlainText(doc([heading(1, 'Contract'), heading(2, 'Parties'), heading(3, 'Buyer')])))
      .toBe('# Contract\n\n## Parties\n\n### Buyer');
  });

  it('projects both list kinds with their own markers', () => {
    const lists = doc([
      { type: 'bulletList', content: [{ type: 'listItem', content: [paragraph('first')] }] },
      {
        type: 'orderedList',
        content: [
          { type: 'listItem', content: [paragraph('second')] },
          { type: 'listItem', content: [paragraph('third')] },
        ],
      },
    ]);

    expect(richToPlainText(lists)).toBe('- first\n\n1. second\n2. third');
  });

  it('projects a table one line per row, cells joined with a pipe', () => {
    const table = doc([
      {
        type: 'table',
        content: [
          {
            type: 'tableRow',
            content: [
              { type: 'tableCell', attrs: { header: true }, content: [paragraph('Beneficiary')] },
              { type: 'tableCell', attrs: { header: true }, content: [paragraph('Adidas AG')] },
            ],
          },
          {
            type: 'tableRow',
            content: [
              { type: 'tableCell', content: [paragraph('Amount')] },
              { type: 'tableCell', content: [paragraph('USD 500,000.00')] },
            ],
          },
        ],
      },
    ]);

    expect(richToPlainText(table)).toBe('Beneficiary | Adidas AG\nAmount | USD 500,000.00');
  });

  it('drops marks but keeps every character of the value', () => {
    const marked = doc([
      {
        type: 'paragraph',
        content: [
          { type: 'text', text: 'Amount: ', marks: ['bold'] },
          { type: 'text', text: 'USD 500,000.00', marks: ['bold', 'italic', 'underline'] },
        ],
      },
    ]);

    expect(richToPlainText(marked)).toBe('Amount: USD 500,000.00');
  });

  it('keeps empty blocks, so paragraph breaks survive', () => {
    const spaced = doc([paragraph('one'), paragraph(''), paragraph('two')]);

    expect(richToPlainText(spaced)).toBe('one\n\n\n\ntwo');
  });

  it('is deterministic: the same document projects twice identically', () => {
    const sample = doc([heading(2, 'Parties'), paragraph('Alpha'), paragraph('Beta')]);

    expect(richToPlainText(sample)).toBe(richToPlainText(sample));
  });

  it('projects nothing for an empty or missing document', () => {
    expect(richToPlainText(emptyDocument())).toBe('');
    expect(richToPlainText(null)).toBe('');
    expect(richToPlainText(undefined)).toBe('');
  });
});

describe('plain-text regression (0.3)', () => {
  it('a pasted document projects back to exactly what was pasted', () => {
    const source = readFileSync(
      fileURLToPath(new URL('../../../fixtures/llm/sample_document.txt', import.meta.url)),
      'utf8',
    );

    const projected = richToPlainText(plainTextToDocument(source));

    // The file ends with a newline; a document cannot hold a trailing blank block, so compare closed.
    expect(projected.trimEnd()).toBe(source.trimEnd());
    expect(projected.split('\n\n')).toEqual(source.trimEnd().split('\n\n'));
  });

  it('multiple blank lines survive the round trip', () => {
    const source = 'first paragraph\n\nsecond paragraph\n\n\n\nfourth paragraph';

    expect(richToPlainText(plainTextToDocument(source))).toBe(source);
  });
});