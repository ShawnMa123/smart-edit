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
  type Citation,
  type EvidenceDetail,
  type FeedbackRating,
  type Run,
  type Session,
} from '../api/assistantTypes';
import { ApiError, explainError } from '../api/errors';
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
  const questionRef = useRef<HTMLTextAreaElement>(null);
  const alive = useRef(true);
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
  const suggestions = useMemo(() => suggestionsFor(selection, locale), [selection, locale]);

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
        { question: trimmed, selection },
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
      } else if (latest.status === 'cancelled') {
        setNotice('Run cancelled — no answer was published.');
      }
    } catch (failure) {
      if (!alive.current) return;
      setError(failure instanceof ApiError ? explainError(failure.code) : String(failure));
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

  const busy = phase !== 'idle';
  const activeRun = run && !isTerminal(run.status);

  return (
    <div className="knowledge-panel">
      <p className="notice notice--warn tiny" role="status">
        Fixture-backed: answers use synthetic demo sources, not official legal texts. The assistant
        never edits the document, approves, submits, or browses the web.
      </p>
      {notice ? (
        <p className="notice notice--warn tiny" role="status">
          {notice}
        </p>
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
      <p className="tiny muted">{SUPPORT_COPY[answer.support_level]}</p>

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
          <div className="knowledge-citations">
            {answer.citations.map((citation) => (
              <button
                key={citation.id}
                type="button"
                aria-label={`Open citation ${citation.title}`}
                onClick={() => onCitation(citation)}
              >
                {citation.title} · {citation.source_version}
              </button>
            ))}
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