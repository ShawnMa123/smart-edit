/** Pure operations for variable-reference nodes (no React, no TipTap). */

import type {
  BlockNode,
  HeadingNode,
  InlineNode,
  ParagraphNode,
  RichDocument,
  VariableReferenceNode,
} from './richDocument';
import type { AssistantSelection } from '../api/assistantTypes';
import { codePointLength, projectDocument } from './projection';

export interface VariableOccurrence {
  variableId: string;
  occurrenceId: string;
  nodeId: string;
  start: number;
  end: number;
}

export interface VariableSummary {
  variableId: string;
  label: string;
  valueType: VariableReferenceNode['attrs']['valueType'];
  required: boolean;
  displayValue: string | null;
  occurrences: VariableOccurrence[];
}

export interface VariableDefinition {
  label: string;
  valueType: VariableReferenceNode['attrs']['valueType'];
  required: boolean;
}

let sequence = 0;

export const newVariableId = (): string => `var_${Date.now()}_${sequence++}`;
export const newOccurrenceId = (): string => `occ_${Date.now()}_${sequence++}`;

export const variableDisplay = (node: VariableReferenceNode): string =>
  node.attrs.displayValue ?? `{{${node.attrs.label}}}`;

const isVariable = (node: InlineNode): node is VariableReferenceNode =>
  node.type === 'variableReference';

function isParagraphOrHeading(
  block: BlockNode,
): block is ParagraphNode | HeadingNode {
  return block.type === 'paragraph' || block.type === 'heading';
}

/** Projected width of one inline node: a variable is one ProseMirror position but many characters. */
const inlineLength = (node: InlineNode): number =>
  isVariable(node)
    ? codePointLength(variableDisplay(node))
    : node.type === 'text'
      ? codePointLength(node.text ?? '')
      : codePointLength((node.content ?? []).map((child) => child.text ?? '').join(''));

/** The text one inline node contributes to the projection (empty nodes contribute nothing). */
const inlinePiece = (node: InlineNode): string =>
  isVariable(node)
    ? variableDisplay(node)
    : node.type === 'text'
      ? node.text ?? ''
      : (node.content ?? []).map((child) => child.text ?? '').join('');

/**
 * Replace `[from, to)` with one variable node, keeping every untouched node (including other
 * variable references) exactly as it was. A selection that touches an existing variable is rejected
 * rather than silently flattening it into text.
 */
function spliceVariable(
  nodes: InlineNode[],
  from: number,
  to: number,
  variable: VariableReferenceNode,
): InlineNode[] {
  const result: InlineNode[] = [];
  let position = 0;
  let inserted = false;
  for (const node of nodes) {
    const start = position;
    const end = start + inlineLength(node);
    position = end;
    if (end <= from || start >= to) {
      result.push(node);
      continue;
    }
    if (isVariable(node)) {
      throw new Error('selection overlaps an existing variable');
    }
    if (node.type === 'pdfGap') {
      throw new Error('selection covers a display gap; select ordinary text instead');
    }
    const chars = Array.from(node.text ?? '');
    const before = chars.slice(0, Math.max(0, from - start)).join('');
    const after = chars.slice(Math.min(chars.length, to - start)).join('');
    if (before) result.push({ ...node, text: before });
    if (!inserted) {
      result.push(variable);
      inserted = true;
    }
    if (after) result.push({ ...node, text: after });
  }
  if (!inserted) throw new Error('selection does not map to this block');
  return result;
}

