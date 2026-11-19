import type { SubmissionStatus } from '../api/approvalTypes';
import { approvalStatusMeta, type ApprovalStatusTone } from '../domain/approvalStatus';

export interface StatusBadgeProps {
  /** Any status string; unknown values render as "Unknown" rather than Draft. */
  status?: SubmissionStatus | 'draft' | string | null;
  className?: string;
  /** Optional title override; the shared description is used by default. */
  title?: string;
}

const toneClass: Record<ApprovalStatusTone, string> = {
  neutral: 'status-badge--neutral',
  processing: 'status-badge--processing',
  success: 'status-badge--success',
  warning: 'status-badge--warning',
  error: 'status-badge--error',
};

/**
 * One badge for every approval status (`approval-status-ui` D1). The accessible name carries the
 * full status so colour is never the only signal.
 */
export function StatusBadge({ status, className, title }: StatusBadgeProps) {
  const meta = approvalStatusMeta(typeof status === 'string' ? status : undefined);
  const classes = ['status-badge', toneClass[meta.tone], className].filter(Boolean).join(' ');
  return (
    <span
      className={classes}
      role="img"
      aria-label={`Approval status: ${meta.label}`}
      title={title ?? meta.description}
      data-status={meta.key}
    >
      <span className="status-badge-icon" aria-hidden="true">
        {meta.icon}
      </span>
      <span className="status-badge-label">{meta.label}</span>
    </span>
  );
}