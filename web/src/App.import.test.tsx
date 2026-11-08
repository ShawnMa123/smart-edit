/** Task 4.4 — import fills the editor, and never replaces what the user typed without asking. */

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
  filename: 'guarantee.pdf',
  form: 'pdf_text',
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

const editor = () => screen.getByTestId('editor-text') as HTMLTextAreaElement;

const importOne = async (document: ImportedDocument = imported()) => {
  createRunWithFiles.mockResolvedValue(doneEnvelope());
  triggerStage.mockResolvedValue({
    ...doneEnvelope(),
    documents: [document],
  });
  const input = screen.getByTestId('import-file-input');
  await userEvent.upload(
    input,
    new File(['%PDF'], document.filename, { type: 'application/pdf' }),
  );
  // Wait for the report itself: the failure case has no "Use this text" button to wait for.
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

    expect(createRunWithFiles).toHaveBeenCalledTimes(1);
    expect(triggerStage).toHaveBeenCalledWith(expect.any(String), 'parse');
    expect(editor().value).toContain('DEMAND GUARANTEE');
  });

  it('asks before replacing what the user typed', async () => {
    render(<App />);
    await userEvent.type(editor(), 'my own draft');
    const confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal('confirm', confirm);

    await importOne();
    await userEvent.click(screen.getByRole('button', { name: /Use this text/ }));

    expect(confirm).toHaveBeenCalled();
    expect(editor().value).toBe('my own draft');
  });

  it('replaces the text when the user agrees', async () => {
    render(<App />);
    await userEvent.type(editor(), 'my own draft');
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true));

    await importOne();
    await userEvent.click(screen.getByRole('button', { name: /Use this text/ }));

    await waitFor(() => expect(editor().value).toContain('DEMAND GUARANTEE'));
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
    expect(editor().value).toBe('');
  });

  it('clears the editor only through "start from blank"', async () => {
    render(<App />);
    await userEvent.type(editor(), 'my own draft');
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true));
    await importOne();

    await userEvent.click(screen.getByRole('button', { name: /Start from blank/ }));

    expect(editor().value).toBe('');
  });
});