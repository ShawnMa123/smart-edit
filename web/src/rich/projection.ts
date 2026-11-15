/**
 * The one deterministic rich-document projection (design D3).
 *
 * Same rules as the audit projection, plus code-point block spans used by anchors. A `pageBreak`
 * contributes no character and no separator; blocks are joined with one blank line.
 */

import type {
  BlockNode,
  InlineNode,
  ListItemNode,
  RichDocument,
  TableCellNode,
} from './richDocument';

export interface BlockSpan {
  nodeId: string;
  /** Inclusive start in Unicode code points. */
  start: number;
  /** Exclusive end in Unicode code points. */
  end: number;
}

export interface Projection {
  text: string;
  blocks: BlockSpan[];
}

/** JS string length counts UTF-16 units; anchors and the server use code points. */
export const codePointLength = (value: string): number => Array.from(value).length;

const inlineText = (nodes: InlineNode[] | undefined): string => {
  let text = '';
  for (const node of nodes ?? []) {
    let piece = '';
    if (node.type === 'text') {
      piece = node.text ?? '';
    } else if (node.type === 'variableReference') {
      piece = node.attrs.displayValue ?? `{{${node.attrs.label}}}`;
    } else {
      piece = inlineText(node.content);
    }
    if (!piece) continue;
    if (text && !/\s$/.test(text) && !/^\s/.test(piece)) text += ' ';
    text += piece;
  }
  return text;
};

const cellText = (cell: TableCellNode): string =>
  (cell.content ?? []).map((paragraph) => inlineText(paragraph.content)).join(' ');

const itemText = (item: ListItemNode): string =>
  (item.content ?? []).map((paragraph) => inlineText(paragraph.content)).join(' ');

function projectBlock(block: BlockNode): string | null {
  switch (block.type) {
    case 'pageBreak':
      return null;
    case 'paragraph':
      return inlineText(block.content);
    case 'heading':
      return `${'#'.repeat(block.attrs.level)} ${inlineText(block.content)}`;
    case 'bulletList':
      return block.content.map((item) => `- ${itemText(item)}`).join('\n');
    case 'orderedList':
      return block.content
        .map((item, index) => `${index + 1}. ${itemText(item)}`)
        .join('\n');
    case 'table':
      return block.content.map((row) => row.content.map(cellText).join(' | ')).join('\n');
    default:
      return '';
  }
}

export function projectDocument(document: RichDocument | null | undefined): Projection {
  if (!document || !Array.isArray(document.content)) return { text: '', blocks: [] };

  const parts: string[] = [];
  const blocks: BlockSpan[] = [];
  let current = 0;
  let first = true;
  document.content.forEach((block, index) => {
    const projected = projectBlock(block);
    if (projected === null) return;
    if (!first) current += 2;
    const start = current;
    parts.push(projected);
    current += codePointLength(projected);
    blocks.push({ nodeId: `b${index}`, start, end: current });
    first = false;
  });
  return { text: parts.join('\n\n'), blocks };
}

/** Legacy/plain text -> paragraphs; kept here so the projection owns the shape. */
export function plainTextDocument(text: string): RichDocument {
  const blocks = (text ?? '').split('\n\n');
  return {
    type: 'doc',
    content: blocks.map((block) => ({
      type: 'paragraph' as const,
      content: block ? [{ type: 'text' as const, text: block }] : [],
    })),
  };
}