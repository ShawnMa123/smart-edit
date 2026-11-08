import { explainError } from '../api/errors';
import type { AuditState } from '../auditMachine';
import {
  LABEL_NOT_RUN,
  NOTE_NO_FINDINGS,
  SCOPE_NOT_RUN,
  SCOPE_RAN,
  buildAuditView,
} from '../auditView';
import { RESULT_TONE, severityToken, stageStatusToken } from '../tokens';
import { StatusChip } from './StatusChip';

export interface AuditPanelProps {
  state: AuditState;
  currentDigest: string;
  onRun: () => void;
  onStopWaiting: () => void;
  /** Injected clock so the elapsed timer is testable. */
  now?: number;
}

const seconds = (ms: number): string => `${(ms / 1000).toFixed(1)}s`;

function ScopeBlock() {
  return (
    <div className="notice tiny">
      <h3>What this audit checks</h3>
      <ul>
        {SCOPE_RAN.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ul>
      <h3>Not checked in this build</h3>
      <ul>
        {SCOPE_NOT_RUN.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ul>
    </div>
  );
}

function OutcomeChip({ checksRan, stale }: { checksRan: boolean; stale: boolean }) {
  if (stale) return <StatusChip token={RESULT_TONE.stale} />;
  return <StatusChip token={checksRan ? RESULT_TONE.ran : RESULT_TONE['did-not-run']} />;
}

/**
 * The audit tab (tasks 7.1-7.6). Every claim comes from `auditView`, never from a JSX condition: an
 * incomplete run shows `blockedReason` and **no** field list.
 */
export function AuditPanel({ state, currentDigest, onRun, onStopWaiting, now }: AuditPanelProps) {
  if (state.phase === 'idle') {
    return (
      <div>
        <h3>Run a spec audit</h3>
        <p className="muted tiny">
          The audit sends a frozen snapshot of the current text to the normalization stage and reports
          what those checks found.
        </p>
        <button type="button" className="primary" onClick={onRun}>
          Run spec audit
        </button>
        <ScopeBlock />
      </div>
    );
  }

  if (state.phase === 'running') {
    const elapsed = Math.max(0, (now ?? Date.now()) - state.startedAt);
    return (
      <div>
        <div className="notice" role="status">
          <h3>Fixed snapshot captured — running checks</h3>
          <p className="tiny muted">
            Auditing snapshot <code>{state.snapshot.digest.slice(0, 12)}</code> · {seconds(elapsed)}{' '}
            elapsed
          </p>
        </div>
        <button type="button" onClick={onStopWaiting}>
          Stop waiting
        </button>
        <p className="muted tiny">
          This only stops waiting here; the run may still be finishing on the server, and no
          conclusion is shown.
        </p>
      </div>
    );
  }

  if (state.phase === 'failed') {
    return (
      <div>
        <div className="notice notice--bad" role="alert">
          <h3>Audit failed — no conclusion produced</h3>
          <p>{explainError(state.failure.code)}</p>
          <p className="tiny muted">
            Code <code>{state.failure.code}</code> · {seconds(state.elapsedMs)} · server message:{' '}
            {state.failure.message}
          </p>
        </div>
        <button type="button" className="primary" onClick={onRun}>
          Run spec audit again
        </button>
      </div>
    );
  }

  const view = buildAuditView(state.envelope, state.snapshot, currentDigest);

  return (
    <div>
      {view.stale ? (
        <div className="notice notice--warn" role="alert">
          <h3>Report is stale</h3>
          <p className="tiny">
            This report is bound to snapshot <code>{view.digest.slice(0, 12)}</code> and the document
            has changed since. It cannot be used for approval — re-audit the current snapshot.
          </p>
        </div>
      ) : null}

      {view.usedFixture ? (
        <div className="notice" role="status">
          <h3>Fixture-backed run</h3>
          <p className="tiny">
            Candidates came from{' '}
            <code>{view.stages.find((row) => row.stage === 'extract')?.reason}</code>, not from a model
            provider — shown so the flow can be inspected, not as an extraction of this document.
          </p>
        </div>
      ) : null}

      <div className="row">
        <OutcomeChip checksRan={view.fieldChecks === 'ran'} stale={view.stale} />
        <span className="tiny muted">{view.resultLabel}</span>
      </div>

      <button type="button" onClick={onRun}>
        Re-audit current snapshot
      </button>

      <h3 className="tiny muted">Stages</h3>
      <ul className="tiny">
        {view.stages.map((row) => (
          <li key={row.stage}>
            <StatusChip token={stageStatusToken(row.status)} /> <strong>{row.stage}</strong>{' '}
            {row.reason ? <span className="muted">— {row.reason}</span> : null}
          </li>
        ))}
      </ul>

      {view.fieldChecks === 'did-not-run' ? (
        <div className="notice notice--bad" role="alert">
          <h3>{LABEL_NOT_RUN}</h3>
          <p className="tiny">
            {view.blockedReason}. No field was checked, so no missing-field list is shown — the empty
            fields are placeholders, not findings about this document.
          </p>
        </div>
      ) : (
        <div>
          <div className="metrics">
            <div className="metric">
              <b>{view.statusCounts.extracted}</b>
              <span>Extracted</span>
            </div>
            <div className="metric">
              <b>{view.statusCounts.inferred}</b>
              <span>Inferred</span>
            </div>
            <div className="metric">
              <b>{view.statusCounts.missing}</b>
              <span>Not found</span>
            </div>
            <div className="metric">
              <b>{view.severityCounts.critical}</b>
              <span>Critical findings</span>
            </div>
            <div className="metric">
              <b>{view.severityCounts.warn}</b>
              <span>Warnings</span>
            </div>
          </div>

          <table className="checks">
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Value</th>
                <th scope="col">Status</th>
                <th scope="col">Notes · source</th>
              </tr>
            </thead>
            <tbody>
              {view.checks.map((check) => (
                <tr key={check.key}>
                  <td>{check.label ?? check.key}</td>
                  <td>
                    {check.value ?? '—'}
                    {check.normalizedFrom && check.normalizedFrom !== check.value ? (
                      <div className="tiny muted">from {check.normalizedFrom}</div>
                    ) : null}
                  </td>
                  <td>
                    <span className={check.statusClass}>{check.statusLabel}</span>
                  </td>
                  <td className="tiny">
                    {check.notes.length > 0 ? check.notes.join(', ') : '—'}
                    {check.source ? (
                      <div className="muted">
                        {check.source.fileId}
                        {check.source.page !== null ? ` · page ${check.source.page}` : ''} ·{' '}
                        {check.source.span}
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {view.findings.length > 0 ? (
            <div>
              <h3 className="tiny muted">Findings</h3>
              {view.findings.map((finding) => (
                <div className="finding" key={finding.id}>
                  <div className="row">
                    <StatusChip token={severityToken(finding.severity)} />
                    <span className="tiny muted">
                      {finding.id} · {finding.source} · blocking: {finding.blocking ? 'yes' : 'no'}
                    </span>
                  </div>
                  <div>{finding.message}</div>
                  {finding.evidence ? (
                    <div className="tiny muted">evidence: {finding.evidence}</div>
                  ) : null}
                  <div className="tiny muted">fields: {finding.fieldKeys.join(', ') || '—'}</div>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      )}

      <ScopeBlock />

      <p className="muted tiny">
        {NOTE_NO_FINDINGS} Jurisdictional applicability was not assessed. Report bound to snapshot{' '}
        <code>{view.digest.slice(0, 12)}</code> captured {new Date(view.capturedAt).toLocaleString()} —
        computed in this browser, not a server-side digest.
      </p>
    </div>
  );
}