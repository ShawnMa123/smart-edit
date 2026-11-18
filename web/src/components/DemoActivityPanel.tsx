import { demoUser, type DemoState } from '../demo/demoData';

export interface DemoActivityPanelProps {
  state: DemoState;
  onMarkAllRead: () => void;
}

export function DemoActivityPanel({ state, onMarkAllRead }: DemoActivityPanelProps) {
  return (
    <div>
      <p className="notice notice--warn tiny">
        <strong>Sample data.</strong> These events use demo actors and are stored separately from the
        real browser-local activity log.
      </p>
      <ul className="demo-activity-list">
        {state.activity.map((entry) => {
          const actor = demoUser(entry.actorId);
          return (
            <li className="demo-activity-entry" key={entry.id}>
              <div className="row">
                <strong>{entry.action}</strong>
                <span className="tag tag--muted">{actor.name}</span>
                {entry.notifiable ? (
                  <span className={`tag ${entry.read ? 'tag--muted' : 'tag--warn'}`}>
                    {entry.read ? 'Read' : 'Unread'}
                  </span>
                ) : null}
              </div>
              <p className="tiny muted">{entry.detail}</p>
              <p className="tiny muted">{new Date(entry.at).toLocaleString()}</p>
            </li>
          );
        })}
      </ul>
      {state.activity.some((entry) => entry.notifiable && !entry.read) ? (
        <div className="dialog-actions">
          <button type="button" onClick={onMarkAllRead}>
            Mark all read
          </button>
        </div>
      ) : null}
    </div>
  );
}