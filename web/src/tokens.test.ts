/** Task 2.3 — status tokens always carry a word, never colour alone. */

import { describe, expect, it } from 'vitest';

import {
  ALL_STATUS_LABELS,
  FIELD_STATUS,
  SEVERITY,
  STAGE_STATUS,
  fieldStatusToken,
  severityToken,
  stageStatusToken,
} from './tokens';

describe('status tokens', () => {
  it('gives every status a non-empty text label and a colour class', () => {
    const tokens = [...Object.values(FIELD_STATUS), ...Object.values(STAGE_STATUS), ...Object.values(SEVERITY)];

    for (const token of tokens) {
      expect(token.label.trim().length).toBeGreaterThan(0);
      expect(token.className.startsWith('status status--')).toBe(true);
    }
  });

  it('covers the contract status values', () => {
    expect(Object.keys(FIELD_STATUS)).toEqual(
      expect.arrayContaining(['extracted', 'inferred', 'missing']),
    );
    expect(Object.keys(STAGE_STATUS)).toEqual(
      expect.arrayContaining(['done', 'skipped', 'partial', 'failed']),
    );
    expect(Object.keys(SEVERITY)).toEqual(expect.arrayContaining(['critical', 'warn', 'info']));
  });

  it('never coerces an unknown value into a known one', () => {
    expect(fieldStatusToken('bogus').label).toBe('Unknown status');
    expect(stageStatusToken('bogus').label).toBe('Unknown status');
    expect(severityToken('bogus').label).toBe('Unknown severity');
  });

  it('exposes a label list with no empty entries', () => {
    expect(ALL_STATUS_LABELS.length).toBeGreaterThan(6);
    expect(ALL_STATUS_LABELS.every((label) => label.trim().length > 0)).toBe(true);
  });
});