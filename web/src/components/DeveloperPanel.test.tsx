import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DeveloperPanel } from './DeveloperPanel';

const response = (status: number, body: unknown) =>
  ({
    ok: status < 400,
    status,
    json: async () => body,
  }) as unknown as Response;

describe('DeveloperPanel', () => {
  it('is closed to members without developer.manage', async () => {
    const fetchImpl = vi.fn(async () => response(403, { code: 'FORBIDDEN' }));
    render(<DeveloperPanel orgId="org_1" fetchImpl={fetchImpl as unknown as typeof fetch} />);
    expect(await screen.findByText(/Developer access requires developer.manage/)).toBeTruthy();
  });

  it('shows a created key once and states that Webhooks are unavailable', async () => {
    const fetchImpl = vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url);
      if (path.includes('/keys') && init?.method === 'POST') {
        return response(201, {
          key_id: 'k1',
          name: 'CI',
          prefix: 'sk_live_abc',
          key_token: 'sk_live_abcdefghijklmnop',
          created_at: '2026-11-19T00:00:00Z',
          revoked_at: null,
          last_used_at: null,
          department_id: null,
        });
      }
      if (path.includes('/keys')) return response(200, []);
      if (path.includes('/request-logs')) return response(200, { items: [], total: 0 });
      return response(200, []);
    }) as unknown as typeof fetch;

    render(<DeveloperPanel orgId="org_1" fetchImpl={fetchImpl} />);
    await userEvent.type(await screen.findByLabelText('API key name'), 'CI');
    await userEvent.click(screen.getByRole('button', { name: 'Create key' }));
    expect((await screen.findByTestId('new-api-key')).textContent).toBe(
      'sk_live_abcdefghijklmnop',
    );
    expect(screen.getByText('Webhooks are not available in this version.')).toBeTruthy();
  });
});