import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ApprovalPanel } from './ApprovalPanel';
import { ToastProvider } from './ToastProvider';

const response = (status: number, body: unknown) =>
  ({
    ok: status < 400,
    status,
    json: async () => body,
  }) as unknown as Response;

const summary = {
  submission_id: 'sub_1',
  document_id: 'doc_1',
  revision: 3,
  content_sha256: 'a'.repeat(64),
  status: 'pending_first',
  submitted_by: 'applicant',
  created_at: '2026-11-19T00:00:00Z',
  request_id: 'apr_1',
  current_stage: 'first',
  approval_revision: 1,
  latest_comment: null,
  latest_decision: null,
  latest_actor: null,
  latest_decided_at: null,
  title: 'Guarantee application',
  snapshot_revision: 3,
  snapshot_sha256: 'a'.repeat(64),
  department_id: null,
};

const detail = {
  ...summary,
  workspace_id: 'ws',
  text: 'Amount: USD 250,000.00',
  content: {},
  variables: {},
  variables_version: 1,
  steps: [],
  can_decide: true,
};

const fetchImpl = (decision = 'approve', status = 201) =>
  vi.fn(async (url: string, _init: RequestInit) => {
    if (String(url).includes('/decisions')) {
      return response(status, {
        ...detail,
        status: decision === 'approve' ? 'pending_second' : 'returned',
        can_decide: false,
      });
    }
    if (String(url).includes('/approvals/apr_1')) return response(200, detail);
    if (String(url).includes('/approvals')) return response(200, [summary]);
    return response(200, []);
  }) as unknown as typeof fetch;

const returnedSummary = {
  ...summary,
  submission_id: 'sub_0',
  request_id: 'apr_0',
  revision: 2,
  status: 'returned',
  current_stage: null,
  latest_comment: 'Add the guarantee expiry date.',
  created_at: '2026-11-18T09:00:00Z',
};

