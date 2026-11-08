/** Task 3.1 — snapshots and their content digest. */

import { describe, expect, it } from 'vitest';

import { createSnapshot, digestText, shortDigest } from './snapshot';

describe('digestText', () => {
  it('is deterministic for identical text', async () => {
    expect(await digestText('Demand Guarantee')).toBe(await digestText('Demand Guarantee'));
  });

  it('changes when a single character changes', async () => {
    expect(await digestText('USD 500,000.00')).not.toBe(await digestText('USD 500,000.01'));
  });

  it('handles multi-byte text deterministically', async () => {
    const first = await digestText('保函金额：USD 500,000.00');
    const second = await digestText('保函金额：USD 500,000.00');

    expect(first).toBe(second);
    expect(first).toMatch(/^[0-9a-f]{64}$/);
    expect(first).not.toBe(await digestText('保函金额：USD 500,000.01'));
  });
});

describe('createSnapshot', () => {
  it('freezes the exact text with a digest, version id and capture time', async () => {
    const snapshot = await createSnapshot('line one\nline two', 'v-1', new Date('2026-11-08T10:00:00Z'));

    expect(snapshot.text).toBe('line one\nline two');
    expect(snapshot.versionId).toBe('v-1');
    expect(snapshot.capturedAt).toBe('2026-11-08T10:00:00.000Z');
    expect(snapshot.digest).toBe(await digestText('line one\nline two'));
  });

  it('uses a null version id when the text is not tied to a captured version', async () => {
    const snapshot = await createSnapshot('draft');
    expect(snapshot.versionId).toBeNull();
  });

  it('shortens a digest for display without losing the full value', () => {
    const full = 'a'.repeat(64);
    expect(shortDigest(full)).toHaveLength(12);
    expect(full.startsWith(shortDigest(full))).toBe(true);
  });
});