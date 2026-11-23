import type { DemoApproval, DemoApprovalStep, DemoUserId } from './demoData';

export type DemoDecision = 'approved' | 'rejected';

export function activeStep(approval: DemoApproval): DemoApprovalStep | null {
  if (approval.status !== 'IN_REVIEW') return null;
  return approval.steps.find((step) => step.decision === null) ?? null;
}

export function canStartApproval(approval: DemoApproval, userId: DemoUserId): boolean {
  return approval.status === 'DRAFT' && approval.requesterId === userId;
}

export function canDecideApproval(approval: DemoApproval, userId: DemoUserId): boolean {
  const step = activeStep(approval);
  return Boolean(
    step &&
      step.assigneeId === userId &&
      userId !== approval.requesterId &&
      approval.status === 'IN_REVIEW',
  );
}

export function canConfirmHandoff(approval: DemoApproval): boolean {
  return approval.status === 'APPROVED';
}

export function startApproval(
  approval: DemoApproval,
  userId: DemoUserId,
): DemoApproval {
  if (!canStartApproval(approval, userId)) return approval;
  return {
    ...approval,
    status: 'IN_REVIEW',
    steps: approval.steps.map((step) => ({ ...step, decision: null, at: null })),
    receipt: null,
  };
}

export function decideApproval(
  approval: DemoApproval,
  userId: DemoUserId,
  decision: DemoDecision,
  now = new Date(),
): DemoApproval {
  if (!canDecideApproval(approval, userId)) return approval;
  const index = approval.steps.findIndex((step) => step.decision === null);
  if (index < 0) return approval;

  const steps = approval.steps.map((step, position) =>
    position === index ? { ...step, decision, at: now.toISOString() } : { ...step },
  );

  if (decision === 'rejected') {
    return {
      ...approval,
      status: 'DRAFT',
      steps: steps.map((step) => ({ ...step, decision: null, at: null })),
      receipt: null,
    };
  }

  const remaining = steps.some((step) => step.decision === null);
  return {
    ...approval,
    status: remaining ? 'IN_REVIEW' : 'APPROVED',
    steps,
    receipt: remaining ? null : 'Simulated — no external system received the document.',
  };
}

export function confirmHandoff(approval: DemoApproval): DemoApproval {
  if (!canConfirmHandoff(approval)) return approval;
  return {
    ...approval,
    status: 'HANDED_OFF',
    receipt: 'Simulated — no external system received the document.',
  };
}