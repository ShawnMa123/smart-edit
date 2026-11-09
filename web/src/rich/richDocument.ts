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
  /** A single visual row: render it as a flex row so its gaps can grow (design D22). */
  row?: boolean;
  /** A single fragment hugging the page's right edge (design D23). */
  align?: 'left' | 'right';
}

export interface ParagraphNode {
  type: 'paragraph';
  attrs?: BlockAttrs;
  content?: InlineNode[];
}

export interface HeadingNode {
  type: 'heading';
  attrs: { level: 1 | 2 | 3 } & BlockAttrs;
  content?: InlineNode[];
}

/**
 * A gap inside one visual row (design D22/D25-D27): a drawn blank (`rule`) or an invisible spacer
 * that pushes a TOC page number to the right. It is display-only when empty; a user may type a value
 * into it, and that value is then part of the document text (and of the audit projection).
 */
export interface PdfGapNode {
  type: 'pdfGap';
  attrs: { rule: boolean; grow: number };
  content?: TextNode[];
}

export type InlineNode = TextNode | PdfGapNode;

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