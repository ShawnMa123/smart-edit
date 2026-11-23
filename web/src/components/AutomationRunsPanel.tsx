/** Automatic-dispatch runs: what happened after the final approval, and the manual fallbacks. */

import { useEffect, useState } from 'react';

import {
  jobsClient,
  type AutomationSettings,
  type DocumentDelivery,
  type Job,
  type JobDetail,
  type JobsClient,
} from '../api/automationJobs';
import { ApiError, explainError } from '../api/errors';
import { approvalStatusMeta } from '../domain/approvalStatus';
import { DeliveryStepper, deliveryStages } from './DeliveryStepper';

export interface AutomationRunsPanelProps {
  /** Runs are always shown for the open document; without one only the global switch is shown. */
  documentId: string | null;
  /** Latest submission status, so approval and delivery share one rail. */
  submissionStatus?: string | null;
  client?: JobsClient;
}

const STATUS_LABELS: Record<string, string> = {
  queued: 'Queued',
  sending: 'Sending',
  needs_review: 'Needs review',
  sent: 'Sent',
  shadowed: 'Shadowed',
  needs_attention: 'Needs attention',
  cancelled: 'Cancelled',
  skipped: 'Skipped',
  not_configured: 'Not configured',
  partial: 'Partial',
};

const SKIP_LABELS: Record<string, string> = {
  no_binding: 'This document has no template binding, so automatic delivery is skipped.',
  no_rule: 'No enabled rule matches this template, so nothing was queued.',
  submission_missing: 'The approved submission snapshot is no longer available.',
};

const statusClass = (status: string): string => {
  if (status === 'sent') return 'tag tag--ok';
  if (status === 'needs_attention') return 'tag tag--bad';
  if (status === 'queued' || status === 'sending' || status === 'partial') return 'tag tag--warn';
  return 'tag tag--muted';
};

export const canRelease = (job: Job): boolean => job.status === 'needs_review';
export const canRetry = (job: Job): boolean =>
  job.status === 'needs_attention' || job.status === 'cancelled';
export const canCancel = (job: Job): boolean =>
  job.status === 'queued' || job.status === 'needs_review' || job.status === 'needs_attention';

