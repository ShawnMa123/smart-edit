import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { MAX_TOASTS, ToastProvider, useToast } from './ToastProvider';

function Harness({ onAction }: { onAction?: () => void }) {
  const toast = useToast();
  return (
    <div>
      <button type="button" onClick={() => toast.success('Saved')}>
        success
      </button>
      <button type="button" onClick={() => toast.info('For information')}>
        info
      </button>
      <button type="button" onClick={() => toast.warning('Check this')}>
        warning
      </button>
      <button type="button" onClick={() => toast.error('Failed')}>
        error
      </button>
      <button
        type="button"
        onClick={() =>
          toast.success('Submitted for approval', { actionLabel: 'View approval', onAction })
        }
      >
        action
      </button>
      {[1, 2, 3, 4].map((number) => (
        <button key={number} type="button" onClick={() => toast.info(`Note ${number}`)}>
          note {number}
        </button>
      ))}
    </div>
  );
}

const renderHarness = (onAction?: () => void) =>
  render(
    <ToastProvider>
      <Harness onAction={onAction} />
    </ToastProvider>,
  );

afterEach(() => {
  vi.useRealTimers();
});

describe('ToastProvider', () => {
  it('renders all four semantic variants in a live region', () => {
    const { container, unmount } = renderHarness();

    fireEvent.click(screen.getByRole('button', { name: 'success' }));
    fireEvent.click(screen.getByRole('button', { name: 'error' }));

    expect(screen.getByText('Saved')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toContain('Failed');
    expect(container.querySelector('.toast-stack')?.getAttribute('aria-live')).toBe('polite');
    expect(container.querySelectorAll('.toast')).toHaveLength(2);
    unmount();

    const second = renderHarness();
    fireEvent.click(screen.getByRole('button', { name: 'info' }));
    fireEvent.click(screen.getByRole('button', { name: 'warning' }));

    expect(screen.getByText('For information')).toBeTruthy();
    expect(screen.getByText('Check this')).toBeTruthy();
    expect(second.container.querySelectorAll('.toast')).toHaveLength(2);
  });

  it('auto-dismisses success but keeps errors until dismissed', () => {
    vi.useFakeTimers();
    renderHarness();

    fireEvent.click(screen.getByRole('button', { name: 'success' }));
    fireEvent.click(screen.getByRole('button', { name: 'error' }));
    expect(screen.getByText('Saved')).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(screen.queryByText('Saved')).toBeNull();
    expect(screen.getByText('Failed')).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByText('Failed')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }));
    expect(screen.queryByText('Failed')).toBeNull();
  });

  it('runs the action and closes the toast', () => {
    const onAction = vi.fn();
    renderHarness(onAction);

    fireEvent.click(screen.getByRole('button', { name: 'action' }));
    fireEvent.click(screen.getByRole('button', { name: 'View approval' }));

    expect(onAction).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Submitted for approval')).toBeNull();
  });

  it('keeps at most three toasts, dropping the oldest', () => {
    const { container } = renderHarness();

    for (const number of [1, 2, 3, 4]) {
      fireEvent.click(screen.getByRole('button', { name: `note ${number}` }));
    }

    expect(MAX_TOASTS).toBe(3);
    expect(container.querySelectorAll('.toast')).toHaveLength(3);
    expect(screen.queryByText('Note 1')).toBeNull();
    expect(screen.getByText('Note 2')).toBeTruthy();
    expect(screen.getByText('Note 3')).toBeTruthy();
    expect(screen.getByText('Note 4')).toBeTruthy();
  });
});