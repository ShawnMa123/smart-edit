/**
 * The rich editor surface (tasks 2.1-2.4): toolbar, table operations, find/replace, and the fallback.
 *
 * Two invariants from the design:
 * 1. The toolbar only *reads* `editor.isActive()` — no local "pressed" state that can drift (D6).
 * 2. If the editor cannot start at all, we fall back to a textarea and say why (D10): a blank pane is
 *    worse than a plain one.
 */

import { EditorContent, useEditorState, type Editor } from '@tiptap/react';
import { useEffect, useState, type MouseEvent } from 'react';

import type { AssistantSelection } from '../api/assistantTypes';
import { richToPlainText } from '../rich/plainText';
import { plainTextToDocument, type RichDocument } from '../rich/richDocument';
import { selectionFromEditor, selectionFromTextarea } from '../rich/selection';
import { useRichEditor as defaultUseRichEditor } from '../rich/useRichEditor';

export interface RichEditorProps {
  document: RichDocument;
  onChange: (document: RichDocument) => void;
  /** Whether the projected text differs from the last captured version. */
  dirty?: boolean;
  /** The latest single-block selection, in projected plain-text offsets (knowledge Q&A). */
  onSelection?: (selection: AssistantSelection | null) => void;
  /** Server draft state (document-host design D6). */
  saveState?: 'local' | 'saving' | 'saved' | 'conflict' | 'error';
  conflict?: { revision: number; sha256: string } | null;
  recoveryNotice?: string | null;
  onUseServer?: () => void;
  onOverwriteLocal?: () => void;
  onKeepLocal?: () => void;
  /** Right-click action for turning the current selection into a variable. */
  onMarkVariable?: (selection: AssistantSelection) => void;
  /** Reports whether the rich surface or the textarea fallback is active (variable actions depend on it). */
  onModeChange?: (mode: 'rich' | 'fallback') => void;
  /** Document identity for the page header; never an example reference (design D4). */
  documentId?: string;
  /** Captured version count; 0 means no version captured yet. */
  versions?: number;
  /** Server draft revision; `null` means there is no server draft. */
  draftRevision?: number | null;
  /** Whether this session holds the edit lock (unknown is its own word). */
  lockHeld?: boolean;
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

function FallbackEditor({ document, onChange, onSelection, reason }: RichEditorProps & { reason: string }) {
  const text = richToPlainText(document);
  const hasVariables = /\{\{[^{}]+\}\}/.test(text);
  return (
    <div>
      <p className="notice notice--warn tiny" role="status">
        Rich text is unavailable in this session ({reason}); editing plain text instead.
      </p>
      <p className="notice tiny" data-testid="fallback-variable-notice">
        Variable editing needs the rich editor. {hasVariables
          ? 'Variable placeholders are shown as {{label}}; mark-as-variable and fill are disabled.'
          : 'Mark-as-variable and fill are disabled here.'}
      </p>
      <textarea
        className="editor-page"
        aria-label="Document text"
        data-testid="editor-text"
        value={text}
        spellCheck={false}
        onChange={(event) => onChange(plainTextToDocument(event.target.value))}
        onSelect={(event) => {
          const target = event.currentTarget;
          onSelection?.(
            selectionFromTextarea(target.value, target.selectionStart, target.selectionEnd),
          );
        }}
        placeholder="Paste or type the document text here, then run the spec audit."
      />
    </div>
  );
}

export function RichEditor(props: RichEditorProps) {
  const [failure, setFailure] = useState<string | null>(null);
  let editor: Editor | null = null;

  // The workbench needs to know whether variable actions are possible at all.
  useEffect(() => {
    props.onModeChange?.(failure ? 'fallback' : 'rich');
  }, [failure, props.onModeChange]);

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
  return (
    <Surface
      editor={editor}
      document={props.document}
      dirty={props.dirty ?? false}
      onSelection={props.onSelection}
      saveState={props.saveState ?? 'local'}
      conflict={props.conflict ?? null}
      recoveryNotice={props.recoveryNotice ?? null}
      onUseServer={props.onUseServer}
      onOverwriteLocal={props.onOverwriteLocal}
      onKeepLocal={props.onKeepLocal}
      onMarkVariable={props.onMarkVariable}
      documentId={props.documentId}
      versions={props.versions ?? 0}
      draftRevision={props.draftRevision ?? null}
      lockHeld={props.lockHeld ?? false}
    />
  );
}

function Surface({
  editor,
  document,
  dirty,
  onSelection,
  saveState,
  conflict,
  recoveryNotice,
  onUseServer,
  onOverwriteLocal,
  onKeepLocal,
  onMarkVariable,
  documentId,
  versions,
  draftRevision,
  lockHeld,
}: {
  editor: Editor;
  document: RichDocument;
  dirty: boolean;
  onSelection?: (selection: AssistantSelection | null) => void;
  saveState: 'local' | 'saving' | 'saved' | 'conflict' | 'error';
  conflict: { revision: number; sha256: string } | null;
  recoveryNotice: string | null;
  onUseServer?: () => void;
  onOverwriteLocal?: () => void;
  onKeepLocal?: () => void;
  onMarkVariable?: (selection: AssistantSelection) => void;
  documentId?: string;
  versions: number;
  draftRevision: number | null;
  lockHeld: boolean;
}) {
  const [findOpen, setFindOpen] = useState(false);
  const [variableMenu, setVariableMenu] = useState<{
    x: number;
    y: number;
    selection: AssistantSelection;
  } | null>(null);

  // Selection capture is a read-only projection: it never changes the document or the run.
  useEffect(() => {
    if (!onSelection) return;
    const handler = () => onSelection(selectionFromEditor(editor));
    editor.on('selectionUpdate', handler);
    return () => {
      editor.off('selectionUpdate', handler);
    };
  }, [editor, onSelection]);
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

      {/* One status band, one source of truth (design D5). */}
      <div className="editor-status" data-testid="editor-status">
        <strong>{versions > 0 ? `snapshot v${versions}` : 'no captured version'}</strong>
        <span>{draftRevision === null ? 'no server draft' : `draft rev ${draftRevision}`}</span>
        <span>{lockHeld ? 'lock: this session' : 'lock: unknown'}</span>
        <span
          aria-live="polite"
          data-testid="save-state"
          style={{
            color:
              saveState === 'conflict' || saveState === 'error'
                ? 'var(--unsaved)'
                : saveState === 'saved'
                  ? 'var(--muted)'
                  : 'var(--unsaved)',
          }}
        >
          {saveState === 'conflict'
            ? 'Save conflict — local content is not saved to the server'
            : saveState === 'saving'
              ? 'Saving…'
              : saveState === 'saved'
                ? 'Saved to server'
                : saveState === 'error'
                  ? 'Save failed — local content is still in the editor'
                  : dirty
                    ? 'Unsaved changes (local only)'
                    : 'No server draft available — local only'}
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
        {onMarkVariable ? (
          <button
            type="button"
            title="Mark selection as variable (Alt+Shift+V)"
            aria-label="Mark selection as variable"
            disabled={!selectionFromEditor(editor)}
            onClick={() => {
              const selection = selectionFromEditor(editor);
              if (selection) onMarkVariable(selection);
            }}
          >
            {'⟨var⟩'}
          </button>
        ) : null}
      </div>

      {findOpen ? <FindPanel editor={editor} total={total} current={current} onClose={() => setFindOpen(false)} /> : null}

      {conflict ? (
        <div className="notice notice--warn" role="alert" data-testid="draft-conflict">
          <strong>Draft conflict.</strong> The server head is revision {conflict.revision}
          {conflict.sha256 ? ` (${conflict.sha256.slice(0, 12)})` : ''}. Your editor content is
          unchanged and was not overwritten.
          {recoveryNotice ? <div className="tiny">{recoveryNotice}</div> : null}
          <div className="version-actions">
            <button type="button" onClick={onUseServer}>
              Use server version
            </button>
            <button type="button" onClick={onOverwriteLocal}>
              Overwrite with local content
            </button>
            <button type="button" onClick={onKeepLocal}>
              Keep local as recovery draft
            </button>
          </div>
        </div>
      ) : null}

      <div className="paper-wrap">
        <article className="paper" aria-label="Document page">
          <header className="paper-head">
            <span className="paper-brand">smart-edit / TRADE</span>
            <span className="paper-ref">
              DOCUMENT WORKING COPY
              <br />
              {documentId ?? 'untitled document'}
            </span>
          </header>

          <div
            onContextMenu={(event: MouseEvent<HTMLDivElement>) => {
          if (!onMarkVariable) return;
          const selection = selectionFromEditor(editor);
          if (!selection) return;
          event.preventDefault();
          setVariableMenu({ x: event.clientX, y: event.clientY, selection });
        }}
        onKeyDown={(event) => {
          if (!onMarkVariable) return;
          if (!event.altKey || !event.shiftKey || event.key.toLowerCase() !== 'v') return;
          const selection = selectionFromEditor(editor);
          if (!selection) return;
          event.preventDefault();
          onMarkVariable(selection);
        }}
      >
        <EditorContent editor={editor} className="editor-page" data-testid="editor-rich" />
        {variableMenu ? (
          <div
            className="variable-context-menu"
            role="menu"
            style={{ position: 'fixed', left: variableMenu.x, top: variableMenu.y, zIndex: 20 }}
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                onMarkVariable?.(variableMenu.selection);
                setVariableMenu(null);
              }}
            >
              Mark as variable
            </button>
            <button type="button" role="menuitem" onClick={() => setVariableMenu(null)}>
              Cancel
            </button>
          </div>
        ) : null}
          </div>

          <footer className="paper-foot">
            <span>Working copy · not an executed document</span>
            <span>{versions > 0 ? `v${versions} captured` : 'no captured version'}</span>
          </footer>
        </article>
      </div>

      <div className="editor-footer">
        <span>{richToPlainText(document).length} characters in the audit text</span>
        <span className="muted">Paper view · the projection above is unchanged</span>
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