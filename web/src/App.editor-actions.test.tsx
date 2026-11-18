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

vi.mock('./api/documents', () => ({
  getDocument: (...args: unknown[]) => getDocument(...args),
  createDocument: (...args: unknown[]) => createDocument(...args),
  acquireLock: (...args: unknown[]) => acquireLock(...args),
  releaseLock: (...args: unknown[]) => releaseLock(...args),
  saveDraft: (...args: unknown[]) => saveDraft(...args),
  getDraft: (...args: unknown[]) => getDraft(...args),
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
});