/**
 * Shell layers above the three-pane grid (workspace-visual-parity / design D1–D3, D8).
 *
 * This build has no authentication, so the shell must not imply a signed-in user or a
 * participating organisation. It shows the product, the session boundary and only document
 * facts the client actually holds.
 */

import type { ReactNode } from 'react';

import type { SubmissionSummary } from '../api/approvalTypes';
import type { DeliveryStatus } from '../api/automationJobs';
import { approvalStatusMeta } from '../domain/approvalStatus';
import { TOPBAR_ENTRIES, type WorkspaceModule } from '../workspace/workspaceModules';
import { DeliveryStepper, deliveryStages } from './DeliveryStepper';
import { StatusBadge } from './StatusBadge';

/** Configurable product label; a deployment may replace it without touching the layout. */
export const PRODUCT_NAME = 'Trade workspace';
export const SESSION_LABEL = 'Local demo session';
export const DOCUMENT_SECTION = 'Trade documents / Guarantees';

export interface DemoIdentityView {
  name: string;
  initials: string;
  org: string;
  role: string;
}

export interface TopBarProps {
  onOpenModule?: (module: WorkspaceModule) => void;
  /** Pending approval requests the principal can decide (server aggregated). */
  approvalCount?: number;
  /** Server-side unread Activity count; never browser-local notifications. */
  activityUnread?: number;
  /** Unread Inbox notifications (local or server, depending on the session). */
  unreadCount?: number;
  sessionLabel?: string;
  demoIdentity?: DemoIdentityView | null;
  /** PG identity: organisation switcher and sign-out (task 6.2). */
  organizations?: Array<{ org_id: string; name: string }>;
  activeOrgId?: string | null;
  onSwitchOrg?: (orgId: string) => void;
  userLabel?: string | null;
  onLogout?: () => void;
  /** Opens the guided product tour launcher (mode + submission choice). */
  onStartTour?: () => void;
}

const badgeLabel = (entryId: string, count: number): string => {
  if (entryId === 'approval') {
    return `${count} approval ${count === 1 ? 'request' : 'requests'} waiting`;
  }
  if (entryId === 'activity') {
    return `${count} unread activity ${count === 1 ? 'entry' : 'entries'}`;
  }
  return `${count} unread ${count === 1 ? 'notification' : 'notifications'}`;
};

