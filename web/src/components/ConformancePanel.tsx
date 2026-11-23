/**
 * Template audit: the primary Audit experience.
 *
 * It reads the saved server draft (pinned by revision + sha), asks the approved Doubao model to
 * judge the calibration config, and renders what is missing / not conforming with a quote that can
 * be jumped to. The deterministic rule audit stays available below as evidence, not as the headline.
 *
 * Honesty rules mirrored from the backend:
 * - a `finding` always has a locatable quote; `unable_to_assess` is shown as its own outcome;
 * - the model summary is labelled as model-written;
 * - the redaction steps (kind, count, masked sample) are shown, never the original value.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  conformanceClient,
  type ConformanceClient,
  type ConformanceConfigDetail,
  type ConformanceConfigSummary,
  type ConformanceReport,
  type ConformanceRun,
  type RequirementResult,
} from '../api/conformance';
import { ApiError } from '../api/errors';
import { reportFileName, reportToMarkdown } from '../conformanceReport';
import { AiWaitBox } from './AiWaitBox';
import { useElapsedMs } from './useElapsedMs';

export interface ConformancePanelProps {
  documentId: string;
  workspaceId?: string;
  /** Server draft identity; the review pins it so a stale answer is refused, not silently used. */
  draftId?: string | null;
  revision?: number | null;
  contentSha?: string | null;
  /** Unsaved editor changes: the audit reads the saved revision, so say so and offer Save. */
  dirty?: boolean;
  saveState?: string;
  onSave?: () => void;
  onJumpToBlock?: (blockIndex: number) => void;
  documentTitle?: string | null;
  /** Client-side demo has no server draft to audit. */
  demoMode?: boolean;
  client?: ConformanceClient;
  pollIntervalMs?: number;
  pollTimeoutMs?: number;
  onBusyChange?: (busy: boolean) => void;
}

type Phase = 'idle' | 'running' | 'done' | 'failed';

const OUTCOME_LABEL: Record<ConformanceReport['outcome'], string> = {
  findings_present: 'Findings',
  no_findings: 'No findings',
  needs_input: 'Needs input',
  unable_to_assess: 'Unable to assess',
};

const OUTCOME_CLASS: Record<ConformanceReport['outcome'], string> = {
  findings_present: 'status status--warn',
  no_findings: 'status status--ok',
  needs_input: 'status status--warn',
  unable_to_assess: 'status status--unknown',
};

const LEVEL_ORDER: Record<RequirementResult['level'], number> = { must: 0, should: 1, info: 2 };
const LEVEL_LABEL: Record<RequirementResult['level'], string> = {
  must: 'Must',
  should: 'Should',
  info: 'Info',
};

const REDACTION_PLAN = [
  'account / card numbers',
  'IBAN and BIC',
  'e-mail addresses',
  'phone numbers',
  'national ID numbers',
];

const STAGE_LABEL: Record<string, string> = {
  queued: 'Queued',
  snapshot: 'Reading the saved draft',
  deterministic: 'Checking required fields (no model)',
  model: 'Asking Doubao to judge the checklist',
  aggregate: 'Assembling the report',
  done: 'Done',
};

const describe = (error: unknown): string => {
  if (error instanceof ApiError) return `${error.code} — ${error.message}`;
  return error instanceof Error ? error.message : String(error);
};

const shortSha = (value: string | null | undefined): string => (value ? value.slice(0, 8) : '—');

interface PreviousAudit {
  at: string;
  outcome: string;
  findings: number;
  missing: number;
  coverage: number;
  revision: number | null;
}

const lastAuditKey = (documentId: string, configId: string): string =>
  `smart-edit:conformance:last:${documentId}:${configId}`;

const readPreviousAudit = (key: string): PreviousAudit | null => {
  try {
    const raw = globalThis.localStorage?.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PreviousAudit>;
    if (typeof parsed.at !== 'string' || typeof parsed.findings !== 'number') return null;
    return {
      at: parsed.at,
      outcome: String(parsed.outcome ?? ''),
      findings: parsed.findings,
      missing: Number(parsed.missing ?? 0),
      coverage: Number(parsed.coverage ?? 0),
      revision: typeof parsed.revision === 'number' ? parsed.revision : null,
    };
  } catch {
    return null;
  }
};

const writePreviousAudit = (key: string, value: PreviousAudit): void => {
  try {
    globalThis.localStorage?.setItem(key, JSON.stringify(value));
  } catch {
    // A browser without storage must not break the audit itself.
  }
};

