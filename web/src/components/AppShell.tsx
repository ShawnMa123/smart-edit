/**
 * Shell layers above the three-pane grid (workspace-visual-parity / design D1–D3, D8).
 *
 * This build has no authentication, so the shell must not imply a signed-in user or a
 * participating organisation. It shows the product, the session boundary and only document
 * facts the client actually holds.
 */

import type { ReactNode } from 'react';

import { TOPBAR_ENTRIES, type WorkspaceModule } from '../workspace/workspaceModules';

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
  activityCount?: number;
  unreadCount?: number;
  sessionLabel?: string;
  demoIdentity?: DemoIdentityView | null;
  /** PG identity: organisation switcher and sign-out (task 6.2). */
  organizations?: Array<{ org_id: string; name: string }>;
  activeOrgId?: string | null;
  onSwitchOrg?: (orgId: string) => void;
  userLabel?: string | null;
  onLogout?: () => void;
}

export function TopBar({
  onOpenModule,
  activityCount = 0,
  unreadCount = 0,
  sessionLabel = SESSION_LABEL,
  demoIdentity = null,
  organizations = [],
  activeOrgId = null,
  onSwitchOrg,
  userLabel = null,
  onLogout,
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
        {TOPBAR_ENTRIES.map((entry) => {
          const count =
            entry.id === 'activity' ? activityCount : entry.id === 'inbox' ? unreadCount : null;
          return (
            <button
              key={entry.id}
              type="button"
              className="small"
              aria-label={entry.label}
              title={entry.label}
              onClick={() => onOpenModule?.(entry.id as WorkspaceModule)}
            >
              <span className="topbar-icon" aria-hidden="true">
                {entry.icon}
              </span>
              <span className="topbar-label">{entry.label}</span>
              {count !== null ? (
                <span
                  className="badge"
                  aria-label={`${count} ${entry.id === 'activity' ? 'activity entries' : 'unread notifications'}`}
                >
                  {count}
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
            {userLabel ? <span className="tiny">{userLabel}</span> : null}
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
  onToggleDemo?: () => void;
  onResetDemo?: () => void;
  demoStorageAvailable?: boolean;
}

/** One standing summary instead of a disclaimer per panel (design D3). */
export function EnvironmentStrip({
  demoMode = false,
  onToggleDemo,
  onResetDemo,
  demoStorageAvailable = true,
}: EnvironmentStripProps = {}) {
  return (
    <div className="environment-strip" role="status" data-demo={demoMode}>
      <span className="environment-copy">
        {demoMode
          ? 'Demo data — sample users, organisations and approvals; not real authentication or workflow.'
          : 'Synthetic demo data · fixed snapshot per audit · the assistant does not approve or submit · version history and templates stay in this browser'}
      </span>
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

export function DocumentHead({
  facts,
  actions,
}: {
  facts: DocumentFacts;
  actions?: ReactNode;
}) {
  const draftLine =
    facts.draftRevision === null ? 'server draft local-only' : `server draft rev ${facts.draftRevision}`;
  return (
    <header className="document-head">
      <div>
        <div className="crumb tiny">
          {DOCUMENT_SECTION} / {facts.documentId}
        </div>
        <div className="document-title">
          <h1>{facts.title}</h1>
          <span className="tag tag--warn">Draft</span>
        </div>
        <div className="meta tiny">
          {facts.versions} captured version{facts.versions === 1 ? '' : 's'} · {facts.characters}{' '}
          characters · {draftLine} · history stored in this browser
        </div>
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