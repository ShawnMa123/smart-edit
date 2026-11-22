/**
 * Guided product tour: data model.
 *
 * A tour is data, not code: each step names a real target (`data-tour`), an optional action the
 * autopilot performs on the real control, and an optional state predicate that must become true
 * before "Next" unlocks. Nothing here bypasses the app's own handlers: a click is a real click and
 * typing goes through the editor's own command chain, so saves/audits happen for real.
 */

export type TourMode = 'guide' | 'auto';
export type ApprovalMode = 'manual' | 'auto';

export interface TourSettings {
  mode: TourMode;
  approvals: ApprovalMode;
}

export type WaitPredicate =
  | { kind: 'selector'; selector: string }
  | { kind: 'text'; selector: string; includes: string }
  /** The selector is not in the DOM (for example a tab hidden by RBAC). */
  | { kind: 'absent'; selector: string }
  /** The editor status chip reads `Saved to server`. */
  | { kind: 'saveState' }
  /** The template-audit report block is on screen. */
  | { kind: 'conformanceReport' };

export type TourAction =
  | { kind: 'click'; selector: string }
  /** Ensure a `<details>` disclosure is open (idempotent: an open one stays open). */
  | { kind: 'open'; selector: string }
  | { kind: 'select'; selector: string; value: string }
  /** Replace the document with a block of text (a paste-like insertion). */
  | { kind: 'paste'; text: string }
  /** Type character-by-character through the editor bridge (or a DOM fallback). */
  | { kind: 'type'; text: string; cps?: number }
  | { kind: 'manual'; instruction: string };

export interface TourStep {
  id: string;
  title: string;
  body: string;
  /** `[data-tour="..."]` selector to spotlight; omitted for a centered message. */
  target?: string;
  placement?: 'top' | 'bottom' | 'left' | 'right' | 'center';
  action?: TourAction;
  /** Next stays disabled (Autopilot waits) until this is true. */
  until?: WaitPredicate;
  /** Autopilot timeout for `until`; guide mode never times out (it hints instead). */
  timeoutMs?: number;
  /** Step-specific hint shown when `until` times out (defaults to a generic message). */
  timeoutHint?: string;
  /** How long to look for `target` before failing/skipping (default 1s; lists may need more). */
  targetTimeoutMs?: number;
  /** A missing target skips the step instead of failing. */
  optional?: boolean;
  /**
   * Skip the step when any predicate is already true (for example the draft is already submitted).
   * The runner advances without performing the action and shows `skipNote` once.
   */
  skipIf?: WaitPredicate[];
  skipNote?: string;
  /**
   * Autopilot must not perform this action unless the operator chose "let the tour submit".
   * Guide mode ignores it (the operator performs the action).
   */
  requiresApprovalAuto?: boolean;
  nextLabel?: string;
}

export interface Tour {
  id: string;
  version: number;
  title: string;
  description: string;
  steps: TourStep[];
}

/** The editor surface exposed to the tour; deliberately tiny so a tour cannot bypass app logic. */
export interface TourEditorApi {
  clear(): void;
  focus(): void;
  insertText(text: string): void;
}

export interface TourContextValue {
  /** Opens the launcher; an id preselects a tour (also used by `?tour=<id>`). */
  openLauncher(tourId?: string): void;
  /** Opens the presenter teleprompter (read-only script + timer). */
  openPresenter(): void;
  registerEditor(api: TourEditorApi | null): void;
  isRunning: boolean;
}