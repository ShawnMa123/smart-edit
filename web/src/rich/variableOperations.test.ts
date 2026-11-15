/** Variable nodes: collection, selection conversion, and value fill (tasks 3.2-3.4). */

import { describe, expect, it } from 'vitest';

import type {
  ParagraphNode,
  RichDocument,
  VariableReferenceNode,
} from './richDocument';
import { projectDocument } from './projection';
import {
  collectVariables,
  replaceSelectionWithVariable,
  setVariableValue,
} from './variableOperations';

const text = (value: string) => ({ type: 'text' as const, text: value });

const variable = (
  variableId: string,
  label: string,
  displayValue: string | null,
  occurrenceId?: string,
): VariableReferenceNode => ({
  type: 'variableReference',
  attrs: { variableId, label, valueType: 'string', required: false, displayValue, occurrenceId },
});

const paragraph = (content: ParagraphNode['content']): ParagraphNode => ({
  type: 'paragraph',
  content,
});

const doc = (...content: RichDocument['content']): RichDocument => ({ type: 'doc', content });

const selectText = (document: RichDocument, value: string) => {
  const start = projectDocument(document).text.indexOf(value);
  if (start < 0) throw new Error(`missing ${value}`);
  return {
    nodeId: 'b0',
    startOffset: start,
    endOffset: start + Array.from(value).length,
    selectedText: value,
  };
};

describe('collectVariables', () => {
  it('lists every occurrence with a stable id even when the node has none', () => {
    const document = doc(
      paragraph([text('A '), variable('v1', 'amount', '1'), text(' B '), variable('v1', 'amount', '1')]),
    );

    const first = collectVariables(document);
    const second = collectVariables(document);

    expect(first).toHaveLength(1);
    expect(first[0].occurrences.map((occurrence) => occurrence.occurrenceId)).toEqual([
      'v1:b0:0',
      'v1:b0:1',
    ]);
    expect(first[0].occurrences.map((occurrence) => occurrence.start)).toEqual([2, 6]);
    expect(second).toEqual(first);
  });

  it('reports the placeholder for an empty value', () => {
    const document = doc(paragraph([variable('v1', 'beneficiary', null)]));
    expect(projectDocument(document).text).toBe('{{beneficiary}}');
    expect(collectVariables(document)[0].displayValue).toBeNull();
  });
});

describe('replaceSelectionWithVariable', () => {
  it('keeps existing nodes, including another variable, and only replaces the selection', () => {
    const existing = variable('v_amount', 'amount', '100');
    const document = doc(paragraph([text('Total '), existing, text(' and 200')]));

    const next = replaceSelectionWithVariable(document, selectText(document, '200'), {
      label: 'extra',
      valueType: 'string',
      required: false,
    });

    const block = next.content[0] as ParagraphNode;
    expect(block.content?.map((node) => node.type)).toEqual([
      'text',
      'variableReference',
      'text',
      'variableReference',
    ]);
    expect(block.content?.[1]).toBe(existing);
    expect(projectDocument(next).text).toBe('Total 100 and 200');
    expect(collectVariables(next).map((entry) => entry.label)).toEqual(['amount', 'extra']);
  });

  it('rejects a selection that overlaps an existing variable', () => {
    const document = doc(paragraph([text('Total '), variable('v_amount', 'amount', '100')]));

    expect(() =>
      replaceSelectionWithVariable(document, selectText(document, '100'), {
        label: 'again',
        valueType: 'string',
        required: false,
      }),
    ).toThrow(/overlaps an existing variable/);
  });

  it('uses code points for CJK and emoji selections', () => {
    const document = doc(paragraph([text('金额: 😀保函')]));

    const next = replaceSelectionWithVariable(document, selectText(document, '😀保函'), {
      label: '担保金额',
      valueType: 'amount',
      required: true,
    });

    expect(projectDocument(next).text).toBe('金额: 😀保函');
    const created = collectVariables(next)[0];
    expect(created.displayValue).toBe('😀保函');
    expect(created.occurrences[0]).toMatchObject({ start: 4, end: 7 });
  });
});

describe('setVariableValue', () => {
  it('updates every occurrence and leaves same-named ordinary text alone', () => {
    const document = doc(
      paragraph([text('Amount '), variable('v1', 'amount', '100', 'occ_1')]),
      paragraph([text('100 is ordinary text')]),
      paragraph([text('Again '), variable('v1', 'amount', '100', 'occ_2')]),
    );

    const next = setVariableValue(document, 'v1', '250');

    expect(projectDocument(next).text).toBe(
      'Amount 250\n\n100 is ordinary text\n\nAgain 250',
    );
    expect(collectVariables(next)[0].occurrences).toHaveLength(2);
    expect(collectVariables(next)[0].displayValue).toBe('250');
  });

  it('updates variables nested in a table cell without touching the cell text', () => {
    const document = doc({
      type: 'table',
      content: [
        {
          type: 'tableRow',
          content: [
            {
              type: 'tableCell',
              content: [paragraph([text('Again '), variable('v1', 'amount', '100')])],
            },
          ],
        },
      ],
    });

    const next = setVariableValue(document, 'v1', '250');

    expect(projectDocument(next).text).toBe('Again 250');
  });

  it('returns an equivalent document when the variable id is unknown', () => {
    const document = doc(paragraph([variable('v1', 'amount', '100')]));
    expect(setVariableValue(document, 'missing', '250')).toEqual(document);
  });
});