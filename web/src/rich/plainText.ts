/**
 * The one deterministic projection from the rich document to the text the audit reads (design D3).
 *
 * Rules, and nothing else:
 *
 * | node            | projection                                  |
 * |-----------------|---------------------------------------------|
 * | heading(level)  | `#` x level + space + text                  |
 * | paragraph       | text (marks are dropped)                    |
 * | bulletList item | `- ` + text                                 |
 * | orderedList     | `1. `, `2. ` … + text                       |
 * | table row       | cell texts joined with ` | `                |
 * | between blocks  | one blank line (`\n\n`)                     |
 *
 * Marks are dropped on purpose: the audit judges values, and `**USD 500,000.00**` would feed noise into
 * the charset/length rules. Structure is kept because it carries meaning a human (and a rule) can read.
 */

import type {
  BlockNode,
  InlineNode,
  ListItemNode,
  RichDocument,
  TableCellNode,
} from './richDocument';

const textOf = (nodes: InlineNode[] | undefined): string => {
  let text = '';
  for (const node of nodes ?? []) {
    const isGap = node.type !== 'text';
    const piece = node.type === 'text' ? (node.text ?? '') : textOf(node.content);
    if (!piece) continue;
    // A filled blank is document text: keep one readable space at the text↔blank boundary. Adjacent
    // text runs are one sentence split only by marks, so joining them must not add a character.
    if (isGap && text && !/\s$/.test(text) && !/^\s/.test(piece)) text += ' ';
    text += piece;
  }
  return text;
};

const cellText = (cell: TableCellNode): string =>
  (cell.content ?? []).map((paragraph) => textOf(paragraph.content)).join(' ');

const itemText = (item: ListItemNode): string =>
  (item.content ?? []).map((paragraph) => textOf(paragraph.content)).join(' ');

function projectBlock(block: BlockNode): string {
  switch (block.type) {
    case 'pageBreak':
      // A page boundary is a display marker: it must not add a single character to the audit text.
      return '';
    case 'paragraph':
      return textOf(block.content);
    case 'heading':
      return `${'#'.repeat(block.attrs.level)} ${textOf(block.content)}`;
    case 'bulletList':
      return block.content.map((item) => `- ${itemText(item)}`).join('\n');
    case 'orderedList':
      return block.content
        .map((item, index) => `${index + 1}. ${itemText(item)}`)
        .join('\n');
    case 'table':
      return block.content
        .map((row) => row.content.map(cellText).join(' | '))
        .join('\n');
    default:
      return '';
  }
}

/**
 * The audit's only view of a rich document. Same document ⇒ same string, every time.
 *
 * Empty blocks are kept: they are what makes `plainTextToDocument` a true round trip, and dropping them
 * would silently join paragraphs that the user separated.
 */
export function richToPlainText(document: RichDocument | null | undefined): string {
  if (!document || !Array.isArray(document.content)) return '';
  return document.content
    .filter((block) => block.type !== 'pageBreak')
    .map(projectBlock)
    .join('\n\n');
}