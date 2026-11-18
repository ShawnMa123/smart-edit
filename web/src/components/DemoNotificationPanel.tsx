import { demoUser, type DemoState } from '../demo/demoData';

export interface DemoNotificationPanelProps {
  state: DemoState;
  onMarkAllRead: () => void;
}

export function DemoNotificationPanel({ state, onMarkAllRead }: DemoNotificationPanelProps) {
  const notifications = state.activity.filter((entry) => entry.notifiable);
  return (
    <div>
      <p className="notice notice--warn tiny">
        <strong>Sample data.</strong> Notifications derive from demo activity. No real person
        assigned or sent them.
      </p>
      {notifications.length === 0 ? (
        <p className="notice tiny">No sample notifications yet.</p>
      ) : (
        <ul className="demo-activity-list">
          {notifications.map((entry) => {
            const actor = demoUser(entry.actorId);
            return (
              <li className="demo-activity-entry" key={entry.id}>
                <div className="row">
                  <strong>{entry.action}</strong>
                  <span className="tag tag--muted">{actor.name}</span>
                  <span className={`tag ${entry.read ? 'tag--muted' : 'tag--warn'}`}>
                    {entry.read ? 'Read' : 'Unread'}
                  </span>
                </div>
                <p className="tiny muted">{entry.detail}</p>
                <p className="tiny muted">{new Date(entry.at).toLocaleString()}</p>
              </li>
            );
          })}
        </ul>
      )}
      {notifications.some((entry) => !entry.read) ? (
        <div className="dialog-actions">
          <button type="button" onClick={onMarkAllRead}>
            Mark all read
          </button>
        </div>
      ) : null}
    </div>
  );
}