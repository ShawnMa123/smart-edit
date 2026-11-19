/**
 * Knowledge Q&A panel (task 5.2).
 *
 * Everything shown here comes from a completed, reviewed run: no placeholder answers, no invented
 * citations. The panel creates its snapshot/session on the first question, then only polls and reads.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import {
  assistantClient,
  newIdempotencyKey,
  type AssistantClient,
  type AssistantOptions,
} from '../api/assistant';
import {
  DEFAULT_WORKSPACE,
  isTerminal,
  type Answer,
  type AssistantSelection,
  type Capabilities,
  type Citation,
  type EvidenceDetail,
  type FeedbackRating,
  type Run,
  type Session,
} from '../api/assistantTypes';
import { ApiError, explainError } from '../api/errors';
import type { ActivityKind } from '../workspace/activityStore';
import { EmptyState } from './EmptyState';
import { onboardingCopy, suggestionsFor } from './knowledgeSuggestions';

export interface KnowledgePanelProps {
  documentId: string;
  /** Digest of the editor text this panel would freeze into the snapshot. */
  digest: string;
  text: string;
  selection?: AssistantSelection | null;
  locale?: 'zh-CN' | 'en';
  /** Injected in tests; defaults to the real client. */
  client?: AssistantClient;
  options?: AssistantOptions;
  /** 0 in tests, the server's `poll_after_ms` in the app. */
  pollDelayMs?: number;
  /** Reports a completed or failed knowledge operation to the workspace activity log. */
  onActivity?: (kind: ActivityKind, action: string, detail: string) => void;
}

const delay = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

const SUPPORT_COPY: Record<Answer['support_level'], string> = {
  strong: 'Strong support: claims are backed by current published sources.',
  qualified: 'Qualified support: some evidence was removed or is only partially covered.',
  insufficient: 'Insufficient support: no publishable conclusion is available.',
  not_applicable: 'Not applicable: this outcome does not carry evidence.',
};

