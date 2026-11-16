/** The conflict surface is text-labelled and keyboard reachable (document-host D6). */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { RichEditor } from './RichEditor';

const renderConflict = () =>
  render(
    <RichEditor
      document={{ type: 'doc', content: [] }}
      onChange={() => undefined}
      saveState="conflict"
      conflict={{ revision: 4, sha256: 'b'.repeat(64) }}
      recoveryNotice="A recovery draft is stored in this browser."
      onUseServer={vi.fn()}
      onOverwriteLocal={vi.fn()}
      onKeepLocal={vi.fn()}
    />,
  );

describe('RichEditor draft conflict', () => {
  it('renders the conflict text and three explicit actions', () => {
    renderConflict();

    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('Draft conflict');
    expect(alert.textContent).toContain('revision 4');
    expect(alert.textContent).toContain('recovery draft');
    expect(screen.getByRole('button', { name: 'Use server version' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Overwrite with local content' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Keep local as recovery draft' })).toBeTruthy();
  });

  it('states the same conflict in the status band and the panel', () => {
    renderConflict();

    const band = screen.getByTestId('editor-status');
    const panel = screen.getByTestId('draft-conflict');
    expect(band.textContent).toContain('Save conflict');
    expect(panel.textContent).toContain('Draft conflict');
    // One saveState, one story: neither surface may claim the draft reached the server.
    expect(band.textContent).not.toContain('Saved to server');
    expect(panel.textContent).not.toContain('Saved to server');
  });
});