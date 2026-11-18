export type DiffKind = 'same' | 'added' | 'removed' | 'changed';

export interface DiffRow {
  kind: DiffKind;
  before?: string;
  after?: string;
}

type Op = { kind: 'same' | 'added' | 'removed'; text: string };

/** The projection joins blocks with one blank line; compare the same block boundaries. */
export function splitBlocks(text: string): string[] {
  return text ? text.split(/\n{2,}/) : [];
}

function lcsOps(before: string[], after: string[]): Op[] {
  const rows = before.length;
  const cols = after.length;
  const table: number[][] = Array.from({ length: rows + 1 }, () =>
    Array.from({ length: cols + 1 }, () => 0),
  );

  for (let i = 1; i <= rows; i += 1) {
    for (let j = 1; j <= cols; j += 1) {
      table[i][j] =
        before[i - 1] === after[j - 1]
          ? table[i - 1][j - 1] + 1
          : Math.max(table[i - 1][j], table[i][j - 1]);
    }
  }

  const reversed: Op[] = [];
  let i = rows;
  let j = cols;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && before[i - 1] === after[j - 1]) {
      reversed.push({ kind: 'same', text: before[i - 1] });
      i -= 1;
      j -= 1;
    } else if (i > 0 && (j === 0 || table[i - 1][j] >= table[i][j - 1])) {
      reversed.push({ kind: 'removed', text: before[i - 1] });
      i -= 1;
    } else {
      reversed.push({ kind: 'added', text: after[j - 1] });
      j -= 1;
    }
  }
  return reversed.reverse();
}

/** A deterministic, read-only block diff; adjacent remove/add pairs become `changed`. */
export function diffBlocks(beforeText: string, afterText: string): DiffRow[] {
  const ops = lcsOps(splitBlocks(beforeText), splitBlocks(afterText));
  const rows: DiffRow[] = [];

  for (let index = 0; index < ops.length; index += 1) {
    const op = ops[index];
    const next = ops[index + 1];
    if (op.kind === 'removed' && next?.kind === 'added') {
      rows.push({ kind: 'changed', before: op.text, after: next.text });
      index += 1;
    } else if (op.kind === 'added' && next?.kind === 'removed') {
      rows.push({ kind: 'changed', before: next.text, after: op.text });
      index += 1;
    } else if (op.kind === 'same') {
      rows.push({ kind: 'same', before: op.text, after: op.text });
    } else if (op.kind === 'removed') {
      rows.push({ kind: 'removed', before: op.text });
    } else {
      rows.push({ kind: 'added', after: op.text });
    }
  }

  return rows;
}

export function hasTextualChanges(rows: DiffRow[]): boolean {
  return rows.some((row) => row.kind !== 'same');
}