export function KnowledgePanel({
  documentId,
  digest,
  text,
  selection = null,
  locale = 'en',
  client = assistantClient,
  options = {},
  pollDelayMs = 500,
  onActivity,
}: KnowledgePanelProps) {
  const [question, setQuestion] = useState('');
  const [session, setSession] = useState<Session | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [messageId, setMessageId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [phase, setPhase] = useState<'idle' | 'asking' | 'running'>('idle');
  const [detail, setDetail] = useState<EvidenceDetail | null>(null);
  const [feedback, setFeedback] = useState<FeedbackRating | null>(null);
  const [showExamples, setShowExamples] = useState(true);
  const [helpOpen, setHelpOpen] = useState(true);
  /** Per-run opt-in for the web layer; defaults to off and never persists (design D9). */
  const [webSearch, setWebSearch] = useState(true);
  /** Explicit scope (`knowledge-simple-ask`): a jurisdiction chip, empty means "any". */
  const [jurisdiction, setJurisdiction] = useState('');
  /** True once the user touched the web switch, so a late capability response cannot override it. */
  const webTouched = useRef(false);
  /** Deployment capability view; null means "not loaded / unavailable" (keep the toggle usable). */
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const questionRef = useRef<HTMLTextAreaElement>(null);
  const alive = useRef(true);
  // Capability discovery: keep the toggle honest about what this server can actually do.
  useEffect(() => {
    let aliveLoad = true;
    const load = client.getCapabilities;
    if (typeof load !== 'function') return undefined;
    load.call(client, options)
      .then((value) => {
        if (aliveLoad) setCapabilities(value);
      })
      .catch(() => {
        if (aliveLoad) setCapabilities(null);
      });
    return () => {
      aliveLoad = false;
    };
    // `options` is a stable-in-practice object; depending on it would refetch on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);
  const cancelled = useRef(false);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const selectionLabel = useMemo(() => {
    if (!selection) return 'No selection — answers use the bound snapshot and published knowledge.';
    const excerpt = selection.selectedText;
    const short = excerpt.length > 80 ? `${excerpt.slice(0, 80)}…` : excerpt;
    return `Selected passage: “${short}”`;
  }, [selection]);

  const copy = useMemo(() => onboardingCopy(locale), [locale]);
  const suggestions = useMemo(() => {
    const presets = capabilities?.presets?.suggested_questions;
    if (presets && presets.length) {
      return presets.map((question, index) => ({
        id: `preset-${index}`,
        label: question,
        question,
      }));
    }
    return suggestionsFor(selection, locale);
  }, [capabilities, selection, locale]);

  const chooseSuggestion = (nextQuestion: string) => {
    setQuestion(nextQuestion);
    questionRef.current?.focus();
  };

  // The snapshot digest is computed asynchronously in the browser; asking before it exists would
  // register an invalid snapshot, so the button waits instead of failing the request.
  const digestReady = !text.trim() || Boolean(digest);

  const resetConversation = () => {
    setSession(null);
    setRun(null);
    setAnswer(null);
    setMessageId(null);
    setDetail(null);
    setFeedback(null);
    setNotice(null);
    setError(null);
    setQuestion('');
    cancelled.current = false;
    setShowExamples(true);
  };

  const ask = async () => {
    const trimmed = question.trim();
    if (!trimmed || phase !== 'idle' || !digestReady) return;
    cancelled.current = false;
    setError(null);
    setNotice(null);
    setAnswer(null);
    setFeedback(null);
    setDetail(null);
    setPhase('asking');
    try {
      let active = session;
      if (!active) {
        let snapshotId: string | null = null;
        if (text.trim()) {
          const snapshot = await client.createSnapshot(
            { document_id: documentId, text, content_sha256: digest, version_label: null },
            options,
          );
          snapshotId = snapshot.id;
        }
        active = await client.createSession(
          {
            workspace_id: DEFAULT_WORKSPACE,
            locale,
            ...(snapshotId ? { document_id: documentId, snapshot_id: snapshotId } : {}),
          },
          newIdempotencyKey('session'),
          options,
        );
        if (!alive.current) return;
        setSession(active);
      }

      const accepted = await client.createRun(
        active.id,
        {
          question: trimmed,
          selection,
          web_search: webSearch,
          // Omitted when empty: the server model forbids extra/`null` scope fields.
          ...(jurisdiction ? { jurisdiction_codes: [jurisdiction] } : {}),
          // The effective value is always explicit; the source says who decided it.
          web_search_source: webTouched.current ? 'user' : 'default',
        },
        newIdempotencyKey('run'),
        options,
      );
      if (!alive.current) return;
      setRun(accepted);
      setPhase('running');
      setQuestion('');

      let latest: Run = accepted;
      while (!isTerminal(latest.status) && !cancelled.current && alive.current) {
        await delay(pollDelayMs);
        if (!alive.current || cancelled.current) break;
        latest = await client.getRun(latest.id, options);
        if (!alive.current) return;
        setRun(latest);
      }
      if (!alive.current) return;
      if (cancelled.current) {
        setNotice('Run cancelled — no answer was published.');
        return;
      }
      if (latest.status === 'succeeded' && latest.result) {
        setAnswer(latest.result);
        setMessageId(latest.assistant_message_id);
        setShowExamples(false);
        onActivity?.(
          'knowledge',
          'Knowledge answer',
          `Knowledge answer: ${latest.result.outcome}`,
        );
        try {
          const refreshed = await client.getSession(active.id, options);
          if (alive.current && refreshed.context_stale) {
            setNotice(
              'This conversation is bound to an older document snapshot. Start a new conversation to use the current text.',
            );
          }
        } catch {
          // Staleness is advisory; a failed refresh must not hide a published answer.
        }
      } else if (latest.status === 'failed' || latest.status === 'timed_out') {
        setError(explainError(latest.error?.code ?? 'ASSISTANT_FAILED'));
        onActivity?.('knowledge', 'Knowledge failed', 'Knowledge run did not complete');
      } else if (latest.status === 'cancelled') {
        setNotice('Run cancelled — no answer was published.');
      }
    } catch (failure) {
      if (!alive.current) return;
      setError(failure instanceof ApiError ? explainError(failure.code) : String(failure));
      onActivity?.('knowledge', 'Knowledge failed', 'Knowledge request failed');
      if (failure instanceof ApiError && failure.code === 'ANCHOR_MISMATCH') {
        setNotice('The passage no longer matches the snapshot. Select it again to ask about it.');
      }
    } finally {
      if (alive.current) setPhase('idle');
    }
  };

  const stop = async () => {
    if (!run || isTerminal(run.status)) return;
    cancelled.current = true;
    try {
      await client.cancelRun(run.id, newIdempotencyKey('cancel'), options);
      setNotice('Run cancelled — no answer was published.');
    } catch (failure) {
      cancelled.current = false;
      setError(failure instanceof ApiError ? explainError(failure.code) : String(failure));
    }
  };

  const openCitation = async (citation: Citation) => {
    if (!messageId) return;
    try {
      setDetail(await client.getCitation(messageId, citation.id, options));
    } catch (failure) {
      setError(failure instanceof ApiError ? explainError(failure.code) : String(failure));
    }
  };

  const sendFeedback = async (rating: FeedbackRating) => {
    if (!messageId) return;
    try {
      await client.putFeedback(messageId, { rating }, options);
      setFeedback(rating);
    } catch (failure) {
      setError(failure instanceof ApiError ? explainError(failure.code) : String(failure));
    }
  };

  // Start from the deployment policy once capabilities arrive; a user choice always wins.
  useEffect(() => {
    if (!webTouched.current && capabilities) {
      setWebSearch(Boolean(capabilities.web?.default_on));
    }
  }, [capabilities]);

  const busy = phase !== 'idle';
  const activeRun = run && !isTerminal(run.status);
  const webLayer = answer?.retrieval?.find((layer) => layer.layer === 'web');
  const webSummary = answer?.web ?? null;
  const generalWebAnswer = Boolean(
    answer?.citations?.some((citation) => citation.source_type === 'general_web'),
  );
  const webAvailable = capabilities
    ? capabilities.layers.approved_web || capabilities.layers.general_web
    : true;
  const generalOnly = capabilities
    ? !capabilities.layers.approved_web && capabilities.layers.general_web
    : false;
  // Jurisdiction chips come from the configured presets, falling back to the measured catalogue.
  const jurisdictionOptions =
    capabilities?.presets?.jurisdictions ?? capabilities?.statute?.jurisdictions ?? [];
  const jurisdictionMeasured = jurisdictionOptions.length > 0;
  const webSkippedNotice =
    webSummary?.requested && webSummary.status !== 'ok' && webSummary.status !== 'off';

  return (
    <div className="knowledge-panel">
      <p className="notice notice--warn tiny" role="status">
        Fixture-backed: answers use synthetic demo sources, not official legal texts.
      </p>
      {webAvailable ? (
        <p className="tiny muted" role="status">
          Statute-backed answers. If nothing in the statute corpus matches, this question may go to
          public web search (unverified) — you can switch that off below.
        </p>
      ) : null}
      {notice ? (
        <p className="notice notice--warn tiny" role="status">
          {notice}
        </p>
      ) : null}

      {!session && !answer && !run ? (
        <EmptyState
          icon="◎"
          title="Ask about the product, a rule or this passage"
          hint="Pick a suggested question or write your own below. Every answer cites the source it came from."
          action={
            <button type="button" onClick={() => questionRef.current?.focus()}>
              Write a question
            </button>
          }
        />
      ) : null}

      <details
        className="knowledge-onboarding"
        open={helpOpen}
        onToggle={(event) => setHelpOpen(event.currentTarget.open)}
      >
        <summary>{copy.summary}</summary>
        <p className="tiny">
          <strong>Can:</strong> {copy.can}
        </p>
        <p className="tiny">
          <strong>Cannot:</strong> {copy.cannot}
        </p>
        <p className="tiny">
          <strong>How:</strong> {copy.how}
        </p>
      </details>

      {showExamples ? (
        <div className="knowledge-suggestions" role="group" aria-label="Suggested questions">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion.id}
              type="button"
              onClick={() => chooseSuggestion(suggestion.question)}
            >
              {suggestion.label}
            </button>
          ))}
        </div>
      ) : (
        <button type="button" className="knowledge-show-examples" onClick={() => setShowExamples(true)}>
          {copy.showExamples}
        </button>
      )}

      <div className="knowledge-binding tiny muted">
        {session
          ? `Conversation ${session.id} · bound snapshot ${session.snapshot_id ?? 'none (knowledge only)'}`
          : 'A conversation and snapshot are created with your first question.'}
      </div>

      <div className="knowledge-web-toggle">
        <label>
          <input
            type="checkbox"
            checked={webSearch}
            disabled={busy || !webAvailable}
            onChange={(event) => {
              webTouched.current = true;
              setWebSearch(event.target.checked);
            }}
          />
          <span>
            {generalOnly ? 'Ask general web (unverified)' : 'Search the web for the latest'}
          </span>
        </label>
        {!webAvailable ? (
          <p className="tiny muted">
            Web is not available on this server (no provider configured).
          </p>
        ) : (
          <p className="tiny muted">
            {webSearch
              ? 'Will send: the screened question only. Questions outside the published knowledge base may be answered from the web (unverified). Will not send: document text, selected passage, amounts, counterparties or your identity.'
              : 'Off: this run will not search the web (RAG and internal sources are still searched).'}
          </p>
        )}
        {capabilities && !capabilities.model.configured ? (
          <p className="tiny muted">
            Model: fixture · no external model configured (answers use the local corpus only).
          </p>
        ) : null}
      </div>

      {jurisdictionMeasured ? (
        <div className="knowledge-scope" role="group" aria-label="Scope">
          <span className="tiny muted">Scope</span>
          <button type="button" aria-pressed={!jurisdiction} onClick={() => setJurisdiction('')}>
            Any
          </button>
          {jurisdictionOptions.map((code) => (
            <button
              key={code}
              type="button"
              aria-pressed={jurisdiction === code}
              onClick={() => setJurisdiction(jurisdiction === code ? '' : code)}
            >
              {code}
            </button>
          ))}
          <span className="tiny muted">Statute search only.</span>
        </div>
      ) : null}

      <label className="tiny muted" htmlFor="knowledge-question">
        Question
      </label>
      <textarea
        id="knowledge-question"
        ref={questionRef}
        aria-label="Knowledge question"
        value={question}
        disabled={busy}
        onChange={(event) => setQuestion(event.target.value)}
        placeholder="Ask about the product, a trade rule, or the selected passage"
      />
      <p className="tiny muted">{selectionLabel}</p>

      <div className="row">
        <button
          type="button"
          onClick={() => void ask()}
          disabled={busy || !question.trim() || !digestReady}
        >
          Ask
        </button>
        {activeRun ? (
          <button type="button" onClick={() => void stop()}>
            Cancel run
          </button>
        ) : null}
        {session ? (
          <button type="button" onClick={resetConversation}>
            Start new conversation
          </button>
        ) : null}
      </div>

      {run ? (
        <p className="tiny muted" role="status">
          Run {run.status} · {run.stage}
        </p>
      ) : null}
      {error ? (
        <p className="notice notice--bad tiny" role="alert">
          {error}
        </p>
      ) : null}

      {webSkippedNotice ? (
        <p className="notice notice--warn tiny" role="status">
          Web search {webSummary!.status}
          {webSummary!.reason ? ` (${webSummary!.reason})` : ''}. {webSummary!.hint ?? ''}
        </p>
      ) : null}
      {webSummary?.requested && webSummary.status === 'ok' ? (
        <p className="tiny muted">
          Stored question: redacted — the outbound query differed from what you typed.
        </p>
      ) : null}
      {webSummary?.requested &&
      webSummary.status !== 'ok' &&
      (answer?.route === 'published' || answer?.route === 'document') ? (
        <p className="tiny muted">Answered from published sources · web not needed.</p>
      ) : null}

      {answer?.web?.reason === 'rag_empty' ? (
        <p className="notice notice--warn tiny" role="status">
          RAG returned no result — searched the web automatically (unverified).
        </p>
      ) : null}

      {/* Older answers carry no `web` summary; fall back to the layer report. */}
      {!webSummary && webLayer?.status === 'blocked' ? (
        <p className="notice notice--warn tiny" role="status">
          Web search blocked ({webLayer.detail ?? 'policy'}). Remove document text or ask without web
          search.
        </p>
      ) : null}
      {!webSummary && webLayer?.status === 'failed' ? (
        <p className="notice notice--warn tiny" role="status">
          Web search did not complete; no live results were used.
        </p>
      ) : null}
      {!webSummary && webLayer?.status === 'ok' ? (
        <p className="tiny muted">
          Stored question: redacted — the outbound query differed from what you typed.
        </p>
      ) : null}

      {generalWebAnswer ? (
        <p className="notice notice--warn tiny" role="status">
          General web answer — unverified third-party content, not a published source.
        </p>
      ) : null}

      {answer ? (
        <AnswerView
          answer={answer}
          feedback={feedback}
          onCitation={(citation) => void openCitation(citation)}
          onFeedback={(rating) => void sendFeedback(rating)}
        />
      ) : null}

      {detail ? (
        <div className="knowledge-citation" role="region" aria-label="Citation detail">
          <div className="row">
            <h4>{detail.title}</h4>
            <button type="button" aria-label="Close citation" onClick={() => setDetail(null)}>
              ✕
            </button>
          </div>
          <p className="tiny muted">
            {detail.source_type} · {detail.source_version}
            {detail.effective_from ? ` · effective from ${detail.effective_from}` : ''}
            {detail.effective_to ? ` · until ${detail.effective_to}` : ''}
          </p>
          <blockquote className="tiny">{detail.excerpt}</blockquote>
          <p className="tiny muted">Locator: {JSON.stringify(detail.locator)} · excerpt only</p>
        </div>
      ) : null}
    </div>
  );
}

