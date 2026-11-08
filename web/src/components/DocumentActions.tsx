import { useState } from 'react';

interface UnavailableAction {
  id: string;
  label: string;
  reason: string;
}

/** Actions the reference prototype offers that this build cannot perform (task 6.4). */
export const UNAVAILABLE_ACTIONS: UnavailableAction[] = [
  { id: 'format', label: 'Formatting', reason: 'Rich-text formatting (ED-02) is not implemented in this build.' },
  { id: 'import', label: 'Import file', reason: 'File import and OCR (ED-03/04/05) are not implemented in this build.' },
  { id: 'export', label: 'Export', reason: 'Export (ED-09) is not implemented in this build.' },
  { id: 'approve', label: 'Start approval', reason: 'The approval workflow (§10) is not implemented in this build.' },
];

/**
 * Header/footer actions from the prototype, present but labelled — activating one says so instead of
 * appearing to succeed.
 */
export function DocumentActions() {
  const [message, setMessage] = useState<string | null>(null);

  return (
    <div>
      <div className="document-actions">
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