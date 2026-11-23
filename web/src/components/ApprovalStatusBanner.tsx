/**
 * Pending-approval banner and four-step progress (`approval-status-ui` D3).
 *
 * Sits between the document header and the editor. It answers "who is holding this now?" with
 * text, a stage marker and the latest comment, and keeps the read-only reason visible.
 */

import type { SubmissionSummary } from '../api/approvalTypes';
import { approvalStatusMeta } from '../domain/approvalStatus';
import { ApprovalStepper } from './ApprovalStepper';
import { StatusBadge } from './StatusBadge';

export interface ApprovalStatusBannerProps {
  status?: SubmissionSummary['status'] | 'draft' | string | null;
  submission?: SubmissionSummary | null;
  onViewApproval?: () => void;
}

export function ApprovalStatusBanner({
  status,
  submission,
  onViewApproval,
}: ApprovalStatusBannerProps) {
  const meta = approvalStatusMeta(status ?? submission?.status ?? 'draft', submission?.route);
  if (meta.key === 'draft') return null;

  const submittedAt = submission?.created_at
    ? new Date(submission.created_at).toLocaleString()
    : null;
  const revision = submission?.revision ?? null;
  const pending = meta.key === 'pending_first' || meta.key === 'pending_second';
  const readOnlyCopy = pending
    ? 'Editing is locked until this submission is returned or approved.'
    : meta.description;

  return (
    <section
      className={`approval-banner approval-banner--${meta.tone}`}
      aria-label="Approval status"
      data-status={meta.key}
    >
      <div className="approval-banner-head">
        <StatusBadge status={status ?? submission?.status} />
        <strong className="approval-banner-title">
          {meta.waitingFor ? `Waiting for ${meta.waitingFor}` : meta.label}
        </strong>
        {onViewApproval ? (
          <button type="button" className="small" onClick={onViewApproval}>
            View approval
          </button>
        ) : null}
      </div>

      <ApprovalStepper
        status={status ?? submission?.status}
        route={submission?.route}
      />

      <p className="approval-banner-meta tiny">
        {submittedAt ? `Submitted ${submittedAt}` : 'Submitted'}
        {revision !== null ? ` · revision ${revision}` : ''}
        {meta.nextActor ? ` · next: ${meta.nextActor}` : ''}
      </p>

      {submission?.latest_comment ? (
        <p className="approval-banner-comment tiny" data-testid="approval-banner-comment">
          {meta.key === 'returned' ? 'Return reason' : 'Latest comment'}: {submission.latest_comment}
        </p>
      ) : null}

      <p className="approval-banner-readonly tiny muted" data-testid="approval-banner-readonly">
        {readOnlyCopy}
      </p>
    </section>
  );
}