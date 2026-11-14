/** A deliberately small fixture-only automation surface (document-host-foundation). */

import { useState } from 'react';

import {
  applyProposal,
  createFixtureProposal,
  decideProposal,
  undoApplication,
  type ApplyReceipt,
  type AutomationProposal,
} from '../api/automation';
import { getDraft, type DraftView, type LockView } from '../api/documents';
import { ApiError } from '../api/errors';

export interface AutomationFixturePanelProps {
  documentId: string;
  draft: DraftView | null;
  lock: LockView | null;
  onApplied: (view: DraftView) => void;
}

export function AutomationFixturePanel({ documentId, draft, lock, onApplied }: AutomationFixturePanelProps) {
  const [proposal, setProposal] = useState<AutomationProposal | null>(null);
  const [receipt, setReceipt] = useState<ApplyReceipt | null>(null);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setFailure(null);
    try {
      await action();
    } catch (error) {
      const message =
        error instanceof ApiError ? `${error.code}: ${error.message}` : String(error);
      setFailure(message);
    } finally {
      setBusy(false);
    }
  };

  const create = () =>
    run(async () => {
      if (!draft) throw new Error('no server draft');
      setReceipt(null);
      setDraftId(draft.draft_id);
      setProposal(
        await createFixtureProposal({ document_id: draft.document_id, draft_id: draft.draft_id }),
      );
    });

  const accept = () =>
    run(async () => {
      if (!proposal) return;
      setProposal(
        await decideProposal(proposal.proposal_id, 'accepted', {
          ifMatch: `proposal-${proposal.revision}`,
        }),
      );
    });

  const apply = () =>
    run(async () => {
      if (!proposal || !lock) return;
      const result = await applyProposal(
        proposal.proposal_id,
        {
          proposal_id: proposal.proposal_id,
          expected_snapshot_id: proposal.context.content_sha256,
          expected_draft_revision: proposal.context.revision,
          lock_id: lock.lock_id,
          fencing_token: lock.fencing_token,
          acknowledged_risk_codes: [],
        },
        { ifMatch: `draft-${proposal.context.revision}` },
      );
      setReceipt(result);
      onApplied(await getDraft(documentId, proposal.context.draft_id));
    });

  const undo = () =>
    run(async () => {
      if (!receipt || !lock) return;
      const target = draftId ?? proposal?.context.draft_id;
      if (!target) return;
      const result = await undoApplication(
        receipt.receipt_id,
        {
          expected_draft_revision: receipt.new_revision,
          lock_id: lock.lock_id,
          fencing_token: lock.fencing_token,
        },
        { ifMatch: `draft-${receipt.new_revision}` },
      );
      setReceipt(result);
      setProposal(null);
      onApplied(await getDraft(documentId, target));
    });

  return (
    <section className="automation-fixture" aria-label="Automation fixture">
      <div className="row">
        <h2>Automation fixture</h2>
        <span className="muted tiny">demo only</span>
      </div>
      <p className="muted tiny">
        Fixture-backed <code>replace_text</code> proposal; no model and no external system. Accept is
        not apply.
      </p>
      {draft ? (
        <p className="tiny">
          Server draft revision {draft.revision} · {draft.content_sha256.slice(0, 12)}
        </p>
      ) : (
        <p className="muted tiny">No server draft — the fixture panel is unavailable.</p>
      )}
      {proposal ? (
        <div className="notice tiny">
          <div>
            <strong>{proposal.disposition}</strong> · {proposal.application_status} ·{' '}
            {proposal.applicability}
          </div>
          <div>
            before: <code>{proposal.preview.before_text}</code>
          </div>
          <div>
            after: <code>{proposal.preview.after_text}</code>
          </div>
        </div>
      ) : null}
      {receipt ? (
        <p className="tiny" data-testid="automation-receipt">
          Receipt {receipt.receipt_id} · revision {receipt.new_revision}
          {receipt.reversal_of_receipt_id ? ' · reversed' : ''}
        </p>
      ) : null}
      {failure ? (
        <p className="notice notice--warn tiny" role="alert">
          {failure}
        </p>
      ) : null}
      <div className="version-actions">
        <button type="button" onClick={create} disabled={busy || !draft}>
          Create fixture proposal
        </button>
        <button
          type="button"
          onClick={accept}
          disabled={busy || !proposal || proposal.disposition !== 'open'}
        >
          Accept proposal
        </button>
        <button
          type="button"
          onClick={apply}
          disabled={
            busy ||
            !proposal ||
            !lock ||
            proposal.disposition !== 'accepted' ||
            proposal.application_status !== 'not_applied'
          }
        >
          Apply proposal
        </button>
        <button type="button" onClick={undo} disabled={busy || !receipt || !lock}>
          Undo application
        </button>
      </div>
    </section>
  );
}