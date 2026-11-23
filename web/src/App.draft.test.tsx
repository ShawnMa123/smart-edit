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
  listDocuments: vi.fn().mockResolvedValue([]),
}));

const legalApi = vi.hoisted(() => ({
  submitReview: vi.fn(),
  getRun: vi.fn(),
  getReport: vi.fn(),
}));

vi.mock('./api/legal', () => ({
  legalClient: {
    submitReview: legalApi.submitReview,
    getRun: legalApi.getRun,
    getReport: legalApi.getReport,
  },
  LEGAL_POLL_INTERVAL_MS: 1,
  LEGAL_SCAN_TIMEOUT_MS: 5000,
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
  legalApi.submitReview.mockReset();
  legalApi.getRun.mockReset();
  legalApi.getReport.mockReset();
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
    fireEvent.click(screen.getByRole('tab', { name: /Automation · server/ }));
    fireEvent.click(screen.getByRole('tab', { name: 'Sandbox' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Templates' }));
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

  it('saves immediately on Cmd/Ctrl+S instead of waiting for the autosave debounce', async () => {
    vi.mocked(getDocument).mockResolvedValue(view());
    vi.mocked(acquireLock).mockResolvedValue(lock);
    vi.mocked(saveDraft).mockResolvedValue(view({ revision: 2, etag: 'draft-2' }));

    render(<App />);
    await waitFor(() => expect(acquireLock).toHaveBeenCalled());
    await act(async () => {
      await Promise.resolve();
    });

    fireEvent.click(screen.getByRole('button', { name: 'edit' }));
    await act(async () => {
      fireEvent.keyDown(window, { key: 's', ctrlKey: true });
      await Promise.resolve();
    });

    await waitFor(() => expect(vi.mocked(saveDraft)).toHaveBeenCalledTimes(1));
    expect(vi.mocked(saveDraft).mock.calls[0][3]).toMatchObject({ text: 'Changed' });
  });
});

describe('legal document scan', () => {
  it('saves pending editor changes before scanning the saved draft', async () => {
    vi.mocked(getDocument).mockResolvedValue(view());
    vi.mocked(acquireLock).mockResolvedValue(lock);
    vi.mocked(saveDraft).mockResolvedValue(
      view({ revision: 2, etag: 'draft-2', text: 'Changed' }),
    );
    legalApi.submitReview.mockResolvedValue({
      run_id: 'run_1',
      status: 'succeeded',
      stage: 'done',
      created_at: '2026-11-23T00:00:00Z',
      deadline_at: '2026-11-23T00:02:00Z',
      report_id: 'rep_1',
      error: null,
      finished_at: '2026-11-23T00:00:01Z',
      progress: { stage: 'done', planned: 3, done: 3 },
    });
    legalApi.getReport.mockResolvedValue({
      report_id: 'rep_1',
      run_id: 'run_1',
      completion: 'complete',
      outcome: 'no_findings',
      findings: [],
      coverage: [],
      limitations: [],
      snapshot: { document_id: 'demo-document', revision: 2, content_sha256: 'a'.repeat(64) },
      coverage_summary: {
        planned: 3,
        settled: 3,
        assessed: 3,
        assessed_ratio: 1,
        by_status: { pass: 3 },
        clauses: 1,
        truncated: false,
      },
      retrieval: { queries: 0, hits: 0, web_requested: false, web_used: false, web_calls: 0 },
      gate: { status: 'clear', reasons: [], coverage_ratio: 1, policy: 'legal-scan/1' },
    });

    render(<App />);
    await waitFor(() => expect(acquireLock).toHaveBeenCalled());
    await screen.findByText(/server draft rev 1/i);

    // The operator types and immediately asks for a document check, before the 2 s autosave fires.
    fireEvent.click(screen.getByRole('button', { name: 'edit' }));
    expect(screen.getByTestId('save-state').textContent).toBe('saving');

    fireEvent.click(screen.getByRole('tab', { name: 'Legal advice' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Document check' }));
    expect(screen.getByTestId('legal-dirty')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Scan document' }));

    await waitFor(() => expect(legalApi.submitReview).toHaveBeenCalledTimes(1));
    // The scan must not read the old, saved revision: the pending text is saved first, and the scan
    // pins that new revision.
    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(vi.mocked(saveDraft).mock.calls[0][3]).toMatchObject({ text: 'Changed' });
    expect(legalApi.submitReview).toHaveBeenCalledWith(
      expect.objectContaining({ scope: 'document', expected_revision: 2 }),
      expect.anything(),
    );
    await waitFor(() =>
      expect(screen.getByTestId('legal-scan-target').textContent).toContain('rev 2'),
    );
  });
});