/** Task 4.3 — the import report: success, partial failure, and never a failure dressed as success. */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ImportReport, type ImportState } from './ImportReport';
import type { ImportedDocument } from '../api/types';

const document = (over: Partial<ImportedDocument> = {}): ImportedDocument => ({
  file_id: 'F-1',
  filename: 'guarantee.pdf',
  form: 'pdf_text',
  errors: [],
  full_text: 'DEMAND GUARANTEE',
  ...over,
});

const state = (over: Partial<ImportState> = {}): ImportState => ({
  phase: 'ready',
  documents: [document()],
  failure: null,
  ...over,
});

const renderReport = (value: ImportState) => {
  const onUse = vi.fn();
  const onRetry = vi.fn();
  const onStartBlank = vi.fn();
  render(
    <ImportReport state={value} onUse={onUse} onRetry={onRetry} onStartBlank={onStartBlank} />,
  );
  return { onUse, onRetry, onStartBlank };
};

describe('idle and reading', () => {
  it('renders nothing before an import starts', () => {
    const { container } = render(
      <ImportReport
        state={{ phase: 'idle', documents: [], failure: null }}
        onUse={vi.fn()}
        onRetry={vi.fn()}
        onStartBlank={vi.fn()}
      />,
    );

    expect(container.textContent).toBe('');
  });

  it('says it is reading, without claiming a result', () => {
    renderReport(state({ phase: 'reading', documents: [] }));

    expect(screen.getByText(/Reading the uploaded file/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Use this text/ })).toBeNull();
  });
});

describe('a document that was read', () => {
  it('names how the text was obtained and offers to use it', async () => {
    const { onUse } = renderReport(state());

    expect(screen.getByText(/PDF · text layer/)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /Use this text/ }));

    expect(onUse).toHaveBeenCalledWith(document());
  });

  it('marks recognised text as recognised', () => {
    renderReport(state({ documents: [document({ form: 'image_ocr', full_text: 'DEMAND' })] }));

    expect(screen.getByText(/Image · recognised text, please check/)).toBeTruthy();
  });

  it('says how the structure was obtained (8.3)', () => {
    renderReport(
      state({
        documents: [
          document({
            form: 'pdf_text',
            rich: {
              type: 'doc',
              provenance: 'heuristic',
              provenanceNote: 'heuristic: 25 pages, levels from font-size rank, 25 headings, 24 page breaks',
              content: [],
            },
          }),
        ],
      }),
    );

    const note = screen.getByTestId('import-provenance-F-1').textContent ?? '';
    expect(note).toContain('heuristic');
    expect(note).toContain('25 pages');
    expect(note).toContain('24 page breaks');
  });
});

describe('a document that failed', () => {
  it('explains the reason and offers no way to use it', () => {
    renderReport(
      state({
        documents: [
          document({
            file_id: 'F-2',
            filename: 'scan.png',
            form: 'image_ocr',
            errors: ['ocr_engine_missing: local OCR engine unavailable'],
            full_text: '',
          }),
        ],
      }),
    );

    expect(screen.getByText(/local OCR engine is not installed/i)).toBeTruthy();
    expect(screen.getByText(/ocr_engine_missing/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Use this text/ })).toBeNull();
    expect(screen.getByText(/could not be read/)).toBeTruthy();
  });

  it('keeps the good file usable when another one failed', () => {
    renderReport(
      state({
        documents: [
          document({ file_id: 'F-1', filename: 'ok.docx', form: 'docx_text' }),
          document({
            file_id: 'F-2',
            filename: 'bad.png',
            form: 'image_ocr',
            errors: ['no_text_recognized: the OCR engine produced no usable text'],
            full_text: '',
          }),
        ],
      }),
    );

    expect(screen.getByRole('button', { name: /Use this text/ })).toBeTruthy();
    expect(screen.getByText(/No text could be recognised/)).toBeTruthy();
  });
});

describe('when the upload itself failed', () => {
  it('shows the code and the two ways forward', async () => {
    const { onRetry, onStartBlank } = renderReport(
      state({ phase: 'failed', documents: [], failure: { code: 'EMPTY_SUBMISSION', message: 'no file' } }),
    );

    expect(screen.getByRole('alert').textContent).toContain('EMPTY_SUBMISSION');
    await userEvent.click(screen.getByRole('button', { name: /Re-upload/ }));
    await userEvent.click(screen.getByRole('button', { name: /Start from blank/ }));

    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onStartBlank).toHaveBeenCalledTimes(1);
  });
});