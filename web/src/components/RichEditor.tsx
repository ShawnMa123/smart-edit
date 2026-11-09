/**
 * The rich editor surface (tasks 2.1-2.4): toolbar, table operations, find/replace, and the fallback.
 *
 * Two invariants from the design:
 * 1. The toolbar only *reads* `editor.isActive()` — no local "pressed" state that can drift (D6).
 * 2. If the editor cannot start at all, we fall back to a textarea and say why (D10): a blank pane is
 *    worse than a plain one.
 */

import { EditorContent, useEditorState, type Editor } from '@tiptap/react';
import { useState } from 'react';

import { richToPlainText } from '../rich/plainText';
import { plainTextToDocument, type RichDocument } from '../rich/richDocument';
import { useRichEditor as defaultUseRichEditor } from '../rich/useRichEditor';

export interface RichEditorProps {
  document: RichDocument;
  onChange: (document: RichDocument) => void;
  /** Whether the projected text differs from the last captured version. */
  dirty?: boolean;
  /** Test seam: a throwing implementation exercises the fallback path. */
  useEditorImpl?: (typeof defaultUseRichEditor);
}

interface Tool {
  label: string;
  title: string;
  run: (editor: Editor) => void;
  active?: (editor: Editor) => boolean;
}

export const TOOLS: Tool[] = [
  { label: '¶', title: 'Paragraph', run: (e) => e.chain().focus().setParagraph().run(), active: (e) => e.isActive('paragraph') },
  { label: 'H1', title: 'Heading 1', run: (e) => e.chain().focus().toggleHeading({ level: 1 }).run(), active: (e) => e.isActive('heading', { level: 1 }) },
  { label: 'H2', title: 'Heading 2', run: (e) => e.chain().focus().toggleHeading({ level: 2 }).run(), active: (e) => e.isActive('heading', { level: 2 }) },
  { label: 'H3', title: 'Heading 3', run: (e) => e.chain().focus().toggleHeading({ level: 3 }).run(), active: (e) => e.isActive('heading', { level: 3 }) },
  { label: 'B', title: 'Bold', run: (e) => e.chain().focus().toggleBold().run(), active: (e) => e.isActive('bold') },
  { label: 'I', title: 'Italic', run: (e) => e.chain().focus().toggleItalic().run(), active: (e) => e.isActive('italic') },
  { label: 'U', title: 'Underline', run: (e) => e.chain().focus().toggleUnderline().run(), active: (e) => e.isActive('underline') },
  { label: '•', title: 'Bullet list', run: (e) => e.chain().focus().toggleBulletList().run(), active: (e) => e.isActive('bulletList') },
  { label: '1.', title: 'Numbered list', run: (e) => e.chain().focus().toggleOrderedList().run(), active: (e) => e.isActive('orderedList') },
  { label: '↶', title: 'Undo', run: (e) => e.chain().focus().undo().run() },
  { label: '↷', title: 'Redo', run: (e) => e.chain().focus().redo().run() },
];

export const TABLE_TOOLS: Tool[] = [
  { label: '⊞', title: 'Insert table', run: (e) => e.chain().focus().insertTable({ rows: 2, cols: 2, withHeaderRow: true }).run() },
  { label: '+R', title: 'Insert row below', run: (e) => e.chain().focus().addRowAfter().run() },
  { label: '−R', title: 'Delete row', run: (e) => e.chain().focus().deleteRow().run() },
  { label: '+C', title: 'Insert column right', run: (e) => e.chain().focus().addColumnAfter().run() },
  { label: '−C', title: 'Delete column', run: (e) => e.chain().focus().deleteColumn().run() },
];

function FallbackEditor({ document, onChange, reason }: RichEditorProps & { reason: string }) {
  return (
    <div>
      <p className="notice notice--warn tiny" role="status">
        Rich text is unavailable in this session ({reason}); editing plain text instead.
      </p>
      <textarea
        className="editor-page"
        aria-label="Document text"
        data-testid="editor-text"
        value={richToPlainText(document)}
        spellCheck={false}
        onChange={(event) => onChange(plainTextToDocument(event.target.value))}
        placeholder="Paste or type the document text here, then run the spec audit."
      />
    </div>
  );
}

