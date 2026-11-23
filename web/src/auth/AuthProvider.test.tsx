import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from './AuthProvider';

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
  roles: ['org_admin'],
  permissions: ['document.read'],
};

function Probe() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="status">{auth.status}</span>
      <span data-testid="workspace">{auth.workspaceId}</span>
      <span data-testid="user">{auth.profile?.user.email ?? ''}</span>
      <button type="button" onClick={() => void auth.login('owner@example.com', 'secret-123')}>
        Login
      </button>
      <button type="button" onClick={() => void auth.logout()}>
        Logout
      </button>
    </div>
  );
}

describe('AuthProvider', () => {
  it('probes /auth/me and exposes the active workspace', async () => {
    const fetchImpl = vi.fn(async () => response(200, profile)) as unknown as typeof fetch;
    render(
      <AuthProvider fetchImpl={fetchImpl} initialStatus="loading" autoProbe>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'));
    expect(screen.getByTestId('workspace').textContent).toBe('org_1');
    expect(screen.getByTestId('user').textContent).toBe('owner@example.com');
  });

  it('treats 401 as signed out and fake mode as unavailable', async () => {
    const unauthorized = vi.fn(async () => response(401, { code: 'AUTH_REQUIRED' }));
    const { unmount } = render(
      <AuthProvider fetchImpl={unauthorized as unknown as typeof fetch} initialStatus="loading" autoProbe>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));
    unmount();

    const fake = vi.fn(async () => response(409, { code: 'AUTH_MODE_FAKE' }));
    render(
      <AuthProvider fetchImpl={fake as unknown as typeof fetch} initialStatus="loading" autoProbe>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unavailable'));
  });
});