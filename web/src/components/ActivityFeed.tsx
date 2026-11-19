/** Activity: server-backed list, filters, unread count and mark-all-read (task 7.3). */

import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../api/errors';
import * as api from '../api/identity';
import type { ActivityEvent } from '../api/identityTypes';

interface ActivityFeedProps {
  orgId: string;
  fetchImpl?: typeof fetch;
}

export function ActivityFeed({ orgId, fetchImpl }: ActivityFeedProps) {
  const [items, setItems] = useState<ActivityEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [scope, setScope] = useState<'all' | 'my_department'>('all');
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (nextCursor: string | null, append: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const page = await api.listActivity(
          orgId,
          { scope, unread: unreadOnly, cursor: nextCursor },
          { fetchImpl },
        );
        setItems((previous) => (append ? [...previous, ...page.items] : page.items));
        setCursor(page.next_cursor);
        setUnreadCount(page.unread_count);
        setForbidden(false);
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 403) {
          setForbidden(true);
        } else {
          setError(caught instanceof Error ? caught.message : 'could not load activity');
        }
      } finally {
        setLoading(false);
      }
    },
    [fetchImpl, orgId, scope, unreadOnly],
  );

  useEffect(() => {
    void load(null, false);
  }, [load]);

  const markAll = async () => {
    try {
      await api.markAllActivityRead(orgId, scope, { fetchImpl });
      await load(null, false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'could not mark activity read');
    }
  };

  const markOne = async (eventId: string) => {
    try {
      await api.markActivityRead(orgId, eventId, { fetchImpl });
      setItems((previous) =>
        previous.map((item) =>
          item.event_id === eventId ? { ...item, is_read: true } : item,
        ),
      );
      setUnreadCount((previous) => Math.max(0, previous - 1));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'could not mark event read');
    }
  };

  if (forbidden) {
    return (
      <div className="empty-state" role="status">
        <strong>No access to activity</strong>
        <p className="tiny">Your role does not include activity for this organisation.</p>
      </div>
    );
  }

  return (
    <div className="activity-feed">
      <div className="inline-form">
        <select
          aria-label="Activity scope"
          value={scope}
          onChange={(event) => setScope(event.target.value as 'all' | 'my_department')}
        >
          <option value="all">All activity</option>
          <option value="my_department">My department</option>
        </select>
        <label className="tiny">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(event) => setUnreadOnly(event.target.checked)}
          />{' '}
          Unread only
        </label>
        <span className="chip" aria-label={`${unreadCount} unread events`}>
          {unreadCount} unread
        </span>
        <button type="button" onClick={() => void markAll()}>
          Mark all read
        </button>
      </div>

      {error ? <p className="notice notice--warn">{error}</p> : null}
      {items.length === 0 && !loading ? <p className="tiny">No activity in this scope.</p> : null}

      <ul className="activity-list">
        {items.map((item) => (
          <li key={item.event_id} className={item.is_read ? 'read' : 'unread'}>
            <div>
              <strong>{item.action}</strong>{' '}
              <span className="tiny">
                {item.actor.removed ? 'Removed user' : item.actor.label || 'System'}
              </span>
            </div>
            <div className="tiny">
              {new Date(item.created_at).toLocaleString()} · {item.kind}
              {item.resource_id ? ` · ${item.resource_id}` : ''}
            </div>
            {typeof item.detail?.title === 'string' ? (
              <div className="tiny">“{item.detail.title}”</div>
            ) : null}
            {!item.is_read ? (
              <button type="button" className="link" onClick={() => void markOne(item.event_id)}>
                Mark read
              </button>
            ) : null}
          </li>
        ))}
      </ul>

      {cursor ? (
        <button type="button" disabled={loading} onClick={() => void load(cursor, true)}>
          {loading ? 'Loading…' : 'Load more'}
        </button>
      ) : null}
    </div>
  );
}