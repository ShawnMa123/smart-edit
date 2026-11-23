import { useRef, useState } from 'react';

export interface UnavailableAction {
  id: string;
  label: string;
  reason: string;
}

/** Actions the reference prototype offers that this build cannot perform (task 6.4). */
export const UNAVAILABLE_ACTIONS: UnavailableAction[] = [
  { id: 'export', label: 'Export', reason: 'Export (ED-09) is not implemented in this build.' },
];

/** What the file picker accepts — the same four types the server can read (ED-03). */
export const IMPORT_ACCEPT = '.pdf,.docx,.png,.jpg,.jpeg';

export interface DocumentActionsProps {
  /** Hand the chosen files to the importer; the button never uploads on its own. */
  onImport?: (files: File[]) => void;
  /** Opens the explicit Comments placeholder; this build has no comment service. */
  onComments?: () => void;
  /** Test seam: documents the caller may open (the header switcher). */
  onNewDocument?: () => void;
  /** False when the role lacks `document.create`. */
  canCreateDocument?: boolean;
  /** Every openable document; renders the "Open document" switcher. */
  documents?: Array<{ document_id: string; title: string; submission_status: string }>;
  activeDocumentId?: string;
  onOpenDocument?: (documentId: string) => void;
  /** Reports a deliberate activation of an action this build cannot perform. */
  onUnavailableAction?: (action: UnavailableAction) => void;
}

/**
 * Header/footer actions from the prototype. `Import file` is real (it opens a picker and hands the
 * files over); every other action is labelled and says so instead of appearing to succeed.
 */
export function DocumentActions({
  onImport,
  onComments,
  onNewDocument,
  canCreateDocument = true,
  documents,
  activeDocumentId,
  onOpenDocument,
  onUnavailableAction,
}: DocumentActionsProps) {
  const [message, setMessage] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  return (
    <div>
      <div className="document-actions">
        <button
          type="button"
          className="primary"
          data-testid="import-file"
          title="Import a PDF, Word or image file as the document text"
          onClick={() => input.current?.click()}
        >
          Import file
        </button>
        {onNewDocument ? (
          <button
            type="button"
            className="quiet"
            data-testid="new-document"
            data-tour="new-document"
            title={
              canCreateDocument
                ? 'Create a new document and keep the current one'
                : 'Your role cannot create documents'
            }
            disabled={!canCreateDocument}
            onClick={onNewDocument}
          >
            New document
          </button>
        ) : null}
        {documents && onOpenDocument ? (
          <select
            aria-label="Open document"
            data-testid="open-document-select"
            data-tour="open-document"
            value=""
            onChange={(event) => {
              const next = event.target.value;
              if (next) onOpenDocument(next);
            }}
          >
            <option value="">Open document…</option>
            {documents.map((item) => (
              <option key={item.document_id} value={item.document_id}>
                {item.title} · {item.submission_status}
                {item.document_id === activeDocumentId ? ' · current' : ''}
              </option>
            ))}
          </select>
        ) : null}
        <input
          ref={input}
          type="file"
          hidden
          multiple
          accept={IMPORT_ACCEPT}
          aria-label="Import file"
          data-testid="import-file-input"
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = ''; // re-choosing the same file must still fire
            if (files.length > 0) onImport?.(files);
          }}
        />
        <button
          type="button"
          className="quiet"
          data-testid="comments"
          title="Comments are not available in this build"
          onClick={() => onComments?.()}
        >
          Comments
        </button>
        {UNAVAILABLE_ACTIONS.map((action) => (
          <button
            key={action.id}
            type="button"
            className="quiet"
            data-unavailable="true"
            aria-label={`${action.label} · not implemented`}
            title={action.reason}
            onClick={() => {
              setMessage(action.reason);
              onUnavailableAction?.(action);
            }}
          >
            {action.label}
            <span className="tag tag--muted" aria-hidden="true">
              Not available
            </span>
          </button>
        ))}
        <button
          type="button"
          title="Focus the document formatting toolbar"
          onClick={() => {
            const editor = document.querySelector<HTMLElement>('.ProseMirror');
            editor?.focus();
          }}
        >
          Formatting
        </button>
      </div>
      {message ? (
        <p className="notice notice--warn tiny" role="status">
          Unavailable: {message}
        </p>
      ) : null}
    </div>
  );
}