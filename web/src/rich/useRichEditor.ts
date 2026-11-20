/**
 * The TipTap hook, wrapped so the fallback path has one seam (`rich-text-editor` D10).
 *
 * Kept out of the component on purpose: a test can replace this module to make the editor fail to
 * start, which is the only realistic way `RichEditor` falls back to a textarea.
 */

import { useEditor, type Editor } from '@tiptap/react';
import { useEffect, useRef } from 'react';

import type { RichDocument } from './richDocument';
import { extensions, toEditorContent, toRichDocument } from './tiptap';

export interface UseRichEditorOptions {
  document: RichDocument;
  onChange: (document: RichDocument) => void;
  /** Approval read-only mode: the document is frozen for this role/status. */
  editable?: boolean;
}

export function useRichEditor({ document, onChange, editable = true }: UseRichEditorOptions): Editor | null {
  // The last document the editor itself produced. The parent echoes it back as a prop; tracking the
  // exact object is what lets the effect tell "my own edit" from "an import/version restore".
  const applied = useRef<RichDocument>(document);

  const editor = useEditor({
    extensions,
    content: toEditorContent(document),
    editable,
    editorProps: {
      attributes: {
        class: 'editor-rich',
        'aria-label': 'Document text',
      },
    },
    onUpdate: ({ editor: instance }) => {
      const next = toRichDocument(instance.getJSON());
      // Import provenance is document-level metadata, not part of the TipTap schema. Carry it
      // forward so an edited import can still be described honestly (never invented).
      const inherited = applied.current.provenance
        ? {
            provenance: applied.current.provenance,
            ...(applied.current.provenanceNote
              ? { provenanceNote: applied.current.provenanceNote }
              : {}),
          }
        : null;
      const withProvenance = inherited ? { ...next, ...inherited } : next;
      applied.current = withProvenance;
      onChange(withProvenance);
    },
  });

  useEffect(() => {
    // `setEditable` emits an update by default, which the parent cannot tell apart from a real
    // edit: on mount it would report the still-empty editor as "the user typed", so a server draft
    // loaded a moment later is discarded and overwritten with empty content.
    if (editor) editor.setEditable(editable, false);
  }, [editor, editable]);

  // Replace the content when a *different* document arrives (import, version restore), without
  // echoing it back as a user edit. Without updating `applied` in `onUpdate`, every keystroke looks
  // like an external document and `setContent` resets the selection to the end.
  useEffect(() => {
    if (!editor || applied.current === document) return;
    applied.current = document;
    editor.commands.setContent(toEditorContent(document), { emitUpdate: false });
  }, [editor, document]);

  return editor;
}