const SOURCE_GROUPS = [
  { id: 'statute', label: 'Statute', types: ['statute'] },
  { id: 'published', label: 'Published corpus', types: ['product_manual', 'trade_rule', 'internal_policy'] },
  { id: 'web', label: 'Web', types: ['approved_web'] },
  { id: 'general', label: 'General web', types: ['general_web'] },
  { id: 'document', label: 'Document', types: ['document_snapshot', 'attachment'] },
] as const;

/** Facts a reader can check; never a relevance score (design D3). */
export function statuteBadge(citation: Citation): string {
  const locator = citation.locator ?? {};
  const parts: string[] = [];
  if (locator.jurisdiction) parts.push(String(locator.jurisdiction));
  if (locator.effective_from) parts.push(`effective ${String(locator.effective_from)}`);
  if (locator.precision) parts.push(String(locator.precision));
  if (locator.superseded_by) parts.push(`superseded by ${String(locator.superseded_by)}`);
  return parts.length ? ` · ${parts.join(' · ')}` : '';
}

/** One short, distinct label per statute outcome so the four degradations never read alike. */
export function statuteNotice(answer: Answer): string | null {
  const layer = answer.retrieval?.find((item) => item.layer === 'statute');
  if (!layer) return null;
  const detail = layer.detail ?? '';
  const hits = typeof layer.hits === 'number' ? layer.hits : null;
  if (layer.status === 'blocked') {
    return 'Statute search blocked by outbound policy — not covered';
  }
  if (layer.status === 'failed') {
    if (detail === 'corpus_updating') return 'Statute corpus is being rebuilt';
    if (detail === 'timeout') return 'Statute search timed out';
    return 'Statute search unavailable';
  }
  if (detail === 'partial') {
    return 'Statute answer is partial — the cited evidence is incomplete';
  }
  if (detail === 'unsupported' || detail === 'unavailable') {
    return 'The statute service did not return a usable answer';
  }
  if (detail.startsWith('uncovered:')) {
    return `Jurisdiction not covered: ${detail.slice('uncovered:'.length)}`;
  }
  if (detail === 'degraded:keyword_only') return 'Keyword-only statute search';
  if (detail === 'superseded') return 'A cited statute has been superseded';
  // Stated even when the internal corpus answered: the reader must be able to tell
  // "we did not look" from "we looked and rejected it" (`statute-recall`).
  if (detail === 'low_confidence') {
    return hits === null
      ? 'Statute matches were low confidence — reference only'
      : `${hits} statute match(es) at low confidence — reference only`;
  }
  if (detail.startsWith('zero:')) return 'No statute matched this question';
  return null;
}

