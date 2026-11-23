import type { ReactNode } from 'react';

/**
 * The shared "AI is working" box for every assistant capability (audit / knowledge / legal).
 *
 * It is deliberately a *status*, not a fake progress percentage: the platforms behind these calls
 * (Doubao, statute retrieval, audit) do not report progress, so a 0–100% bar would be a lie. What it
 * does show is that the request is in flight, what is happening, the elapsed time, and — when the
 * call supports it — a way to stop waiting.
 *
 * Visual language follows the HSBC editorial style: white paper, ink text, one red accent, a thin
 * indeterminate rule instead of a spinner overlay.
 */
export interface AiWaitBoxProps {
  title: string;
  message?: ReactNode;
  hint?: ReactNode;
  elapsedMs?: number;
  /** Optional phase labels. Only pass phases the backend actually reports (no fake stage names). */
  steps?: string[];
  /** Index of the current phase; phases before it render as done. */
  activeStep?: number;
  onCancel?: () => void;
  cancelLabel?: string;
  testId?: string;
  /** `card` is the full status card; `inline` is a one-line status for tooltips. */
  variant?: 'card' | 'inline';
}

const seconds = (ms: number): string => `${(ms / 1000).toFixed(1)}s elapsed`;

export function AiWaitBox({
  title,
  message,
  hint,
  elapsedMs,
  steps,
  activeStep,
  onCancel,
  cancelLabel = 'Stop waiting',
  testId = 'ai-wait',
  variant = 'card',
}: AiWaitBoxProps) {
  const glyph = <span className="ai-wait__glyph" aria-hidden="true" />;
  const thinking = (
    <span className="ai-wait__thinking" aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  );

  if (variant === 'inline') {
    // Tooltip-sized status: no progress bar, no message/hint — just the live marker and the cause.
    return (
      <div
        className="ai-wait ai-wait--inline"
        role="status"
        aria-live="polite"
        aria-busy="true"
        data-testid={testId}
      >
        {glyph}
        <strong>{title}</strong>
        {thinking}
        {elapsedMs !== undefined ? (
          <span className="tiny muted">{seconds(elapsedMs)}</span>
        ) : null}
        {onCancel ? (
          <button type="button" className="tiny" onClick={onCancel}>
            {cancelLabel}
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className="ai-wait"
      role="status"
      aria-live="polite"
      aria-busy="true"
      data-testid={testId}
    >
      <div className="ai-wait__progress" aria-hidden="true">
        <span />
      </div>
      <div className="ai-wait__head">
        {glyph}
        <strong>{title}</strong>
        {thinking}
        {elapsedMs !== undefined ? (
          <span className="tiny muted">{seconds(elapsedMs)}</span>
        ) : null}
      </div>
      {message ? <div className="ai-wait__message tiny">{message}</div> : null}
      {steps && steps.length > 0 ? (
        <ol className="ai-wait__steps" aria-label="Progress">
          {steps.map((step, index) => {
            const state =
              activeStep === undefined
                ? 'pending'
                : index < activeStep
                  ? 'done'
                  : index === activeStep
                    ? 'active'
                    : 'pending';
            return (
              <li key={step} data-state={state} aria-current={state === 'active' ? 'step' : undefined}>
                {step}
              </li>
            );
          })}
        </ol>
      ) : null}
      {hint ? <div className="ai-wait__hint tiny muted">{hint}</div> : null}
      {onCancel ? (
        <div className="row">
          <button type="button" onClick={onCancel}>
            {cancelLabel}
          </button>
        </div>
      ) : null}
    </div>
  );
}