import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { SubmitVersionDialog } from './SubmitVersionDialog';
import { ToastProvider } from './ToastProvider';
import type { DraftView, LockView } from '../api/documents';
import { plainTextToDocument } from '../rich/richDocument';

const response = (status: number, body: unknown) =>
  ({
    ok: status < 400,
    status,
    json: async () => body,
  }) as unknown as Response;

const draft = {
  document_id: 'doc_1',
  draft_id: 'draft_1',
  title: 'Guarantee',
  revision: 3,
  etag: 'draft-3',
  content: plainTextToDocument('Amount: USD 250,000.00'),
  text: 'Amount: USD 250,000.00',
  content_sha256: 'a'.repeat(64),
  variables: {},
  variables_version: 1,
  updated_at: null,
  submission_status: 'draft',
} as DraftView;

const lock = {
  lock_id: 'lock_1',
  draft_id: 'draft_1',
  owner_user_id: 'u1',
  lease_until: '2026-11-19T01:00:00Z',
  fencing_token: 2,
  released_at: null,
} as LockView;

describe('SubmitVersionDialog', () => {
  it('submits the frozen revision with the lock token', async () => {
    const calls: Array<[string, RequestInit]> = [];
    const fetchImpl = vi.fn(async (url: string, init: RequestInit) => {
      calls.push([String(url), init]);
      return response(201, {
        submission: { submission_id: 'sub_1', status: 'pending_first', revision: 3 },
        request: { request_id: 'apr_1', status: 'pending_first' },
      });
    }) as unknown as typeof fetch;
    const submitted = vi.fn();
    const onViewApproval = vi.fn();
    render(
      <ToastProvider>
        <SubmitVersionDialog
          draft={draft}
          lock={lock}
          onClose={() => undefined}
          onSubmitted={submitted}
          onViewApproval={onViewApproval}
          fetchImpl={fetchImpl}
        />
      </ToastProvider>,
    );
    expect(screen.getByText(/Bank Operations/)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Submit for approval' }));
    await waitFor(() => expect(submitted).toHaveBeenCalled());
    expect(calls[0][0]).toContain('/documents/doc_1/submissions');
    expect(JSON.parse(String(calls[0][1].body))).toMatchObject({
      lock_id: 'lock_1',
      fencing_token: 2,
      expected_revision: 3,
    });
    const toast = await screen.findByText(/Submitted for approval/);
    expect(toast.textContent).toContain('revision 3');
    await userEvent.click(screen.getByRole('button', { name: 'View approval' }));
    expect(onViewApproval).toHaveBeenCalledTimes(1);
  });

  it('keeps the dialog open and shows an error toast when the write fails', async () => {
    const fetchImpl = vi.fn(async () =>
      response(409, { code: 'stale_revision', message: 'the draft moved' }),
    ) as unknown as typeof fetch;
    const submitted = vi.fn();
    render(
      <ToastProvider>
        <SubmitVersionDialog
          draft={draft}
          lock={lock}
          onClose={() => undefined}
          onSubmitted={submitted}
          fetchImpl={fetchImpl}
        />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Submit for approval' }));

    const alerts = await screen.findAllByRole('alert');
    expect(alerts.some((alert) => alert.textContent?.includes('the draft moved'))).toBe(true);
    expect(screen.getByRole('dialog', { name: 'Submit for approval' })).toBeTruthy();
    expect(screen.queryByText(/Submitted for approval/)).toBeNull();
    expect(submitted).not.toHaveBeenCalled();
  });

  it('shows a stale revision error instead of claiming success', async () => {
    const fetchImpl = vi.fn(async () =>
      response(409, { code: 'stale_revision', message: 'the draft moved' }),
    ) as unknown as typeof fetch;
    render(
      <SubmitVersionDialog
        draft={draft}
        lock={lock}
        onClose={() => undefined}
        onSubmitted={() => undefined}
        fetchImpl={fetchImpl}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Submit for approval' }));
    expect((await screen.findByRole('alert')).textContent).toContain('the draft moved');
  });

  it('reports a permission refusal without pretending to submit', async () => {
    const fetchImpl = vi.fn(async () =>
      response(403, { code: 'FORBIDDEN', message: 'you do not have permission' }),
    ) as unknown as typeof fetch;
    const submitted = vi.fn();
    render(
      <SubmitVersionDialog
        draft={draft}
        lock={lock}
        onClose={() => undefined}
        onSubmitted={submitted}
        fetchImpl={fetchImpl}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Submit for approval' }));
    expect((await screen.findByRole('alert')).textContent).toContain('permission');
    expect(submitted).not.toHaveBeenCalled();
  });
});