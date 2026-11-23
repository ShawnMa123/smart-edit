import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ActivityFeed } from './ActivityFeed';

const response = (status: number, body: unknown) =>
  ({
    ok: status < 400,
    status,
    json: async () => body,
  }) as unknown as Response;

const page = {
  items: [
    {
      event_id: 'e1',
      kind: 'document',
      action: 'document locked',
      resource_type: 'document',
      resource_id: 'doc_1',
      detail: { title: 'Contracts memo' },
      created_at: '2026-11-19T10:00:00Z',
      is_read: false,
      actor: { user_id: 'u9', label: 'Removed user', removed: true },
      department_id: null,
    },
  ],
  next_cursor: 'e1',
  unread_count: 1,
};

describe('ActivityFeed', () => {
  it('lists server events, labels removed actors and marks all read', async () => {
    const calls: Array<[string, RequestInit | undefined]> = [];
    const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
      calls.push([String(url), init]);
      if (String(url).includes('/read-all')) return response(200, { marked_read: 1 });
      return response(200, page);
    }) as unknown as typeof fetch;

    render(<ActivityFeed orgId="org_1" fetchImpl={fetchImpl} />);
    expect(await screen.findByText('document locked')).toBeTruthy();
    expect(screen.getByText('Removed user')).toBeTruthy();
    expect(screen.getByLabelText('1 unread events')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Mark all read' }));
    await waitFor(() =>
      expect(calls.some(([url]) => url.includes('/activity/read-all'))).toBe(true),
    );

    await userEvent.selectOptions(screen.getByLabelText('Activity scope'), 'my_department');
    await waitFor(() =>
      expect(calls.some(([url]) => url.includes('scope=my_department'))).toBe(true),
    );
  });

  it('shows an empty state when activity is forbidden', async () => {
    const fetchImpl = vi.fn(async () => response(403, { code: 'FORBIDDEN' }));
    render(<ActivityFeed orgId="org_1" fetchImpl={fetchImpl as unknown as typeof fetch} />);
    expect(await screen.findByText('No access to activity')).toBeTruthy();
  });
});