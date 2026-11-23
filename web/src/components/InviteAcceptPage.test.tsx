import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AuthProvider } from '../auth/AuthProvider';
import { InviteAcceptPage } from './InviteAcceptPage';

const response = (status: number, body: unknown) =>
  ({
    ok: status < 400,
    status,
    json: async () => body,
  }) as unknown as Response;

const profile = {
  user: { user_id: 'u1', email: 'owner@example.com', display_name: 'Owner' },
  active_org: { org_id: 'org_1', workspace_id: 'org_1', name: 'Acme' },
  active_department_id: null,
  organizations: [{ org_id: 'org_1', workspace_id: 'org_1', name: 'Acme' }],
  roles: ['member'],
  permissions: ['document.read'],
};

describe('InviteAcceptPage', () => {
  it('accepts the one-time token and switches to the inviting organisation', async () => {
    const fetchImpl = vi.fn(async (url: string) => {
      if (String(url).includes('/invites/accept')) {
        return response(200, { org_id: 'org_2', department_id: null, role_key: 'member' });
      }
      return response(200, profile);
    });
    render(
      <AuthProvider
        fetchImpl={fetchImpl as unknown as typeof fetch}
        initialStatus="authenticated"
        initialProfile={profile}
      >
        <InviteAcceptPage token="token-123" fetchImpl={fetchImpl as unknown as typeof fetch} />
      </AuthProvider>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Accept invite' }));
    await waitFor(() => expect(fetchImpl.mock.calls.length).toBeGreaterThanOrEqual(2));
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/invites/accept');
    expect(JSON.parse(String(init.body))).toEqual({ invite_token: 'token-123' });
    expect((init.headers as Record<string, string>)['X-Requested-With']).toBe('smart-edit');
  });
});