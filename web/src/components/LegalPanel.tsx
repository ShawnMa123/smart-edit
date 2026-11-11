import type { LegalOpinion, RunEnvelope } from '../api/types';

export type LegalState =
  | { phase: 'idle' }
  | { phase: 'running' }
  | { phase: 'report'; envelope: RunEnvelope }
  | { phase: 'failed'; failure: { code: string; message: string } };

export interface LegalPanelProps {
  state: LegalState;
  /** True only when a run exists; without one there is nothing to trigger. */
  canRun: boolean;
  onRun: () => void;
  /** Why the button is disabled (e.g. "run the audit first"). */
  hint?: string;
}

const NOT_A_VERDICT =
  'Not a legal opinion. This does not replace formal sanctions or export-control screening.';
const LIMITS =
  'This build quotes retrieved provisions; it does not perform legal reasoning or semantic entailment.';

function CoverageBlock({ legal }: { legal: LegalOpinion }) {
  const coverage = legal.coverage;
  return (
    <div className="notice tiny" data-testid="legal-coverage">
      <h3>Coverage</h3>
      <p>
        mode <code>{legal.input_mode}</code>
        {' · '}jurisdictions {coverage.jurisdictions.join(', ') || '—'}
        {' · '}standards {coverage.standards.join(', ') || '—'}
      </p>
      <p>
        corpus {coverage.corpus?.version ?? '—'} · documents {coverage.corpus?.documents ?? '—'}
        {coverage.unavailable ? ' · coverage unavailable' : ''}
        {coverage.business_type_uncertain ? ' · business type uncertain' : ''}
        {legal.input_mode === 'raw' && coverage.inferred_business_type
          ? ` · inferred ${coverage.inferred_business_type}`
          : ''}
      </p>
      {coverage.notes.length > 0 ? (
        <ul>
          {coverage.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function RulesBlock({ legal }: { legal: LegalOpinion }) {
  if (legal.applicable_rules.length === 0) return null;
  return (
    <div>
      <h3 className="tiny muted">Applicable rules</h3>
      <table className="legal-table">
        <thead>
          <tr>
            <th>Rule</th>
            <th>Version</th>
            <th>Effective from</th>
            <th>chunk_id</th>
          </tr>
        </thead>
        <tbody>
          {legal.applicable_rules.map((rule) => (
            <tr key={`${rule.rule_id}:${rule.chunk_id}`}>
              <td>
                <div>{rule.title}</div>
                <div className="tiny muted">{rule.rule_id}</div>
              </td>
              <td>{rule.version}</td>
              <td>{rule.effective_from ?? '—'}</td>
              <td className="tiny">
                <code>{rule.chunk_id}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ClaimsBlock({ legal }: { legal: LegalOpinion }) {
  if (legal.claims.length === 0) return null;
  return (
    <div>
      <h3 className="tiny muted">Claims (quoted from the cited source)</h3>
      {legal.claims.map((claim, index) => (
        <div
          className={claim.support === 'insufficient' ? 'finding finding--warn' : 'finding'}
          key={`${claim.chunk_id ?? 'none'}:${index}`}
          data-support={claim.support}
        >
          <div className="row">
            <span className="tiny muted">
              {claim.kind} · {claim.support} · citation {claim.chunk_id ?? 'none'}
            </span>
          </div>
          <div>{claim.text}</div>
        </div>
      ))}
    </div>
  );
}

function RegulatoryFindings({ envelope }: { envelope: RunEnvelope }) {
  const findings = envelope.findings.filter((finding) => finding.source === 'regulatory');
  if (findings.length === 0) return null;
  return (
    <div>
      <h3 className="tiny muted">Regulatory findings (human review)</h3>
      {findings.map((finding) => (
        <div className="finding" key={finding.id}>
          <div className="row">
            <span className={`chip chip--${finding.severity}`}>{finding.severity}</span>
            <span className="tiny muted">
              {finding.id} · {finding.rule_id} · blocking: {String(finding.blocking)}
            </span>
          </div>
          <div>{finding.message}</div>
          {finding.evidence ? <div className="tiny muted">evidence: {finding.evidence}</div> : null}
        </div>
      ))}
    </div>
  );
}

/**
 * Agent 3 output. Two claims this panel refuses to make: an absent/empty retrieval is *not* a clean
 * result, and a claim marked `insufficient` is not deleted — both stay visible with their word.
 */
export function LegalPanel({ state, canRun, onRun, hint }: LegalPanelProps) {
  return (
    <div data-testid="legal-panel">
      <div className="row">
        <button type="button" onClick={onRun} disabled={!canRun || state.phase === 'running'}>
          {state.phase === 'running' ? 'Running legal check…' : 'Run legal check'}
        </button>
        {!canRun && hint ? <span className="tiny muted">{hint}</span> : null}
      </div>

      <p className="tiny muted">{NOT_A_VERDICT}</p>
      <p className="tiny muted">{LIMITS}</p>

      {state.phase === 'idle' ? (
        <div className="notice" role="status">
          <h3>No legal check has run on this run</h3>
          <p className="tiny">
            Nothing here means "compliant"; trigger the check to retrieve citable provisions.
          </p>
        </div>
      ) : null}

      {state.phase === 'running' ? (
        <div className="notice" role="status">
          <h3>Retrieving provisions…</h3>
        </div>
      ) : null}

      {state.phase === 'failed' ? (
        <div className="notice notice--bad" role="alert">
          <h3>Legal check failed</h3>
          <p className="tiny">
            {state.failure.code}: {state.failure.message}
          </p>
          <p className="tiny">Failure is reported, never treated as a clean pass.</p>
        </div>
      ) : null}

      {state.phase === 'report' ? <LegalReport envelope={state.envelope} /> : null}
    </div>
  );
}

function LegalReport({ envelope }: { envelope: RunEnvelope }) {
  const legal = envelope.legal;
  if (!legal) {
    return (
      <div className="notice" role="status">
        <h3>No legal opinion in this run</h3>
        <p className="tiny">The response has no `legal` object; that is not a clean result.</p>
      </div>
    );
  }
  return (
    <div>
      <div className="row">
        <span className={`chip ${legal.escalate_to_human ? 'chip--warn' : ''}`}>
          {legal.escalate_to_human ? 'escalate to human' : 'no escalation triggered'}
        </span>
      </div>
      <p>{legal.summary}</p>
      <CoverageBlock legal={legal} />
      <RulesBlock legal={legal} />
      <ClaimsBlock legal={legal} />
      <RegulatoryFindings envelope={envelope} />
      {(envelope.retrieved ?? []).length > 0 ? (
        <div>
          <h3 className="tiny muted">Retrieved chunks</h3>
          <ul className="tiny">
            {(envelope.retrieved ?? []).map((chunk) => (
              <li key={chunk.chunk_id}>
                <code>{chunk.chunk_id}</code> · {chunk.source_doc ?? chunk.title} · score{' '}
                {chunk.score.toFixed(3)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
