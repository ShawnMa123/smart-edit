import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { WorkspaceDialog } from './WorkspaceDialog';

describe('WorkspaceDialog', () => {
  it('renders a labelled modal dialog and closes from its button', () => {
    const onClose = vi.fn();
    render(
      <WorkspaceDialog title="Activity" onClose={onClose}>
        <p>Browser-local activity</p>
      </WorkspaceDialog>,
    );

    const dialog = screen.getByRole('dialog', { name: 'Activity' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(screen.getByText('Browser-local activity')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on Escape and backdrop click', () => {
    const onClose = vi.fn();
    render(
      <WorkspaceDialog title="Inbox" onClose={onClose}>
        <p>Empty</p>
      </WorkspaceDialog>,
    );

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.mouseDown(screen.getByTestId('dialog-backdrop'));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('returns focus to the trigger when it unmounts', () => {
    const trigger = document.createElement('button');
    trigger.textContent = 'Open activity';
    document.body.append(trigger);
    trigger.focus();

    const { unmount } = render(
      <WorkspaceDialog title="Activity" onClose={() => undefined}>
        <p>Body</p>
      </WorkspaceDialog>,
    );

    unmount();
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });
});