import { describe, expect, it } from 'vitest';

import {
  activeStep,
  canDecideApproval,
  canStartApproval,
  confirmHandoff,
  decideApproval,
  startApproval,
} from './demoApproval';
import { seedDemoState } from './demoData';

const approval = () => seedDemoState().approval;

describe('demo approval state machine', () => {
  it('starts for the applicant and moves to the first reviewer', () => {
    const approvalState = approval();
    expect(canStartApproval(approvalState, 'applicant')).toBe(true);
    const started = startApproval(approvalState, 'applicant');
    expect(started.status).toBe('IN_REVIEW');
    expect(activeStep(started)?.assigneeId).toBe('ops');
    expect(canStartApproval(started, 'applicant')).toBe(false);
  });

  it('advances through both reviewers and reaches APPROVED', () => {
    let state = startApproval(approval(), 'applicant');
    state = decideApproval(state, 'ops', 'approved', new Date('2026-11-17T10:01:00Z'));
    expect(state.status).toBe('IN_REVIEW');
    expect(activeStep(state)?.assigneeId).toBe('compliance');
    state = decideApproval(state, 'compliance', 'approved', new Date('2026-11-17T10:02:00Z'));
    expect(state.status).toBe('APPROVED');
    expect(state.receipt).toContain('Simulated');
    expect(confirmHandoff(state).status).toBe('HANDED_OFF');
  });

  it('blocks self-approval and returns a rejected request to DRAFT', () => {
    const self = { ...approval(), requesterId: 'ops' as const };
    const started = startApproval(self, 'ops');
    expect(canDecideApproval(started, 'ops')).toBe(false);

    const rejected = decideApproval(startApproval(approval(), 'applicant'), 'ops', 'rejected');
    expect(rejected.status).toBe('DRAFT');
    expect(rejected.steps.every((step) => step.decision === null)).toBe(true);
  });
});