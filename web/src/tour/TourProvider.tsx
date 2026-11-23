/**
 * Guided tour engine: launcher → spotlight/tooltip steps → optional autopilot.
 *
 * Two modes, chosen by the operator in the launcher:
 * - Guide: the operator clicks; "Next" unlocks only when the step's `until` predicate is true.
 * - Autopilot ("Watch me"): the engine clicks the real control and types through the editor bridge,
 *   then waits for the real app state. Submission steps are gated by the approval choice.
 *
 * The engine never re-implements app behaviour: clicks are real DOM clicks, typing uses TipTap's
 * own command chain (so autosave/locks run), and every "Next" gate reads real DOM state.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';

import { useToast } from '../components/ToastProvider';
import { AiWaitBox } from '../components/AiWaitBox';
import { useElapsedMs } from '../components/useElapsedMs';
import { PresenterPanel } from './PresenterPanel';
import { LIFECYCLE_IDS } from './catalog';
import type {
  ApprovalMode,
  Tour,
  TourAction,
  TourContextValue,
  TourEditorApi,
  TourMode,
  TourSettings,
  TourStep,
  WaitPredicate,
} from './types';

const TourContext = createContext<TourContextValue | null>(null);

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

const prefersReducedMotion = (): boolean =>
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const completedKey = (tour: Tour): string =>
  `smart-edit:tour:${tour.id}:v${tour.version}:completed`;

const readCompleted = (tour: Tour): boolean => {
  try {
    return globalThis.localStorage?.getItem(completedKey(tour)) === '1';
  } catch {
    return false;
  }
};

const markCompleted = (tour: Tour): void => {
  try {
    globalThis.localStorage?.setItem(completedKey(tour), '1');
  } catch {
    // Storage is optional; the tour still runs.
  }
};

const elementFor = (selector: string): HTMLElement | null => {
  try {
    return document.querySelector<HTMLElement>(selector);
  } catch {
    return null;
  }
};

const boxOf = (element: HTMLElement) => {
  const rect = element.getBoundingClientRect();
  return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
};

const checkPredicate = (predicate: WaitPredicate): boolean => {
  if (predicate.kind === 'saveState') {
    return document.querySelector('[data-testid="save-state"]')?.textContent === 'Saved to server';
  }
  if (predicate.kind === 'conformanceReport') {
    return Boolean(document.querySelector('[data-testid="conformance-report"]'));
  }
  if (predicate.kind === 'absent') {
    return !elementFor(predicate.selector);
  }
  if (predicate.kind === 'selector') {
    return Boolean(elementFor(predicate.selector));
  }
  const element = elementFor(predicate.selector);
  return Boolean(element && (element.textContent ?? '').includes(predicate.includes));
};

const isApprovalGated = (step: TourStep, settings: TourSettings): boolean =>
  Boolean(step.requiresApprovalAuto && settings.mode === 'auto' && settings.approvals === 'manual');

const tooltipStyle = (rect: ReturnType<typeof boxOf> | null, placement?: TourStep['placement']) => {
  if (!rect || placement === 'center') {
    return {
      left: '50%',
      top: '50%',
      transform: 'translate(-50%, -50%)',
    } as CSSProperties;
  }
  const gap = 16;
  const width = Math.min(380, window.innerWidth - 24);
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let left = rect.x;
  let top = rect.y + rect.height + gap;
  let transform = '';
  if (placement === 'left') {
    left = rect.x - width - gap;
    top = rect.y + rect.height / 2;
    transform = 'translateY(-50%)';
  } else if (placement === 'right') {
    left = rect.x + rect.width + gap;
    top = rect.y + rect.height / 2;
    transform = 'translateY(-50%)';
  } else if (placement === 'top') {
    top = rect.y - gap;
    transform = 'translateY(-100%)';
  }
  if (left + width > vw - 12) left = vw - width - 12;
  if (left < 12) left = 12;
  if (top < 12) top = 12;
  if (top > vh - 120) top = Math.max(12, vh - 200);
  return { left, top, transform, width } as CSSProperties;
};

export function TourProvider({
  tour,
  tours,
  children,
  autoDwellMs = 10_000,
}: {
  /** Single-tour shorthand (tests and one-tour embeds). */
  tour?: Tour;
  /** Catalog offered by the launcher and by `?tour=<id>` deep links. */
  tours?: Tour[];
  children: ReactNode;
  /** Autopilot reading time per step before it advances (default 10 seconds). */
  autoDwellMs?: number;
}) {
  const catalog = useMemo<Tour[]>(
    () => (tours && tours.length ? tours : tour ? [tour] : []),
    [tour, tours],
  );
  const [tourId, setTourId] = useState(() => catalog[0]?.id ?? '');
  const active =
    catalog.find((item) => item.id === tourId) ??
    catalog[0] ?? { id: 'empty', version: 1, title: '', description: '', steps: [] };
  const toast = useToast();
  const [phase, setPhase] = useState<'idle' | 'launcher' | 'running' | 'presenter'>('idle');
  const [mode, setMode] = useState<TourMode>('guide');
  const [approvals, setApprovals] = useState<ApprovalMode>('manual');
  const [settings, setSettings] = useState<TourSettings>({ mode: 'guide', approvals: 'manual' });
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<ReturnType<typeof boxOf> | null>(null);
  const [missing, setMissing] = useState(false);
  const [satisfied, setSatisfied] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  /** Honest wait time shown inside the tooltip while `until` has not been reached yet. */
  const waitingElapsed = useElapsedMs(phase === 'running' && !satisfied && !missing);
  const [paused, setPaused] = useState(false);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [countdown, setCountdown] = useState<number | null>(null);
  /** 0–100 of the autopilot reading time left, for the horizontal bar. */
  const [countdownPct, setCountdownPct] = useState<number | null>(null);
  const [completedIds, setCompletedIds] = useState<string[]>(() =>
    catalog.filter((item) => readCompleted(item)).map((item) => item.id),
  );
  const completed = completedIds.includes(active.id);
  const lifecycleTotal = catalog.filter((item) =>
    (LIFECYCLE_IDS as readonly string[]).includes(item.id),
  ).length;
  const lifecycleDone = LIFECYCLE_IDS.filter((id) => completedIds.includes(id)).length;
  const editorRef = useRef<TourEditorApi | null>(null);
  const pausedRef = useRef(false);
  const performedRef = useRef<string>('');
  const step: TourStep | null = active.steps[index] ?? null;

  const registerEditor = useCallback((api: TourEditorApi | null) => {
    editorRef.current = api;
  }, []);

  const finish = useCallback(() => {
    markCompleted(active);
    setCompletedIds((ids) => (ids.includes(active.id) ? ids : [...ids, active.id]));
    toast.success('Tour completed');
    setPhase('idle');
    setIndex(0);
    setRect(null);
    setCursor(null);
    setHint(null);
  }, [active, toast]);

  const advance = useCallback(() => {
    if (pausedRef.current) {
      pausedRef.current = false;
      setPaused(false);
    }
    if (index + 1 >= active.steps.length) {
      finish();
      return;
    }
    setIndex(index + 1);
  }, [active.steps.length, finish, index]);

  const skip = useCallback(() => {
    if (pausedRef.current) {
      pausedRef.current = false;
      setPaused(false);
    }
    setHint(null);
    if (index + 1 >= active.steps.length) {
      finish();
      return;
    }
    setIndex(index + 1);
  }, [active.steps.length, finish, index]);

  const back = useCallback(() => {
    if (pausedRef.current) {
      pausedRef.current = false;
      setPaused(false);
    }
    setHint(null);
    setIndex(Math.max(0, index - 1));
  }, [index]);

  const stop = useCallback(() => {
    setPhase('idle');
    setIndex(0);
    setRect(null);
    setCursor(null);
    setHint(null);
    setMissing(false);
    setSatisfied(false);
    pausedRef.current = false;
    setPaused(false);
    toast.info('Tour stopped');
  }, [toast]);

  const openLauncher = useCallback((nextTourId?: string) => {
    if (nextTourId && catalog.some((item) => item.id === nextTourId)) {
      setTourId(nextTourId);
      setIndex(0);
    }
    setPhase((current) => (current === 'running' ? current : 'launcher'));
  }, [catalog]);

  const openPresenter = useCallback(() => {
    setPhase((current) => (current === 'running' ? current : 'presenter'));
  }, []);

  const start = useCallback(() => {
    setSettings({ mode, approvals });
    setIndex(0);
    setSatisfied(false);
    setMissing(false);
    setHint(null);
    setCursor(null);
    setAttempt(0);
    performedRef.current = '';
    pausedRef.current = false;
    setPaused(false);
    setPhase('running');
  }, [approvals, mode]);

  const togglePause = useCallback(() => {
    setPaused((current) => {
      pausedRef.current = !current;
      return !current;
    });
  }, []);

  const retry = useCallback(() => {
    setMissing(false);
    setHint(null);
    setAttempt((value) => value + 1);
  }, []);
const perform = useCallback(
    async (action: TourAction, isCancelled: () => boolean): Promise<string | null> => {
      if (action.kind === 'manual') {
        setHint(action.instruction);
        return null;
      }

      if (action.kind === 'paste' || action.kind === 'type') {
        const editor = editorRef.current;
        if (editor) {
          editor.focus();
          editor.clear();
          if (action.kind === 'paste' || prefersReducedMotion()) {
            editor.insertText(action.text);
            return null;
          }
          const chunk = 3;
          const interval = Math.max(16, (1000 / (action.cps ?? 90)) * chunk);
          for (let offset = 0; offset < action.text.length; offset += chunk) {
            if (isCancelled()) return null;
            while (pausedRef.current && !isCancelled()) await sleep(150);
            editor.insertText(action.text.slice(offset, offset + chunk));
            await sleep(interval);
          }
          return null;
        }
        const textarea = document.querySelector<HTMLTextAreaElement>(
          '[data-testid="editor-text"]',
        );
        if (textarea) {
          const setter = Object.getOwnPropertyDescriptor(
            HTMLTextAreaElement.prototype,
            'value',
          )?.set;
          setter?.call(textarea, action.text);
          textarea.dispatchEvent(new Event('input', { bubbles: true }));
          return null;
        }
        return 'I could not reach the editor. Type or paste into it, then press Next.';
      }

      if (action.kind === 'open') {
        // A summary click is a toggle, so a repeated step would close it again. Only act when the
        // disclosure is closed; the app's own handler still decides what "open" means (React state
        // for a controlled <details>, native toggle otherwise).
        const element = elementFor(action.selector);
        if (!element) return `I could not find ${action.selector}.`;
        if (element.tagName === 'DETAILS') {
          const details = element as HTMLDetailsElement;
          if (!details.open) {
            const summary = details.querySelector<HTMLElement>('summary');
            const box = boxOf(summary ?? details);
            setCursor({ x: box.x + box.width / 2, y: box.y + box.height / 2 });
            await sleep(prefersReducedMotion() ? 0 : 300);
            summary?.click();
            // jsdom does not toggle <details> from a summary click; keep the action honest there.
            if (!details.open) details.open = true;
          }
          return null;
        }
        return null;
      }

      if (action.kind === 'clickByText') {
        // Labels are more stable than generated ids, and a list can contain several rows.
        const candidates = Array.from(
          document.querySelectorAll<HTMLElement>(action.selector),
        );
        const target = candidates.find((item) =>
          (item.textContent ?? '').includes(action.includes),
        );
        if (!target) return `No control matching “${action.includes}” in ${action.selector}.`;
        if (target instanceof HTMLButtonElement && target.disabled) {
          return 'That control is disabled right now.';
        }
        const box = boxOf(target);
        setCursor({ x: box.x + box.width / 2, y: box.y + box.height / 2 });
        await sleep(prefersReducedMotion() ? 0 : 300);
        target.click();
        return null;
      }

      const element = elementFor(action.selector);
      if (!element) return `I could not find ${action.selector}.`;
      if (action.kind === 'click') {
        if (element instanceof HTMLButtonElement && element.disabled) {
          return 'That control is disabled right now.';
        }
        const box = boxOf(element);
        setCursor({ x: box.x + box.width / 2, y: box.y + box.height / 2 });
        await sleep(prefersReducedMotion() ? 0 : 300);
        element.click();
        return null;
      }
      if (action.kind === 'select') {
        const select = element as HTMLSelectElement;
        const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set;
        setter?.call(select, action.value);
        select.dispatchEvent(new Event('change', { bubbles: true }));
        return null;
      }
      if (action.kind === 'selectByText') {
        const select = element as HTMLSelectElement;
        const option = Array.from(select.options).find((item) =>
          (item.textContent ?? '').includes(action.includes),
        );
        if (!option) return `No option matching “${action.includes}” in ${action.selector}.`;
        const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set;
        setter?.call(select, option.value);
        select.dispatchEvent(new Event('change', { bubbles: true }));
        return null;
      }
      return null;
    },
    [],
  );
// Resolve + perform + wait, once per step (and once per explicit retry).
  useEffect(() => {
    if (phase !== 'running' || !step) return;
    let cancelled = false;
    const isCancelled = () => cancelled;
    setSatisfied(false);
    setMissing(false);
    setHint(null);
    setCursor(null);

    // A step whose precondition is already true (already submitted/approved, no lock) is skipped
    // with an explanation, instead of waiting for a dialog that will never open.
    const skipBecause = step.skipIf?.some((predicate) => checkPredicate(predicate)) ?? false;
    if (skipBecause) {
      const skipKey = `skip:${index}:${attempt}`;
      if (performedRef.current !== skipKey) {
        performedRef.current = skipKey;
        if (step.skipNote) toast.info(step.skipNote);
      }
      advance();
      return;
    }

    const run = async () => {
      let target: HTMLElement | null = null;
      if (step.target) {
        const attempts = Math.max(1, Math.ceil((step.targetTimeoutMs ?? 1000) / 100));
        for (let attemptIndex = 0; attemptIndex < attempts && !cancelled; attemptIndex += 1) {
          target = elementFor(step.target);
          if (target) break;
          await sleep(100);
        }
        if (cancelled) return;
        if (!target) {
          if (step.optional) {
            advance();
            return;
          }
          setMissing(true);
          return;
        }
        target.scrollIntoView({
          block: 'center',
          inline: 'nearest',
          behavior: prefersReducedMotion() ? 'auto' : 'smooth',
        });
        setRect(boxOf(target));
      } else {
        setRect(null);
      }

      const gated = isApprovalGated(step, settings);
      if (gated) {
        setHint('This step stayed manual: click the real control yourself, then press Next.');
      }
      if (settings.mode === 'auto' && step.action && !gated) {
        const key = `${index}:${settings.mode}:${settings.approvals}:${attempt}`;
        if (performedRef.current !== key) {
          performedRef.current = key;
          const failure = await perform(step.action, isCancelled);
          if (cancelled) return;
          if (failure) setHint(failure);
        }
      }

      if (!step.until) {
        setSatisfied(true);
        return;
      }
      const startedAt = Date.now();
      const limit = settings.mode === 'auto' ? step.timeoutMs ?? 30_000 : null;
      while (!cancelled) {
        if (checkPredicate(step.until)) {
          setSatisfied(true);
          setHint(null);
          return;
        }
        if (limit !== null && Date.now() - startedAt > limit) {
          setHint(
            step.timeoutHint ??
              'The app did not reach the expected state in time. Retry the step, or Skip it.',
          );
          return;
        }
        await sleep(300);
      }
    };
    void run();

    return () => {
      cancelled = true;
    };
  }, [advance, attempt, index, perform, phase, settings, step, toast]);

  // Autopilot reading time: stay on the step for `autoDwellMs` with a visible countdown, so the
  // reader can finish the copy before it moves on. Pause freezes it; Next now skips the wait.
  useEffect(() => {
    if (phase !== 'running' || settings.mode !== 'auto' || !satisfied || missing) {
      setCountdown(null);
      setCountdownPct(null);
      return;
    }
    let remaining = autoDwellMs;
    setCountdown(Math.max(1, Math.ceil(remaining / 1000)));
    setCountdownPct(100);
    const timer = window.setInterval(() => {
      if (pausedRef.current) return;
      remaining = Math.max(0, remaining - 250);
      setCountdown(Math.max(0, Math.ceil(remaining / 1000)));
      setCountdownPct(Math.max(0, Math.round((remaining / autoDwellMs) * 100)));
      if (remaining <= 0) {
        window.clearInterval(timer);
        advance();
      }
    }, 250);
    return () => window.clearInterval(timer);
  }, [advance, autoDwellMs, missing, phase, satisfied, settings.mode, step]);

  // Keep the spotlight on the target while the layout settles (async panels, scroll).
  useEffect(() => {
    if (phase !== 'running' || !step?.target) return;
    const selector = step.target;
    const timer = window.setInterval(() => {
      const element = elementFor(selector);
      if (element) setRect(boxOf(element));
    }, 400);
    return () => window.clearInterval(timer);
  }, [phase, step]);

  useEffect(() => {
    if (phase !== 'running') return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        stop();
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        advance();
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault();
        back();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [advance, back, phase, stop]);

  const contextValue = useMemo<TourContextValue>(
    () => ({ openLauncher, openPresenter, registerEditor, isRunning: phase === 'running' }),
    [openLauncher, openPresenter, phase, registerEditor],
  );

  const canNext = Boolean(!step?.until || satisfied) && !missing;
  const tipStyle = tooltipStyle(rect, step?.placement);

  const overlay =
    phase === 'running' && step
      ? createPortal(
          <div className="tour-layer" data-testid="tour-layer">
            {rect ? (
              <>
                <div className="tour-mask" style={{ left: 0, top: 0, right: 0, height: rect.y }} />
                <div
                  className="tour-mask"
                  style={{ left: 0, top: rect.y + rect.height, right: 0, bottom: 0 }}
                />
                <div
                  className="tour-mask"
                  style={{ left: 0, top: rect.y, width: rect.x, height: rect.height }}
                />
                <div
                  className="tour-mask"
                  style={{
                    left: rect.x + rect.width,
                    top: rect.y,
                    right: 0,
                    height: rect.height,
                  }}
                />
                <div
                  className="tour-ring"
                  style={{ left: rect.x, top: rect.y, width: rect.width, height: rect.height }}
                />
              </>
            ) : (
              <div className="tour-mask" style={{ inset: 0 }} />
            )}

            {cursor ? (
              <div
                className="tour-cursor"
                data-testid="tour-cursor"
                style={{ left: cursor.x, top: cursor.y }}
                aria-hidden="true"
              >
                <svg width="22" height="26" viewBox="0 0 22 26">
                  <path
                    d="M2 2 L20 13 L11 14 L8 24 Z"
                    fill="#ffffff"
                    stroke="#1f4e79"
                    strokeWidth="2"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>
            ) : null}

            <div
              className="tour-tip"
              role="dialog"
              aria-modal="false"
              aria-labelledby="tour-step-title"
              aria-describedby="tour-step-body"
              style={tipStyle}
              data-testid="tour-tooltip"
            >
              <div className="tour-tip-head">
                <span className="tiny muted">
                  Step {index + 1} / {active.steps.length}
                </span>
                <button type="button" onClick={stop} aria-label="Stop tour">
                  ×
                </button>
              </div>
              <div className="tour-progress" data-testid="tour-progress" aria-hidden="true">
                <span style={{ width: `${((index + 1) / active.steps.length) * 100}%` }} />
              </div>
              <h3 id="tour-step-title">{step.title}</h3>
              <p id="tour-step-body" className="tiny">
                {step.body}
              </p>
              {settings.mode === 'auto' && satisfied && !missing ? (
                <div
                  className="tour-countdown"
                  data-testid="tour-countdown"
                  data-paused={paused ? 'yes' : 'no'}
                >
                  <div
                    className="tour-countdown-bar"
                    role="progressbar"
                    aria-label="Autopilot reading time"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={countdownPct ?? 0}
                    data-testid="tour-countdown-bar"
                  >
                    <span style={{ width: `${countdownPct ?? 0}%` }} />
                  </div>
                  <p className="tiny muted" aria-hidden="true">
                    {paused
                      ? 'Paused — press Resume to continue.'
                      : `Auto-advance in ${countdown ?? 0}s · press "Next now" to move on.`}
                  </p>
                </div>
              ) : null}
              {hint ? (
                <p className="notice notice--warn tiny" data-testid="tour-hint">
                  {hint}
                </p>
              ) : null}
              {missing ? (
                <p className="notice notice--bad tiny" data-testid="tour-missing">
                  I could not find the target for this step. Retry, or Skip it.
                </p>
              ) : null}
              {!satisfied && !missing && !hint ? (
                <AiWaitBox
                  variant="inline"
                  testId="tour-waiting"
                  title={
                    settings.mode === 'auto'
                      ? 'Waiting for the app to reach this step’s state'
                      : 'Next unlocks when this step’s state is reached — or press Skip'
                  }
                  elapsedMs={waitingElapsed}
                />
              ) : null}
              <div className="row tour-tip-actions">
                <button type="button" onClick={back} disabled={index === 0}>
                  Back
                </button>
                <button
                  type="button"
                  className="primary"
                  onClick={advance}
                  disabled={!canNext}
                  data-testid="tour-next"
                >
                  {step.nextLabel ?? (settings.mode === 'auto' ? 'Next now' : 'Next')}
                </button>
                {settings.mode === 'auto' ? (
                  <button type="button" onClick={togglePause}>
                    {paused ? 'Resume' : 'Pause'}
                  </button>
                ) : null}
                {missing ? (
                  <button type="button" onClick={retry}>
                    Retry
                  </button>
                ) : null}
                <button type="button" onClick={skip} data-testid="tour-skip">
                  Skip
                </button>
                <button type="button" onClick={stop}>
                  Stop
                </button>
              </div>
            </div>
            <div className="visually-hidden" aria-live="polite">
              Step {index + 1}: {step.title}. {step.body}
            </div>
          </div>,
          document.body,
        )
      : null;
const launcher =
    phase === 'launcher'
      ? createPortal(
          <div className="tour-modal-backdrop" data-testid="tour-launcher">
            <div
              className="tour-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="tour-modal-title"
            >
              <h3 id="tour-modal-title">{active.title}</h3>
              <p className="tiny muted">{active.description}</p>
              {active.requiresRole ? (
                <p className="tour-requirement" data-testid="tour-requirement">
                  <span className="tag tag--warn">{active.requiresRole} only</span>
                  <span className="tiny muted">
                    Sign in as {active.requiresRole}; other roles skip with a note.
                  </span>
                </p>
              ) : null}
              {catalog.length > 1 ? (
                <label className="tiny muted" htmlFor="tour-picker">
                  Tour
                </label>
              ) : null}
              {catalog.length > 1 ? (
                <select
                  id="tour-picker"
                  aria-label="Tour"
                  value={active.id}
                  onChange={(event) => {
                    setTourId(event.target.value);
                    setIndex(0);
                    setSatisfied(false);
                    setMissing(false);
                    setHint(null);
                  }}
                >
                  {catalog.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title}
                      {completedIds.includes(item.id) ? ' ✓' : ''}
                    </option>
                  ))}
                </select>
              ) : null}
              {catalog.length > 1 && lifecycleTotal > 0 ? (
                <p className="tiny muted" data-testid="lifecycle-progress">
                  Lifecycle: {lifecycleDone}/{lifecycleTotal} parts complete · run applicant → Bank
                  Ops → Compliance, each in its own window.
                </p>
              ) : null}
              <div className="tour-options">
                <fieldset className="tour-mode-cards">
                  <legend className="tiny muted">Mode</legend>
                  <label className="tour-mode-card" data-selected={mode === 'guide'}>
                    <input
                      type="radio"
                      name="tour-mode"
                      checked={mode === 'guide'}
                      onChange={() => setMode('guide')}
                      data-testid="tour-mode-guide"
                    />
                    <span className="tour-mode-icon" aria-hidden="true">
                      ▷
                    </span>
                    <span className="tour-mode-copy">
                      <strong>Guide me</strong>
                      <small>You click; Next unlocks when the step’s state is reached.</small>
                    </span>
                  </label>
                  <label className="tour-mode-card" data-selected={mode === 'auto'}>
                    <input
                      type="radio"
                      name="tour-mode"
                      checked={mode === 'auto'}
                      onChange={() => setMode('auto')}
                      data-testid="tour-mode-auto"
                    />
                    <span className="tour-mode-icon" aria-hidden="true">
                      ◉
                    </span>
                    <span className="tour-mode-copy">
                      <strong>
                        Watch me <span className="tag tag--ok">Recommended</span>
                      </strong>
                      <small>
                        Autopilot clicks and types; {Math.round(autoDwellMs / 1000)}s reading time per
                        step.
                      </small>
                    </span>
                  </label>
                </fieldset>

                <fieldset className="tour-mode-cards tour-mode-cards--submission">
                  <legend className="tiny muted">Submission step</legend>
                  <label className="tour-mode-card" data-selected={approvals === 'manual'}>
                    <input
                      type="radio"
                      name="tour-approvals"
                      checked={approvals === 'manual'}
                      onChange={() => setApprovals('manual')}
                      data-testid="tour-approvals-manual"
                    />
                    <span className="tour-mode-icon" aria-hidden="true">
                      ↪
                    </span>
                    <span className="tour-mode-copy">
                      <strong>Hand off to me</strong>
                      <small>You click Submit; the tour continues after.</small>
                    </span>
                  </label>
                  <label className="tour-mode-card" data-selected={approvals === 'auto'}>
                    <input
                      type="radio"
                      name="tour-approvals"
                      checked={approvals === 'auto'}
                      onChange={() => setApprovals('auto')}
                      data-testid="tour-approvals-auto"
                    />
                    <span className="tour-mode-icon" aria-hidden="true">
                      ✓
                    </span>
                    <span className="tour-mode-copy">
                      <strong>Let the tour submit</strong>
                      <small>Demo only: it confirms the dialog; the draft becomes read-only.</small>
                    </span>
                  </label>
                </fieldset>
              </div>
              <p className="tiny muted">
                Approvals by Bank Ops and Compliance still need their own windows; the tour hands
                off there. Reset the demo document before the next full run.
              </p>
              {completed ? <p className="tiny">You have completed this tour before.</p> : null}
              <div className="tour-modal-actions">
                <span className="tiny muted" data-testid="tour-summary">
                  Mode: {mode === 'auto' ? 'Watch me' : 'Guide me'} · Submission:{' '}
                  {approvals === 'auto' ? 'the tour submits' : 'hand off to me'}
                </span>
                <div className="row tour-tip-actions">
                  <button type="button" className="primary" onClick={start} data-testid="tour-start">
                    Start tour
                  </button>
                  <button type="button" onClick={openPresenter} data-testid="tour-presenter">
                    Presenter script
                  </button>
                  <button type="button" onClick={() => setPhase('idle')}>
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <TourContext.Provider value={contextValue}>
      {children}
      {launcher}
      {overlay}
      <PresenterPanel open={phase === 'presenter'} onClose={() => setPhase('idle')} />
    </TourContext.Provider>
  );
}

export function useTour(): TourContextValue {
  const value = useContext(TourContext);
  if (value === null) {
    throw new Error('useTour must be used inside <TourProvider>');
  }
  return value;
}