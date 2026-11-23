/** Approval + delivery rail: five stages from draft to what the downstream actually received. */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DeliveryStepper, deliveryStages } from './DeliveryStepper';

describe('DeliveryStepper', () => {
  it('starts at draft and keeps the rest upcoming', () => {
    expect(deliveryStages('draft').map((stage) => stage.state)).toEqual([
      'current',
      'upcoming',
      'upcoming',
      'upcoming',
      'upcoming',
    ]);
  });

  it('marks the role that currently holds the submission', () => {
    expect(deliveryStages('pending_first').map((stage) => stage.state)).toEqual([
      'done',
      'done',
      'current',
      'upcoming',
      'upcoming',
    ]);
    expect(deliveryStages('pending_second').map((stage) => stage.state)).toEqual([
      'done',
      'done',
      'done',
      'current',
      'upcoming',
    ]);
  });

  it('completes the rail only when the downstream accepted the request', () => {
    expect(deliveryStages('approved', 'sent').every((stage) => stage.state === 'done')).toBe(true);

    const shadowed = deliveryStages('approved', 'shadowed').at(-1);
    expect(shadowed).toMatchObject({ state: 'held', label: 'Shadowed' });

    const failed = deliveryStages('approved', 'needs_attention').at(-1);
    expect(failed).toMatchObject({ state: 'error', label: 'Needs attention' });

    const waiting = deliveryStages('approved', 'needs_review').at(-1);
    expect(waiting).toMatchObject({ state: 'current', label: 'Needs review' });
  });

  it('keeps compact labels in aria only and renders five hexagons', () => {
    render(<DeliveryStepper submissionStatus="approved" deliveryStatus="shadowed" />);
    const rail = screen.getByTestId('delivery-stepper-compact');

    expect(rail.textContent).toBe('');
    expect(rail.querySelectorAll('[data-state]')).toHaveLength(5);
    expect(rail.querySelector('[data-stage="delivered"]')?.getAttribute('aria-label')).toBe(
      'Shadowed',
    );
  });
});