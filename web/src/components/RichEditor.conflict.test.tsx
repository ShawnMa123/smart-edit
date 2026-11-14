/** The conflict surface is text-labelled and keyboard reachable (document-host D6). */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { RichEditor } from './RichEditor';

describe('RichEditor draft conflict', () => {
  it('renders the conflict text and three explicit actions', () => {
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

    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('Draft conflict');
    expect(alert.textContent).toContain('revision 4');
    expect(alert.textContent).toContain('recovery draft');
    expect(screen.getByRole('button', { name: 'Use server version' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Overwrite with local content' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Keep local as recovery draft' })).toBeTruthy();
  });
});