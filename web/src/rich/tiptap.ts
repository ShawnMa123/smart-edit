/**
 * TipTap wiring (`rich-text-editor` D1): the extension list and the document conversion.
 *
 * The editor's JSON is deliberately the same shape as `RichDocument`, so conversion is a validation,
 * not a translation — one less place where the audit's text can drift from what the user sees.
 */

import { Node, Extension, mergeAttributes } from '@tiptap/core';
import { FindAndReplace } from '@tiptap/extension-find-and-replace';
import { TableKit } from '@tiptap/extension-table';
import type { JSONContent } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';

import { isRichDocument, type RichDocument } from './richDocument';

/**
 * Display-only attributes (design D14): a PDF block knows its size, font and page. They are rendered so
 * the editor looks like the original, and `richToPlainText` ignores them entirely.
 */
const DisplayAttributes = Extension.create({
  name: 'displayAttributes',
  addGlobalAttributes() {
    return [
      {
        types: ['paragraph', 'heading'],
        attributes: {
          fontSize: {
            default: null,
            parseHTML: (element) => element.getAttribute('data-font-size'),
            renderHTML: (attributes) =>
              attributes.fontSize
                ? { 'data-font-size': String(attributes.fontSize), style: `font-size:${attributes.fontSize}pt` }
                : {},
          },
          fontFamily: {
            default: null,
            parseHTML: (element) => element.getAttribute('data-font-family'),
            renderHTML: (attributes) =>
              attributes.fontFamily
                ? {
                    'data-font-family': String(attributes.fontFamily),
                    style: `font-family:'${attributes.fontFamily}'`,
                  }
                : {},
          },
          page: {
            default: null,
            parseHTML: (element) => element.getAttribute('data-page'),
            renderHTML: (attributes) =>
              attributes.page ? { 'data-page': String(attributes.page) } : {},
          },
          row: {
            default: null,
            parseHTML: (element) => element.getAttribute('data-pdf-row') === 'true',
            renderHTML: (attributes) => (attributes.row ? { 'data-pdf-row': 'true' } : {}),
          },
          align: {
            default: null,
            parseHTML: (element) => element.getAttribute('data-pdf-align'),
            renderHTML: (attributes) =>
              attributes.align ? { 'data-pdf-align': String(attributes.align) } : {},
          },
        },
      },
    ];
  },
});

/** A page boundary the reader can see; it carries no text (design D15). */
const PageBreak = Node.create({
  name: 'pageBreak',
  group: 'block',
  atom: true,
  selectable: true,
  parseHTML: () => [{ tag: 'hr[data-page-break]' }],
  renderHTML: () => ['hr', { 'data-page-break': 'true', class: 'page-break' }],
});

/** A gap inside one visual row: a drawn blank or a spacer; it may hold user-entered text (D22/D25-D27). */
const PdfGap = Node.create({
  name: 'pdfGap',
  group: 'inline',
  inline: true,
  content: 'text*',
  selectable: false,
  draggable: false,
  addAttributes() {
    return {
      rule: { default: false },
      grow: { default: 1 },
    };
  },
  parseHTML: () => [
    {
      tag: 'span[data-pdf-gap]',
      getAttrs: (element) => ({
        rule: element.getAttribute('data-pdf-rule') === 'true',
        grow: Number(element.getAttribute('data-pdf-grow') ?? 1),
      }),
    },
  ],
  renderHTML({ HTMLAttributes }) {
    const { rule, grow, ...rest } = HTMLAttributes;
    const visible = Boolean(rule);
    return [
      'span',
      mergeAttributes(rest, {
        'data-pdf-gap': 'true',
        'data-pdf-rule': visible ? 'true' : 'false',
        'data-pdf-grow': String(grow ?? 1),
        class: visible ? 'pdf-gap pdf-gap--rule' : 'pdf-gap',
        style: `flex-grow:${grow ?? 1}`,
      }),
      0,
    ];
  },
});

/** Everything ED-02 asks for that the library provides in one place. */
export const extensions = [
  StarterKit.configure({
    heading: { levels: [1, 2, 3] },
    // History is part of StarterKit; undo/redo come with it. Underline is part of StarterKit too
    // (v3), so adding `Underline` separately would register the same extension twice.
  }),
  TableKit.configure({ table: { resizable: false } }),
  FindAndReplace.configure({ searchTerm: '', searchDebounceMs: 0 }),
  DisplayAttributes,
  PageBreak,
  PdfGap,
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