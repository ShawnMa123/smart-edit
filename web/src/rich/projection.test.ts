// @vitest-environment node
/** Projection + selection are one implementation, in code points. */

import { describe, expect, it } from 'vitest';

import type { Editor } from '@tiptap/react';

import projectionFixture from '../../../fixtures/automation/variable_projection.json';
import type { InlineNode, RichDocument } from './richDocument';
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

describe('variable projection parity (1.3)', () => {
  it('matches the shared golden fixture, code points and block spans included', () => {
    const projection = projectDocument(projectionFixture.document as unknown as RichDocument);
    expect(projection.text).toBe(projectionFixture.expected_text);
    expect(
      projection.blocks.map(({ nodeId, start, end }) => ({ nodeId, start, end })),
    ).toEqual(projectionFixture.expected_blocks);
  });

  it('shows {{label}} for an empty variable and never invents a value', () => {
    const projection = projectDocument(
      doc([
        {
          type: 'paragraph',
          content: [
            { type: 'text', text: 'Beneficiary: ' },
            {
              type: 'variableReference',
              attrs: {
                variableId: 'var_beneficiary',
                label: 'beneficiary',
                valueType: 'string',
                required: true,
                displayValue: null,
              },
            },
          ],
        },
      ]),
    );
    expect(projection.text).toBe('Beneficiary: {{beneficiary}}');
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

/** ProseMirror positions inside one block: text in UTF-16 units, a variable atom as one position. */
const inlinePmLength = (node: InlineNode): number => {
  if (node.type === 'text') return (node.text ?? '').length;
  if (node.type === 'variableReference') return 1;
  return (node.content ?? []).reduce((sum, child) => sum + (child.text ?? '').length, 0);
};

/** The same fake projection the editor tests use: only block boundaries matter to `selectionFromEditor`. */
const editorWithSelection = (content: RichDocument, from: number, to: number): Editor => {
  const nodes = content.content.map((block) => ({
    type: { name: block.type },
    textContent:
      block.type === 'paragraph' || block.type === 'heading'
        ? (block.content ?? [])
            .map((node) => (node.type === 'text' ? node.text ?? '' : '{{variable}}'))
            .join('')
        : '',
    toJSON: () => block,
  }));
  const offsets: number[] = [];
  let offset = 0;
  for (const block of content.content) {
    offsets.push(offset);
    const pmLength =
      block.type === 'paragraph' || block.type === 'heading'
        ? (block.content ?? []).reduce((sum, node) => sum + inlinePmLength(node), 0)
        : 1;
    offset += 1 + pmLength;
  }
  return {
    state: {
      selection: { from, to },
      doc: {
        content: {
          forEach: (callback: (node: (typeof nodes)[number], at: number) => void) =>
            nodes.forEach((node, index) => callback(node, offsets[index])),
        },
        toJSON: () => content,
      },
    },
  } as unknown as Editor;
};

describe('selectionFromEditor: variable conversion boundaries (1.4)', () => {
  it('accepts a single-paragraph CJK/emoji selection in code points', () => {
    const content = doc([paragraph('Amount: 保函 😀 end')]);
    // Block content starts at PM position 1; "保函 😀" occupies 5 UTF-16 units (emoji is a pair).
    const selection = selectionFromEditor(editorWithSelection(content, 1 + 8, 1 + 8 + 5));

    expect(selection?.nodeId).toBe('b0');
    expect(selection?.selectedText).toBe('保函 😀');
    expect(selection?.startOffset).toBe(8);
    expect(selection?.endOffset).toBe(12);
  });

  it('accepts a heading selection relative to its hashes', () => {
    const content = doc([heading(2, 'Parties')]);
    const selection = selectionFromEditor(editorWithSelection(content, 1, 1 + 'Parties'.length));

    expect(selection?.selectedText).toBe('Parties');
    expect(selection?.startOffset).toBe(codePointLength('## '));
  });

  it('rejects a selection that crosses blocks', () => {
    const content = doc([paragraph('first'), paragraph('second')]);
    // Block 1 starts after "first" plus the two paragraph boundaries.
    const editor = editorWithSelection(content, 1, 1 + 5 + 2 + 3);

    expect(selectionFromEditor(editor)).toBeNull();
  });

  it('rejects a selection inside a table', () => {
    const content = doc([
      {
        type: 'table',
        content: [
          {
            type: 'tableRow',
            content: [{ type: 'tableCell', content: [paragraph('Amount')] }],
          },
        ],
      },
    ]);

    expect(selectionFromEditor(editorWithSelection(content, 1, 4))).toBeNull();
  });

  it('rejects an empty selection', () => {
    expect(selectionFromEditor(editorWithSelection(doc([paragraph('Amount')]), 2, 2))).toBeNull();
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