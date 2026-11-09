/** Tasks 3.3/3.4 — import fills the editor, and never replaces what the user typed without asking. */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import type { ImportedDocument } from './api/types';
import { doneEnvelope } from './test/fixtures';

const createRunWithFiles = vi.fn();
const triggerStage = vi.fn();

vi.mock('./api/client', () => ({
  API_BASE: '/api',
  createRun: vi.fn(),
  createRunWithFiles: (...args: unknown[]) => createRunWithFiles(...args),
  triggerStage: (...args: unknown[]) => triggerStage(...args),
  getRun: vi.fn(),
}));

const imported = (over: Partial<ImportedDocument> = {}): ImportedDocument => ({
  file_id: 'F-1',
  filename: 'guarantee.docx',
  form: 'docx_text',
  errors: [],
  full_text: 'DEMAND GUARANTEE\nAmount: USD 500,000.00',
  ...over,
});

const setViewport = (narrow: boolean) => {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: narrow,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }));
};

const surface = () => screen.getByTestId('editor-rich').textContent ?? '';

const importOne = async (document: ImportedDocument = imported()) => {
  createRunWithFiles.mockResolvedValue(doneEnvelope());
  triggerStage.mockResolvedValue({ ...doneEnvelope(), documents: [document] });
  await userEvent.upload(
    screen.getByTestId('import-file-input'),
    new File(['x'], document.filename, { type: 'application/octet-stream' }),
  );
  await waitFor(() => expect(createRunWithFiles).toHaveBeenCalled());
  await screen.findByText(/documents? ready|No document could be read/);
};

beforeEach(() => {
  setViewport(false);
  createRunWithFiles.mockReset();
  triggerStage.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('importing a document', () => {
  it('uploads, parses, and puts the text into the editor', async () => {
    render(<App />);
    await importOne();

    await userEvent.click(screen.getByRole('button', { name: /Use this text/ }));

    expect(triggerStage).toHaveBeenCalledWith(expect.any(String), 'parse');
    await waitFor(() => expect(surface()).toContain('DEMAND GUARANTEE'));
    expect(surface()).toContain('USD 500,000.00');
  });

  it('asks before replacing what the user already has in the editor', async () => {
    render(<App />);
    // A real structural edit through the toolbar marks the document unsaved (jsdom cannot type into
    // ProseMirror reliably, so this uses a toolbar command rather than keystrokes).
    await userEvent.click(await screen.findByRole('button', { name: 'Insert table' }));
    const confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal('confirm', confirm);

    await importOne();
    await userEvent.click(screen.getByRole('button', { name: /Use this text/ }));

    expect(confirm).toHaveBeenCalled();
    expect(surface()).not.toContain('DEMAND GUARANTEE');
  });

  it('replaces the document when the user agrees', async () => {
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'Insert table' }));
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true));

    await importOne();
    await userEvent.click(screen.getByRole('button', { name: /Use this text/ }));

    await waitFor(() => expect(surface()).toContain('DEMAND GUARANTEE'));
  });

  it('prefers the imported structure when the file carries one', async () => {
    render(<App />);
    await importOne(
      imported({
        rich: {
          type: 'doc',
          provenance: 'deterministic',
          content: [
            { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'DEMAND GUARANTEE' }] },
            {
              type: 'table',
              content: [
                {
                  type: 'tableRow',
                  content: [
                    { type: 'tableCell', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Amount' }] }] },
                    { type: 'tableCell', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'USD 500,000.00' }] }] },
                  ],
                },
              ],
            },
          ],
        },
      }),
    );

    await userEvent.click(screen.getByRole('button', { name: /Use this text/ }));

    await waitFor(() => expect(surface()).toContain('DEMAND GUARANTEE'));
    expect(screen.getByTestId('editor-rich').querySelector('h1')).toBeTruthy();
    expect(screen.getByTestId('editor-rich').querySelector('table')).toBeTruthy();
    expect(screen.getByText(/imported \(deterministic\)/)).toBeTruthy();
  });

  it('never fills the editor from a file that failed', async () => {
    render(<App />);
    await importOne(
      imported({
        file_id: 'F-2',
        filename: 'scan.png',
        form: 'image_ocr',
        errors: ['ocr_engine_missing: local OCR engine unavailable'],
        full_text: '',
      }),
    );

    expect(screen.queryByRole('button', { name: /Use this text/ })).toBeNull();
    expect(surface().trim()).toBe('');
  });

  it('clears the editor only through "start from blank"', async () => {
    render(<App />);
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true));
    await importOne();
    await userEvent.click(screen.getByRole('button', { name: /Use this text/ }));
    await waitFor(() => expect(surface()).toContain('DEMAND GUARANTEE'));

    await importOne();
    await userEvent.click(screen.getByRole('button', { name: /Start from blank/ }));

    await waitFor(() => expect(surface().trim()).toBe(''));
  });
});