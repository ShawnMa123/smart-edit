import { describe, expect, it } from 'vitest';

import { diffBlocks, hasTextualChanges, splitBlocks } from './versionDiff';

describe('version diff', () => {
  it('splits the projection into paragraph blocks', () => {
    expect(splitBlocks('A\n\nB\n\nC')).toEqual(['A', 'B', 'C']);
    expect(splitBlocks('')).toEqual([]);
  });

  it('marks identical text as unchanged', () => {
    const rows = diffBlocks('A\n\nB', 'A\n\nB');
    expect(rows).toEqual([
      { kind: 'same', before: 'A', after: 'A' },
      { kind: 'same', before: 'B', after: 'B' },
    ]);
    expect(hasTextualChanges(rows)).toBe(false);
  });

  it('marks added and removed blocks', () => {
    expect(diffBlocks('A', 'A\n\nB')).toEqual([
      { kind: 'same', before: 'A', after: 'A' },
      { kind: 'added', after: 'B' },
    ]);
    expect(diffBlocks('A\n\nB', 'A')).toEqual([
      { kind: 'same', before: 'A', after: 'A' },
      { kind: 'removed', before: 'B' },
    ]);
  });

  it('pairs an adjacent removal and addition into a changed row', () => {
    expect(diffBlocks('A\n\nB', 'A\n\nC')).toEqual([
      { kind: 'same', before: 'A', after: 'A' },
      { kind: 'changed', before: 'B', after: 'C' },
    ]);
  });

  it('handles empty versions and reports changes', () => {
    expect(diffBlocks('', '')).toEqual([]);
    expect(diffBlocks('', 'A')).toEqual([{ kind: 'added', after: 'A' }]);
    expect(diffBlocks('A', '')).toEqual([{ kind: 'removed', before: 'A' }]);
    expect(hasTextualChanges(diffBlocks('A', 'A\n\nB'))).toBe(true);
  });
});