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

  it('reports unavailability instead of appearing to succeed', async () => {
    render(<DocumentActions />);

    await userEvent.click(screen.getByRole('button', { name: /Export · not implemented/ }));

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
describe('spec regressions found by the audit test design', () => {
  it('formatting is an implemented action, not an unavailable one', () => {
    expect(UNAVAILABLE_ACTIONS.some((action) => action.id === 'format')).toBe(false);
    render(<DocumentActions />);
    expect(screen.getByRole('button', { name: 'Formatting' })).toBeTruthy();
  });
});
