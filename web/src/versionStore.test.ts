/** Task 3.2 — append-only, browser-local version history. */

import { describe, expect, it } from 'vitest';

import { MAX_VERSIONS, createVersionStore, memoryStorage } from './versionStore';

const DOC = 'doc-1';

const store = () => createVersionStore(memoryStorage());

describe('version history', () => {
  it('captures a version with label, digest, timestamp and size', () => {
    const history = store();
    const at = new Date('2026-11-08T09:00:00Z');

    const version = history.capture(DOC, { digest: 'abc', text: 'Demand Guarantee' }, at);

    expect(version.label).toBe('Version 1');
    expect(version.digest).toBe('abc');
    expect(version.chars).toBe('Demand Guarantee'.length);
    expect(version.createdAt).toBe('2026-11-08T09:00:00.000Z');
    expect(history.list(DOC)).toHaveLength(1);
  });

  it('lists newest first', () => {
    const history = store();
    history.capture(DOC, { digest: 'a', text: 'first' }, new Date('2026-11-08T09:00:00Z'));
    history.capture(DOC, { digest: 'b', text: 'second', label: 'Reviewed' }, new Date('2026-11-08T10:00:00Z'));

    expect(history.list(DOC).map((entry) => entry.label)).toEqual(['Reviewed', 'Version 1']);
  });

  it('restores text without mutating history', () => {
    const history = store();
    const first = history.capture(DOC, { digest: 'a', text: 'first' }, new Date('2026-11-08T09:00:00Z'));
    history.capture(DOC, { digest: 'b', text: 'second' }, new Date('2026-11-08T10:00:00Z'));
    const before = JSON.stringify(history.list(DOC));

    expect(history.restore(DOC, first.id)).toBe('first');
    expect(JSON.stringify(history.list(DOC))).toBe(before);
  });

  it('returns null for an unknown version', () => {
    const history = store();
    expect(history.restore(DOC, 'nope')).toBeNull();
    expect(history.get(DOC, 'nope')).toBeNull();
  });

  it('caps the history, evicting the oldest entry', () => {
    const history = store();
    for (let index = 1; index <= MAX_VERSIONS + 2; index += 1) {
      history.capture(DOC, { digest: `d${index}`, text: `text ${index}` }, new Date(2026, 0, index));
    }

    const entries = history.list(DOC);
    expect(entries).toHaveLength(MAX_VERSIONS);
    expect(entries[0].text).toBe(`text ${MAX_VERSIONS + 2}`);
    expect(entries.some((entry) => entry.text === 'text 1')).toBe(false);
  });

  it('clears a document history', () => {
    const history = store();
    history.capture(DOC, { digest: 'a', text: 'first' });
    history.clear(DOC);
    expect(history.list(DOC)).toEqual([]);
  });

  it('keeps documents separate', () => {
    const history = store();
    history.capture('doc-1', { digest: 'a', text: 'one' });
    history.capture('doc-2', { digest: 'b', text: 'two' });

    expect(history.list('doc-1').map((entry) => entry.text)).toEqual(['one']);
    expect(history.list('doc-2').map((entry) => entry.text)).toEqual(['two']);
  });
});
describe('spec regressions found by the audit test design', () => {
  it.fails('BUG-F4 corrupt entries in browser storage are ignored, not exposed', () => {
    const storage = memoryStorage();
    storage.setItem('smart-edit:versions:doc-1', JSON.stringify([null, { id: 7 }]));
    const history = createVersionStore(storage);

    expect(history.list(DOC)).toEqual([]);
    expect(history.get(DOC, 'anything')).toBeNull();
  });
});
