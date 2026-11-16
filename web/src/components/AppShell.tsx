/**
 * Shell layers above the three-pane grid (workspace-visual-parity / design D1–D3, D8).
 *
 * This build has no authentication, so the shell must not imply a signed-in user or a
 * participating organisation. It shows the product, the session boundary and only document
 * facts the client actually holds.
 */

import type { ReactNode } from 'react';

/** Configurable product label; a deployment may replace it without touching the layout. */
export const PRODUCT_NAME = 'Trade workspace';
export const SESSION_LABEL = 'Local demo session';
export const DOCUMENT_SECTION = 'Trade documents / Guarantees';

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

export function TopBar() {
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
        <span className="tag tag--muted session-chip">{SESSION_LABEL}</span>
      </div>
    </header>
  );
}

/** One standing summary instead of a disclaimer per panel (design D3). */
export function EnvironmentStrip() {
  return (
    <div className="environment-strip" role="status">
      Synthetic demo data
      {' · '}fixed snapshot per audit
      {' · '}the assistant does not approve or submit
      {' · '}version history and templates stay in this browser
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