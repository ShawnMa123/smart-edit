export const CHAR_SOFT_LIMIT = 50_000;

export interface EditorColumnProps {
  text: string;
  dirty: boolean;
  onChange: (text: string) => void;
  onCapture: () => void;
}

/**
 * Centre pane: the document surface (task 6.2).
 *
 * A plain `<textarea>` on purpose (design D3): the audit's input is text and exact fidelity is the
 * point — a `contenteditable` surface silently rewrites quotes, non-breaking spaces and paragraph
 * breaks, which is exactly the corruption the backend's `normalize_ws` exists to survive.
 */
export function EditorColumn({ text, dirty, onChange, onCapture }: EditorColumnProps) {
  const tooLong = text.length > CHAR_SOFT_LIMIT;

  return (
    <section className="pane" aria-label="Document editor">
      <div className="row">
        <h2>Document</h2>
        <span className="tiny muted">Plain text · rich text is not implemented in this build</span>
      </div>

      <textarea
        className="editor-page"
        aria-label="Document text"
        data-testid="editor-text"
        value={text}
        spellCheck={false}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Paste or type the document text here, then run the spec audit."
      />

      <div className="editor-footer">
        <span>{text.length} characters</span>
        <span aria-live="polite" style={{ color: dirty ? 'var(--unsaved)' : 'var(--muted)' }}>
          {dirty ? 'Unsaved changes' : 'No unsaved changes'}
        </span>
        {tooLong ? (
          <span className="muted" style={{ color: 'var(--status-warn)' }}>
            Above the {CHAR_SOFT_LIMIT.toLocaleString()} character guidance — audits will be slow
          </span>
        ) : null}
      </div>

      <div className="version-actions">
        <button type="button" className="primary" onClick={onCapture}>
          Capture version
        </button>
      </div>
    </section>
  );
}