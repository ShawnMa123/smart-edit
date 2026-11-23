/** Custom-field textarea → request fields (for downstreams without an OpenAPI document). */

import { describe, expect, it } from 'vitest';

import { parseFieldLines } from './fieldSpec';

describe('parseFieldLines', () => {
  it('reads path, type and the required marker', () => {
    const parsed = parseFieldLines(
      ['# partner contract', 'amount: number *', 'beneficiary.name: string*', 'note'].join('\n'),
    );

    expect(parsed.errors).toEqual([]);
    expect(parsed.fields).toEqual([
      { path: 'amount', type: 'number', required: true },
      { path: 'beneficiary.name', type: 'string', required: true },
      { path: 'note', type: 'string', required: false },
    ]);
  });

  it('reports bad names, duplicates and unknown types with line numbers', () => {
    const parsed = parseFieldLines(['1bad: string', 'amount: string', 'amount: number', 'x: list'].join('\n'));

    expect(parsed.fields).toEqual([{ path: 'amount', type: 'string', required: false }]);
    expect(parsed.errors).toEqual([
      'line 1: “1bad” is not a dotted field name',
      'line 3: “amount” is declared twice',
      'line 4: “list” is not one of string / number / integer / boolean',
    ]);
  });

  it('asks for at least one field when the box is empty', () => {
    expect(parseFieldLines('   \n').errors).toEqual(['add at least one field']);
  });
});