describe('ApprovalPanel', () => {
  it('shows the first-stage inbox and decides with a comment', async () => {
    const calls: Array<[string, RequestInit]> = [];
    const base = fetchImpl();
    const spy = vi.fn(async (url: string, init: RequestInit) => {
      calls.push([String(url), init]);
      return base(url, init);
    }) as unknown as typeof fetch;
    render(
      <ToastProvider>
        <ApprovalPanel
          orgId="org_1"
          documentId="doc_1"
          permissions={['approval.first']}
          fetchImpl={spy}
        />
      </ToastProvider>,
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Guarantee application' }));
    expect((await screen.findByLabelText('Submitted snapshot text')).textContent).toContain(
      'Amount: USD 250,000.00',
    );
    await userEvent.type(screen.getByLabelText('Approval comment'), 'first check ok');
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() =>
      expect(calls.some(([url]) => url.includes('/decisions'))).toBe(true),
    );
    const decisionCall = calls.find(([url]) => url.includes('/decisions'));
    expect(JSON.parse(String(decisionCall?.[1].body))).toEqual({
      decision: 'approve',
      comment: 'first check ok',
      expected_revision: 1,
    });
    expect((await screen.findByText(/Approval approved/)).textContent).toContain('revision 3');
  });

  it('shows an error toast and keeps the detail when a decision fails', async () => {
    const spy = vi.fn(async (url: string) => {
      const path = String(url);
      if (path.includes('/decisions')) {
        return response(409, { code: 'stale_revision', message: 'the approval moved' });
      }
      if (path.includes('/approvals/apr_1')) return response(200, detail);
      return response(200, [summary]);
    }) as unknown as typeof fetch;
    render(
      <ToastProvider>
        <ApprovalPanel
          orgId="org_1"
          documentId="doc_1"
          permissions={['approval.first']}
          fetchImpl={spy}
        />
      </ToastProvider>,
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Guarantee application' }));
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));

    const alerts = await screen.findAllByRole('alert');
    expect(alerts.some((alert) => alert.textContent?.includes('the approval moved'))).toBe(true);
    expect(screen.getByLabelText('Submitted snapshot text')).toBeTruthy();
    expect(screen.queryByText(/Approval approved/)).toBeNull();
  });

  it('requires a comment before return and does not call the API', async () => {
    const calls: string[] = [];
    const spy = vi.fn(async (url: string) => {
      calls.push(String(url));
      return String(url).includes('/approvals/apr_1')
        ? response(200, detail)
        : response(200, [summary]);
    }) as unknown as typeof fetch;
    render(
      <ApprovalPanel
        orgId="org_1"
        documentId="doc_1"
        permissions={['approval.first']}
        fetchImpl={spy}
      />,
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Guarantee application' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Return' }));
    expect((await screen.findByRole('alert')).textContent).toContain('comment is required');
    expect(calls.some((url) => url.includes('/decisions'))).toBe(false);
  });

  it('rejects with a comment', async () => {
    const calls: Array<[string, RequestInit]> = [];
    const base = fetchImpl('reject');
    const spy = vi.fn(async (url: string, init: RequestInit) => {
      calls.push([String(url), init]);
      return base(url, init);
    }) as unknown as typeof fetch;
    render(
      <ApprovalPanel
        orgId="org_1"
        documentId="doc_1"
        permissions={['approval.first']}
        fetchImpl={spy}
      />,
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Guarantee application' }));
    await userEvent.type(screen.getByLabelText('Approval comment'), 'sanctions hit');
    await userEvent.click(screen.getByRole('button', { name: 'Reject' }));
    await waitFor(() =>
      expect(calls.some(([url]) => url.includes('/decisions'))).toBe(true),
    );
    const decisionCall = calls.find(([url]) => url.includes('/decisions'));
    expect(JSON.parse(String(decisionCall?.[1].body))).toMatchObject({
      decision: 'reject',
      comment: 'sanctions hit',
    });
  });

  it('shows an access empty state without approval permissions', async () => {
    const forbidden = vi.fn(async () => response(403, { code: 'FORBIDDEN' }));
    render(
      <ApprovalPanel
        orgId="org_1"
        documentId="doc_1"
        permissions={['document.read']}
        fetchImpl={forbidden as unknown as typeof fetch}
      />,
    );
    expect(await screen.findByText('No access to approvals')).toBeTruthy();
  });

  it('lists every submission as a status card and opens its timeline', async () => {
    const spy = vi.fn(async (url: string) => {
      const path = String(url);
      if (path.includes('/approvals/apr_0')) {
        return response(200, { ...detail, ...returnedSummary, can_decide: false });
      }
      if (path.includes('/submissions')) return response(200, [returnedSummary, summary]);
      return response(200, []);
    }) as unknown as typeof fetch;
    render(
      <ApprovalPanel
        orgId="org_1"
        documentId="doc_1"
        permissions={['approval.submit']}
        fetchImpl={spy}
      />,
    );

    const returned = await screen.findByRole('button', { name: 'Submission revision 2' });
    expect(returned.textContent).toContain('Returned');
    expect(returned.textContent).toContain('Add the guarantee expiry date.');
    const pending = screen.getByRole('button', { name: 'Submission revision 3' });
    expect(pending.textContent).toContain('Pending first approval');
    expect(pending.textContent).toContain('Waiting for Bank Operations');
    expect(document.querySelectorAll('.submission-card')).toHaveLength(2);

    await userEvent.click(returned);
    expect(await screen.findByRole('heading', { name: 'Guarantee application' })).toBeTruthy();
    expect((await screen.findByLabelText('Submitted snapshot text')).textContent).toContain(
      'Amount: USD 250,000.00',
    );
    expect(screen.getByText(/Submitted by applicant/)).toBeTruthy();
  });

  it('shows an empty state when there are no submissions', async () => {
    const empty = vi.fn(async () => response(200, [])) as unknown as typeof fetch;
    render(
      <ApprovalPanel
        orgId="org_1"
        documentId="doc_1"
        permissions={['approval.submit']}
        fetchImpl={empty}
      />,
    );
    expect(await screen.findByText('No submissions yet.')).toBeTruthy();
  });

  it('offers document entry points for a submitted document', async () => {
    const openDocument = vi.fn();
    const spy = vi.fn(async (url: string) => {
      const path = String(url);
      if (path.includes('/submissions')) return response(200, [summary]);
      if (path.includes('/approvals/apr_1')) return response(200, detail);
      if (path.includes('/approvals')) return response(200, [summary]);
      if (path.includes('/documents/doc_1')) {
        return response(200, {
          document_id: 'doc_1',
          draft_id: 'draft_1',
          title: 'Guarantee application',
          revision: 3,
          etag: 'draft-3',
          content: {},
          text: 'Amount: USD 250,000.00',
          content_sha256: 'a'.repeat(64),
          variables: {},
          variables_version: 1,
          updated_at: null,
          submission_status: 'pending_first',
          submission: summary,
        });
      }
      return response(200, []);
    }) as unknown as typeof fetch;

    render(
      <ToastProvider>
        <ApprovalPanel
          orgId="org_1"
          documentId="doc_1"
          permissions={['approval.first']}
          fetchImpl={spy}
          onOpenDocument={openDocument}
        />
      </ToastProvider>,
    );

    const header = await screen.findByTestId('approval-document');
    expect(header.textContent).toContain('Guarantee application');
    expect(header.textContent).toContain('Pending first approval');
    expect(header.textContent).toContain('revision 3');

    await userEvent.click(screen.getByTestId('open-document'));
    expect(openDocument).toHaveBeenCalledWith('doc_1');

    await userEvent.click(screen.getByTestId('open-document-sub_1'));
    expect(openDocument).toHaveBeenCalledTimes(2);

    await userEvent.click(screen.getByTestId('view-submitted-version'));
    expect((await screen.findByLabelText('Submitted snapshot text')).textContent).toContain(
      'Amount: USD 250,000.00',
    );
    await userEvent.click(screen.getByTestId('open-document-detail'));
    expect(openDocument).toHaveBeenCalledWith('doc_1');
  });

  it('marks a not-yet-submitted document as the working draft', async () => {
    const openDocument = vi.fn();
    const spy = vi.fn(async (url: string) => {
      if (String(url).includes('/submissions')) return response(200, []);
      if (String(url).includes('/documents/doc_1')) {
        return response(200, {
          document_id: 'doc_1',
          draft_id: 'draft_1',
          title: 'Guarantee application',
          revision: 5,
          etag: 'draft-5',
          content: {},
          text: 'Draft body',
          content_sha256: 'b'.repeat(64),
          variables: {},
          variables_version: 1,
          updated_at: null,
          submission_status: 'draft',
          submission: null,
        });
      }
      return response(200, []);
    }) as unknown as typeof fetch;

    render(
      <ApprovalPanel
        orgId="org_1"
        documentId="doc_1"
        permissions={['approval.submit']}
        fetchImpl={spy}
        onOpenDocument={openDocument}
      />,
    );

    expect((await screen.findByTestId('approval-document')).textContent).toContain('Draft');
    expect(screen.getByTestId('document-not-submitted').textContent).toContain('working draft');
    expect(screen.queryByTestId('view-submitted-version')).toBeNull();
    await userEvent.click(screen.getByTestId('open-document'));
    expect(openDocument).toHaveBeenCalledWith('doc_1');
  });

  it('lists documents and offers Open / New document entry points', async () => {
    const openDocument = vi.fn();
    const newDocument = vi.fn();
    const spy = vi.fn(async (url: string) => {
      const path = String(url);
      if (path.includes('/submissions')) return response(200, []);
      if (path.endsWith('/documents')) {
        return response(200, [
          {
            document_id: 'doc_1',
            title: 'Guarantee application',
            revision: 3,
            draft_id: 'draft_1',
            submission_status: 'pending_first',
            updated_at: '2026-11-22T00:00:00Z',
            owner_user_id: 'usr_applicant',
            department_id: null,
          },
          {
            document_id: 'doc_2',
            title: 'Commercial invoice',
            revision: 1,
            draft_id: 'draft_2',
            submission_status: 'draft',
            updated_at: null,
            owner_user_id: 'usr_applicant',
            department_id: null,
          },
        ]);
      }
      if (path.includes('/documents/doc_1')) {
        return response(200, {
          document_id: 'doc_1',
          draft_id: 'draft_1',
          title: 'Guarantee application',
          revision: 3,
          etag: 'draft-3',
          content: {},
          text: 'Amount: USD 250,000.00',
          content_sha256: 'a'.repeat(64),
          variables: {},
          variables_version: 1,
          updated_at: null,
          submission_status: 'draft',
          submission: null,
        });
      }
      return response(200, []);
    }) as unknown as typeof fetch;

    render(
      <ApprovalPanel
        orgId="org_1"
        documentId="doc_1"
        permissions={['approval.submit']}
        fetchImpl={spy}
        onOpenDocument={openDocument}
        onNewDocument={newDocument}
      />,
    );

    await userEvent.click(await screen.findByRole('tab', { name: 'Documents' }));
    const documentsPanel = await screen.findByTestId('approval-documents');
    expect(within(documentsPanel).getByText('Commercial invoice')).toBeTruthy();
    expect(within(documentsPanel).getByText('Guarantee application')).toBeTruthy();

    await userEvent.click(screen.getByTestId('open-doc-doc_2'));
    expect(openDocument).toHaveBeenCalledWith('doc_2');

    await userEvent.click(screen.getByTestId('new-document'));
    expect(newDocument).toHaveBeenCalledTimes(1);
  });
});