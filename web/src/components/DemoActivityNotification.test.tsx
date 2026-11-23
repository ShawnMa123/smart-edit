import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { seedDemoState } from '../demo/demoData';
import { DemoActivityPanel } from './DemoActivityPanel';
import { DemoNotificationPanel } from './DemoNotificationPanel';

describe('DemoActivityPanel', () => {
  it('shows seeded sample activity with actors and a local mark-read action', () => {
    const onMarkAllRead = vi.fn();
    render(<DemoActivityPanel state={seedDemoState()} onMarkAllRead={onMarkAllRead} />);

    expect(screen.getByText(/stored separately from the real browser-local activity/i)).toBeTruthy();
    expect(screen.getByText('Version captured')).toBeTruthy();
    expect(screen.getByText('Comment added')).toBeTruthy();
    expect(screen.getAllByText('Unread').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'Mark all read' }));
    expect(onMarkAllRead).toHaveBeenCalledTimes(1);
  });
});

describe('DemoNotificationPanel', () => {
  it('derives notifications from demo activity and never invents a real assignee', () => {
    const onMarkAllRead = vi.fn();
    render(<DemoNotificationPanel state={seedDemoState()} onMarkAllRead={onMarkAllRead} />);

    expect(screen.getByText(/No real person/i)).toBeTruthy();
    expect(screen.getByText('Comment added')).toBeTruthy();
    expect(screen.getByText('Approval requested')).toBeTruthy();
    expect(screen.queryByText('Version captured')).toBeNull();
    expect(document.body.textContent ?? '').not.toMatch(/assignee:|sent by/i);
    fireEvent.click(screen.getByRole('button', { name: 'Mark all read' }));
    expect(onMarkAllRead).toHaveBeenCalledTimes(1);
  });
});