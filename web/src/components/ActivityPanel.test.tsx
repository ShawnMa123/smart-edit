import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ActivityEntry } from '../workspace/activityStore';
import { ActivityPanel } from './ActivityPanel';

const entry = (over: Partial<ActivityEntry> = {}): ActivityEntry => ({
  id: 'a-1',
  kind: 'capture',
  action: 'Version captured',
  detail: 'Version 2 captured',
  at: '2026-11-17T09:00:00.000Z',
  read: false,
  notifiable: true,
  ...over,
});

describe('ActivityPanel', () => {
  it('states the browser-local scope and lists events newest first as supplied', () => {
    render(
      <ActivityPanel
        activity={[entry({ id: 'a-2', action: 'Audit completed' }), entry()]}
        available
        onClear={() => undefined}
      />,
    );

    expect(screen.getByText(/Browser-local activity — not a server audit trail/i)).toBeTruthy();
    const items = screen.getAllByRole('listitem');
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining('Audit completed'),
      expect.stringContaining('Version captured'),
    ]);
  });

  it('requires confirmation before clearing and supports cancel', () => {
    const onClear = vi.fn();
    render(<ActivityPanel activity={[entry()]} available onClear={onClear} />);

    fireEvent.click(screen.getByRole('button', { name: 'Clear activity' }));
    expect(onClear).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClear).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Clear activity' }));
    fireEvent.click(screen.getByRole('button', { name: 'Clear activity' }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it('shows an empty state and the storage degradation notice', () => {
    render(<ActivityPanel activity={[]} available={false} onClear={() => undefined} />);

    expect(screen.getByText(/No activity yet/i)).toBeTruthy();
    expect(screen.getByText(/session-only because browser storage is unavailable/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Clear activity' })).toBeNull();
  });
});