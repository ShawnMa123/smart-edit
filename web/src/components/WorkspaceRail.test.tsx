import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { WorkspaceRail } from './WorkspaceRail';

describe('WorkspaceRail', () => {
  it('exposes the reference entry set with accessible names', () => {
    render(<WorkspaceRail active={null} onOpen={() => undefined} />);

    for (const label of ['Document', 'Versions', 'Approval', 'Comments', 'People', 'Developer']) {
      expect(screen.getByRole('button', { name: label })).toBeTruthy();
    }
  });

  it('marks the active entry in words as well as colour', () => {
    render(<WorkspaceRail active="versions" onOpen={() => undefined} />);

    expect(screen.getByRole('button', { name: 'Versions' }).getAttribute('aria-current')).toBe(
      'page',
    );
    expect(screen.getByRole('button', { name: 'Document' }).getAttribute('aria-current')).toBeNull();
  });

  it('opens the selected rail entry', () => {
    const onOpen = vi.fn();
    render(<WorkspaceRail active="document" onOpen={onOpen} />);

    fireEvent.click(screen.getByRole('button', { name: 'People' }));
    expect(onOpen).toHaveBeenCalledWith('people');
  });
});