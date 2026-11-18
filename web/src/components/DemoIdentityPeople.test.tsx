import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { seedDemoState } from '../demo/demoData';
import { DemoIdentityDialog } from './DemoIdentityDialog';
import { DemoPeopleDialog } from './DemoPeopleDialog';

describe('DemoIdentityDialog', () => {
  it('lists sample users, marks the current identity and switches', () => {
    const onSelect = vi.fn();
    render(<DemoIdentityDialog state={seedDemoState()} onSelect={onSelect} />);

    expect(screen.getByText(/not an authentication result/i)).toBeTruthy();
    expect(screen.getByText('Chen Rui')).toBeTruthy();
    expect(screen.getByText('Emma Wong')).toBeTruthy();
    expect(screen.getByText('Current demo identity')).toBeTruthy();

    fireEvent.click(screen.getAllByRole('button', { name: 'Switch' })[0]);
    expect(onSelect).toHaveBeenCalledWith('ops');
  });
});

describe('DemoPeopleDialog', () => {
  it('shows sample organisations and the guest status with local actions', () => {
    const onInviteGuest = vi.fn();
    const onRevokeGuest = vi.fn();
    const { rerender } = render(
      <DemoPeopleDialog
        state={seedDemoState()}
        onInviteGuest={onInviteGuest}
        onRevokeGuest={onRevokeGuest}
      />,
    );

    expect(screen.getByText('Alpha Tech Ltd.')).toBeTruthy();
    expect(screen.getByText('HSBC Trade Operations')).toBeTruthy();
    expect(screen.getByText(/Status: active · simulated/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Revoke guest' }));
    expect(onRevokeGuest).toHaveBeenCalledTimes(1);

    rerender(
      <DemoPeopleDialog
        state={{ ...seedDemoState(), guestStatus: 'revoked' }}
        onInviteGuest={onInviteGuest}
        onRevokeGuest={onRevokeGuest}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Invite external counsel' }));
    expect(onInviteGuest).toHaveBeenCalledTimes(1);
  });
});