export function TopBar({
  onOpenModule,
  approvalCount = 0,
  activityUnread = 0,
  unreadCount = 0,
  sessionLabel = SESSION_LABEL,
  demoIdentity = null,
  organizations = [],
  activeOrgId = null,
  onSwitchOrg,
  userLabel = null,
  onLogout,
  onStartTour,
}: TopBarProps = {}) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          S
        </span>
        <strong>smart-edit</strong>
        <span className="product">{PRODUCT_NAME}</span>
      </div>
      <div className="topbar-actions">
        {onStartTour ? (
          <button
            type="button"
            className="small"
            data-tour="tour-launcher"
            title="Take the guided product tour"
            aria-label="Take the guided product tour"
            onClick={onStartTour}
          >
            <span className="topbar-icon" aria-hidden="true">
              ?
            </span>
            <span className="topbar-label">Take the tour</span>
          </button>
        ) : null}
        {TOPBAR_ENTRIES.map((entry) => {
          const count =
            entry.id === 'approval'
              ? approvalCount
              : entry.id === 'activity'
                ? activityUnread
                : entry.id === 'inbox'
                  ? unreadCount
                  : null;
          return (
            <button
              key={entry.id}
              type="button"
              className="small"
              data-tour={`topbar-${entry.id}`}
              aria-label={entry.label}
              title={entry.label}
              onClick={() => onOpenModule?.(entry.id as WorkspaceModule)}
            >
              <span className="topbar-icon" aria-hidden="true">
                {entry.icon}
              </span>
              <span className="topbar-label">{entry.label}</span>
              {count !== null && count > 0 ? (
                <span className="badge" aria-label={badgeLabel(entry.id, count)}>
                  {count > 99 ? '99+' : count}
                </span>
              ) : null}
            </button>
          );
        })}
        {organizations.length > 0 ? (
          <div className="org-switcher">
            <label className="tiny" htmlFor="active-org">
              Organisation
            </label>
            <select
              id="active-org"
              aria-label="Active organisation"
              value={activeOrgId ?? organizations[0]?.org_id}
              onChange={(event) => onSwitchOrg?.(event.target.value)}
            >
              {organizations.map((organization) => (
                <option key={organization.org_id} value={organization.org_id}>
                  {organization.name}
                </option>
              ))}
            </select>
            {userLabel ? (
              <span className="tiny" data-tour="session-user">
                {userLabel}
              </span>
            ) : null}
            {onLogout ? (
              <button type="button" className="small" onClick={onLogout}>
                Sign out
              </button>
            ) : null}
          </div>
        ) : null}
        {demoIdentity ? (
          <button
            type="button"
            className="demo-identity"
            aria-label={`Demo identity: ${demoIdentity.name}, ${demoIdentity.org}, ${demoIdentity.role}`}
            title="Switch demo identity"
            onClick={() => onOpenModule?.('identity')}
          >
            <span className="avatar" aria-hidden="true">
              {demoIdentity.initials}
            </span>
            <span className="identity-copy">
              <strong>{demoIdentity.name}</strong>
              <span>{demoIdentity.org}</span>
            </span>
            <span className="tag tag--warn">Demo identity</span>
          </button>
        ) : (
          <button
            type="button"
            className="tag tag--muted session-chip"
            aria-label={`${sessionLabel} · authentication not configured`}
            title="Local session"
            onClick={() => onOpenModule?.('identity')}
          >
            {sessionLabel}
          </button>
        )}
      </div>
    </header>
  );
}

export interface DocumentFacts {
  documentId: string;
  title: string;
  versions: number;
  characters: number;
  /** `null` means there is no server draft yet. */
  draftRevision: number | null;
  draftSha256?: string | null;
  provenance?: string | null;
  /** Worded lock state; unknown is a first-class value. */
  lockLabel?: string;
}

export interface EnvironmentStripProps {
  demoMode?: boolean;
  /** True once PG identity is active: approval is server-backed, not a demo placeholder. */
  authenticated?: boolean;
  onToggleDemo?: () => void;
  onResetDemo?: () => void;
  demoStorageAvailable?: boolean;
}

/** One standing summary instead of a disclaimer per panel (design D3/D7). */
export function EnvironmentStrip({
  demoMode = false,
  authenticated = false,
  onToggleDemo,
  onResetDemo,
  demoStorageAvailable = true,
}: EnvironmentStripProps = {}) {
  const copy = demoMode
    ? 'Demo data — sample users, organisations and approvals; not real authentication or workflow.'
    : authenticated
      ? 'PG identity · server-backed drafts, approvals and activity'
      : 'Synthetic demo data · fixed snapshot per audit · version history and templates stay in this browser';
  return (
    <div className="environment-strip" role="status" data-demo={demoMode}>
      <span className="environment-copy">{copy}</span>
      <div className="environment-actions">
        {demoMode && !demoStorageAvailable ? (
          <span className="tiny muted">Demo data is session-only in this browser.</span>
        ) : null}
        <label className="demo-toggle">
          <input type="checkbox" checked={demoMode} onChange={() => onToggleDemo?.()} />
          Demo data
        </label>
        {demoMode && onResetDemo ? (
          <button type="button" className="small" onClick={onResetDemo}>
            Reset demo data
          </button>
        ) : null}
      </div>
    </div>
  );
}

export interface DocumentHeadProps {
  facts: DocumentFacts;
  actions?: ReactNode;
  /** Latest submission status; `draft` only when the document was never submitted. */
  submissionStatus?: SubmissionSummary['status'] | 'draft' | string | null;
  /** Latest submission summary; supplies submitted time, revision and latest comment. */
  submission?: SubmissionSummary | null;
  /** Worker delivery state for the same document; only shown once both approvals landed. */
  deliveryStatus?: DeliveryStatus | null;
}

