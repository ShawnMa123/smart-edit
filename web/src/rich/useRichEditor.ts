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
}

export function useRichEditor({ document, onChange }: UseRichEditorOptions): Editor | null {
  const editor = useEditor({
    extensions,
    content: toEditorContent(document),
    editorProps: {
      attributes: {
        class: 'editor-rich',
        'aria-label': 'Document text',
      },
    },
    onUpdate: ({ editor: instance }) => onChange(toRichDocument(instance.getJSON())),
  });

  // Replace the content when a *different* document arrives (import, version restore), without
  // echoing it back as a user edit.
  const applied = useRef<RichDocument>(document);
  useEffect(() => {
    if (!editor || applied.current === document) return;
    applied.current = document;
    editor.commands.setContent(toEditorContent(document), { emitUpdate: false });
  }, [editor, document]);

  return editor;
}