/**
 * Audit state machine (design D5).
 *
 * Four phases make impossible states unrepresentable, and `isStale` derives "the document no longer
 * matches this report" from the snapshot the report is bound to — never from the current text.
 */

import type { RunEnvelope } from './api/types';
import type { Snapshot } from './snapshot';

export interface AuditFailure {
  code: string;
  message: string;
  detail?: unknown;
}

export type AuditState =
  | { phase: 'idle' }
  | { phase: 'running'; snapshot: Snapshot; startedAt: number }
  | { phase: 'failed'; failure: AuditFailure; elapsedMs: number; snapshot: Snapshot }
  | { phase: 'report'; envelope: RunEnvelope; snapshot: Snapshot; completedAt: number };

export type AuditEvent =
  | { type: 'start'; snapshot: Snapshot; at: number }
  | { type: 'succeed'; envelope: RunEnvelope; at: number }
  /** Gate/disposition refreshed the run without re-auditing; the bound snapshot stays the same. */
  | { type: 'refresh'; envelope: RunEnvelope; at: number }
  | { type: 'fail'; failure: AuditFailure; at: number }
  | { type: 'reset' };

export const initialAuditState: AuditState = { phase: 'idle' };

export function auditReducer(state: AuditState, event: AuditEvent): AuditState {
  switch (event.type) {
    case 'start':
      return { phase: 'running', snapshot: event.snapshot, startedAt: event.at };
    case 'succeed':
      // Keeping the snapshot (not the current text) is what makes the report staleness-checkable.
      if (state.phase !== 'running') return state;
      return { phase: 'report', envelope: event.envelope, snapshot: state.snapshot, completedAt: event.at };
    case 'refresh':
      // Only a rendered report can be refreshed: its snapshot and completion time already exist.
      if (state.phase !== 'report') return state;
      return { ...state, envelope: event.envelope };
    case 'fail':
      if (state.phase !== 'running') return state;
      return {
        phase: 'failed',
        failure: event.failure,
        elapsedMs: Math.max(0, event.at - state.startedAt),
        snapshot: state.snapshot,
      };
    case 'reset':
      return initialAuditState;
    default:
      return state;
  }
}

/** True when a rendered report no longer matches the current document text. */
export function isStale(state: AuditState, currentDigest: string | null): boolean {
  if (state.phase !== 'report') return false;
  return currentDigest !== null && state.snapshot.digest !== currentDigest;
}

/** Milliseconds since the in-flight audit started, for the elapsed timer. */
export function elapsedMs(state: AuditState, now: number): number {
  return state.phase === 'running' ? Math.max(0, now - state.startedAt) : 0;
}