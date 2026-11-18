import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ActivityEntry } from '../workspace/activityStore';
import { NotificationPanel } from './NotificationPanel';

const entry = (over: Partial<ActivityEntry> = {}): ActivityEntry => ({
  id: 'a-1',
  kind: 'audit',
  action: 'Audit completed',
  detail: '0 findings',
  at: '2026-11-17T09:00:00.000Z',
  read: false,
  notifiable: true,
  ...over,
});

describe('NotificationPanel', () => {
  it('shows only notifiable local events with an unread marker', () => {
    render(
      <NotificationPanel
        activity={[entry(), entry({ id: 'a-2', kind: 'save', action: 'Draft saved', notifiable: false })]}
        onMarkAllRead={() => undefined}
      />,
    );

    expect(screen.getByText('Audit completed')).toBeTruthy();
    expect(screen.queryByText('Draft saved')).toBeNull();
    expect(screen.getByText('Unread')).toBeTruthy();
    expect(document.body.textContent ?? '').not.toMatch(/assignee|sender|Alpha Tech|HSBC/i);
  });

  it('marks all read through the callback and exposes the empty state', () => {
    const onMarkAllRead = vi.fn();
    const { unmount } = render(
      <NotificationPanel activity={[entry()]} onMarkAllRead={onMarkAllRead} />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Mark all read' }));
    expect(onMarkAllRead).toHaveBeenCalledTimes(1);

    unmount();
    render(<NotificationPanel activity={[]} onMarkAllRead={onMarkAllRead} />);
    expect(screen.getByText(/No notifications yet/i)).toBeTruthy();
  });
});