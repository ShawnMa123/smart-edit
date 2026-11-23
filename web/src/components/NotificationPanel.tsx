import type { ActivityEntry } from '../workspace/activityStore';

export interface NotificationPanelProps {
  activity: ActivityEntry[];
  onMarkAllRead: () => void;
}

/** Inbox: a derived view of notifiable local activity, never a fabricated task list. */
export function NotificationPanel({ activity, onMarkAllRead }: NotificationPanelProps) {
  const notifications = activity.filter((entry) => entry.notifiable);
  const unread = notifications.filter((entry) => !entry.read).length;

  return (
    <div>
      <p className="notice tiny">
        Notifications are derived from real browser-local activity. They are not assigned by another
        person and are not a server inbox.
      </p>

      {notifications.length === 0 ? (
        <p className="notice tiny">
          No notifications yet. A completed audit, import, conflict or knowledge answer appears here.
        </p>
      ) : (
        <ul className="notification-list">
          {notifications.map((entry) => (
            <li className="notification-entry" key={entry.id}>
              <div className="row">
                <strong>{entry.action}</strong>
                {entry.read ? (
                  <span className="tag tag--muted">Read</span>
                ) : (
                  <span className="tag tag--warn">Unread</span>
                )}
              </div>
              {entry.detail ? <p className="tiny muted">{entry.detail}</p> : null}
              <p className="tiny muted">{new Date(entry.at).toLocaleString()}</p>
            </li>
          ))}
        </ul>
      )}

      {unread > 0 ? (
        <div className="dialog-actions">
          <button type="button" onClick={onMarkAllRead}>
            Mark all read
          </button>
        </div>
      ) : null}
    </div>
  );
}