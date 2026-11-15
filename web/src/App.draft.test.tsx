/** App draft wiring: initial load, autosave and the Hybrid conflict panel. */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from './api/errors';
import { App } from './App';
import { automationTemplateStore } from './automation/templateStore';
import { plainTextToDocument } from './rich/richDocument';
import { versionStore } from './versionStore';
import {
  acquireLock,
  createDocument,
  getDocument,
  getDraft,
  saveDraft,
} from './api/documents';

vi.mock('./api/documents', () => ({
  getDocument: vi.fn(),
  createDocument: vi.fn(),
  acquireLock: vi.fn(),
  saveDraft: vi.fn(),
  getDraft: vi.fn(),
  releaseLock: vi.fn(),
}));

vi.mock('./components/RichEditor', () => ({
  RichEditor: (props: {
    onChange: (document: unknown) => void;
    saveState?: string;
    conflict?: { revision: number } | null;
    onUseServer?: () => void;
  }) => (
    <div>
      <button
        type="button"
        onClick={() =>
          props.onChange({
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Changed' }] }],
          })
        }
      >
        edit
      </button>
      <span data-testid="save-state">{props.saveState}</span>
      {props.conflict ? (
        <div data-testid="conflict">
          revision {props.conflict.revision}
          <button type="button" onClick={props.onUseServer}>
            use-server
          </button>
        </div>
      ) : null}
    </div>
  ),
}));

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

const view = (over: Record<string, unknown> = {}) => ({
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
  ...over,
});

const lock = {
  lock_id: 'lock-1',
  draft_id: 'draft-1',
  owner_user_id: 'user_demo_01',
  lease_until: '2030-01-01T00:00:00+00:00',
  fencing_token: 1,
  released_at: null,
};

beforeEach(() => {
  setViewport();
  vi.mocked(getDocument).mockReset();
  vi.mocked(createDocument).mockReset();
  vi.mocked(acquireLock).mockReset();
  vi.mocked(saveDraft).mockReset();
  vi.mocked(getDraft).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('App draft load', () => {
  it('reads the server draft and acquires the lock', async () => {
    vi.mocked(getDocument).mockResolvedValue(view());
    vi.mocked(acquireLock).mockResolvedValue(lock);

    render(<App />);

    await waitFor(() => expect(getDocument).toHaveBeenCalledWith('demo-document'));
    await waitFor(() => expect(acquireLock).toHaveBeenCalledWith('demo-document', 'draft-1'));
    expect(await screen.findByText(/server draft rev 1/i)).toBeTruthy();
  });

  it('creates a draft when the document does not exist yet', async () => {
    vi.mocked(getDocument).mockRejectedValue(new ApiError(404, 'RESOURCE_NOT_FOUND', 'missing'));
    vi.mocked(createDocument).mockResolvedValue(view());
    vi.mocked(acquireLock).mockResolvedValue(lock);

    render(<App />);

    await waitFor(() => expect(createDocument).toHaveBeenCalled());
    expect(vi.mocked(createDocument).mock.calls[0][0]).toMatchObject({
      document_id: 'demo-document',
      title: 'Demand Guarantee',
    });
  });
});

describe('autosave', () => {
  it('saves after the debounce with the current revision and lock', async () => {
    vi.useFakeTimers();
    vi.mocked(getDocument).mockResolvedValue(view());
    vi.mocked(acquireLock).mockResolvedValue(lock);
    vi.mocked(saveDraft).mockResolvedValue(view({ revision: 2, etag: 'draft-2', text: 'Changed' }));

    render(<App />);
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.click(screen.getByRole('button', { name: 'edit' }));
    expect(screen.getByTestId('save-state').textContent).toBe('saving');

    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
    });

    expect(saveDraft).toHaveBeenCalledTimes(1);
    const [documentId, draftId, revision, body] = vi.mocked(saveDraft).mock.calls[0];
    expect(documentId).toBe('demo-document');
    expect(draftId).toBe('draft-1');
    expect(revision).toBe(1);
    expect(body).toMatchObject({ lockId: 'lock-1', fencingToken: 1, text: 'Changed' });
    expect(body).not.toHaveProperty('variables');
  });

  it('keeps the local editor content and stores a recovery draft on 412', async () => {
    vi.useFakeTimers();
    vi.mocked(getDocument).mockResolvedValue(view());
    vi.mocked(acquireLock).mockResolvedValue(lock);
    vi.mocked(saveDraft).mockRejectedValue(
      new ApiError(412, 'stale_draft', 'moved', {
        current_revision: 2,
        content_sha256: 'b'.repeat(64),
      }),
    );
    vi.mocked(getDraft).mockResolvedValue(view({ revision: 2, etag: 'draft-2', text: 'Server' }));

    render(<App />);
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.click(screen.getByRole('button', { name: 'edit' }));
    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByTestId('conflict').textContent).toContain('revision 2');
    expect(screen.getByTestId('save-state').textContent).toBe('conflict');
    const stored = globalThis.localStorage.getItem('smart-edit:recovery:demo-document');
    expect(stored).toContain('Changed');
    expect(stored).toContain('"serverRevision":2');
  });

  it('does not claim a conflict is resolved when a template is applied', async () => {
    vi.useFakeTimers();
    automationTemplateStore.capture({
      name: 'Conflict template',
      document: plainTextToDocument('Template body'),
      source: { kind: 'edited' },
      revision: null,
      charCount: 'Template body'.length,
      variables: [],
      now: new Date('2026-11-15T10:00:00Z'),
    });
    vi.mocked(getDocument).mockResolvedValue(view());
    vi.mocked(acquireLock).mockResolvedValue(lock);
    vi.mocked(saveDraft).mockRejectedValue(
      new ApiError(412, 'stale_draft', 'moved', {
        current_revision: 2,
        content_sha256: 'b'.repeat(64),
      }),
    );
    vi.mocked(getDraft).mockResolvedValue(view({ revision: 2, etag: 'draft-2', text: 'Server' }));

    render(<App />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    fireEvent.click(screen.getByRole('tab', { name: /Automation · fixture only/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Conflict template · v1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Apply to editor' }));

    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByTestId('conflict').textContent).toContain('revision 2');
    expect(screen.getByTestId('save-state').textContent).toBe('conflict');
  });

  it('restores a local version by writing a new server revision', async () => {
    vi.useFakeTimers();
    vi.mocked(getDocument).mockResolvedValue(view());
    vi.mocked(acquireLock).mockResolvedValue(lock);
    vi.mocked(saveDraft).mockResolvedValue(view({ revision: 2, etag: 'draft-2', text: 'Restored text' }));
    versionStore.capture('demo-document', { digest: 'd'.repeat(64), text: 'Restored text' });

    render(<App />);
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.click(screen.getByRole('button', { name: /Restore into editor/i }));
    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
    });

    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(vi.mocked(saveDraft).mock.calls[0][3]).toMatchObject({ text: 'Restored text' });
  });
});