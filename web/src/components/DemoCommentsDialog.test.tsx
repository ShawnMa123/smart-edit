import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { seedDemoState } from '../demo/demoData';
import { DemoCommentsDialog } from './DemoCommentsDialog';

describe('DemoCommentsDialog', () => {
  it('shows seeded sample threads and resolves locally', () => {
    const onResolve = vi.fn();
    render(
      <DemoCommentsDialog
        state={seedDemoState()}
        quote={null}
        onAdd={() => undefined}
        onResolve={onResolve}
      />,
    );

    expect(screen.getByText(/Sample data/i)).toBeTruthy();
    expect(screen.getByText(/Please confirm the demand period/i)).toBeTruthy();
    expect(screen.getByText(/Guest review/i)).toBeTruthy();
    expect(screen.getByText('Resolved')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    expect(onResolve).toHaveBeenCalledWith('demo-comment-1');
  });

  it('adds a comment with the current selection quote and blocks empty text', () => {
    const onAdd = vi.fn();
    render(
      <DemoCommentsDialog
        state={seedDemoState()}
        quote="Payment will be made within a reasonable time."
        onAdd={onAdd}
        onResolve={() => undefined}
      />,
    );

    expect(screen.getByText(/Selected passage:/)).toBeTruthy();
    const add = screen.getByRole('button', { name: 'Add sample comment' }) as HTMLButtonElement;
    expect(add.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText('New sample comment'), {
      target: { value: 'Please confirm this point.' },
    });
    fireEvent.click(add);
    expect(onAdd).toHaveBeenCalledWith(
      'Please confirm this point.',
      'Payment will be made within a reasonable time.',
    );
  });
});