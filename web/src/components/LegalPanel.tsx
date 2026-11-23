/**
 * Legal panel (L1 slice): statute advice + deterministic rule check.
 *
 * - Advice mode asks the statute service (`/v1/chat`) and shows the advice plus traceable citations.
 * - Rule mode runs the synthetic `DEMO-AMOUNT-REQUIRED` rule over three fact states so the three
 *   outcomes (missing -> Critical, confirmed -> pass, unconfirmed -> unable_to_assess) are visible.
 *
 * "Not checked" is shown as `unable_to_assess`/`failed`, never as "no problem": the backend
 * aggregates that invariant and this panel surfaces each coverage check status verbatim.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react';

import { DEFAULT_WORKSPACE } from '../api/assistantTypes';
import { ApiError, explainError } from '../api/errors';
import { AiWaitBox } from './AiWaitBox';
import { useElapsedMs } from './useElapsedMs';
import {
  legalClient,
  LEGAL_POLL_INTERVAL_MS,
  LEGAL_SCAN_TIMEOUT_MS,
  type CheckStatus,
  type DocumentAnchor,
  type EvidenceAnchor,
  type Finding,
  type LegalClient,
  type LegalGate,
  type LegalMethod,
  type LegalOptions,
  type ReviewRun,
  type ReviewReport,
  type SupportLevel,
} from '../api/legal';

export interface LegalPanelProps {
  documentId: string;
  workspaceId?: string;
  /** The draft revision on screen; a scan pins it so a stale answer is refused, not silently used. */
  revision?: number | null;
  contentSha?: string | null;
  /** Injected in tests; defaults to the real client. */
  client?: LegalClient;
  options?: LegalOptions;
  /** Scroll the editor to the anchor's top-level block. */
  onJumpToBlock?: (blockIndex: number) => void;
  /** Lets the workbench know whether the last scan blocks a submission. */
  onGate?: (gate: LegalGate) => void;
  /** Lets the assistant pane show a "Working" marker on this tab while a review runs. */
  onBusyChange?: (busy: boolean) => void;
}

type Mode = 'advice' | 'document';
type Tone = 'ok' | 'warn' | 'bad' | 'muted';

const OUTCOME_LABEL: Record<ReviewReport['outcome'], string> = {
  findings_present: 'Findings',
  no_findings: 'No findings',
  needs_input: 'Needs input',
  unable_to_assess: 'Unable to assess',
};

const OUTCOME_TONE: Record<ReviewReport['outcome'], Tone> = {
  findings_present: 'warn',
  no_findings: 'ok',
  needs_input: 'warn',
  unable_to_assess: 'muted',
};

const SUPPORT_LABEL: Record<SupportLevel, string> = {
  strong: 'Strong support',
  qualified: 'Qualified',
  insufficient: 'Insufficient evidence',
  not_applicable: 'Not applicable',
};

const SUPPORT_TONE: Record<SupportLevel, Tone> = {
  strong: 'ok',
  qualified: 'warn',
  insufficient: 'bad',
  not_applicable: 'muted',
};

const SEVERITY_TONE: Record<string, Tone> = {
  Critical: 'bad',
  Warning: 'warn',
  Info: 'ok',
};

const GATE_LABEL: Record<string, string> = {
  hard_block: 'Blocks',
  human_review: 'Needs human review',
  advisory: 'Advisory',
};

const CHECK_TONE: Record<CheckStatus, Tone> = {
  pass: 'ok',
  finding: 'warn',
  not_applicable: 'muted',
  needs_input: 'warn',
  unable_to_assess: 'muted',
  failed: 'bad',
};

const CHECK_STATUS_LABEL: Record<CheckStatus, string> = {
  pass: 'Pass',
  finding: 'Finding',
  not_applicable: 'Not applicable',
  needs_input: 'Needs input',
  unable_to_assess: 'Unable to assess',
  failed: 'Failed',
};

const DOCUMENT_MODE_NOTE =
  'Scans the draft on screen: required elements, date consistency, risky wording, then statute evidence per clause. Web sources are only used when you switch them on, and they never block a submission.';

