/**
 * Maps a TipTap selection onto the shared plain-text projection (design D3).
 *
 * Offsets are Unicode code points, not UTF-16 units. Variable-reference atoms occupy one ProseMirror
 * position but contribute their display value/placeholder to the projection, so the mapping walks the
 * block's inline nodes instead of using `textContent` alone.
 */

import type { Editor } from '@tiptap/react';

import type { AssistantSelection } from '../api/assistantTypes';
import type { InlineNode, RichDocument, VariableReferenceNode } from './richDocument';
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

const variableText = (node: VariableReferenceNode): string =>
  node.attrs.displayValue ?? `{{${node.attrs.label}}}`;

/** ProseMirror offset inside a block -> code-point offset in that block's projection. */
function pmToCodePoint(nodes: InlineNode[], target: number): number {
  let pm = 0;
  let cp = 0;
  for (const node of nodes) {
    if (node.type === 'text') {
      const value = node.text ?? '';
      if (target <= pm + value.length) {
        return cp + codePointLength(value.slice(0, Math.max(0, target - pm)));
      }
      pm += value.length;
      cp += codePointLength(value);
      continue;
    }
    if (node.type === 'variableReference') {
      const value = variableText(node);
      if (target <= pm) return cp;
      if (target <= pm + 1) return cp + codePointLength(value);
      pm += 1;
      cp += codePointLength(value);
      continue;
    }
    const value = (node.content ?? []).map((child) => child.text ?? '').join('');
    if (target <= pm + value.length) {
      return cp + codePointLength(value.slice(0, Math.max(0, target - pm)));
    }
    pm += value.length;
    cp += codePointLength(value);
  }
  return cp;
}

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
    const block = node.toJSON();
    blockIndex += 1;
    if (!span || !('content' in block)) return;

    const contentStart = offset + 1;
    const inlineContent = (block.content ?? []) as InlineNode[];
    const pmLength = inlineContent.reduce((total, item) => {
      if (item.type === 'text') return total + (item.text ?? '').length;
      if (item.type === 'variableReference') return total + 1;
      return total + (item.content ?? []).map((child) => child.text ?? '').join('').length;
    }, 0);
    if (from < contentStart || to > contentStart + pmLength) return;

    const relativeStart = pmToCodePoint(inlineContent, from - contentStart);
    const relativeEnd = pmToCodePoint(inlineContent, to - contentStart);
    const prefix = headingPrefixLength(node);
    // Offsets are code points, so slice the projection by characters, not UTF-16 units.
    const projected = Array.from(projection.text);
    const selectedText = projected
      .slice(span.start + prefix + relativeStart, span.start + prefix + relativeEnd)
      .join('');
    if (!selectedText) return;
    result = {
      nodeId: span.nodeId,
      startOffset: span.start + prefix + relativeStart,
      endOffset: span.start + prefix + relativeEnd,
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