/** One approval model, two densities: compact header markers and the labelled banner rail. */

import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ApprovalStepper, approvalStages } from './ApprovalStepper';

describe('ApprovalStepper', () => {
  it('treats a draft as the first current stage', () => {
    const stages = approvalStages('draft');
    expect(stages.map((stage) => stage.label)).toEqual([
      'Draft',
      'Bank Operations',
      'Compliance',
      'Approved',
    ]);
    expect(stages.map((stage) => stage.state)).toEqual([
      'current',
      'upcoming',
      'upcoming',
      'upcoming',
    ]);
  });

  it('moves the current marker to the role that holds the submission', () => {
    render(<ApprovalStepper status="pending_first" />);
    const stepper = screen.getByTestId('approval-stepper-full');
    const steps = within(stepper).getAllByRole('listitem');

    expect(steps.map((step) => step.getAttribute('data-state'))).toEqual([
      'done',
      'current',
      'upcoming',
      'upcoming',
    ]);
    expect(steps[1].getAttribute('aria-current')).toBe('step');
    expect(steps[1].textContent).toContain('Bank Operations');
  });

  it('uses the counterparty as the first approver when the route says so', () => {
    const stages = approvalStages('pending_first', 'counterparty_first');
    expect(stages[1].label).toBe('Applicant (counterparty)');
  });

  it('keeps compact labels out of the visible text flow', () => {
    render(<ApprovalStepper variant="compact" status="pending_first" />);
    const stepper = screen.getByTestId('approval-stepper-compact');

    expect(stepper.textContent).toBe('');
    expect(stepper.querySelectorAll('[data-state]')).toHaveLength(4);
    expect(stepper.querySelector('[data-stage="first"]')?.getAttribute('aria-label')).toBe(
      'Bank Operations',
    );
    expect(stepper.querySelector('[aria-current="step"]')?.getAttribute('data-stage')).toBe('first');
  });

  it('completes every stage for an approved submission', () => {
    render(<ApprovalStepper status="approved" />);
    const steps = within(screen.getByTestId('approval-stepper-full')).getAllByRole('listitem');
    expect(steps.every((step) => step.getAttribute('data-state') === 'done')).toBe(true);
    expect(screen.getByTestId('approval-stepper-full').textContent).toContain('Approved');
  });
});