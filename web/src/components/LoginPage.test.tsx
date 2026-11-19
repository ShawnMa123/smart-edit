import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AuthProvider } from '../auth/AuthProvider';
import { LoginPage } from './LoginPage';

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

describe('LoginPage', () => {
  it('shows the generic failure message without revealing account existence', async () => {
    const fetchImpl = vi.fn(async () =>
      response(401, { code: 'INVALID_CREDENTIALS', message: 'email or password is incorrect' }),
    );
    render(
      <AuthProvider fetchImpl={fetchImpl as unknown as typeof fetch} initialStatus="unauthenticated">
        <LoginPage />
      </AuthProvider>,
    );
    await userEvent.type(screen.getByLabelText('Email'), 'owner@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'wrong-password');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect((await screen.findByRole('alert')).textContent).toContain('email or password is incorrect');
  });

  it('sends the CSRF signal and signs in with a registered account', async () => {
    const fetchImpl = vi.fn(async () => response(200, profile));
    render(
      <AuthProvider fetchImpl={fetchImpl as unknown as typeof fetch} initialStatus="unauthenticated">
        <LoginPage />
      </AuthProvider>,
    );
    await userEvent.type(screen.getByLabelText('Email'), 'owner@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'correct-horse-1');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(fetchImpl).toHaveBeenCalled());
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/auth/login');
    expect((init.headers as Record<string, string>)['X-Requested-With']).toBe('smart-edit');
    expect(init.credentials).toBe('include');
    expect(screen.queryByRole('alert')).toBeNull();
  });
});