export function RichEditor(props: RichEditorProps) {
  const [failure, setFailure] = useState<string | null>(null);
  let editor: Editor | null = null;

  try {
    editor = (props.useEditorImpl ?? defaultUseRichEditor)({
      document: props.document,
      onChange: props.onChange,
    });
  } catch (error) {
    if (!failure) setFailure(error instanceof Error ? error.message : String(error));
  }

  if (failure || !editor) {
    return <FallbackEditor {...props} reason={failure ?? 'the editor did not start'} />;
  }
  return <Surface editor={editor} document={props.document} dirty={props.dirty ?? false} />;
}

function Surface({
  editor,
  document,
  dirty,
}: {
  editor: Editor;
  document: RichDocument;
  dirty: boolean;
}) {
  const [findOpen, setFindOpen] = useState(false);
  // Reactive read of the search plugin: `useEditor` alone does not re-render on every transaction.
  const { total, current } = useEditorState({
    editor,
    selector: ({ editor: instance }) => {
      const storage = (instance.storage as { findAndReplace?: { results?: unknown[]; currentIndex?: number | null } })
        .findAndReplace;
      return { total: storage?.results?.length ?? 0, current: storage?.currentIndex ?? null };
    },
  });

  return (
    <section className="pane" aria-label="Document editor">
      <div className="row">
        <h2>Document</h2>
        <span className="tiny muted">
          Rich text · the audit reads a plain-text projection
          {document.provenance ? ` · imported (${document.provenance})` : ''}
        </span>
      </div>

      <div className="toolbar" role="toolbar" aria-label="Formatting">
        {[...TOOLS, ...TABLE_TOOLS].map((tool) => {
          const active = tool.active ? tool.active(editor) : false;
          return (
            <button
              key={tool.title}
              type="button"
              title={tool.title}
              aria-label={tool.title}
              aria-pressed={active}
              onClick={() => tool.run(editor)}
            >
              {tool.label}
            </button>
          );
        })}
        <button
          type="button"
          title="Find and replace"
          aria-label="Find and replace"
          aria-expanded={findOpen}
          onClick={() => setFindOpen((open) => !open)}
        >
          ⌕
        </button>
      </div>

      {findOpen ? <FindPanel editor={editor} total={total} current={current} onClose={() => setFindOpen(false)} /> : null}

      <EditorContent editor={editor} className="editor-page" data-testid="editor-rich" />

      <div className="editor-footer">
        <span>{richToPlainText(document).length} characters in the audit text</span>
        <span aria-live="polite" style={{ color: dirty ? 'var(--unsaved)' : 'var(--muted)' }}>
          {dirty ? 'Unsaved changes' : 'No unsaved changes'}
        </span>
      </div>
    </section>
  );
}

function FindPanel({
  editor,
  total,
  current,
  onClose,
}: {
  editor: Editor;
  total: number;
  current: number | null;
  onClose: () => void;
}) {
  const [term, setTerm] = useState('');
  const [replacement, setReplacement] = useState('');

  return (
    <div className="toolbar" role="search" aria-label="Find and replace">
      <input
        aria-label="Find"
        placeholder="Find"
        value={term}
        onChange={(event) => {
          setTerm(event.target.value);
          editor.commands.setSearchTerm(event.target.value);
        }}
      />
      <input
        aria-label="Replace with"
        placeholder="Replace with"
        value={replacement}
        onChange={(event) => {
          setReplacement(event.target.value);
          editor.commands.setReplaceTerm(event.target.value);
        }}
      />
      <span className="tiny muted" data-testid="find-status">
        {term === '' ? 'no search yet' : total === 0 ? 'no matches' : `${(current ?? 0) + 1} / ${total}`}
      </span>
      <button type="button" aria-label="Previous match" onClick={() => editor.commands.goToPreviousResult()}>
        ↑
      </button>
      <button type="button" aria-label="Next match" onClick={() => editor.commands.goToNextResult()}>
        ↓
      </button>
      <button type="button" aria-label="Replace" onClick={() => editor.commands.replace()}>
        Replace
      </button>
      <button type="button" aria-label="Replace all" onClick={() => editor.commands.replaceAll()}>
        Replace all
      </button>
      <button
        type="button"
        aria-label="Close find"
        onClick={() => {
          editor.commands.clearSearch();
          onClose();
        }}
      >
        ✕
      </button>
    </div>
  );
}