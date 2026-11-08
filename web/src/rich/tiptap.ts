/**
 * TipTap wiring (`rich-text-editor` D1): the extension list and the document conversion.
 *
 * The editor's JSON is deliberately the same shape as `RichDocument`, so conversion is a validation,
 * not a translation — one less place where the audit's text can drift from what the user sees.
 */

import { FindAndReplace } from '@tiptap/extension-find-and-replace';
import { TableKit } from '@tiptap/extension-table';
import { Underline } from '@tiptap/extension-underline';
import type { JSONContent } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';

import { isRichDocument, type RichDocument } from './richDocument';

/** Everything ED-02 asks for that the library provides in one place. */
export const extensions = [
  StarterKit.configure({
    heading: { levels: [1, 2, 3] },
    // History is part of StarterKit; undo/redo come with it.
  }),
  Underline,
  TableKit.configure({ table: { resizable: false } }),
  FindAndReplace.configure({ searchTerm: '', searchDebounceMs: 0 }),
];

type AnyNode = {
  type?: string;
  attrs?: Record<string, unknown>;
  content?: AnyNode[];
  text?: string;
  marks?: unknown[];
  [key: string]: unknown;
};

/** Editor JSON (marks as `{type}`) -> our model (marks as names). */
const marksToNames = (node: AnyNode): AnyNode => ({
  ...node,
  ...(Array.isArray(node.marks)
    ? { marks: node.marks.map((mark) => (typeof mark === 'string' ? mark : (mark as AnyNode).type)) }
    : {}),
  ...(Array.isArray(node.content) ? { content: node.content.map(marksToNames) } : {}),
});

/** Our model (marks as names) -> editor JSON (marks as `{type}`). */
const marksToObjects = (node: AnyNode): AnyNode => ({
  ...node,
  ...(Array.isArray(node.marks)
    ? {
        marks: node.marks.map((mark) =>
          typeof mark === 'string' ? { type: mark } : mark,
        ),
      }
    : {}),
  ...(Array.isArray(node.content) ? { content: node.content.map(marksToObjects) } : {}),
});

/** Our model -> editor content. */
export function toEditorContent(document: RichDocument): JSONContent {
  return marksToObjects(document as unknown as AnyNode) as unknown as JSONContent;
}

/** Editor JSON -> our model. A malformed payload becomes an empty document, never a crash. */
export function toRichDocument(json: unknown): RichDocument {
  if (!json || typeof json !== 'object') return { type: 'doc', content: [] };
  const normalised = marksToNames(json as AnyNode);
  if (!isRichDocument(normalised)) return { type: 'doc', content: [] };
  const document = normalised as unknown as RichDocument;
  return {
    type: 'doc',
    content: document.content,
    ...(document.provenance ? { provenance: document.provenance } : {}),
    ...(document.provenanceNote ? { provenanceNote: document.provenanceNote } : {}),
  };
}