export function AutomationRunsPanel({
  documentId,
  submissionStatus,
  client = jobsClient,
}: AutomationRunsPanelProps) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [delivery, setDelivery] = useState<DocumentDelivery | null>(null);
  const [settings, setSettings] = useState<AutomationSettings | null>(null);
  const [selected, setSelected] = useState<JobDetail | null>(null);
  /** `workspace` = the open document has no jobs, so the newest workspace runs are shown instead. */
  const [scope, setScope] = useState<'document' | 'workspace'>('document');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async <T,>(work: () => Promise<T>, message?: string): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      const result = await work();
      if (message) setNotice(message);
      return result;
    } catch (failure) {
      setError(failure instanceof ApiError ? explainError(failure.code) : String(failure));
      return null;
    } finally {
      setBusy(false);
    }
  };

  const refresh = async () => {
    const [page, deliveryState, settingsState] = await Promise.all([
      client.listJobs({ document_id: documentId ?? undefined }),
      documentId ? client.readDocumentDelivery(documentId) : Promise.resolve(null),
      client.readSettings(),
    ]);
    let items = page.items;
    let nextScope: 'document' | 'workspace' = 'document';
    if (documentId && items.length === 0) {
      // A "no binding"/"no rule" skip is not a run: fall back to the workspace board so the panel
      // still shows the real jobs a Bank Ops reviewer is expected to watch.
      const all = await client.listJobs({});
      const visible = all.items.filter((job) => job.status !== 'skipped');
      if (visible.length > 0) {
        items = visible;
        nextScope = 'workspace';
      }
    }
    setJobs(items);
    setScope(nextScope);
    setDelivery(deliveryState);
    setSettings(settingsState);
  };

  useEffect(() => {
    void run(refresh).catch((failure) => setError(String(failure)));
    // The list follows the open document; actions refresh explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  const open = async (job: Job) => {
    const detail = await run(() => client.getJob(job.job_id));
    if (detail) setSelected(detail);
  };

  const act = async (job: Job, action: () => Promise<Job>, message: string) => {
    const updated = await run(action, message);
    if (!updated) return;
    await run(refresh);
    if (selected?.job_id === job.job_id) {
      const detail = await run(() => client.getJob(job.job_id));
      if (detail) setSelected(detail);
    }
  };

  return (
    <div
      className="automation-server"
      aria-label="Automatic dispatch runs"
      data-testid="automation-runs"
      data-tour="automation-runs"
    >
      {notice ? (
        <p className="tiny" role="status" aria-live="polite">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="notice notice--bad tiny" role="alert">
          {error}
        </p>
      ) : null}

      <p className="tiny muted">
        After the final approval the worker turns each matching rule into one job per downstream. A
        job sends only in <strong>auto_send</strong>; <strong>needs_review</strong> waits for you.
      </p>

      {settings ? (
        <p
          className={`notice tiny ${settings.auto_send_enabled ? '' : 'notice--warn'}`}
          data-testid="auto-send-switch"
          data-enabled={settings.auto_send_enabled ? 'yes' : 'no'}
          data-tour="automation-auto-send"
        >
          {settings.auto_send_enabled
            ? 'Automatic sending is enabled globally (SMART_EDIT_AUTOMATION_AUTO_SEND).'
            : 'Automatic sending is disabled globally: every auto_send rule behaves like shadow until the kill switch is turned back on.'}
        </p>
      ) : null}

      {documentId ? (
        <div className="delivery-chain" data-testid="delivery-chain">
          <DeliveryStepper
            variant="compact"
            submissionStatus={submissionStatus}
            deliveryStatus={delivery?.status ?? null}
          />
          <span className="tiny muted" data-testid="delivery-chain-caption">
            {approvalStatusMeta(submissionStatus ?? 'draft').shortLabel}
            {delivery
              ? ` · ${deliveryStages(submissionStatus, delivery.status).at(-1)?.label ?? ''}`
              : ''}
          </span>
        </div>
      ) : null}

      {delivery ? (
        <div className="delivery-block" data-testid="document-delivery" data-status={delivery.status}>
          <div className="delivery-head">
            <span className={statusClass(delivery.status)}>
              Delivery: {STATUS_LABELS[delivery.status] ?? delivery.status}
            </span>
            {delivery.skipped_reason ? (
              <span data-testid="delivery-skip" className="tiny muted">
                {SKIP_LABELS[delivery.skipped_reason] ?? delivery.skipped_reason}
              </span>
            ) : null}
          </div>
          {delivery.rows.length ? (
            <table className="delivery-table" data-testid="delivery-rows">
              <caption className="visually-hidden">Delivery per downstream</caption>
              <thead>
                <tr>
                  <th scope="col">Downstream</th>
                  <th scope="col">Status</th>
                  <th scope="col">Detail</th>
                </tr>
              </thead>
              <tbody>
                {delivery.rows.map((row) => (
                  <tr
                    key={row.job_id}
                    data-status={row.status}
                    data-testid={`delivery-row-${row.job_id}`}
                  >
                    <th scope="row">{row.connector_name ?? row.connector_id}</th>
                    <td>
                      <span className={statusClass(row.status)}>
                        {STATUS_LABELS[row.status] ?? row.status}
                      </span>
                      <span className="tiny muted delivery-meta">
                        {row.required ? 'Required' : 'Optional'}
                        {row.attempts > 0 ? ` · attempt ${row.attempts}` : ''}
                      </span>
                    </td>
                    <td className="tiny muted">
                      {row.error_code ??
                        (row.receipt_id ? `receipt ${row.receipt_id.slice(0, 12)}` : '—')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
      ) : (
        <p className="tiny muted">Open a document to see its delivery state.</p>
      )}

      <div className="legal-section" aria-label="Runs">
        <h3>Runs</h3>
        {scope === 'workspace' ? (
          <p className="notice tiny" data-testid="runs-scope">
            This document has no runs — showing the newest runs in this workspace.
          </p>
        ) : null}
        {jobs.length === 0 ? (
          <div className="empty-state" data-testid="runs-empty">
            <p className="tiny muted">No automatic runs yet.</p>
            <ol className="empty-steps tiny muted">
              <li>Bind this document to a server template in Automate.</li>
              <li>Add an enabled rule for that template.</li>
              <li>Send it through final approval; the worker queues one job per downstream.</li>
            </ol>
            <button
              type="button"
              className="primary"
              onClick={() => void run(refresh, 'Runs reloaded.')}
              disabled={busy}
              data-testid="runs-refresh"
            >
              Refresh runs
            </button>
          </div>
        ) : null}
        <ul className="legal-findings" data-testid="runs-list">
          {jobs.map((job) => (
            <li
              key={job.job_id}
              className="legal-finding"
              data-testid={`run-${job.job_id}`}
              data-tour="automation-run-item"
            >
              <div className="row">
                <span className={statusClass(job.status)}>
                  {STATUS_LABELS[job.status] ?? job.status}
                </span>
                <span className="tag tag--muted">
                  {job.connector_name ?? (job.connector_id || '(no downstream)')}
                </span>
                <span className="tag tag--muted">{job.rule_name ?? job.rule_id}</span>
                <span className="tag tag--muted">{job.mode}</span>
                {job.required ? null : <span className="tag tag--muted">optional</span>}
                {job.attempts ? <span className="tag tag--muted">attempt {job.attempts}</span> : null}
              </div>
              {job.error_code ? <p className="tiny muted">{job.error_code}</p> : null}
              <div className="row">
                <button type="button" onClick={() => void open(job)} disabled={busy}>
                  Details
                </button>
                {canRelease(job) ? (
                  <button
                    type="button"
                    className="primary"
                    onClick={() =>
                      void act(job, () => client.releaseJob(job.job_id), 'Job released to the worker.')
                    }
                    disabled={busy}
                    data-testid={`release-${job.job_id}`}
                  >
                    Release
                  </button>
                ) : null}
                {canRetry(job) ? (
                  <button
                    type="button"
                    onClick={() =>
                      void act(job, () => client.retryJob(job.job_id), 'Job queued again.')
                    }
                    disabled={busy}
                    data-testid={`retry-${job.job_id}`}
                  >
                    Retry
                  </button>
                ) : null}
                {canCancel(job) ? (
                  <button
                    type="button"
                    onClick={() =>
                      void act(job, () => client.cancelJob(job.job_id), 'Job cancelled.')
                    }
                    disabled={busy}
                    data-testid={`cancel-${job.job_id}`}
                  >
                    Cancel
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      </div>

      {selected ? (
        <div className="legal-findings" data-testid="run-detail">
          <p className="tiny muted">
            {selected.job_id} · {selected.document_title ?? selected.document_id} · submission{' '}
            {selected.submission_id}
          </p>
          <ol className="tiny" data-testid="run-timeline" data-tour="automation-run-timeline">
            {selected.events.map((event) => (
              <li key={event.event_id} data-testid={`run-event-${event.event_id}`}>
                {event.from_status ? `${event.from_status} → ` : ''}
                {event.to_status} · {event.created_at}
              </li>
            ))}
          </ol>
          <button type="button" onClick={() => setSelected(null)}>
            Close
          </button>
        </div>
      ) : null}
    </div>
  );
}