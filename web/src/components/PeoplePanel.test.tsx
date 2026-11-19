import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { PeoplePanel } from './PeoplePanel';

const response = (status: number, body: unknown) =>
  ({
    ok: status < 400,
    status,
    json: async () => body,
  }) as unknown as Response;

const departments = [
  { department_id: 'legal', org_id: 'org_1', parent_id: null, name: 'Legal' },
  { department_id: 'contracts', org_id: 'org_1', parent_id: 'legal', name: 'Contracts' },
];
const members = [
  {
    user_id: 'u1',
    email: 'owner@example.com',
    display_name: 'Owner',
    status: 'active',
    department_id: 'contracts',
    department_name: 'Contracts',
    role_assignments: [
      {
        assignment_id: 'a1',
        user_id: 'u1',
        role_key: 'dept_admin',
        scope_type: 'department',
        scope_id: 'legal',
        created_at: '2026-11-19T00:00:00Z',
      },
    ],
  },
];

const fetchImpl = (overrides: Record<string, () => Response> = {}) =>
  vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url);
    for (const [needle, handler] of Object.entries(overrides)) {
      if (path.includes(needle)) return handler();
    }
    if (path.endsWith('/departments') && (init?.method ?? 'GET') === 'GET') {
      return response(200, departments);
    }
    if (path.endsWith('/members')) return response(200, members);
    if (path.endsWith('/invites') && (init?.method ?? 'GET') === 'GET') {
      return response(200, []);
    }
    if (path.endsWith('/invites')) {
      return response(201, { invite_id: 'i1', accept_path: '/invites/token-123' });
    }
    return response(404, { code: 'NOT_FOUND' });
  }) as unknown as typeof fetch;

describe('PeoplePanel', () => {
  it('renders the department tree, members and inherited roles read-only', async () => {
    render(<PeoplePanel orgId="org_1" fetchImpl={fetchImpl()} />);
    expect((await screen.findAllByText('Contracts')).length).toBeGreaterThan(0);
    expect((await screen.findAllByText('Legal')).length).toBeGreaterThan(0);
    await userEvent.click(await screen.findByRole('button', { name: 'Owner' }));
    expect(screen.getByRole('region', { name: 'Roles for Owner' })).toBeTruthy();
    expect(screen.getByText('inherited · read-only')).toBeTruthy();
  });

  it('creates an invite and exposes the copyable one-time link', async () => {
    const writeText = vi.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<PeoplePanel orgId="org_1" fetchImpl={fetchImpl()} />);
    await userEvent.type(await screen.findByLabelText('Invite email'), 'new@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Create invite link' }));
    expect(await screen.findByText(/\/invites\/token-123/)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Copy link' }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
  });

  it('shows an empty state when the role cannot list members', async () => {
    const forbidden = fetchImpl({
      '/departments': () => response(403, { code: 'FORBIDDEN' }),
    });
    render(<PeoplePanel orgId="org_1" fetchImpl={forbidden} />);
    expect(await screen.findByText('No access to members')).toBeTruthy();
  });
});