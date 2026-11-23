import { describe, expect, it } from 'vitest';

import { MAX_ACTIVITY, createActivityStore, memoryStorage } from './activityStore';

const DOC = 'doc-1';

const store = () => createActivityStore(memoryStorage());

describe('browser-local activity store', () => {
  it('records newest first with the real event fields', () => {
    const activity = store();
    const at = new Date('2026-11-17T09:00:00Z');

    const entry = activity.record(
      DOC,
      { kind: 'capture', action: 'Version captured', detail: 'Version 2 captured', notifiable: true },
      at,
    );
    activity.record(
      DOC,
      { kind: 'save', action: 'Draft saved', detail: 'Draft revision 4 saved', notifiable: false },
      new Date('2026-11-17T09:01:00Z'),
    );

    expect(entry.at).toBe('2026-11-17T09:00:00.000Z');
    expect(entry.read).toBe(false);
    expect(activity.list(DOC).map((item) => item.action)).toEqual(['Draft saved', 'Version captured']);
  });

  it('caps the log and evicts the oldest entry', () => {
    const activity = store();
    for (let index = 1; index <= MAX_ACTIVITY + 2; index += 1) {
      activity.record(
        DOC,
        { kind: 'save', action: `Event ${index}`, detail: '', notifiable: false },
        new Date(2026, 0, index),
      );
    }

    const entries = activity.list(DOC);
    expect(entries).toHaveLength(MAX_ACTIVITY);
    expect(entries[0].action).toBe(`Event ${MAX_ACTIVITY + 2}`);
    expect(entries.some((entry) => entry.action === 'Event 1')).toBe(false);
  });

  it('marks all entries read without changing their content', () => {
    const activity = store();
    activity.record(DOC, { kind: 'audit', action: 'Audit completed', detail: '0 findings', notifiable: true });
    activity.record(DOC, { kind: 'import', action: 'Import complete', detail: '1 file', notifiable: true });

    activity.markAllRead(DOC);

    const entries = activity.list(DOC);
    expect(entries.every((entry) => entry.read)).toBe(true);
    expect(entries.map((entry) => entry.action)).toEqual(['Import complete', 'Audit completed']);
  });

  it('clears only the requested document', () => {
    const activity = store();
    activity.record('doc-1', { kind: 'save', action: 'One', detail: '', notifiable: false });
    activity.record('doc-2', { kind: 'save', action: 'Two', detail: '', notifiable: false });

    activity.clear('doc-1');

    expect(activity.list('doc-1')).toEqual([]);
    expect(activity.list('doc-2').map((entry) => entry.action)).toEqual(['Two']);
  });

  it('persists entries when the same storage is reused', () => {
    const storage = memoryStorage();
    const first = createActivityStore(storage);
    first.record(DOC, { kind: 'save', action: 'Saved', detail: '', notifiable: false });

    const second = createActivityStore(storage);
    expect(second.list(DOC).map((entry) => entry.action)).toEqual(['Saved']);
  });

  it('falls back to session memory when storage throws', () => {
    const broken: Storage = {
      length: 0,
      clear: () => undefined,
      getItem: () => {
        throw new Error('storage unavailable');
      },
      key: () => null,
      removeItem: () => undefined,
      setItem: () => {
        throw new Error('storage unavailable');
      },
    };
    const activity = createActivityStore(broken);

    const entry = activity.record(
      DOC,
      { kind: 'save', action: 'Session only', detail: '', notifiable: false },
    );

    expect(activity.available()).toBe(false);
    expect(activity.list(DOC).map((item) => item.id)).toEqual([entry.id]);
  });

  it('reports corrupt storage instead of throwing', () => {
    const storage = memoryStorage();
    storage.setItem('smart-edit:activity:doc-1', '{not json');
    const activity = createActivityStore(storage);

    expect(activity.list(DOC)).toEqual([]);
    expect(activity.available()).toBe(false);

    activity.record(DOC, { kind: 'save', action: 'After corruption', detail: '', notifiable: false });
    expect(activity.list(DOC).map((entry) => entry.action)).toEqual(['After corruption']);
  });

  it('keeps documents separate', () => {
    const activity = store();
    activity.record('doc-1', { kind: 'save', action: 'One', detail: '', notifiable: false });
    activity.record('doc-2', { kind: 'save', action: 'Two', detail: '', notifiable: false });

    expect(activity.list('doc-1').map((entry) => entry.action)).toEqual(['One']);
    expect(activity.list('doc-2').map((entry) => entry.action)).toEqual(['Two']);
  });
});