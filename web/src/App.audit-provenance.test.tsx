/** Change config-driven-audit-extraction (tasks 5.1 / 6.1) — the page must reach the deterministic path. */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { deterministicEnvelope, doneEnvelope } from './test/fixtures';

const createRun = vi.fn();
const triggerStage = vi.fn();

vi.mock('./api/client', () => ({
  API_BASE: '/api',
  createRun: (...args: unknown[]) => createRun(...args),
  createRunWithFiles: vi.fn(),
  triggerStage: (...args: unknown[]) => triggerStage(...args),
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
  triggerStage.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('deterministic extraction from the page', () => {
  it('passes the named template to normalize, where extraction actually runs', async () => {
    createRun.mockResolvedValue(doneEnvelope());
    // normalize backfills parse+extract; the audit then reports the deterministic provenance.
    triggerStage
      .mockResolvedValueOnce(doneEnvelope())
      .mockResolvedValueOnce(deterministicEnvelope());

    render(<App />);
    const prose = screen.getByTestId('editor-rich').querySelector('.ProseMirror') as HTMLElement;
    await userEvent.click(prose);
    await userEvent.type(prose, 'Amount: USD 500,000.00');
    await userEvent.type(screen.getByLabelText('Customer template'), 'adidas-guarantee');
    await userEvent.click(screen.getByRole('button', { name: /Run spec audit/i }));

    await waitFor(() =>
      expect(triggerStage).toHaveBeenCalledWith(expect.any(String), 'normalize', {
        template: 'adidas-guarantee',
      }),
    );
    expect(triggerStage).toHaveBeenCalledWith(expect.any(String), 'audit', {
      template: 'adidas-guarantee',
    });

    const block = await screen.findByTestId('extraction-source');
    expect(block.getAttribute('data-source')).toBe('deterministic');
    expect(screen.getByText('Deterministic profile · guarantee-default v1.0.0')).toBeTruthy();
    expect(screen.getByText(/6 fields found · 1 missing/)).toBeTruthy();
  });
});