export function collectVariables(document: RichDocument): VariableSummary[] {
  const projection = projectDocument(document);
  const spans = new Map(projection.blocks.map((span) => [span.nodeId, span]));
  const byId = new Map<string, VariableSummary>();
  const occurrenceCounts = new Map<string, number>();

  document.content.forEach((block, index) => {
    if (!isParagraphOrHeading(block)) return;
    const span = spans.get(`b${index}`);
    if (!span) return;
    const prefix =
      block.type === 'heading' ? codePointLength(`${'#'.repeat(block.attrs.level)} `) : 0;
    let offset = span.start + prefix;
    let projectedSoFar = '';
    for (const node of block.content ?? []) {
      const piece = inlinePiece(node);
      if (!piece) continue;
      // Mirror `projection.ts`: adjacent nodes get one separating space.
      if (projectedSoFar && !/\s$/.test(projectedSoFar) && !/^\s/.test(piece)) offset += 1;
      projectedSoFar += piece;
      if (!isVariable(node)) {
        offset += codePointLength(piece);
        continue;
      }
      const ordinal = occurrenceCounts.get(node.attrs.variableId) ?? 0;
      occurrenceCounts.set(node.attrs.variableId, ordinal + 1);
      // A stable fallback keeps React keys and occurrence lists identical across renders.
      const occurrenceId =
        node.attrs.occurrenceId ?? `${node.attrs.variableId}:b${index}:${ordinal}`;
      const end = offset + codePointLength(variableDisplay(node));
      const existing = byId.get(node.attrs.variableId);
      const occurrence = {
        variableId: node.attrs.variableId,
        occurrenceId,
        nodeId: `b${index}`,
        start: offset,
        end,
      };
      if (existing) {
        existing.occurrences.push(occurrence);
      } else {
        byId.set(node.attrs.variableId, {
          variableId: node.attrs.variableId,
          label: node.attrs.label,
          valueType: node.attrs.valueType,
          required: node.attrs.required,
          displayValue: node.attrs.displayValue,
          occurrences: [occurrence],
        });
      }
      offset = end;
    }
  });

  return Array.from(byId.values());
}

export function replaceSelectionWithVariable(
  document: RichDocument,
  selection: AssistantSelection,
  definition: VariableDefinition,
): RichDocument {
  const index = Number(selection.nodeId.replace(/^b/, ''));
  const block = document.content[index];
  if (!block || !isParagraphOrHeading(block)) {
    throw new Error('only a paragraph/heading selection can become a variable');
  }
  const projection = projectDocument(document);
  const span = projection.blocks.find((item) => item.nodeId === selection.nodeId);
  if (!span) throw new Error('unknown block');
  const prefix =
    block.type === 'heading' ? codePointLength(`${'#'.repeat(block.attrs.level)} `) : 0;
  const localStart = selection.startOffset - span.start - prefix;
  const localEnd = selection.endOffset - span.start - prefix;
  const content = block.content ?? [];
  const total = content.reduce((length, node) => length + inlineLength(node), 0);
  if (localStart < 0 || localEnd > total || localStart >= localEnd) {
    throw new Error('selection does not map to this block');
  }
  const variable: VariableReferenceNode = {
    type: 'variableReference',
    attrs: {
      variableId: newVariableId(),
      label: definition.label.trim() || 'variable',
      valueType: definition.valueType,
      required: definition.required,
      displayValue: selection.selectedText,
      occurrenceId: newOccurrenceId(),
    },
  };
  const updated = { ...block, content: spliceVariable(content, localStart, localEnd, variable) } as BlockNode;
  const next = [...document.content];
  next[index] = updated;
  return { ...document, content: next };
}

export function setVariableValue(
  document: RichDocument,
  variableId: string,
  value: string,
): RichDocument {
  const mapInline = (nodes: InlineNode[]): InlineNode[] =>
    nodes.map((node) => {
      if (isVariable(node)) {
        return node.attrs.variableId === variableId
          ? { ...node, attrs: { ...node.attrs, displayValue: value } }
          : node;
      }
      return node;
    });

  const mapBlock = (block: BlockNode): BlockNode => {
    if (block.type === 'paragraph') {
      return { ...block, content: mapInline(block.content ?? []) };
    }
    if (block.type === 'heading') {
      return { ...block, content: mapInline(block.content ?? []) };
    }
    if (block.type === 'table') {
      return {
        ...block,
        content: block.content.map((row) => ({
          ...row,
          content: row.content.map((cell) => ({
            ...cell,
            content: cell.content.map((paragraph) => ({
              ...paragraph,
              content: mapInline(paragraph.content ?? []),
            })),
          })),
        })),
      };
    }
    if (block.type === 'bulletList' || block.type === 'orderedList') {
      return {
        ...block,
        content: block.content.map((item) => ({
          ...item,
          content: item.content.map((paragraph) => ({
            ...paragraph,
            content: mapInline(paragraph.content ?? []),
          })),
        })),
      };
    }
    return block;
  };

  return { ...document, content: document.content.map(mapBlock) };
}