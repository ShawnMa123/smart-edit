import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { decideApproval, startApproval } from '../demo/demoApproval';
import { seedDemoState } from '../demo/demoData';
import { DemoApprovalDialog } from './DemoApprovalDialog';

const seed = () => seedDemoState().approval;

describe('DemoApprovalDialog', () => {
  it('starts for the applicant and blocks applicant approval', () => {
    const onStart = vi.fn();
    render(
      <DemoApprovalDialog
        approval={seed()}
        currentUserId="applicant"
        onStart={onStart}
        onDecide={() => undefined}
        onHandoff={() => undefined}
      />,
    );

    expect(screen.getByText('DRAFT')).toBeTruthy();
    expect(screen.getByText('Simulated')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Start approval' }) as HTMLButtonElement).disabled).toBe(
      false,
    );
    expect((screen.getByRole('button', { name: 'Approve' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Start approval' }));
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it('allows the active reviewer to decide and exposes the simulated receipt', () => {
    const onDecide = vi.fn();
    const started = startApproval(seed(), 'applicant');
    const { rerender } = render(
      <DemoApprovalDialog
        approval={started}
        currentUserId="ops"
        onStart={() => undefined}
        onDecide={onDecide}
        onHandoff={() => undefined}
      />,
    );

    expect((screen.getByRole('button', { name: 'Approve' }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(onDecide).toHaveBeenCalledWith('approved');

    const approved = decideApproval(
      decideApproval(started, 'ops', 'approved'),
      'compliance',
      'approved',
    );
    rerender(
      <DemoApprovalDialog
        approval={approved}
        currentUserId="compliance"
        onStart={() => undefined}
        onDecide={onDecide}
        onHandoff={() => undefined}
      />,
    );
    expect(screen.getByText('APPROVED')).toBeTruthy();
    expect(screen.getByText(/Simulated — no external system received/i)).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: 'Confirm sample handoff' }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });
});