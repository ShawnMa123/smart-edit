/** Approval inbox, snapshot detail, decisions and entry points back to the document. */

import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  decideApproval,
  getApproval,
  listApprovals,
  listMySubmissions,
} from '../api/approval';
import { getDocument as readDocument, listDocuments, type DocumentSummary, type DraftView } from '../api/documents';
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
  /** The document currently open in the editor (labels the Open action as "Back to editor"). */
  activeDocumentId?: string;
  /** Switch the workspace back to the Document pane (the module dialog is owned by App). */
  onOpenDocument?: (documentId: string) => void;
  /** Create and open a new draft for another submission (App owns the creation + navigation). */
  onNewDocument?: () => void;
}

type View = 'first' | 'second' | 'mine' | 'documents';

export function ApprovalPanel({
  documentId,
  activeDocumentId,
  permissions,
  fetchImpl,
  onOpenDocument,
  onNewDocument,
}: ApprovalPanelProps) {
  const toast = useToast();
  const canFirst = permissions.includes('approval.first');
  const canCounterparty = permissions.includes('approval.counterparty');
  const canFirstTab = canFirst || canCounterparty;
  const canSecond = permissions.includes('approval.second');
  const canSubmit = permissions.includes('approval.submit');
  const [view, setView] = useState<View>(
    canFirstTab ? 'first' : canSecond ? 'second' : 'mine',
  );
  const [items, setItems] = useState<Array<ApprovalSummary | SubmissionSummary>>([]);
  /** Newest first, so a just-submitted request is the first row (the lifecycle tour relies on it). */
  const orderedItems = useMemo(
    () =>
      [...items].sort((left, right) =>
        String(right.created_at).localeCompare(String(left.created_at)),
      ),
    [items],
  );
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selected, setSelected] = useState<ApprovalDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  /** Title + approval status of the open document: the "open / submitted" entry point header. */
  const [document, setDocument] = useState<DraftView | null>(null);

  const load = useCallback(
    async (nextView: View = view) => {
      setError(null);
      setForbidden(false);
      try {
        if (nextView === 'documents') {
          setDocuments(await listDocuments({ fetchImpl }));
          setItems([]);
        } else if (nextView === 'mine') {
          setItems(await listMySubmissions({ fetchImpl }));
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

  // The header shows both cases: a working draft (no submission) and the latest submitted version.
  useEffect(() => {
    let cancelled = false;
    void readDocument(documentId, { fetchImpl })
      .then((view) => {
        if (!cancelled) setDocument(view);
      })
      .catch(() => {
        if (!cancelled) setDocument(null);
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, fetchImpl]);

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
        canFirstTab ? { id: 'first' as const, label: 'First approval' } : null,
        canSecond ? { id: 'second' as const, label: 'Second approval' } : null,
        canSubmit ? { id: 'mine' as const, label: 'My submissions' } : null,
        onOpenDocument || onNewDocument
          ? { id: 'documents' as const, label: 'Documents' }
          : null,
      ].filter(Boolean) as Array<{ id: View; label: string }>,
    [canFirstTab, canSecond, canSubmit, onOpenDocument, onNewDocument],
  );

  if (!tabs.length) {
    return (
      <div className="empty-state" role="status">
        <strong>No access to approvals</strong>
        <p className="tiny">Your role does not include approval or submission visibility.</p>
      </div>
    );
  }

  const submittedRequestId = document?.submission?.request_id ?? null;

  return (
    <div className="approval-panel">
      <section
        className="approval-document"
        aria-label="Current document"
        data-testid="approval-document"
        data-tour="approval-document"
      >
        <div className="row">
          <strong>{document?.title ?? 'Current document'}</strong>
          <StatusBadge status={document?.submission_status ?? 'draft'} />
          <span className="tiny">revision {document?.revision ?? '—'}</span>
        </div>
        <div className="row">
          {onOpenDocument ? (
            <button
              type="button"
              onClick={() => onOpenDocument(documentId)}
              data-testid="open-document"
            >
              {activeDocumentId === documentId ? 'Back to editor' : 'Open document'}
            </button>
          ) : null}
          {submittedRequestId ? (
            <button
              type="button"
              onClick={() => void select(submittedRequestId)}
              data-testid="view-submitted-version"
            >
              View submitted version
            </button>
          ) : (
            <span className="tiny muted" data-testid="document-not-submitted">
              No submission yet — this is the working draft.
            </span>
          )}
        </div>
      </section>

      <div className="inline-form" role="tablist" aria-label="Approval views" data-tour="approval-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={view === tab.id}
            data-tour={`approval-tab-${tab.id}`}
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
      {forbidden ? (
        <p className="notice notice--warn tiny" role="status">
          Your role cannot read this document's submissions; the document list stays available.
        </p>
      ) : null}

      {view === 'documents' ? (
        <section
          className="legal-section"
          aria-label="Documents"
          data-testid="approval-documents"
        >
          <div className="row">
            <h3>Documents</h3>
            {onNewDocument ? (
              <button
                type="button"
                className="primary"
                onClick={onNewDocument}
                data-testid="new-document"
              >
                New document
              </button>
            ) : null}
          </div>
          <p className="tiny muted">
            Open any draft or submitted document. A submitted document stays read-only; create a new
            document to keep working and submit it as well.
          </p>
          {documents.length === 0 ? <p className="tiny">No documents yet.</p> : null}
          <ul className="member-list">
            {documents.map((item) => (
              <li key={item.document_id}>
                <strong className="tiny">{item.title}</strong>
                <StatusBadge status={item.submission_status} />
                <span className="tiny">
                  {' '}rev {item.revision}
                  {item.updated_at ? ` · ${new Date(item.updated_at).toLocaleString()}` : ''}
                </span>
                {item.document_id === activeDocumentId ? (
                  <span className="tag tag--ok">open</span>
                ) : null}
                {onOpenDocument ? (
                  <button
                    type="button"
                    className="link tiny"
                    data-testid={`open-doc-${item.document_id}`}
                    data-tour="approval-open-document"
                    onClick={() => onOpenDocument(item.document_id)}
                  >
                    {item.document_id === activeDocumentId ? 'Back to editor' : 'Open'}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <div className="approval-grid">
        <section aria-label="Approval queue" data-tour="approval-queue">
          <h3>{view === 'mine' ? 'My submissions' : 'Pending requests'}</h3>
          {items.length === 0 ? (
            <p className="tiny">
              {view === 'mine' ? 'No submissions yet.' : 'Nothing waiting in this view.'}
            </p>
          ) : null}
          {view === 'mine' ? (
            <ul className="submission-cards">
              {orderedItems.map((item) => {
                const meta = approvalStatusMeta(item.status, item.route);
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
                        {item.route === 'counterparty_first' ? (
                          <span className="tag tag--warn">counterparty first</span>
                        ) : null}
                      </span>
                      <span className="tiny" data-testid={`submission-doc-${item.submission_id}`}>
                        <strong>{item.title ?? item.document_id}</strong>
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
                    {onOpenDocument ? (
                      <button
                        type="button"
                        className="link tiny"
                        data-testid={`open-document-${item.submission_id}`}
                        onClick={() => onOpenDocument(item.document_id)}
                      >
                        {item.document_id === activeDocumentId ? 'Back to editor' : 'Open document'}
                      </button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <ul className="member-list">
              {orderedItems.map((item) => (
                <li key={item.submission_id}>
                  <button type="button" className="link" onClick={() => void select(item.request_id)} data-tour="approval-select">
                    {'title' in item && item.title ? item.title : item.submission_id}
                  </button>
                  <StatusBadge status={item.status} />
                  {item.status === 'pending_first' ? (
                    <span className="tag tag--muted">
                      {item.route === 'counterparty_first'
                        ? 'counterparty → compliance'
                        : 'bank ops → compliance'}
                    </span>
                  ) : null}
                  <span className="tiny">
                    {' '}rev {item.revision} · {new Date(item.created_at).toLocaleString()}
                  </span>
                  {onOpenDocument ? (
                    <button
                      type="button"
                      className="link tiny"
                      data-testid={`open-document-${item.submission_id}`}
                      onClick={() => onOpenDocument(item.document_id)}
                    >
                      {item.document_id === activeDocumentId ? 'Back to editor' : 'Open document'}
                    </button>
                  ) : null}
                  {item.latest_comment ? (
                    <div className="tiny">Latest comment: {item.latest_comment}</div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-label="Approval detail" data-tour="approval-detail">
          {!selected ? (
            <p className="tiny">Select a request to read its frozen snapshot.</p>
          ) : (
            <>
              <h3>{selected.title ?? `Submission revision ${selected.revision}`}</h3>
              <p className="tiny">
                <StatusBadge status={selected.status} /> · revision {selected.revision} ·{' '}
                <code>{selected.content_sha256.slice(0, 16)}…</code>
              </p>
              {onOpenDocument ? (
                <button
                  type="button"
                  className="link tiny"
                  data-testid="open-document-detail"
                  onClick={() => onOpenDocument(selected.document_id)}
                >
                  {selected.document_id === activeDocumentId ? 'Back to editor' : 'Open document'}
                </button>
              ) : null}
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
                    <button type="button" className="primary" disabled={busy} onClick={() => void decide('approve')} data-tour="approval-approve">
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
      )}
    </div>
  );
}