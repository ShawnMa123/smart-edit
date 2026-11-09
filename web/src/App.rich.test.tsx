/** Tasks 3.1/3.4 and 4.3 — the projection drives snapshots, dirty state and the audit request. */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { ApiError } from './api/errors';
import { richToPlainText } from './rich/plainText';
import { createVersionStore, memoryStorage } from './versionStore';

const createRun = vi.fn();

vi.mock('./api/client', () => ({
  API_BASE: '/api',
  createRun: (...args: unknown[]) => createRun(...args),
  createRunWithFiles: vi.fn(),
  triggerStage: vi.fn(),
  getRun: vi.fn(),
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

beforeEach(() => {
  setViewport();
  createRun.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('the empty document (4.3)', () => {
  it('projects to nothing and is never submitted as a fabricated text', async () => {
    expect(richToPlainText({ type: 'doc', content: [] })).toBe('');

    createRun.mockRejectedValue(new ApiError(400, 'EMPTY_SUBMISSION', 'provide at least one file'));
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Run spec audit/i }));

    await waitFor(() => expect(createRun).toHaveBeenCalledWith(''));
    // The server refuses an empty submission, and the panel says so instead of showing a conclusion.
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('EMPTY_SUBMISSION'));
    expect(screen.getByRole('alert').textContent).toMatch(/no conclusion/i);
  });
});

describe('versions keep both forms (3.2)', () => {
  it('restores the rich document, and reads entries that predate rich text', () => {
    const store = createVersionStore(memoryStorage());
    const rich = {
      type: 'doc' as const,
      content: [{ type: 'heading' as const, attrs: { level: 1 as const }, content: [{ type: 'text' as const, text: 'DEMAND' }] }],
    };

    const captured = store.capture('demo-document', { digest: 'd1', text: '# DEMAND', rich });
    store.capture('demo-document', { digest: 'd2', text: 'legacy text' });

    expect(store.restoreRich('demo-document', captured.id)).toEqual(rich);
    const legacy = store.list('demo-document').find((entry) => entry.text === 'legacy text');
    expect(legacy?.rich).toBeUndefined();
    expect(store.restoreRich('demo-document', legacy!.id)).toBeNull();
  });
});