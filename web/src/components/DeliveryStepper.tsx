/**
 * Approval + delivery on one rail: Draft → Submitted → Bank Operations → Compliance → Delivered.
 *
 * Approval states come from the submission; the last stage comes from the worker's delivery
 * aggregate (`sent`, `shadowed`, `needs_review`, `needs_attention`, `not_configured`). A shadow
 * delivery is deliberately `held`, never `done`: the request was recorded, not sent.
 */

import type { ApprovalRoute } from '../api/approvalTypes';
import type { DeliveryStatus } from '../api/automationJobs';

export type DeliveryStageState = 'done' | 'current' | 'upcoming' | 'held' | 'error';

export interface DeliveryStage {
  key: 'draft' | 'submitted' | 'first' | 'second' | 'delivered';
  label: string;
  state: DeliveryStageState;
}

const DELIVERY_LABEL: Record<DeliveryStatus, string> = {
  sent: 'Delivered',
  shadowed: 'Shadowed',
  needs_review: 'Needs review',
  queued: 'Sending',
  sending: 'Sending',
  partial: 'Partial',
  needs_attention: 'Needs attention',
  not_configured: 'Not configured',
};

export function deliveryStages(
  submissionStatus?: string | null,
  deliveryStatus?: DeliveryStatus | null,
  route?: ApprovalRoute | null,
): DeliveryStage[] {
  const status = submissionStatus ?? 'draft';
  const unknown = status === 'unknown';
  const draft = status === 'draft' || unknown;
  const approved = status === 'approved';
  const pendingFirst = status === 'pending_first';
  const pendingSecond = status === 'pending_second';

  const delivered: { state: DeliveryStageState; label: string } = (() => {
    if (!approved) return { state: 'upcoming', label: 'Delivered' };
    if (deliveryStatus === 'sent') return { state: 'done', label: DELIVERY_LABEL.sent };
    if (deliveryStatus === 'shadowed') return { state: 'held', label: DELIVERY_LABEL.shadowed };
    if (deliveryStatus === 'needs_attention') {
      return { state: 'error', label: DELIVERY_LABEL.needs_attention };
    }
    if (
      deliveryStatus === 'queued' ||
      deliveryStatus === 'sending' ||
      deliveryStatus === 'partial' ||
      deliveryStatus === 'needs_review'
    ) {
      return { state: 'current', label: DELIVERY_LABEL[deliveryStatus] };
    }
    return { state: 'upcoming', label: DELIVERY_LABEL.not_configured };
  })();

  return [
    { key: 'draft', label: 'Draft', state: draft ? 'current' : 'done' },
    { key: 'submitted', label: 'Submitted', state: draft ? 'upcoming' : 'done' },
    {
      key: 'first',
      label: route === 'counterparty_first' ? 'Applicant (counterparty)' : 'Bank Operations',
      state: approved || pendingSecond ? 'done' : pendingFirst ? 'current' : 'upcoming',
    },
    {
      key: 'second',
      label: 'Compliance',
      state: approved ? 'done' : pendingSecond ? 'current' : 'upcoming',
    },
    { key: 'delivered', label: delivered.label, state: delivered.state },
  ];
}

export interface DeliveryStepperProps {
  submissionStatus?: string | null;
  deliveryStatus?: DeliveryStatus | null;
  route?: ApprovalRoute | null;
  variant?: 'compact' | 'full';
  className?: string;
}

export function DeliveryStepper({
  submissionStatus,
  deliveryStatus,
  route,
  variant = 'compact',
  className,
}: DeliveryStepperProps) {
  const stages = deliveryStages(submissionStatus, deliveryStatus, route);
  const classes = [
    'approval-stepper',
    'delivery-stepper',
    variant === 'compact' ? 'approval-stepper--compact' : null,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <ol
      className={classes}
      aria-label="Approval and delivery progress"
      data-testid={`delivery-stepper-${variant}`}
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