const WEB_TOGGLE_NOTE =
  'Sends the uncovered clause headings to the model’s web search. Results are labelled unverified.';

const GATE_STATUS_LABEL: Record<string, string> = {
  clear: 'Clear',
  advisory: 'Advisory',
  needs_human_review: 'Needs human review',
  blocked: 'Blocked',
};

const GATE_STATUS_TONE: Record<string, Tone> = {
  clear: 'ok',
  advisory: 'warn',
  needs_human_review: 'warn',
  blocked: 'bad',
};

const GATE_REASON_COPY: Record<string, string> = {
  hard_block_finding: 'A blocking finding must be fixed first.',
  limited_coverage: 'Too little of the draft could be assessed.',
  unchecked_units: 'Some checks could not run; this result does not cover them.',
  human_review_finding: 'At least one finding needs a human decision.',
  no_document_text: 'The draft has no text to scan.',
};

const STAGE_COPY: Record<string, string> = {
  queued: 'Queued',
  splitting: 'Splitting the draft into clauses',
  deterministic: 'Running deterministic checks',
  retrieving: 'Checking statute evidence',
  done: 'Done',
  failed: 'Failed',
};

/** One-click questions for the statute corpus — keeps a live demo from stalling. */
const SUGGESTIONS = [
  '银行保函的金额条款有哪些法律要求？',
  '独立保函必须载明哪些事项才有效？',
  '独立保函在什么情形下权利义务终止？',
];

/** Friendly copy for the backend's machine `reason_codes` (a failure must never read like a pass). */
const REASON_COPY: Record<string, string> = {
  out_of_scope: 'Not a legal/regulatory question; the statute corpus was not queried.',
  missing_question: 'Enter a legal question first.',
  statute_unavailable: 'The statute retrieval service is not configured on this server.',
  timeout: 'Statute retrieval timed out; this result does not cover the law.',
  corpus_updating: 'The statute corpus is being rebuilt; this result does not cover the law.',
  unsupported: 'The statute service did not return a usable answer.',
  no_hit: 'No matching statute was found.',
  unsupported_mode: 'This review mode is not implemented in this build.',
  unconfirmed_fact: 'The amount is not confirmed yet, so this rule cannot pass.',
  missing_required_facts: 'Required facts are missing, so this rule cannot run.',
  rule_violated: 'The rule was violated.',
};

function reasonText(code: string): string {
  if (REASON_COPY[code]) return REASON_COPY[code];
  if (code.startsWith('retrieval_error')) {
    return 'Statute retrieval failed; this result does not cover the law.';
  }
  if (code.startsWith('uncovered:')) {
    return `Not covered for jurisdiction: ${code.slice('uncovered:'.length)}.`;
  }
  if (code.startsWith('zero:')) {
    return `No matching statute (${code.slice('zero:'.length)}).`;
  }
  if (code.startsWith('coverage:')) {
    return `Coverage: ${code.slice('coverage:'.length)}`;
  }
  return code;
}

/** Chinese-numeral-aware ordering for article labels like 第一条 / 第十三条. */
function cnToInt(text: string): number {
  const digits = '零一二三四五六七八九';
  let section = 0;
  let num = 0;
  for (const ch of text) {
    const digit = digits.indexOf(ch);
    if (digit >= 0) {
      num = digit;
      continue;
    }
    if (ch === '十') {
      section += (num || 1) * 10;
      num = 0;
      continue;
    }
    if (ch === '百') {
      section += (num || 1) * 100;
      num = 0;
      continue;
    }
  }
  return section + num;
}

function articleNumber(label: string | null | undefined): number {
  if (!label) return Number.POSITIVE_INFINITY;
  const match = /第(.+?)条/.exec(label);
  return match ? cnToInt(match[1]) : Number.POSITIVE_INFINITY;
}

/** A status word plus colour — never colour alone (Requirements §13). */
function Badge({ label, tone }: { label: string; tone: Tone }) {
  return <span className={`tag tag--${tone}`}>{label}</span>;
}

