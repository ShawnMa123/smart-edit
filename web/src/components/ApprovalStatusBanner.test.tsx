import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { SubmissionSummary } from '../api/approvalTypes';
import { ApprovalStatusBanner } from './ApprovalStatusBanner';

const submission = (over: Partial<SubmissionSummary> = {}): SubmissionSummary => ({
  submission_id: 'sub_1',
  document_id: 'demo-document',
  revision: 3,
  content_sha256: 'a'.repeat(64),
  status: 'pending_first',
  submitted_by: 'user_applicant',
  created_at: '2026-11-19T14:02:00Z',
  request_id: 'apr_1',
  current_stage: 'first',
  approval_revision: 1,
  latest_comment: null,
  latest_decision: null,
  latest_actor: null,
  latest_decided_at: null,
  ...over,
});

describe('ApprovalStatusBanner', () => {
  it('highlights Bank Operations while waiting for the first approver', () => {
    render(<ApprovalStatusBanner status="pending_first" submission={submission()} />);

    const banner = screen.getByRole('region', { name: 'Approval status' });
    expect(banner.textContent).toContain('Waiting for Bank Operations');
    expect(banner.textContent).toContain('revision 3');
    expect(banner.textContent).toContain('Submitted');
    expect(screen.getByTestId('approval-banner-readonly').textContent).toContain(
      'Editing is locked until this submission is returned or approved.',
    );

    const steps = within(banner).getAllByRole('listitem');
    expect(steps).toHaveLength(4);
    expect(steps.map((step) => step.getAttribute('data-state'))).toEqual([
      'done',
      'current',
      'upcoming',
      'upcoming',
    ]);
    expect(steps[1].getAttribute('aria-current')).toBe('step');
    expect(steps[1].textContent).toContain('Bank Operations');
  });

  it('moves the current stage to Compliance after the first approval', () => {
    render(
      <ApprovalStatusBanner
        status="pending_second"
        submission={submission({ status: 'pending_second', current_stage: 'second' })}
      />,
    );

    const banner = screen.getByRole('region', { name: 'Approval status' });
    expect(banner.textContent).toContain('Waiting for Compliance');
    const steps = within(banner).getAllByRole('listitem');
    expect(steps.map((step) => step.getAttribute('data-state'))).toEqual([
      'done',
      'done',
      'current',
      'upcoming',
    ]);
    expect(steps[2].getAttribute('aria-current')).toBe('step');
  });

  it('shows an approved submission with every step complete', () => {
    render(
      <ApprovalStatusBanner
        status="approved"
        submission={submission({ status: 'approved', revision: 4, latest_comment: 'ok' })}
      />,
    );

    const banner = screen.getByRole('region', { name: 'Approval status' });
    expect(banner.textContent).toContain('Approved');
    expect(screen.getByTestId('approval-banner-readonly').textContent).toMatch(/approved/i);
    expect(screen.getByTestId('approval-banner-comment').textContent).toContain('ok');
    const steps = within(banner).getAllByRole('listitem');
    expect(steps.every((step) => step.getAttribute('data-state') === 'done')).toBe(true);
  });

  it('shows the return reason and asks for a new submission', () => {
    render(
      <ApprovalStatusBanner
        status="returned"
        submission={submission({
          status: 'returned',
          latest_comment: 'Add the guarantee expiry date.',
        })}
      />,
    );

    const banner = screen.getByRole('region', { name: 'Approval status' });
    expect(banner.textContent).toContain('Returned');
    expect(banner.textContent).toContain('Return reason: Add the guarantee expiry date.');
    expect(banner.textContent).toContain('next: Applicant (revise and resubmit)');
    expect(banner.querySelector('[aria-current="step"]')).toBeNull();
  });

  it('renders nothing for a draft and opens the approval view on demand', () => {
    const { container, rerender } = render(<ApprovalStatusBanner status="draft" />);
    expect(container.querySelector('.approval-banner')).toBeNull();

    const onViewApproval = vi.fn();
    rerender(
      <ApprovalStatusBanner
        status="pending_first"
        submission={submission()}
        onViewApproval={onViewApproval}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'View approval' }));
    expect(onViewApproval).toHaveBeenCalledTimes(1);
  });
});