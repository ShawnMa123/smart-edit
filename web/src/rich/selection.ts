/**
 * Maps a TipTap selection onto the shared plain-text projection (design D3).
 *
 * Offsets are Unicode code points, not UTF-16 units: the server slices Python strings by code point.
 * A selection is still limited to one paragraph/heading block in this build; other selections return
 * `null` rather than guessing a range.
 */

import type { Editor } from '@tiptap/react';

import type { AssistantSelection } from '../api/assistantTypes';
import type { RichDocument } from './richDocument';
import { codePointLength, projectDocument } from './projection';

interface ProjectableNode {
  type: { name: string };
  textContent: string;
  toJSON: () => RichDocument['content'][number];
}

interface ProjectableDoc {
  content: { forEach: (callback: (node: ProjectableNode, offset: number) => void) => void };
  toJSON: () => RichDocument;
}

const headingPrefixLength = (node: ProjectableNode): number => {
  if (node.type.name !== 'heading') return 0;
  const attrs = (node.toJSON() as { attrs?: { level?: number } }).attrs;
  const level = Math.max(1, Math.min(6, Number(attrs?.level ?? 1)));
  return codePointLength(`${'#'.repeat(level)} `);
};

export function selectionFromEditor(editor: Editor): AssistantSelection | null {
  const { from, to } = editor.state.selection;
  if (from === to) return null;

  const doc = (editor.state.doc as unknown as ProjectableDoc).toJSON();
  const projection = projectDocument(doc);
  const spans = new Map(projection.blocks.map((span) => [span.nodeId, span]));

  let result: AssistantSelection | null = null;
  let blockIndex = 0;
  (editor.state.doc as unknown as ProjectableDoc).content.forEach((node, offset) => {
    if (result || (node.type.name !== 'paragraph' && node.type.name !== 'heading')) {
      blockIndex += 1;
      return;
    }
    const span = spans.get(`b${blockIndex}`);
    blockIndex += 1;
    if (!span) return;

    const contentStart = offset + 1;
    const contentEnd = contentStart + node.textContent.length;
    if (from < contentStart || to > contentEnd) return;

    const textBefore = node.textContent.slice(0, from - contentStart);
    const selectedText = node.textContent.slice(from - contentStart, to - contentStart);
    if (!selectedText) return;
    const startOffset = span.start + headingPrefixLength(node) + codePointLength(textBefore);
    result = {
      nodeId: span.nodeId,
      startOffset,
      endOffset: startOffset + codePointLength(selectedText),
      selectedText,
    };
  });

  return result;
}

/** The textarea fallback has no blocks; the whole projection is one block. */
export function selectionFromTextarea(
  value: string,
  start: number,
  end: number,
): AssistantSelection | null {
  if (start === end) return null;
  const selectedText = value.slice(start, end);
  if (!selectedText) return null;
  const startOffset = codePointLength(value.slice(0, start));
  return {
    nodeId: 'block_0',
    startOffset,
    endOffset: startOffset + codePointLength(selectedText),
    selectedText,
  };
}