/** Approval inbox, snapshot detail and decisions (document-submission-approval). */

import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  decideApproval,
  getApproval,
  listApprovals,
  listSubmissions,
} from '../api/approval';
import type {
  ApprovalDetail,
  ApprovalSummary,
  SubmissionSummary,
} from '../api/approvalTypes';
import { ApiError } from '../api/errors';
import { approvalStatusMeta } from '../domain/approvalStatus';
import { StatusBadge } from './StatusBadge';
import { useToast } from './ToastProvider';

interface ApprovalPanelProps {
  orgId: string;
  documentId: string;
  permissions: string[];
  fetchImpl?: typeof fetch;
}

type View = 'first' | 'second' | 'mine';

export function ApprovalPanel({ documentId, permissions, fetchImpl }: ApprovalPanelProps) {
  const toast = useToast();
  const canFirst = permissions.includes('approval.first');
  const canSecond = permissions.includes('approval.second');
  const canSubmit = permissions.includes('approval.submit');
  const [view, setView] = useState<View>(canFirst ? 'first' : canSecond ? 'second' : 'mine');
  const [items, setItems] = useState<Array<ApprovalSummary | SubmissionSummary>>([]);
  const [selected, setSelected] = useState<ApprovalDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (nextView: View = view) => {
      setError(null);
      setForbidden(false);
      try {
        if (nextView === 'mine') {
          setItems(await listSubmissions(documentId, { fetchImpl }));
        } else {
          setItems(await listApprovals(nextView, { fetchImpl }));
        }
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 403) {
          setForbidden(true);
        } else {
          setError(caught instanceof Error ? caught.message : 'could not load approvals');
        }
      }
    },
    [documentId, fetchImpl, view],
  );

  useEffect(() => {
    void load(view);
  }, [load, view]);

  const select = async (requestId: string) => {
    setError(null);
    try {
      setSelected(await getApproval(requestId, { fetchImpl }));
      setComment('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'could not load the approval');
    }
  };

  const decide = async (decision: 'approve' | 'return' | 'reject') => {
    if (!selected) return;
    if (decision !== 'approve' && !comment.trim()) {
      setError('A comment is required when returning or rejecting.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await decideApproval(
        selected.request_id,
        { decision, comment: comment.trim() || undefined, expectedRevision: selected.approval_revision },
        { fetchImpl },
      );
      setSelected(updated);
      setComment('');
      if (decision === 'approve') {
        toast.success(`Approval approved · revision ${updated.revision}`);
      } else if (decision === 'return') {
        toast.warning('Approval returned to the applicant');
      } else {
        toast.error('Approval rejected');
      }
      await load(view);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'decision failed';
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  const tabs = useMemo(
    () =>
      [
        canFirst ? { id: 'first' as const, label: 'First approval' } : null,
        canSecond ? { id: 'second' as const, label: 'Second approval' } : null,
        canSubmit ? { id: 'mine' as const, label: 'My submissions' } : null,
      ].filter(Boolean) as Array<{ id: View; label: string }>,
    [canFirst, canSecond, canSubmit],
  );

  if (!tabs.length || forbidden) {
    return (
      <div className="empty-state" role="status">
        <strong>No access to approvals</strong>
        <p className="tiny">Your role does not include approval or submission visibility.</p>
      </div>
    );
  }

  return (
    <div className="approval-panel">
      <div className="inline-form" role="tablist" aria-label="Approval views">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={view === tab.id}
            onClick={() => setView(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {error ? (
        <p className="notice notice--warn" role="alert">
          {error}
        </p>
      ) : null}

      <div className="approval-grid">
        <section aria-label="Approval queue">
          <h3>{view === 'mine' ? 'My submissions' : 'Pending requests'}</h3>
          {items.length === 0 ? (
            <p className="tiny">
              {view === 'mine' ? 'No submissions yet.' : 'Nothing waiting in this view.'}
            </p>
          ) : null}
          {view === 'mine' ? (
            <ul className="submission-cards">
              {items.map((item) => {
                const meta = approvalStatusMeta(item.status);
                return (
                  <li key={item.submission_id}>
                    <button
                      type="button"
                      className="submission-card"
                      aria-label={`Submission revision ${item.revision}`}
                      aria-pressed={selected?.submission_id === item.submission_id}
                      data-status={meta.key}
                      onClick={() => void select(item.request_id)}
                    >
                      <span className="submission-card-head">
                        <StatusBadge status={item.status} />
                        <strong>Revision {item.revision}</strong>
                      </span>
                      <span className="tiny">
                        Submitted {new Date(item.created_at).toLocaleString()}
                      </span>
                      <span className="tiny">
                        {meta.waitingFor ? `Waiting for ${meta.waitingFor}` : meta.label}
                        {meta.nextActor ? ` · next: ${meta.nextActor}` : ''}
                      </span>
                      {item.latest_comment ? (
                        <span className="tiny">Latest comment: {item.latest_comment}</span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <ul className="member-list">
              {items.map((item) => (
                <li key={item.submission_id}>
                  <button type="button" className="link" onClick={() => void select(item.request_id)}>
                    {'title' in item && item.title ? item.title : item.submission_id}
                  </button>
                  <StatusBadge status={item.status} />
                  <span className="tiny">
                    {' '}rev {item.revision} · {new Date(item.created_at).toLocaleString()}
                  </span>
                  {item.latest_comment ? (
                    <div className="tiny">Latest comment: {item.latest_comment}</div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label="Approval detail">
          {!selected ? (
            <p className="tiny">Select a request to read its frozen snapshot.</p>
          ) : (
            <>
              <h3>{selected.title ?? `Submission revision ${selected.revision}`}</h3>
              <p className="tiny">
                <StatusBadge status={selected.status} /> · revision {selected.revision} ·{' '}
                <code>{selected.content_sha256.slice(0, 16)}…</code>
              </p>
              <pre className="approval-snapshot" aria-label="Submitted snapshot text">
                {selected.text}
              </pre>
              <h4>Timeline</h4>
              <ul className="tiny">
                <li>
                  Submitted by {selected.submitted_by} ·{' '}
                  {new Date(selected.created_at).toLocaleString()}
                </li>
                {selected.steps.map((step) => (
                  <li key={step.step_id}>
                    {step.stage === 'first' ? 'First approver' : 'Second approver'} —{' '}
                    {step.decision} by {step.actor_user_id} ·{' '}
                    {new Date(step.decided_at).toLocaleString()}
                    {step.comment ? ` — “${step.comment}”` : ''}
                  </li>
                ))}
              </ul>
              {selected.can_decide ? (
                <div className="approval-decisions">
                  <label className="tiny">
                    Comment
                    <textarea
                      aria-label="Approval comment"
                      value={comment}
                      onChange={(event) => setComment(event.target.value)}
                    />
                  </label>
                  <div className="inline-form">
                    <button type="button" className="primary" disabled={busy} onClick={() => void decide('approve')}>
                      Approve
                    </button>
                    <button type="button" disabled={busy} onClick={() => void decide('return')}>
                      Return
                    </button>
                    <button type="button" disabled={busy} onClick={() => void decide('reject')}>
                      Reject
                    </button>
                  </div>
                  <p className="tiny">Return and Reject require a comment. No email is sent in this version.</p>
                </div>
              ) : null}
            </>
          )}
        </section>
      </div>
    </div>
  );
}