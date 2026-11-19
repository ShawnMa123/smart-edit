/** Real submit-for-approval dialog (replaces the placeholder). */

import { useState } from 'react';

import { submitDocument } from '../api/approval';
import type { SubmissionSummary } from '../api/approvalTypes';
import { ApiError } from '../api/errors';
import type { DraftView, LockView } from '../api/documents';
import { useToast } from './ToastProvider';
import { WorkspaceDialog } from './WorkspaceDialog';

interface SubmitVersionDialogProps {
  draft: DraftView | null;
  lock: LockView | null;
  onClose: () => void;
  onSubmitted: (submission: SubmissionSummary) => void;
  /** Opens the Approval view from the success toast. */
  onViewApproval?: () => void;
  fetchImpl?: typeof fetch;
}

export function SubmitVersionDialog({
  draft,
  lock,
  onClose,
  onSubmitted,
  onViewApproval,
  fetchImpl,
}: SubmitVersionDialogProps) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!draft || !lock) return;
    setBusy(true);
    setError(null);
    try {
      const result = await submitDocument(
        draft.document_id,
        {
          lockId: lock.lock_id,
          fencingToken: lock.fencing_token,
          expectedRevision: draft.revision,
          contentSha256: draft.content_sha256,
        },
        { fetchImpl },
      );
      toast.success(
        `Submitted for approval · revision ${result.submission.revision ?? draft.revision}`,
        {
          actionLabel: onViewApproval ? 'View approval' : undefined,
          onAction: onViewApproval,
        },
      );
      onSubmitted(result.submission);
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : 'submission failed';
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  const ready = Boolean(draft && lock);
  return (
    <WorkspaceDialog
      title="Submit for approval"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={!ready || busy} onClick={() => void submit()}>
            {busy ? 'Submitting…' : 'Submit for approval'}
          </button>
        </>
      }
    >
      {!ready ? (
        <p className="notice notice--warn">
          A server draft and the current edit lock are required before submitting.
        </p>
      ) : (
        <>
          <p>
            This freezes revision <strong>{draft?.revision}</strong> and sends it to:
          </p>
          <ol>
            <li>Bank Operations — First Approver</li>
            <li>Compliance — Second Approver</li>
          </ol>
          <p className="tiny">
            Content digest: <code>{draft?.content_sha256?.slice(0, 16)}…</code>. Editing is disabled
            until the request is returned or approved.
          </p>
        </>
      )}
      {error ? (
        <p className="notice notice--warn" role="alert">
          {error}
        </p>
      ) : null}
    </WorkspaceDialog>
  );
}