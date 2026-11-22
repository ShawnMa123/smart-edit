import { describe, expect, it } from 'vitest';

import {
  APPROVAL_STATUS,
  APPROVAL_STEPS,
  approvalStatusMeta,
  approvalStepStates,
  approvalSteps,
} from './approvalStatus';

describe('approvalStatusMeta', () => {
  it('maps all six approval statuses to one shared shape', () => {
    const statuses = [
      'draft',
      'pending_first',
      'pending_second',
      'approved',
      'returned',
      'rejected',
    ] as const;

    for (const status of statuses) {
      const meta = APPROVAL_STATUS[status];
      expect(meta.key).toBe(status);
      expect(meta.label.length).toBeGreaterThan(0);
      expect(meta.shortLabel.length).toBeGreaterThan(0);
      expect(meta.icon.length).toBeGreaterThan(0);
      expect(meta.description.length).toBeGreaterThan(0);
      expect(meta.step).toBeGreaterThanOrEqual(0);
      expect(meta.step).toBeLessThanOrEqual(4);
      expect(approvalStatusMeta(status)).toBe(meta);
    }
  });

  it('names the waiting role and read-only rule for pending statuses', () => {
    expect(APPROVAL_STATUS.pending_first.waitingFor).toBe('Bank Operations');
    expect(APPROVAL_STATUS.pending_first.nextActor).toContain('First Approver');
    expect(APPROVAL_STATUS.pending_first.readOnly).toBe(true);
    expect(APPROVAL_STATUS.pending_first.tone).toBe('processing');

    expect(APPROVAL_STATUS.pending_second.waitingFor).toBe('Compliance');
    expect(APPROVAL_STATUS.pending_second.nextActor).toContain('Second Approver');
    expect(APPROVAL_STATUS.pending_second.readOnly).toBe(true);
  });

  it('marks approved read-only and returned/rejected editable again', () => {
    expect(APPROVAL_STATUS.approved.readOnly).toBe(true);
    expect(APPROVAL_STATUS.approved.tone).toBe('success');
    expect(APPROVAL_STATUS.returned.readOnly).toBe(false);
    expect(APPROVAL_STATUS.returned.tone).toBe('warning');
    expect(APPROVAL_STATUS.rejected.readOnly).toBe(false);
    expect(APPROVAL_STATUS.rejected.tone).toBe('error');
    expect(APPROVAL_STATUS.draft.readOnly).toBe(false);
  });

  it('keeps an unknown status visibly unknown instead of Draft', () => {
    const meta = approvalStatusMeta('awaiting_something');

    expect(meta.key).toBe('unknown');
    expect(meta.label).toBe('Unknown');
    expect(meta.readOnly).toBe(true);
    expect(meta.description).toContain('awaiting_something');
    expect(meta.label).not.toBe('Draft');
    expect(approvalStatusMeta(undefined).label).toBe('Unknown');
  });

  it('derives the four-step marker states from the shared status', () => {
    expect(APPROVAL_STEPS.map((step) => step.label)).toEqual([
      'Submitted',
      'Bank Operations',
      'Compliance',
      'Approved',
    ]);
    expect(approvalStepStates(APPROVAL_STATUS.draft)).toEqual([
      'upcoming',
      'upcoming',
      'upcoming',
      'upcoming',
    ]);
    expect(approvalStepStates(APPROVAL_STATUS.pending_first)).toEqual([
      'done',
      'current',
      'upcoming',
      'upcoming',
    ]);
    expect(approvalStepStates(APPROVAL_STATUS.pending_second)).toEqual([
      'done',
      'done',
      'current',
      'upcoming',
    ]);
    expect(approvalStepStates(APPROVAL_STATUS.approved)).toEqual([
      'done',
      'done',
      'done',
      'done',
    ]);
    expect(approvalStepStates(APPROVAL_STATUS.returned)).toEqual([
      'done',
      'upcoming',
      'upcoming',
      'upcoming',
    ]);
  });

  it('routes the first stage to the counterparty for bank-originated drafts', () => {
    const meta = approvalStatusMeta('pending_first', 'counterparty_first');
    expect(meta.waitingFor).toContain('counterparty');
    expect(meta.nextActor).toContain('counterparty');
    expect(approvalSteps('counterparty_first')[1].label).toContain('counterparty');

    // Applicant-originated drafts keep the existing Bank Operations wording.
    expect(approvalStatusMeta('pending_first').waitingFor).toBe('Bank Operations');
    expect(approvalSteps('bank_first')[1].label).toBe('Bank Operations');
  });
});