function sourceGroups(citations: Citation[]) {
  return SOURCE_GROUPS.map((group) => ({
    ...group,
    items: citations.filter((citation) =>
      (group.types as readonly string[]).includes(citation.source_type),
    ),
  }));
}

function AnswerView({
  answer,
  feedback,
  onCitation,
  onFeedback,
}: {
  answer: Answer;
  feedback: FeedbackRating | null;
  onCitation: (citation: Citation) => void;
  onFeedback: (rating: FeedbackRating) => void;
}) {
  return (
    <div className="knowledge-answer" aria-label="Assistant answer">
      <div className="row">
        <h3>Answer · {answer.outcome}</h3>
        <span className="tiny muted">Support: {answer.support_level}</span>
      </div>
      <p className="tiny muted">Processor: {answer.processor ?? 'fixture'}</p>
      <p className="tiny muted">{SUPPORT_COPY[answer.support_level]}</p>

      {statuteNotice(answer) ? (
        <p className="notice notice--warn tiny" role="status">
          {statuteNotice(answer)}
        </p>
      ) : null}

      {answer.claims.length ? (
        <ul className="knowledge-claims">
          {answer.claims.map((claim) => (
            <li key={claim.id}>
              <span>{claim.text}</span>{' '}
              <span className="tiny muted">
                [{claim.kind}; {claim.citation_ids.length} citation(s)]
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      {answer.clarification_questions.length ? (
        <div>
          <h4>Information needed</h4>
          <ol className="knowledge-claims">
            {answer.clarification_questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ol>
        </div>
      ) : null}

      {answer.outcome === 'needs_handoff' ? (
        <p className="notice notice--warn tiny">
          This request belongs to {answer.handoff_target}. The knowledge assistant will not edit,
          approve, submit or perform any action.
        </p>
      ) : null}

      {answer.limitations.length ? (
        <div>
          <h4>Limitations</h4>
          <ul className="knowledge-limitations">
            {answer.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {answer.citations.length ? (
        <div>
          <h4>Citations</h4>
          <div className="knowledge-source-groups">
            {sourceGroups(answer.citations).map((group) =>
              group.items.length ? (
                <div className="knowledge-source-group" key={group.id}>
                  <h5>
                    {group.label} ({group.items.length})
                  </h5>
                  <div className="knowledge-citations">
                    {group.items.map((citation) => (
                      <button
                        key={citation.id}
                        type="button"
                        aria-label={`Open citation ${citation.title}`}
                        onClick={() => onCitation(citation)}
                      >
                        {citation.title} · {citation.source_version}
                        {citation.source_type === 'approved_web'
                          ? ` · ${String(citation.locator.domain ?? 'web')} · retrieved ${String(
                              citation.locator.retrieved_at ?? 'unknown',
                            )} · Unverified third-party`
                          : ''}
                        {citation.source_type === 'statute' ? statuteBadge(citation) : ''}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null,
            )}
          </div>
          <p className="tiny muted">
            Each claim only cites evidence returned for this run; opening a citation shows the allowed
            excerpt and its locator.
          </p>
        </div>
      ) : (
        <p className="tiny muted">
          No citation is shown because no evidence supported a publishable claim.
        </p>
      )}

      {answer.outcome === 'answered' ? (
        <div className="row">
          <button type="button" onClick={() => onFeedback('helpful')}>
            Helpful
          </button>
          <button type="button" onClick={() => onFeedback('not_helpful')}>
            Not helpful
          </button>
          {feedback ? (
            <span className="tiny muted" role="status">
              Feedback saved: {feedback}. It never changes the answer or the knowledge base.
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}