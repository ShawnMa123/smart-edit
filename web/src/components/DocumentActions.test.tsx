/** Tasks 4.2 — `Import file` is a real action now; the rest are still labelled. */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DocumentActions, IMPORT_ACCEPT, UNAVAILABLE_ACTIONS } from './DocumentActions';

describe('DocumentActions', () => {
  it('labels every unavailable action', () => {
    render(<DocumentActions />);

    for (const action of UNAVAILABLE_ACTIONS) {
      expect(screen.getByRole('button', { name: new RegExp(`${action.label} · not implemented`) })).toBeTruthy();
    }
  });

  it('keeps the unavailable actions visible but quiet', () => {
    render(<DocumentActions />);

    for (const action of UNAVAILABLE_ACTIONS) {
      const button = screen.getByRole('button', {
        name: new RegExp(`${action.label} · not implemented`),
      });
      expect(button.className).toContain('quiet');
      expect(button.textContent).toContain('Not available');
      expect(button.textContent).not.toContain('not implemented');
    }
  });

  it('offers Comments after Import and reports the click', async () => {
    const onComments = vi.fn();
    render(<DocumentActions onComments={onComments} />);

    const comments = screen.getByRole('button', { name: 'Comments' });
    expect(comments).toBeTruthy();
    const buttons = screen.getAllByRole('button');
    const importIndex = buttons.findIndex((button) => button.getAttribute('data-testid') === 'import-file');
    const commentsIndex = buttons.findIndex((button) => button.getAttribute('data-testid') === 'comments');
    expect(commentsIndex).toBe(importIndex + 1);

    await userEvent.click(comments);
    expect(onComments).toHaveBeenCalledTimes(1);
  });

  it('does not mark formatting as unavailable in the header', () => {
    render(<DocumentActions />);

    expect(screen.queryByRole('button', { name: /Formatting/ })).toBeNull();
    expect(UNAVAILABLE_ACTIONS.some((action) => action.id === 'format')).toBe(false);
  });

  it('reports unavailability instead of appearing to succeed', async () => {
    const onUnavailableAction = vi.fn();
    render(<DocumentActions onUnavailableAction={onUnavailableAction} />);

    await userEvent.click(screen.getByRole('button', { name: /Export · not implemented/ }));

    expect(onUnavailableAction).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'export', label: 'Export' }),
    );
    expect(screen.getByRole('status').textContent).toContain('Unavailable');
    expect(screen.getByRole('status').textContent).toContain('Export');
    expect(screen.queryByText(/success|done|exported/i)).toBeNull();
  });

  it('explains the reason for the specific action', async () => {
    render(<DocumentActions />);

    await userEvent.click(screen.getByRole('button', { name: /Start approval · not implemented/ }));

    expect(screen.getByRole('status').textContent).toContain('approval workflow');
  });

  it('offers import as a real action, not a labelled placeholder', () => {
    render(<DocumentActions />);

    const button = screen.getByRole('button', { name: 'Import file' });
    expect(button.textContent).not.toContain('not implemented');
    expect(UNAVAILABLE_ACTIONS.some((action) => action.id === 'import')).toBe(false);
  });

  it('accepts exactly the four document types and hands the files over', async () => {
    const onImport = vi.fn();
    render(<DocumentActions onImport={onImport} />);
    const input = screen.getByTestId('import-file-input') as HTMLInputElement;

    expect(input.accept).toBe(IMPORT_ACCEPT);
    const file = new File(['%PDF'], 'guarantee.pdf', { type: 'application/pdf' });
    await userEvent.upload(input, file);

    expect(onImport).toHaveBeenCalledTimes(1);
    expect(onImport.mock.calls[0][0]).toHaveLength(1);
    expect((onImport.mock.calls[0][0] as File[])[0].name).toBe('guarantee.pdf');
    // The input is cleared so choosing the same file again still fires `change`.
    expect(input.value).toBe('');
  });
});