export function DocumentHead({
  facts,
  actions,
  submissionStatus,
  submission,
  deliveryStatus,
}: DocumentHeadProps) {
  const status = submissionStatus ?? submission?.status ?? 'draft';
  const statusMeta = approvalStatusMeta(status, submission?.route);
  const deliveryCaption =
    statusMeta.key === 'approved'
      ? (deliveryStages(status, deliveryStatus, submission?.route).at(-1)?.label ?? null)
      : null;
  const draftLine =
    facts.draftRevision === null ? 'server draft local-only' : `server draft rev ${facts.draftRevision}`;
  const submittedAt = submission?.created_at
    ? new Date(submission.created_at).toLocaleString()
    : null;
  const submissionRevision = submission?.revision ?? facts.draftRevision;
  const readOnlyCopy =
    statusMeta.key === 'approved'
      ? statusMeta.description
      : statusMeta.key === 'unknown'
        ? statusMeta.description
        : 'Editing is locked until the submission is returned or approved.';
  return (
    <header className="document-head">
      <div>
        <div className="crumb tiny">
          {DOCUMENT_SECTION} / {facts.documentId}
        </div>
        <div className="document-title" data-tour="document-title">
          <h1>{facts.title}</h1>
          <StatusBadge status={status} />
        </div>
        <div className="document-approval">
          <DeliveryStepper
            variant="compact"
            submissionStatus={status}
            deliveryStatus={deliveryStatus}
            route={submission?.route}
          />
          {deliveryCaption ? (
            <span
              className="document-approval-caption tiny muted"
              data-testid="document-approval-caption"
            >
              {statusMeta.shortLabel} · {deliveryCaption}
            </span>
          ) : null}
        </div>
        <div className="meta tiny">
          {facts.versions} captured version{facts.versions === 1 ? '' : 's'} · {facts.characters}{' '}
          characters · {draftLine} · drafts and approvals are server-backed
        </div>
        {statusMeta.key !== 'draft' ? (
          <div className="document-status-line tiny" data-testid="document-status-line">
            <strong>{statusMeta.waitingFor ? `Waiting for ${statusMeta.waitingFor}` : statusMeta.label}</strong>
            {submissionRevision !== null ? <span> · revision {submissionRevision}</span> : null}
            {submittedAt ? <span> · submitted {submittedAt}</span> : null}
            {statusMeta.nextActor ? <span> · next: {statusMeta.nextActor}</span> : null}
          </div>
        ) : null}
        {statusMeta.readOnly ? (
          <p className="document-readonly tiny muted" data-testid="document-readonly">
            {readOnlyCopy}
          </p>
        ) : null}
        {submission?.latest_comment ? (
          <p className="document-latest-comment tiny" data-testid="document-latest-comment">
            Latest comment: {submission.latest_comment}
          </p>
        ) : null}
        <details className="document-details">
          <summary>Technical details</summary>
          <dl>
            <div>
              <dt>Document id</dt>
              <dd>{facts.documentId}</dd>
            </div>
            <div>
              <dt>Draft digest</dt>
              <dd>{facts.draftSha256 ? `${facts.draftSha256.slice(0, 12)}…` : 'not available'}</dd>
            </div>
            <div>
              <dt>Edit lock</dt>
              <dd>{facts.lockLabel ?? 'unknown'}</dd>
            </div>
            <div>
              <dt>Content source</dt>
              <dd>{facts.provenance ?? 'edited in this browser'}</dd>
            </div>
            <div>
              <dt>Storage</dt>
              <dd>draft on this machine's API · versions and templates in this browser</dd>
            </div>
          </dl>
        </details>
      </div>
      {actions ? <div className="document-actions">{actions}</div> : null}
    </header>
  );
}