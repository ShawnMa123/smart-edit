import { useRef, useState } from 'react';

interface UnavailableAction {
  id: string;
  label: string;
  reason: string;
}

/** Actions the reference prototype offers that this build cannot perform (task 6.4). */
export const UNAVAILABLE_ACTIONS: UnavailableAction[] = [
  { id: 'format', label: 'Formatting', reason: 'Rich-text formatting (ED-02) is not implemented in this build.' },
  { id: 'export', label: 'Export', reason: 'Export (ED-09) is not implemented in this build.' },
  { id: 'approve', label: 'Start approval', reason: 'The approval workflow (§10) is not implemented in this build.' },
];

/** What the file picker accepts — the same four types the server can read (ED-03). */
export const IMPORT_ACCEPT = '.pdf,.docx,.png,.jpg,.jpeg';

export interface DocumentActionsProps {
  /** Hand the chosen files to the importer; the button never uploads on its own. */
  onImport?: (files: File[]) => void;
}

/**
 * Header/footer actions from the prototype. `Import file` is real (it opens a picker and hands the
 * files over); every other action is labelled and says so instead of appearing to succeed.
 */
export function DocumentActions({ onImport }: DocumentActionsProps) {
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
        {UNAVAILABLE_ACTIONS.map((action) => (
          <button
            key={action.id}
            type="button"
            data-unavailable="true"
            title={action.reason}
            onClick={() => setMessage(action.reason)}
          >
            {action.label} · not implemented
          </button>
        ))}
      </div>
      {message ? (
        <p className="notice notice--warn tiny" role="status">
          Unavailable: {message}
        </p>
      ) : null}
    </div>
  );
}