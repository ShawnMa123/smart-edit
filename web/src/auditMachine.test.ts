/** Task 3.3 — audit state machine and staleness derivation. */

import { describe, expect, it } from 'vitest';

import { auditReducer, elapsedMs, initialAuditState, isStale } from './auditMachine';
import type { Snapshot } from './snapshot';
import { doneEnvelope } from './test/fixtures';

const snapshot = (digest: string): Snapshot => ({
  text: 'document text',
  digest,
  versionId: null,
  capturedAt: '2026-11-08T09:00:00.000Z',
});

describe('auditReducer', () => {
  it('starts running with the frozen snapshot', () => {
    const state = auditReducer(initialAuditState, { type: 'start', snapshot: snapshot('aaa'), at: 1000 });

    expect(state.phase).toBe('running');
    if (state.phase === 'running') {
      expect(state.snapshot.digest).toBe('aaa');
      expect(state.startedAt).toBe(1000);
    }
  });

  it('binds a report to the snapshot that was audited', () => {
    const running = auditReducer(initialAuditState, {
      type: 'start',
      snapshot: snapshot('aaa'),
      at: 1000,
    });
    const report = auditReducer(running, {
      type: 'succeed',
      envelope: doneEnvelope(),
      at: 4000,
    });

    expect(report.phase).toBe('report');
    if (report.phase === 'report') {
      expect(report.snapshot.digest).toBe('aaa');
      expect(report.completedAt).toBe(4000);
    }
  });

  it('records a failure with elapsed time and keeps the snapshot', () => {
    const running = auditReducer(initialAuditState, {
      type: 'start',
      snapshot: snapshot('aaa'),
      at: 1000,
    });
    const failed = auditReducer(running, {
      type: 'fail',
      failure: { code: 'REFUSED', message: 'refused' },
      at: 2500,
    });

    expect(failed.phase).toBe('failed');
    if (failed.phase === 'failed') {
      expect(failed.elapsedMs).toBe(1500);
      expect(failed.failure.code).toBe('REFUSED');
      expect(failed.snapshot.digest).toBe('aaa');
    }
  });

  it('ignores success or failure events when nothing is running', () => {
    expect(auditReducer(initialAuditState, { type: 'succeed', envelope: doneEnvelope(), at: 1 })).toBe(
      initialAuditState,
    );
    expect(
      auditReducer(initialAuditState, { type: 'fail', failure: { code: 'X', message: 'x' }, at: 1 }),
    ).toBe(initialAuditState);
  });

  it('resets to idle', () => {
    const running = auditReducer(initialAuditState, { type: 'start', snapshot: snapshot('aaa'), at: 1 });
    expect(auditReducer(running, { type: 'reset' })).toEqual(initialAuditState);
  });
});

describe('isStale', () => {
  const reportState = auditReducer(
    auditReducer(initialAuditState, { type: 'start', snapshot: snapshot('aaa'), at: 1 }),
    { type: 'succeed', envelope: doneEnvelope(), at: 2 },
  );

  it('is false while the document still matches the audited snapshot', () => {
    expect(isStale(reportState, 'aaa')).toBe(false);
  });

  it('turns true as soon as the document changes', () => {
    expect(isStale(reportState, 'bbb')).toBe(true);
  });

  it('keeps the previous report readable but stale after edits during a run', () => {
    // "edited while running": the audit started on aaa, the editor meanwhile holds bbb.
    const running = auditReducer(initialAuditState, { type: 'start', snapshot: snapshot('aaa'), at: 1 });
    const finished = auditReducer(running, { type: 'succeed', envelope: doneEnvelope(), at: 2 });

    expect(isStale(finished, 'bbb')).toBe(true);
    if (finished.phase === 'report') {
      expect(finished.envelope).toEqual(doneEnvelope());
    }
  });

  it('is false when there is no report', () => {
    expect(isStale(initialAuditState, 'bbb')).toBe(false);
  });
});

describe('elapsedMs', () => {
  it('counts only while running', () => {
    const running = auditReducer(initialAuditState, { type: 'start', snapshot: snapshot('aaa'), at: 1000 });
    expect(elapsedMs(running, 3500)).toBe(2500);
    expect(elapsedMs(initialAuditState, 3500)).toBe(0);
  });
});