function Excerpt({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 140;
  if (!long) return <blockquote className="tiny legal-excerpt">{text}</blockquote>;
  return (
    <div>
      <blockquote className={`tiny legal-excerpt${open ? '' : ' legal-excerpt--clamp'}`}>
        {text}
      </blockquote>
      <button type="button" className="legal-excerpt-toggle" onClick={() => setOpen(!open)}>
        {open ? 'Collapse' : 'Show full text'}
      </button>
    </div>
  );
}

function Citations({ anchors }: { anchors: EvidenceAnchor[] }) {
  const sorted = [...anchors].sort(
    (a, b) => articleNumber(a.article_label) - articleNumber(b.article_label),
  );
  return (
    <div>
      <h5 className="tiny muted">Citations ({sorted.length})</h5>
      <div className="legal-citations">
        {sorted.map((anchor, index) => (
          <div
            className="legal-citation"
            key={`${anchor.chunk_id ?? 'anchor'}-${index}`}
            id={anchor.chunk_id ? `cite-${anchor.chunk_id}` : undefined}
          >
            <div className="row">
              {anchor.article_label ? <Badge label={anchor.article_label} tone="muted" /> : null}
              {anchor.jurisdiction ? <Badge label={anchor.jurisdiction} tone="muted" /> : null}
              {anchor.effective_from ? (
                <span className="tiny muted">{String(anchor.effective_from)} 生效</span>
              ) : null}
            </div>
            <p className="tiny">
              <strong>{anchor.title ?? 'Statute'}</strong>
            </p>
            {anchor.url ? (
              <p className="tiny">
                <a href={anchor.url} target="_blank" rel="noreferrer noopener">
                  {anchor.url}
                </a>
                {anchor.unverified ? ' · unverified' : ''}
              </p>
            ) : null}
            {anchor.excerpt ? <Excerpt text={anchor.excerpt} /> : null}
            {anchor.chunk_id ? (
              <p className="tiny muted legal-chunk">chunk {anchor.chunk_id}</p>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

// The `/v1/chat` draft is markdown-ish: `**bold**`, `1.` numbered items and `[chunk_id]` citation
// markers. Render that subset without pulling in a markdown dependency.
const INLINE_RE = /(\*\*[^*]+\*\*|\[[0-9a-f]{8,}\]|`[^`]+`)/g;

function CiteChip({ id, anchors }: { id: string; anchors: EvidenceAnchor[] }) {
  const anchor = anchors.find((candidate) => candidate.chunk_id === id);
  const label = anchor ? [anchor.article_label, anchor.title].filter(Boolean).join(' · ') : undefined;
  const jump = () => {
    const card = document.getElementById(`cite-${id}`);
    if (!card) return;
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    card.classList.add('legal-citation--flash');
    window.setTimeout(() => card.classList.remove('legal-citation--flash'), 1600);
  };
  return (
    <button type="button" className="legal-cite" title={label ?? id} onClick={jump}>
      [{id}]
    </button>
  );
}

function renderInline(text: string, key: string, anchors: EvidenceAnchor[]): ReactNode[] {
  return text.split(INLINE_RE).map((part, index) => {
    if (!part) return null;
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={`${key}-${index}`}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('[') && part.endsWith(']')) {
      return <CiteChip key={`${key}-${index}`} id={part.slice(1, -1)} anchors={anchors} />;
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={`${key}-${index}`}>{part.slice(1, -1)}</code>;
    }
    return <span key={`${key}-${index}`}>{part}</span>;
  });
}

function AdviceText({ text, anchors }: { text: string; anchors: EvidenceAnchor[] }) {
  const lines = text.split('\n');
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let listKey = 0;

  const flushList = () => {
    if (!list.length) return;
    blocks.push(
      <ol key={`list-${listKey}`} className="legal-list">
        {list.map((item, index) => (
          <li key={index}>{renderInline(item, `li-${listKey}-${index}`, anchors)}</li>
        ))}
      </ol>,
    );
    list = [];
    listKey += 1;
  };

  lines.forEach((line, index) => {
    const item = /^\s*(\d+)[.、)]\s*(.*)$/.exec(line);
    if (item) {
      list.push(item[2]);
      return;
    }
    flushList();
    if (line.trim() === '') return;
    blocks.push(
      <p key={`p-${index}`}>{renderInline(line, `p-${index}`, anchors)}</p>,
    );
  });
  flushList();

  return <div className="legal-advice">{blocks}</div>;
}

function DocumentAnchors({
  anchors,
  onJump,
}: {
  anchors: DocumentAnchor[];
  onJump?: (blockIndex: number) => void;
}) {
  return (
    <div className="legal-document-anchors">
      <h5 className="tiny muted">In the draft ({anchors.length})</h5>
      {anchors.map((anchor, index) => (
        <div className="legal-document-anchor" key={`${anchor.clause_id}-${anchor.block_index}-${index}`}>
          <blockquote className="tiny legal-excerpt">{anchor.quote}</blockquote>
          <div className="row">
            <Badge label={anchor.clause_id} tone="muted" />
            {onJump ? (
              <button
                type="button"
                className="legal-jump"
                data-tour="legal-jump"
                onClick={() => onJump(anchor.block_index)}
              >
                Jump to clause
              </button>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function FindingView({
  finding,
  onJump,
}: {
  finding: Finding;
  onJump?: (blockIndex: number) => void;
}) {
  const limitations = finding.applicability?.limitations;
  const basis = finding.basis ?? (finding.method === 'legal' ? 'statute' : 'rule');
  const documentAnchors = finding.document_anchors ?? [];
  return (
    <div className="legal-finding" aria-label="Finding">
      <div className="row">
        <Badge label={finding.severity} tone={SEVERITY_TONE[finding.severity] ?? 'muted'} />
        <Badge label={GATE_LABEL[finding.gate_type] ?? finding.gate_type} tone="muted" />
        {basis === 'statute' ? (
          <Badge
            label={SUPPORT_LABEL[finding.support_level]}
            tone={SUPPORT_TONE[finding.support_level]}
          />
        ) : null}
        {basis === 'web' ? <Badge label="Unverified web source" tone="muted" /> : null}
      </div>
      <h4>{finding.title}</h4>
      <AdviceText text={finding.explanation} anchors={finding.anchors} />
      {finding.suggestion ? (
        <p className="tiny legal-suggestion">Suggested edit: {finding.suggestion}</p>
      ) : null}
      {documentAnchors.length ? <DocumentAnchors anchors={documentAnchors} onJump={onJump} /> : null}
      {finding.rule_refs.length ? (
        <p className="tiny muted">
          Rule: {finding.rule_refs.map((ref) => `${ref.rule_id} v${ref.version}`).join(', ')}
        </p>
      ) : null}
      {finding.anchors.length ? <Citations anchors={finding.anchors} /> : null}
      {Array.isArray(limitations) && limitations.length ? (
        <p className="tiny muted">
          Limitations: {(limitations as unknown[]).map(String).join(' · ')}
        </p>
      ) : null}
    </div>
  );
}

const SEVERITY_ORDER: readonly string[] = ['Critical', 'Warning', 'Info'];

function ReportView({
  report,
  onJump,
}: {
  report: ReviewReport;
  onJump?: (blockIndex: number) => void;
}) {
  const summary = report.coverage_summary;
  const gate = report.gate;
  const ordered = [...report.findings].sort(
    (left, right) =>
      SEVERITY_ORDER.indexOf(left.severity) - SEVERITY_ORDER.indexOf(right.severity),
  );
  return (
    <div className="legal-report" aria-label="Legal review" data-tour="legal-report">
      <div className="row">
        <Badge label={OUTCOME_LABEL[report.outcome]} tone={OUTCOME_TONE[report.outcome]} />
        <span className="tiny muted">
          {report.completion === 'complete' ? 'Complete' : 'Partial'}
        </span>
        {gate ? (
          <Badge
            label={`Gate: ${GATE_STATUS_LABEL[gate.status] ?? gate.status}`}
            tone={GATE_STATUS_TONE[gate.status] ?? 'muted'}
          />
        ) : null}
      </div>

      {summary ? (
        <p className="tiny muted" data-testid="legal-coverage-summary">
          Planned {summary.planned} · assessed {summary.assessed} (
          {Math.round((summary.assessed_ratio ?? 0) * 100)}%)
          {summary.clauses ? ` · ${summary.clauses} clauses` : ''}
          {summary.truncated ? ' · truncated' : ''}
        </p>
      ) : null}
      {gate && gate.reasons.length ? (
        <ul className="legal-gate-reasons tiny muted">
          {gate.reasons.map((reason) => (
            <li key={reason}>{GATE_REASON_COPY[reason] ?? reason}</li>
          ))}
        </ul>
      ) : null}

      {report.coverage.map((check) =>
        check.status === 'finding' ? null : (
          <div key={check.check_id} className="row">
            <Badge label={CHECK_STATUS_LABEL[check.status]} tone={CHECK_TONE[check.status]} />
            <span className="tiny muted">
              {check.method}
              {check.clause_id ? ` · ${check.clause_id}` : ''}
              {check.evidence_count ? ` · ${check.evidence_count} evidence` : ''}
              {check.reason_codes.length
                ? ` · ${check.reason_codes.map(reasonText).join(' · ')}`
                : ''}
            </span>
          </div>
        ),
      )}

      <div data-tour="legal-findings">
        {ordered.map((finding) => (
          <FindingView key={finding.finding_id} finding={finding} onJump={onJump} />
        ))}
      </div>

      {report.limitations.length ? (
        <ul className="legal-limitations tiny muted">
          {report.limitations.map((item, index) => (
            <li key={index}>
              {String((item as { message?: string }).message ?? JSON.stringify(item))}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function LegalPanel({
  documentId,
  workspaceId = DEFAULT_WORKSPACE,
  revision = null,
  contentSha = null,
  client = legalClient,
  options = {},
  onJumpToBlock,
  onGate,
  onBusyChange,
}: LegalPanelProps) {
  const [mode, setMode] = useState<Mode>('advice');
  const [question, setQuestion] = useState('');
  const [webSearch, setWebSearch] = useState(false);
  const [busy, setBusy] = useState(false);
  const waitElapsed = useElapsedMs(busy);
  const [run, setRun] = useState<ReviewRun | null>(null);
  const [report, setReport] = useState<ReviewReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const questionRef = useRef<HTMLTextAreaElement>(null);
  const busyNotify = useRef(onBusyChange);
  busyNotify.current = onBusyChange;
  useEffect(() => {
    busyNotify.current?.(busy);
  }, [busy]);
  useEffect(
    () => () => {
      busyNotify.current?.(false);
    },
    [],
  );

  const askAdvice = async () => {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const accepted = await client.submitReview(
        {
          workspace_id: workspaceId,
          document_id: documentId,
          snapshot_id: 'demo-snapshot',
          facts_version_id: 'demo-facts',
          modes: ['legal'] as LegalMethod[],
          question: trimmed,
        },
        options,
      );
      if (!accepted.report_id) {
        throw new Error('The review was accepted but produced no report id.');
      }
      setReport(await client.getReport(accepted.report_id, options));
    } catch (failure) {
      setError(failure instanceof ApiError ? explainError(failure.code) : String(failure));
    } finally {
      setBusy(false);
    }
  };

  /** Scan the draft on screen: queue a run, poll it, then read the report. */
  const scanDocument = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setReport(null);
    setRun(null);
    try {
      const getRun = client.getRun;
      let current = await client.submitReview(
        {
          workspace_id: workspaceId,
          document_id: documentId,
          scope: 'document',
          modes: ['deterministic', 'legal'],
          expected_revision: revision ?? undefined,
          expected_content_sha256: contentSha ?? undefined,
          web_search: webSearch,
        },
        options,
      );
      setRun(current);
      const deadline = Date.now() + LEGAL_SCAN_TIMEOUT_MS;
      while (
        getRun &&
        (current.status === 'queued' || current.status === 'running')
      ) {
        if (Date.now() > deadline) {
          throw new ApiError(0, 'SCAN_TIMEOUT', 'the scan did not finish in time');
        }
        await new Promise((resolve) => setTimeout(resolve, LEGAL_POLL_INTERVAL_MS));
        current = await getRun(current.run_id, options);
        setRun(current);
      }
      if (current.status !== 'succeeded' || !current.report_id) {
        throw new ApiError(
          0,
          current.error ?? 'SCAN_FAILED',
          `the scan ended as ${current.status}`,
        );
      }
      const next = await client.getReport(current.report_id, options);
      setReport(next);
      if (next.gate) onGate?.(next.gate);
    } catch (failure) {
      setError(failure instanceof ApiError ? explainError(failure.code) : String(failure));
    } finally {
      setBusy(false);
    }
  };

  const switchMode = (next: Mode) => {
    setMode(next);
    setReport(null);
    setRun(null);
    setError(null);
    setQuestion('');
  };

  const stage = run?.progress?.stage ?? run?.stage;
  const stale =
    report?.snapshot?.revision != null &&
    revision != null &&
    report.snapshot.revision !== revision;

  return (
    <div className="legal-panel">
      <div className="legal-modes" role="tablist" aria-label="Legal review mode">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'advice'}
          onClick={() => switchMode('advice')}
        >
          Statute advice
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'document'}
          data-tour="legal-document-tab"
          onClick={() => switchMode('document')}
        >
          Document check
        </button>
      </div>

      {mode === 'advice' ? (
        <div className="legal-section">
          <p className="notice notice--warn tiny" role="status">
            Advisory only — backed by the statute corpus.
          </p>
          <div className="legal-suggestions" role="group" aria-label="Suggested questions">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                disabled={busy}
                onClick={() => {
                  setQuestion(suggestion);
                  questionRef.current?.focus();
                }}
              >
                {suggestion}
              </button>
            ))}
          </div>
          <label className="tiny muted" htmlFor="legal-question">
            Legal question
          </label>
          <textarea
            id="legal-question"
            aria-label="Legal question"
            ref={questionRef}
            value={question}
            disabled={busy}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask a statute question, e.g. “Is the amount required before approval?”"
          />
          <div className="row">
            <button type="button" onClick={() => void askAdvice()} disabled={busy || !question.trim()}>
              Ask
            </button>
          </div>
        </div>
      ) : (
        <div className="legal-section legal-scan">
          <p className="notice tiny" role="status">
            {DOCUMENT_MODE_NOTE}
          </p>
          <p className="tiny muted" data-testid="legal-scan-target">
            Draft {revision != null ? `rev ${revision}` : 'current revision'}
            {contentSha ? ` · ${contentSha.slice(0, 12)}…` : ''}
          </p>
          <label className="legal-web-toggle tiny">
            <input
              type="checkbox"
              checked={webSearch}
              disabled={busy}
              onChange={(event) => setWebSearch(event.target.checked)}
            />
            Use web search for clauses the corpus does not cover
          </label>
          <p className="tiny muted">{WEB_TOGGLE_NOTE}</p>
          <div className="row">
            <button type="button" onClick={() => void scanDocument()} disabled={busy} data-tour="legal-scan">
              {report ? 'Scan again' : 'Scan document'}
            </button>
          </div>
          {stale ? (
            <p className="notice notice--warn tiny" role="status">
              The draft changed since this scan (scanned rev {report?.snapshot?.revision}). Scan
              again to cover the current text.
            </p>
          ) : null}
        </div>
      )}

      {busy ? (
        <AiWaitBox
          title={mode === 'advice' ? 'Asking the statute service' : 'Scanning the draft'}
          message={
            mode === 'advice'
              ? 'Searching the statute corpus — usually 2–5 seconds…'
              : `${STAGE_COPY[String(stage ?? 'queued')] ?? stage ?? 'Scanning'}${
                  run?.progress?.current ? ` (${run.progress.current})` : ''
                }…`
          }
          hint={
            mode === 'advice'
              ? 'The answer will cite the statute chunks it used, or say it could not assess them.'
              : 'Deterministic checks run first; statute evidence follows per clause.'
          }
          elapsedMs={waitElapsed}
        />
      ) : null}

      {error ? (
        <p className="notice notice--bad tiny" role="alert">
          {error}
        </p>
      ) : null}

      {report ? <ReportView report={report} onJump={onJumpToBlock} /> : null}
    </div>
  );
}
