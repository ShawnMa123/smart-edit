/** Authenticated top-bar counts and applicant polling (`approval-ui-polish` tasks 3.3 / 4.2). */

import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import type { AuthProfile } from './api/identityTypes';
import type { SubmissionSummary } from './api/approvalTypes';
import type { DraftView } from './api/documents';
import { activityStore } from './workspace/activityStore';
import {
  acquireLock,
  createDocument,
  getDocument,
  getDraft,
  releaseLock,
  saveDraft,
} from './api/documents';

vi.mock('./api/documents', () => ({
  getDocument: vi.fn(),
  createDocument: vi.fn(),
  acquireLock: vi.fn(),
  releaseLock: vi.fn(),
  saveDraft: vi.fn(),
  getDraft: vi.fn(),
}));

const jsonResponse = (body: unknown, status = 200) =>
  ({
    ok: status < 400,
    status,
    json: async () => body,
  }) as unknown as Response;

const submission = (
  status: 'pending_first' | 'pending_second' | 'approved' | 'returned',
): SubmissionSummary => ({
  submission_id: 'sub_1',
  document_id: 'demo-document',
  revision: 3,
  content_sha256: 'a'.repeat(64),
  status,
  submitted_by: 'user_applicant',
  created_at: '2026-11-19T14:02:00Z',
  request_id: 'apr_1',
  current_stage:
    status === 'pending_first' ? 'first' : status === 'pending_second' ? 'second' : null,
  approval_revision: 1,
  latest_comment: status === 'returned' ? 'Add the expiry date.' : null,
  latest_decision: null,
  latest_actor: null,
  latest_decided_at: null,
});

const view = (over: Partial<DraftView> = {}): DraftView => ({
  document_id: 'demo-document',
  draft_id: 'draft-1',
  title: 'Demand Guarantee',
  revision: 3,
  etag: 'draft-3',
  content: { type: 'doc' as const, content: [] },
  text: '',
  content_sha256: 'a'.repeat(64),
  variables: {},
  variables_version: 1,
  updated_at: null,
  submission_status: 'draft',
  submission: null,
  ...over,
});

const lock = {
  lock_id: 'lock-1',
  draft_id: 'draft-1',
  owner_user_id: 'user_applicant',
  lease_until: '2030-01-01T00:00:00Z',
  fencing_token: 1,
  released_at: null,
};

const profile: AuthProfile = {
  user: { user_id: 'user_applicant', email: 'applicant@example.com', display_name: 'Applicant' },
  active_org: { org_id: 'org_1', workspace_id: 'ws_1', name: 'Alpha Tech' },
  active_department_id: null,
  organizations: [{ org_id: 'org_1', workspace_id: 'ws_1', name: 'Alpha Tech' }],
  roles: ['applicant'],
  permissions: ['approval.submit', 'approval.first'],
};

const setViewport = () => {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }));
};

beforeEach(() => {
  setViewport();
  vi.mocked(getDocument).mockReset().mockResolvedValue(view());
  vi.mocked(createDocument).mockReset().mockResolvedValue(view());
  vi.mocked(acquireLock).mockReset().mockResolvedValue(lock);
  vi.mocked(releaseLock).mockReset().mockResolvedValue(lock);
  vi.mocked(saveDraft).mockReset().mockResolvedValue(view());
  vi.mocked(getDraft).mockReset().mockResolvedValue(view());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete (document as { visibilityState?: string }).visibilityState;
});

const authenticated = () =>
  render(<App authStatus="authenticated" authProfile={profile} autoProbe={false} />);

describe('authenticated top-bar counts', () => {
  it('uses the approval/activity APIs instead of local numbers', async () => {
    const fetchImpl = vi.fn(async (url: string) => {
      const path = String(url);
      if (path.includes('/approvals?stage=first')) {
        return jsonResponse([{ submission_id: 'a' }, { submission_id: 'b' }]);
      }
      if (path.includes('/activity/unread-count')) return jsonResponse({ unread_count: 3 });
      return jsonResponse([]);
    });
    vi.stubGlobal('fetch', fetchImpl);

    authenticated();

    expect(await screen.findByLabelText('2 approval requests waiting')).toBeTruthy();
    expect(await screen.findByLabelText('3 unread activity entries')).toBeTruthy();
  });

  it('falls back to no server badges when the counts are refused', async () => {
    activityStore.record('demo-document', {
      kind: 'save',
      action: 'Local activity',
      detail: 'Browser-local only',
      notifiable: true,
    });
    const fetchImpl = vi.fn(async () => jsonResponse({ code: 'FORBIDDEN' }, 403));
    vi.stubGlobal('fetch', fetchImpl);

    authenticated();

    await waitFor(() => expect(fetchImpl).toHaveBeenCalled());
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.queryByLabelText(/approval requests waiting/)).toBeNull();
    expect(screen.queryByLabelText(/unread activity entr/)).toBeNull();
  });
});
describe('applicant status polling', () => {
  const pollCallback = () => {
    const call = vi.mocked(window.setInterval).mock.calls.find(([, delay]) => delay === 10_000);
    expect(call).toBeTruthy();
    return call?.[0] as () => void;
  };

  it('refreshes pending submissions and stops after a terminal status', async () => {
    vi.mocked(getDocument).mockResolvedValue(
      view({ submission_status: 'pending_first', submission: submission('pending_first') }),
    );
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([])));
    vi.spyOn(window, 'setInterval');

    authenticated();
    await screen.findByRole('region', { name: 'Approval status' });
    const poll = pollCallback();
    const initialCalls = vi.mocked(getDocument).mock.calls.length;

    await act(async () => {
      poll();
    });
    await waitFor(() => expect(vi.mocked(getDocument).mock.calls.length).toBe(initialCalls + 1));

    vi.mocked(getDocument).mockResolvedValue(
      view({ submission_status: 'approved', submission: submission('approved') }),
    );
    await act(async () => {
      poll();
    });
    expect(
      (await screen.findAllByRole('img', { name: 'Approval status: Approved' })).length,
    ).toBeGreaterThan(0);
    const terminalCalls = vi.mocked(getDocument).mock.calls.length;

    await act(async () => {
      poll();
    });
    expect(vi.mocked(getDocument).mock.calls.length).toBe(terminalCalls);
  });

  it('pauses the document refresh while the page is hidden', async () => {
    vi.mocked(getDocument).mockResolvedValue(
      view({ submission_status: 'pending_first', submission: submission('pending_first') }),
    );
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([])));
    vi.spyOn(window, 'setInterval');

    authenticated();
    await screen.findByRole('region', { name: 'Approval status' });
    const poll = pollCallback();
    const initialCalls = vi.mocked(getDocument).mock.calls.length;

    Object.defineProperty(document, 'visibilityState', {
      value: 'hidden',
      configurable: true,
    });
    poll();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(vi.mocked(getDocument).mock.calls.length).toBe(initialCalls);
  });
});