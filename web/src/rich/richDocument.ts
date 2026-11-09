/**
 * The rich document model (`rich-text-editor` D2/D4/D5).
 *
 * Deliberately the same shape TipTap/ProseMirror uses (`{type, attrs, content}`), so converting between
 * the editor and this model is a pass-through rather than a translation layer. It is **client-only**: the
 * audit never receives it — `richToPlainText()` is the only thing that crosses that boundary.
 */

export type Mark = 'bold' | 'italic' | 'underline';

/** Where a block came from. Imported structure is never presented as a document fact (D5). */
export type Provenance = 'deterministic' | 'heuristic' | 'fallback';

export interface TextNode {
  type: 'text';
  text: string;
  marks?: Mark[];
}

/** Display-only facts a PDF gives us; they never reach the audit text (`plainText.ts` ignores them). */
export interface BlockAttrs {
  fontSize?: number;
  fontFamily?: string;
  page?: number;
}

export interface ParagraphNode {
  type: 'paragraph';
  attrs?: BlockAttrs;
  content?: TextNode[];
}

export interface HeadingNode {
  type: 'heading';
  attrs: { level: 1 | 2 | 3 } & BlockAttrs;
  content?: TextNode[];
}

/** A page boundary: visible in the editor, contributes no characters to the audit text. */
export interface PageBreakNode {
  type: 'pageBreak';
}

export interface ListItemNode {
  type: 'listItem';
  /** Single-level lists in this build (design Non-Goals): one paragraph per item. */
  content: ParagraphNode[];
}

export interface BulletListNode {
  type: 'bulletList';
  content: ListItemNode[];
}

export interface OrderedListNode {
  type: 'orderedList';
  content: ListItemNode[];
}

export interface TableCellNode {
  type: 'tableCell';
  attrs?: { header?: boolean };
  content: ParagraphNode[];
}

export interface TableRowNode {
  type: 'tableRow';
  content: TableCellNode[];
}

export interface TableNode {
  type: 'table';
  content: TableRowNode[];
}

export type BlockNode =
  | ParagraphNode
  | HeadingNode
  | BulletListNode
  | OrderedListNode
  | TableNode
  | PageBreakNode;

export interface RichDocument {
  type: 'doc';
  content: BlockNode[];
  /** Set when the document came from an import; absent for hand-typed documents. */
  provenance?: Provenance;
  /** Human-readable reason for a `heuristic`/`fallback` provenance (e.g. `font_size_1.42x`). */
  provenanceNote?: string;
}

const BLOCK_TYPES = new Set([
  'paragraph',
  'heading',
  'bulletList',
  'orderedList',
  'table',
  'pageBreak',
]);

export const emptyDocument = (): RichDocument => ({ type: 'doc', content: [] });

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

/** Structural guard: enough to reject a malformed payload before the editor sees it. */
export function isRichDocument(value: unknown): value is RichDocument {
  if (!isRecord(value) || value.type !== 'doc' || !Array.isArray(value.content)) return false;
  return value.content.every((block) => isRecord(block) && BLOCK_TYPES.has(String(block.type)));
}

/**
 * Legacy/plain text -> document, one paragraph per blank-line-separated block.
 *
 * This is the bridge that keeps pre-rich behaviour intact: a document derived this way projects back to
 * exactly the text it came from (see `plainText.test.ts`), so a user who only ever pasted text sees no
 * change at all.
 */
export function plainTextToDocument(text: string): RichDocument {
  const blocks = (text ?? '').split('\n\n');
  return {
    type: 'doc',
    content: blocks.map((block) => ({
      type: 'paragraph' as const,
      content: block ? [{ type: 'text' as const, text: block }] : [],
    })),
  };
}