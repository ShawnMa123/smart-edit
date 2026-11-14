// @vitest-environment node
/** Projection + selection are one implementation, in code points. */

import { describe, expect, it } from 'vitest';

import type { Editor } from '@tiptap/react';

import type { RichDocument } from './richDocument';
import { codePointLength, projectDocument } from './projection';
import { selectionFromEditor, selectionFromTextarea } from './selection';

const text = (value: string) => ({ type: 'text' as const, text: value });
const paragraph = (value: string) => ({ type: 'paragraph' as const, content: [text(value)] });
const heading = (level: 1 | 2 | 3, value: string) => ({
  type: 'heading' as const,
  attrs: { level },
  content: [text(value)],
});

const doc = (content: RichDocument['content']): RichDocument => ({ type: 'doc', content });

describe('projectDocument', () => {
  it('skips a page break without adding a character or separator', () => {
    const projection = projectDocument(doc([paragraph('page one'), { type: 'pageBreak' }, paragraph('page two')]));
    expect(projection.text).toBe('page one\n\npage two');
    expect(projection.blocks.map((block) => block.nodeId)).toEqual(['b0', 'b2']);
    expect(projection.blocks[1].start).toBe(codePointLength('page one\n\n'));
  });

  it('measures spans in code points, not UTF-16 units', () => {
    const projection = projectDocument(doc([paragraph('A😀B')]));
    expect(projection.text).toBe('A😀B');
    expect(Array.from(projection.text).slice(1, 2).join('')).toBe('😀');
    expect(projection.blocks[0].end).toBe(3);
  });

  it('keeps heading and table projections stable', () => {
    const projection = projectDocument(
      doc([
        heading(2, 'Parties'),
        {
          type: 'table',
          content: [
            {
              type: 'tableRow',
              content: [
                { type: 'tableCell', content: [paragraph('Amount')] },
                { type: 'tableCell', content: [paragraph('USD 500,000.00')] },
              ],
            },
          ],
        },
      ]),
    );
    expect(projection.text).toBe('## Parties\n\nAmount | USD 500,000.00');
  });
});

describe('selectionFromTextarea', () => {
  it('returns code-point offsets around an emoji', () => {
    expect(selectionFromTextarea('A😀B', 1, 3)).toEqual({
      nodeId: 'block_0',
      startOffset: 1,
      endOffset: 2,
      selectedText: '😀',
    });
  });
});

describe('selectionFromEditor', () => {
  it('matches the projection after a page break', () => {
    const content = doc([paragraph('page one'), { type: 'pageBreak' }, paragraph('Amount: USD 500,000.00')]);
    const nodes = content.content.map((block) => ({
      type: { name: block.type },
      textContent: block.type === 'pageBreak' ? '' : (block as { content: { text: string }[] }).content.map((node) => node.text).join(''),
      toJSON: () => block,
    }));
    const offsets: number[] = [];
    let offset = 0;
    for (const node of nodes) {
      offsets.push(offset);
      offset += 1 + node.textContent.length;
    }
    const editor = {
      state: {
        selection: { from: offsets[2] + 1, to: offsets[2] + 1 + 'Amount'.length },
        doc: {
          content: {
            forEach: (callback: (node: (typeof nodes)[number], at: number) => void) =>
              nodes.forEach((node, index) => callback(node, offsets[index])),
          },
          toJSON: () => content,
        },
      },
    } as unknown as Editor;

    const selection = selectionFromEditor(editor);
    expect(selection?.nodeId).toBe('b2');
    expect(selection?.startOffset).toBe(codePointLength('page one\n\n'));
    expect(selection?.selectedText).toBe('Amount');
  });
});