import { useState } from 'react';

import type { ActivityEntry } from '../workspace/activityStore';

export interface ActivityPanelProps {
  activity: ActivityEntry[];
  available: boolean;
  onClear: () => void;
}

/** The Activity dialog: a browser-local list, never a server audit trail. */
export function ActivityPanel({ activity, available, onClear }: ActivityPanelProps) {
  const [confirming, setConfirming] = useState(false);

  return (
    <div>
      <p className="notice tiny">
        <strong>Browser-local activity — not a server audit trail.</strong> Events are stored in this
        browser only and never written to the backend.
      </p>
      {!available ? (
        <p className="notice notice--warn tiny">
          Activity is session-only because browser storage is unavailable.
        </p>
      ) : null}

      {activity.length === 0 ? (
        <p className="notice tiny">
          No activity yet. Events appear here after you import, save, capture a version, run an
          audit or ask the assistant.
        </p>
      ) : (
        <ol className="activity-list">
          {activity.map((entry) => (
            <li className="activity-entry" key={entry.id}>
              <div className="row">
                <strong>{entry.action}</strong>
                <span className="tag tag--muted">{entry.kind}</span>
              </div>
              {entry.detail ? <p className="tiny muted">{entry.detail}</p> : null}
              <p className="tiny muted">{new Date(entry.at).toLocaleString()}</p>
            </li>
          ))}
        </ol>
      )}

      {activity.length > 0 ? (
        <div className="dialog-actions">
          {confirming ? (
            <>
              <span className="tiny muted">Clear this browser-local activity?</span>
              <button
                type="button"
                className="danger"
                onClick={() => {
                  setConfirming(false);
                  onClear();
                }}
              >
                Clear activity
              </button>
              <button type="button" onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </>
          ) : (
            <button type="button" onClick={() => setConfirming(true)}>
              Clear activity
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}