const signed = (value: number): string => (value > 0 ? `+${value}` : String(value));

export function ConformancePanel({
  documentId,
  workspaceId,
  draftId = null,
  revision = null,
  contentSha = null,
  dirty = false,
  saveState,
  onSave,
  onJumpToBlock,
  documentTitle = null,
  demoMode = false,
  client,
  pollIntervalMs = 700,
  pollTimeoutMs = 150_000,
  onBusyChange,
}: ConformancePanelProps) {
  const api = useMemo(() => client ?? conformanceClient, [client]);
  const [configs, setConfigs] = useState<ConformanceConfigSummary[] | null>(null);
  const [configId, setConfigId] = useState('');
  const [phase, setPhase] = useState<Phase>('idle');
  const runningElapsed = useElapsedMs(phase === 'running');
  const [run, setRun] = useState<ConformanceRun | null>(null);
  const [report, setReport] = useState<ConformanceReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [detail, setDetail] = useState<ConformanceConfigDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [previous, setPrevious] = useState<PreviousAudit | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const timer = useRef<number | null>(null);
  const alive = useRef(true);

  const stopTimer = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, []);

  useEffect(() => {
    onBusyChange?.(phase === 'running');
  }, [phase, onBusyChange]);

  useEffect(() => {
    if (demoMode) return;
    let cancelled = false;
    void api
      .listConfigs()
      .then((items) => {
        if (cancelled || !alive.current) return;
        setConfigs(items);
        setConfigId((current) => current || items[0]?.config_id || '');
      })
      .catch((failure) => {
        if (cancelled || !alive.current) return;
        setConfigs([]);
        setLoadError(describe(failure));
      });
    return () => {
      cancelled = true;
    };
  }, [api, demoMode]);

  useEffect(() => {
    if (demoMode || !configId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailError(null);
    setPrevious(null);
    void api
      .getConfig(configId)
      .then((loaded) => {
        if (!cancelled && alive.current) setDetail(loaded);
      })
      .catch((failure) => {
        if (!cancelled && alive.current) {
          setDetail(null);
          setDetailError(describe(failure));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [api, configId, demoMode]);

  const finish = useCallback(
    async (reportId: string) => {
      try {
        const loaded = await api.getReport(reportId);
        if (!alive.current) return;
        const key = lastAuditKey(documentId, loaded.config.config_id);
        setPrevious(readPreviousAudit(key));
        writePreviousAudit(key, {
          at: new Date().toISOString(),
          outcome: loaded.outcome,
          findings: loaded.counts.findings,
          missing: loaded.counts.missing_fields,
          coverage: loaded.counts.coverage_ratio,
          revision: loaded.snapshot.revision,
        });
        setReport(loaded);
        setCopyState('idle');
        setPhase('done');
      } catch (failure) {
        if (!alive.current) return;
        setPhase('failed');
        setError(describe(failure));
      }
    },
    [api, documentId],
  );

  const poll = useCallback(
    (runId: string, startedAt: number) => {
      const tick = async () => {
        try {
          const next = await api.getRun(runId);
          if (!alive.current) return;
          setRun(next);
          if (next.status === 'succeeded' && next.report_id) {
            await finish(next.report_id);
            return;
          }
          if (next.status === 'failed') {
            setPhase('failed');
            setError(next.error ?? 'review_failed');
            return;
          }
          if (Date.now() - startedAt > pollTimeoutMs) {
            setPhase('failed');
            setError('TIMEOUT — the review did not finish in time; it may still be running.');
            return;
          }
          timer.current = window.setTimeout(() => void tick(), pollIntervalMs);
        } catch (failure) {
          if (!alive.current) return;
          setPhase('failed');
          setError(describe(failure));
        }
      };
      void tick();
    },
    [api, finish, pollIntervalMs, pollTimeoutMs],
  );

  const startReview = async () => {
    if (!configId || demoMode) return;
    stopTimer();
    setPhase('running');
    setError(null);
    setReport(null);
    setRun(null);
    try {
      const created = await api.submitReview({
        workspace_id: workspaceId || 'ws_demo_01',
        document_id: documentId,
        config_id: configId,
        draft_id: draftId,
        expected_revision: revision,
        expected_content_sha256: contentSha,
      });
      if (!alive.current) return;
      setRun(created);
      if (created.status === 'succeeded' && created.report_id) {
        await finish(created.report_id);
        return;
      }
      if (created.status === 'failed') {
        setPhase('failed');
        setError(created.error ?? 'review_failed');
        return;
      }
      poll(created.run_id, Date.now());
    } catch (failure) {
      if (!alive.current) return;
      setPhase('failed');
      setError(describe(failure));
    }
  };

  const stopWaiting = () => {
    stopTimer();
    setPhase('idle');
    setRun(null);
  };

  const copyReport = async () => {
    if (!report) return;
    try {
      const clipboard = globalThis.navigator?.clipboard;
      if (!clipboard?.writeText) throw new Error('clipboard unavailable');
      await clipboard.writeText(reportToMarkdown(report));
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  };

  const downloadReport = () => {
    if (!report) return;
    try {
      const blob = new Blob([reportToMarkdown(report)], {
        type: 'text/markdown;charset=utf-8',
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = reportFileName(report);
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      setCopyState('failed');
    }
  };

  const printReport = () => {
    if (typeof window.print === 'function') window.print();
  };

  const findings = useMemo(
    () =>
      (report?.results ?? [])
        .filter((item) => item.status === 'finding')
        .sort((a, b) => (LEVEL_ORDER[a.level] ?? 9) - (LEVEL_ORDER[b.level] ?? 9)),
    [report],
  );
  const passed = useMemo(
    () => (report?.results ?? []).filter((item) => item.status === 'pass'),
    [report],
  );
  const unable = useMemo(
    () => (report?.results ?? []).filter((item) => item.status === 'unable_to_assess'),
    [report],
  );
  const stale = Boolean(
    report &&
      revision !== null &&
      report.snapshot.revision !== null &&
      report.snapshot.revision !== revision,
  );
  const activeConfig = configs?.find((item) => item.config_id === configId) ?? null;

  return (
    <section className="conformance" data-testid="conformance-panel" aria-label="Template audit">
      <div className="row">
        <h3>Template audit</h3>
        <span className="tiny muted">Config-driven · Doubao synthesises · human decides</span>
      </div>

      <p className="tiny muted">
        Reads the saved draft ({documentTitle ?? 'untitled'} · rev {revision ?? '—'} · sha{' '}
        {shortSha(contentSha)}) and judges it against a calibration config.
      </p>

      {dirty ? (
        <div className="notice notice--warn tiny" data-testid="conformance-dirty">
          There are unsaved editor changes ({saveState ?? 'unsaved'}). This audit reads the saved
          revision {revision ?? ''}; save first so the report covers what you see.
          {onSave ? (
            <button type="button" onClick={onSave}>
              Save now
            </button>
          ) : null}
        </div>
      ) : null}

      <label className="tiny muted" htmlFor="conformance-config">
        Calibration config
      </label>
      <select
        id="conformance-config"
        aria-label="Calibration config"
        data-tour="conformance-config"
        value={configId}
        onChange={(event) => setConfigId(event.target.value)}
        disabled={phase === 'running' || demoMode}
      >
        {(configs ?? []).map((config) => (
          <option key={config.config_id} value={config.config_id}>
            {config.name} · v{config.version}
          </option>
        ))}
      </select>
      {activeConfig ? (
        <p className="tiny muted">
          {activeConfig.requirement_count} requirement(s) ·{' '}
          {activeConfig.required_fields.length} required field(s) ·{' '}
          {activeConfig.document_types.join(', ')}
        </p>
      ) : null}

      {detail ? (
        <details className="audit-scope" data-testid="conformance-config-detail" data-tour="conformance-details">
          <summary className="tiny muted">
            Config details · {detail.requirement_count} requirement(s)
          </summary>
          <p className="tiny muted">
            Extraction profile: <code>{detail.extraction_profile ?? 'none'}</code> · limits:{' '}
            {Object.entries(detail.generation)
              .map(([key, value]) => `${key}=${value}`)
              .join(' · ')}
          </p>
          <ul className="tiny">
            {detail.requirements.map((requirement) => (
              <li key={requirement.id}>
                <strong>{requirement.title}</strong>{' '}
                <span className="muted">
                  ({requirement.level} · {requirement.id})
                </span>
                {requirement.check ? <div className="muted">{requirement.check}</div> : null}
                {requirement.suggestion ? (
                  <div className="muted">Suggestion: {requirement.suggestion}</div>
                ) : null}
              </li>
            ))}
          </ul>
          <p className="tiny muted">
            Read-only: publishing a config is a file change under{' '}
            <code>app/configs/conformance/</code>, so its version and sha stay auditable.
          </p>
        </details>
      ) : null}
      {detailError ? (
        <p className="notice notice--warn tiny" data-testid="conformance-detail-error">
          Could not load config details: {detailError}
        </p>
      ) : null}

      <div className="row">
        <button
          type="button"
          className="primary"
          onClick={() => void startReview()}
          disabled={!configId || demoMode}
          data-testid="conformance-run"
          data-tour="conformance-run"
        >
          Run template audit
        </button>
        {phase === 'running' ? (
          <button type="button" onClick={stopWaiting} data-testid="conformance-stop">
            Stop waiting
          </button>
        ) : null}
        {phase === 'done' ? (
          <button type="button" onClick={() => void startReview()}>
            Re-audit
          </button>
        ) : null}
      </div>

      {demoMode ? (
        <p className="notice tiny" data-testid="conformance-demo">
          Demo mode has no server draft, so the template audit is unavailable here.
        </p>
      ) : null}
      {loadError ? (
        <p className="notice notice--warn tiny" data-testid="conformance-load-error">
          Could not load calibration configs: {loadError}
        </p>
      ) : null}
      {configs && configs.length === 0 && !loadError ? (
        <p className="notice notice--warn tiny">No published calibration config is available.</p>
      ) : null}

      <details className="audit-scope" data-testid="conformance-outbound">
        <summary className="tiny muted">What leaves the service (and what is masked)</summary>
        <p className="tiny">
          {activeConfig?.description ||
            'The saved draft text and the checklist are sent to the approved model.'}
        </p>
        <p className="tiny">
          Redaction is best-effort and pattern-based. Before the call these are replaced with{' '}
          <code>[redacted]</code>: {REDACTION_PLAN.join(', ')}. Names, amounts and addresses still
          leave the service; the egress policy and the approved-processor gate remain the
          authoritative controls.
        </p>
      </details>

      {phase === 'running' ? (
        <AiWaitBox
          testId="conformance-running"
          title="Running the template audit"
          message={
            <>
              {STAGE_LABEL[String(run?.progress?.stage ?? run?.stage ?? 'queued')] ?? 'Working'}
              {run?.progress?.done != null && run?.progress?.planned != null
                ? ` · ${String(run.progress.done)}/${String(run.progress.planned)}`
                : ' · deterministic checks first, then the model judges each requirement'}
            </>
          }
          hint="Identifiers are redacted before the model call; the report pins this draft revision."
          elapsedMs={runningElapsed}
        />
      ) : null}

      {phase === 'failed' ? (
        <div className="notice notice--bad" role="alert" data-testid="conformance-error">
          <strong>Audit failed — no conclusion produced</strong>
          <p className="tiny">{error}</p>
        </div>
      ) : null}

      {report && phase === 'done' ? (
        <div data-testid="conformance-report">
          {stale ? (
            <div className="notice notice--warn" role="alert" data-testid="conformance-stale">
              <strong>Report is stale</strong>
              <p className="tiny">
                This report covers draft rev {report.snapshot.revision}; the draft is now rev{' '}
                {revision}. Re-audit before relying on it.
              </p>
            </div>
          ) : null}

          <div className="row" data-testid="conformance-outcome" data-tour="conformance-outcome">
            <span className={OUTCOME_CLASS[report.outcome]}>{OUTCOME_LABEL[report.outcome]}</span>
            <span className="tiny muted">
              {report.counts.passed}/{report.counts.requirements} requirement(s) assessed ·{' '}
              {Math.round(report.counts.coverage_ratio * 100)}% coverage · {report.completion}
            </span>
          </div>

          <div className="row" data-testid="conformance-export" data-tour="conformance-export">
            <button type="button" onClick={() => void copyReport()} data-testid="conformance-copy">
              Copy report
            </button>
            <button type="button" onClick={downloadReport} data-testid="conformance-download">
              Download .md
            </button>
            <button type="button" onClick={printReport} data-testid="conformance-print">
              Print / PDF
            </button>
            {copyState === 'copied' ? <span className="tiny">Copied</span> : null}
            {copyState === 'failed' ? <span className="tiny">Copy failed</span> : null}
          </div>

          {previous ? (
            <p className="tiny muted" data-testid="conformance-delta">
              Previous audit {new Date(previous.at).toLocaleString()} (rev{' '}
              {previous.revision ?? '—'}): findings{' '}
              {signed(report.counts.findings - previous.findings)} · missing fields{' '}
              {signed(report.counts.missing_fields - previous.missing)} · coverage{' '}
              {signed(Math.round((report.counts.coverage_ratio - previous.coverage) * 100))} pts
            </p>
          ) : null}

          {report.summary ? (
            <div className="notice tiny">
              <p>{report.summary}</p>
              <p className="muted">{report.summary_note}</p>
            </div>
          ) : null}

          {report.missing_fields.length > 0 ? (
            <div className="notice notice--warn" data-testid="conformance-missing" data-tour="conformance-missing">
              <h3>Required fields not found</h3>
              <ul className="tiny">
                {report.missing_fields.map((field) => (
                  <li key={field.key}>
                    <strong>{field.label}</strong> <code>{field.key}</code>
                    {field.note ? <span className="muted"> — {field.note}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {findings.length > 0 ? (
            <div data-testid="conformance-findings" data-tour="conformance-findings">
              <h3>Does not match the config</h3>
              {findings.map((item) => (
                <article key={item.id} className="notice" data-testid="conformance-finding">
                  <div className="row">
                    <strong>{item.title}</strong>
                    <span className="tiny muted">
                      {LEVEL_LABEL[item.level]} · {item.severity} · {item.confidence} confidence
                    </span>
                  </div>
                  <p className="tiny">{item.explanation}</p>
                  {item.quote ? (
                    <p className="tiny">
                      <code>{item.quote}</code>{' '}
                      {onJumpToBlock ? (
                        <button
                          type="button"
                          className="tiny"
                          onClick={() => {
                            if (item.block_index !== null) onJumpToBlock(item.block_index);
                          }}
                        >
                          Show in document
                        </button>
                      ) : null}
                    </p>
                  ) : null}
                  {item.suggestion ? <p className="tiny">Suggestion: {item.suggestion}</p> : null}
                </article>
              ))}
            </div>
          ) : null}

          {passed.length > 0 ? (
            <details className="audit-scope" data-testid="conformance-passed">
              <summary className="tiny muted">{passed.length} requirement(s) met</summary>
              <ul className="tiny">
                {passed.map((item) => (
                  <li key={item.id}>
                    {item.title}
                    {item.quote ? <span className="muted"> — “{item.quote}”</span> : null}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          {unable.length > 0 ? (
            <details className="audit-scope" data-testid="conformance-unable">
              <summary className="tiny muted">
                {unable.length} requirement(s) not assessed
              </summary>
              <ul className="tiny">
                {unable.map((item) => (
                  <li key={item.id}>
                    {item.title}
                    <span className="muted">
                      {' '}
                      — {item.reason_codes.join(', ') || 'not assessed'}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          {report.limitations.length > 0 ? (
            <details className="audit-scope" data-testid="conformance-limitations">
              <summary className="tiny muted">Limitations</summary>
              <ul className="tiny">
                {report.limitations.map((item, index) => (
                  <li key={`${item.code}-${index}`}>
                    <code>{item.code}</code> {item.message}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          <details className="audit-scope" data-testid="conformance-redaction" data-tour="conformance-redaction">
            <summary className="tiny muted">
              Redaction steps ({report.provenance.redaction.total} value(s))
            </summary>
            <p className="tiny">{report.provenance.redaction.note}</p>
            {report.provenance.redaction.steps.length > 0 ? (
              <table className="checks">
                <thead>
                  <tr>
                    <th>Kind</th>
                    <th>Count</th>
                    <th>Masked sample</th>
                  </tr>
                </thead>
                <tbody>
                  {report.provenance.redaction.steps.map((step) => (
                    <tr key={step.kind}>
                      <td>{step.kind}</td>
                      <td>{step.count}</td>
                      <td>
                        <code>{step.sample}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="tiny muted">Nothing matched the redaction patterns.</p>
            )}
          </details>

          <p className="tiny muted" data-testid="conformance-provenance">
            {report.config.config_id} v{report.config.version} · config{' '}
            {shortSha(report.config.content_sha256)} · {report.provenance.model ?? 'no model'} ·
            prompt {report.provenance.prompt_version} · extraction{' '}
            {report.provenance.extraction_status} · {report.provenance.model_calls} model call(s) ·{' '}
            {report.provenance.duration_ms} ms · snapshot{' '}
            {shortSha(report.snapshot.content_sha256)} · {report.snapshot.analyzed_chars} chars
            {report.snapshot.truncated ? ' (truncated)' : ''}
          </p>
        </div>
      ) : null}
    </section>
  );
}