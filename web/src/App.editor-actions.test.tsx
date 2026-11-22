/** App lock actions and the honest Submit new version path (workspace-editor-visual-alignment). */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { versionStore } from './versionStore';

const getDocument = vi.fn();
const createDocument = vi.fn();
const acquireLock = vi.fn();
const releaseLock = vi.fn();
const saveDraft = vi.fn();
const getDraft = vi.fn();
const listDocuments = vi.fn();

vi.mock('./api/documents', () => ({
  getDocument: (...args: unknown[]) => getDocument(...args),
  createDocument: (...args: unknown[]) => createDocument(...args),
  acquireLock: (...args: unknown[]) => acquireLock(...args),
  releaseLock: (...args: unknown[]) => releaseLock(...args),
  saveDraft: (...args: unknown[]) => saveDraft(...args),
  getDraft: (...args: unknown[]) => getDraft(...args),
  listDocuments: (...args: unknown[]) => listDocuments(...args),
}));

const view = {
  document_id: 'demo-document',
  draft_id: 'draft-1',
  title: 'Demand Guarantee',
  revision: 1,
  etag: 'draft-1',
  content: { type: 'doc' as const, content: [] },
  text: '',
  content_sha256: 'a'.repeat(64),
  variables: {},
  variables_version: 1,
  updated_at: null,
};

const lock = {
  lock_id: 'lock-1',
  draft_id: 'draft-1',
  owner_user_id: 'user_a',
  lease_until: '2026-11-17T10:00:00Z',
  fencing_token: 1,
  released_at: null,
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
  versionStore.clear('demo-document');
  getDocument.mockReset().mockResolvedValue(view);
  createDocument.mockReset().mockResolvedValue(view);
  acquireLock.mockReset().mockResolvedValue(lock);
  releaseLock.mockReset().mockResolvedValue({ ...lock, released_at: '2026-11-17T10:01:00Z' });
  saveDraft.mockReset().mockResolvedValue({ ...view, revision: 2 });
  getDraft.mockReset().mockResolvedValue(view);
  listDocuments.mockReset().mockResolvedValue([]);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('editor lock and submit actions', () => {
  it('releases and reacquires the real lock from the footer', async () => {
    render(<App />);

    await screen.findByText('lock: this session');
    await userEvent.click(screen.getByRole('button', { name: 'Release lock' }));

    await waitFor(() => expect(releaseLock).toHaveBeenCalledWith('demo-document', 'lock-1'));
    await screen.findByText('lock: unknown');
    expect((screen.getByRole('button', { name: 'Release lock' }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect((screen.getByRole('button', { name: 'Start editing' }) as HTMLButtonElement).disabled).toBe(
      false,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Start editing' }));
    await waitFor(() => expect(acquireLock).toHaveBeenCalledTimes(2));
    await screen.findByText('lock: this session');
  });

  it('keeps Submit new version honest and captures a browser-local version instead', async () => {
    render(<App />);
    await screen.findByText('lock: this session');

    await userEvent.click(screen.getByRole('button', { name: 'Submit new version' }));
    const dialog = screen.getByRole('dialog', { name: 'Submit new version' });
    expect(dialog.textContent).toContain('not available in this build');
    expect(dialog.textContent).toContain('not sent to a server');
    expect(dialog.textContent).not.toMatch(/submitted|approved/i);

    await userEvent.click(screen.getByRole('button', { name: 'Capture browser-local version' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Submit new version' })).toBeNull());
    expect(versionStore.list('demo-document')).toHaveLength(1);
  });

  it('does not overwrite a loaded draft with an empty editor when starting to edit', async () => {
    // The editor content is empty while the server draft has text (the exact state after a failed
    // mount-time load). Acquiring a lock must not autosave that empty body over the draft.
    getDocument.mockResolvedValue({ ...view, text: 'Server body' });

    render(<App />);
    await screen.findByText('lock: this session');
    await userEvent.click(screen.getByRole('button', { name: 'Release lock' }));
    await screen.findByText('lock: unknown');

    await userEvent.click(screen.getByRole('button', { name: 'Start editing' }));
    await waitFor(() => expect(acquireLock).toHaveBeenCalledTimes(2));
    await new Promise((resolve) => setTimeout(resolve, 800));

    expect(saveDraft).not.toHaveBeenCalled();
  });

  it('creates and opens a new document from the header action', async () => {
    const created = {
      ...view,
      document_id: 'doc-new',
      draft_id: 'draft-new',
      etag: 'draft-new',
      title: 'Untitled document',
    };
    createDocument.mockResolvedValue(created);
    getDocument.mockImplementation(async (documentId: string) =>
      documentId === 'doc-new' ? created : view,
    );

    render(<App />);
    await screen.findByText('lock: this session');

    await userEvent.click(screen.getByTestId('new-document'));

    await waitFor(() => expect(createDocument).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(getDocument).toHaveBeenCalledWith('doc-new'));
  });

  it('opens another document from the header switcher (authenticated)', async () => {
    const profile = {
      user: { user_id: 'usr_applicant', email: 'applicant@example.com', display_name: 'Applicant' },
      active_org: { org_id: 'org_1', workspace_id: 'ws_1', name: 'Atlas Trade Bank' },
      active_department_id: null,
      organizations: [{ org_id: 'org_1', workspace_id: 'ws_1', name: 'Atlas Trade Bank' }],
      roles: ['applicant'],
      permissions: ['document.read', 'document.create', 'approval.submit'],
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => [] }) as unknown as Response),
    );
    listDocuments.mockResolvedValue([
      {
        document_id: 'demo-document',
        title: 'Demand Guarantee',
        revision: 1,
        draft_id: 'draft-1',
        submission_status: 'draft',
        updated_at: null,
        owner_user_id: 'usr_applicant',
        department_id: null,
      },
      {
        document_id: 'doc-2',
        title: 'Commercial invoice',
        revision: 1,
        draft_id: 'draft-2',
        submission_status: 'draft',
        updated_at: null,
        owner_user_id: 'usr_applicant',
        department_id: null,
      },
    ]);
    const other = { ...view, document_id: 'doc-2', draft_id: 'draft-2', title: 'Commercial invoice' };
    getDocument.mockImplementation(async (documentId: string) =>
      documentId === 'doc-2' ? other : view,
    );

    render(<App authStatus="authenticated" authProfile={profile} autoProbe={false} />);
    await screen.findByText('lock: this session');

    const select = await screen.findByLabelText('Open document');
    await userEvent.selectOptions(select, 'doc-2');

    await waitFor(() => expect(getDocument).toHaveBeenCalledWith('doc-2'));
  });
});