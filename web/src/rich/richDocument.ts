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

/**
 * A document-local variable reference. `displayValue` is the current rendered value; when it is
 * null the editor/projection show `{{label}}` instead of inventing a value.
 */
export interface VariableReferenceNode {
  type: 'variableReference';
  attrs: {
    variableId: string;
    label: string;
    valueType: 'string' | 'amount' | 'date' | 'currency';
    required: boolean;
    displayValue: string | null;
    occurrenceId?: string;
  };
}

export type InlineNode = TextNode | PdfGapNode | VariableReferenceNode;

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
  /** TipTap emits `tableHeader` for a header row; both project the same way. */
  type: 'tableCell' | 'tableHeader';
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

const VALUE_TYPES = new Set(['string', 'amount', 'date', 'currency']);

export const emptyDocument = (): RichDocument => ({ type: 'doc', content: [] });

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

function isTextNode(node: unknown): boolean {
  return isRecord(node) && node.type === 'text' && typeof node.text === 'string';
}

function isVariableNode(node: Record<string, unknown>): boolean {
  const attrs = node.attrs;
  return (
    isRecord(attrs) &&
    typeof attrs.variableId === 'string' &&
    attrs.variableId.length > 0 &&
    typeof attrs.label === 'string' &&
    attrs.label.length > 0 &&
    typeof attrs.valueType === 'string' &&
    VALUE_TYPES.has(attrs.valueType) &&
    typeof attrs.required === 'boolean' &&
    (attrs.displayValue === null || typeof attrs.displayValue === 'string') &&
    (attrs.occurrenceId === undefined ||
      attrs.occurrenceId === null ||
      typeof attrs.occurrenceId === 'string')
  );
}

/** `text` | `pdfGap` (text children) | `variableReference`; anything else is rejected. */
function isInlineNode(node: unknown): boolean {
  if (!isRecord(node)) return false;
  switch (node.type) {
    case 'text':
      return typeof node.text === 'string';
    case 'variableReference':
      return isVariableNode(node);
    case 'pdfGap':
      return node.content === undefined || (Array.isArray(node.content) && node.content.every(isTextNode));
    default:
      return false;
  }
}

function isInlineContent(value: unknown): boolean {
  return value === undefined || (Array.isArray(value) && value.every(isInlineNode));
}

function isListItem(node: unknown): boolean {
  return (
    isRecord(node) &&
    node.type === 'listItem' &&
    Array.isArray(node.content) &&
    node.content.every((paragraph) => isRecord(paragraph) && paragraph.type === 'paragraph' && isInlineContent(paragraph.content))
  );
}

function isTableCell(node: unknown): boolean {
  return (
    isRecord(node) &&
    (node.type === 'tableCell' || node.type === 'tableHeader') &&
    Array.isArray(node.content) &&
    node.content.every((paragraph) => isRecord(paragraph) && paragraph.type === 'paragraph' && isInlineContent(paragraph.content))
  );
}

function isTableRow(node: unknown): boolean {
  return (
    isRecord(node) &&
    node.type === 'tableRow' &&
    Array.isArray(node.content) &&
    node.content.every(isTableCell)
  );
}

function isBlockNode(node: unknown): boolean {
  if (!isRecord(node)) return false;
  switch (node.type) {
    case 'paragraph':
      return isInlineContent(node.content);
    case 'heading': {
      const level = isRecord(node.attrs) ? Number(node.attrs.level) : NaN;
      return [1, 2, 3].includes(level) && isInlineContent(node.content);
    }
    case 'pageBreak':
      return true;
    case 'bulletList':
    case 'orderedList':
      return Array.isArray(node.content) && node.content.every(isListItem);
    case 'table':
      return Array.isArray(node.content) && node.content.every(isTableRow);
    default:
      return false;
  }
}

/** Structural guard: enough to reject a malformed payload before the editor sees it. */
export function isRichDocument(value: unknown): value is RichDocument {
  if (!isRecord(value) || value.type !== 'doc' || !Array.isArray(value.content)) return false;
  return value.content.every(isBlockNode);
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