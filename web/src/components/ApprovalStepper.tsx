/**
 * The shared approval stepper (`approval-status-ui` D3, HSBC visual pass).
 *
 * One stage model, two densities:
 * - `full`    — labelled Submitted → first approver → second approver → Approved (banner)
 * - `compact` — four small hexagon markers under the document title; labels stay in aria/title,
 *               so the header adds no extra words and the word "Draft" never appears for a
 *               submitted document.
 */

import type { ApprovalRoute, SubmissionSummary } from '../api/approvalTypes';
import {
  approvalStatusMeta,
  approvalSteps,
  approvalStepStates,
  type ApprovalStepState,
} from '../domain/approvalStatus';

export interface ApprovalStage {
  key: string;
  label: string;
  state: ApprovalStepState;
}

/** Status → the four markers. Draft is its own first stage; every other status keeps the path. */
export function approvalStages(
  status?: SubmissionSummary['status'] | 'draft' | string | null,
  route?: ApprovalRoute | null,
): ApprovalStage[] {
  const meta = approvalStatusMeta(status ?? 'draft', route);
  if (meta.key === 'draft') {
    return [
      { key: 'draft', label: 'Draft', state: 'current' },
      ...approvalSteps(route)
        .slice(1)
        .map((step) => ({ key: step.key, label: step.label, state: 'upcoming' as const })),
    ];
  }
  const states = approvalStepStates(meta);
  return approvalSteps(route).map((step, index) => ({
    key: step.key,
    label: step.label,
    state: states[index],
  }));
}

export interface ApprovalStepperProps {
  status?: SubmissionSummary['status'] | 'draft' | string | null;
  route?: ApprovalRoute | null;
  variant?: 'compact' | 'full';
  className?: string;
}

export function ApprovalStepper({
  status,
  route,
  variant = 'full',
  className,
}: ApprovalStepperProps) {
  const stages = approvalStages(status, route);
  const classes = [
    'approval-stepper',
    variant === 'compact' ? 'approval-stepper--compact' : null,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <ol
      className={classes}
      aria-label="Approval progress"
      data-testid={`approval-stepper-${variant}`}
    >
      {stages.map((stage, index) => (
        <li
          key={stage.key}
          className={`approval-step approval-step--${stage.state}`}
          data-state={stage.state}
          data-stage={stage.key}
          aria-current={stage.state === 'current' ? 'step' : undefined}
          aria-label={stage.label}
          title={stage.label}
        >
          <span className="approval-step-dot" aria-hidden="true">
            {variant === 'full'
              ? stage.state === 'done'
                ? '✓'
                : stage.state === 'current'
                  ? '●'
                  : index + 1
              : ''}
          </span>
          {variant === 'full' ? <span className="approval-step-label">{stage.label}</span> : null}
        </li>
      ))}
    </ol>
  );
}