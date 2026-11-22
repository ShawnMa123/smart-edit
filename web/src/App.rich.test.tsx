/** Tasks 3.1/3.4 and 4.3 — the projection drives snapshots, dirty state and the audit request. */

import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
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
  it('projects to nothing and cannot start an audit with fabricated text', async () => {
    expect(richToPlainText({ type: 'doc', content: [] })).toBe('');

    render(<App />);
    const run = await screen.findByTestId('audit-run');
    expect((run as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId('audit-empty').textContent).toContain('Paste or import text');

    // Nothing was sent: the empty document never becomes a fabricated submission.
    expect(createRun).not.toHaveBeenCalled();
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