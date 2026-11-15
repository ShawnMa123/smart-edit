/** OpenAPI field mapping and JSON assembly (tasks 10.3/10.4). */

import { describe, expect, it } from 'vitest';

import { buildOpenApiPayload, suggestMappings } from './openapiPayload';
import type { ContractField } from './openapi';

const field = (over: Partial<ContractField> & Pick<ContractField, 'path' | 'type'>): ContractField => ({
  required: false,
  ...over,
});

const variables = [
  { variableId: 'v_amount', label: 'Amount', displayValue: '500000' },
  { variableId: 'v_type', label: 'application type', displayValue: 'guarantee' },
  { variableId: 'v_name', label: 'Beneficiary Name', displayValue: 'ACME' },
  { variableId: 'v_flag', label: 'Flag', displayValue: 'true' },
];

describe('suggestMappings', () => {
  it('matches normalised labels to the last path segment or the full path', () => {
    const mappings = suggestMappings(
      [
        field({ path: 'amount', type: 'number' }),
        field({ path: 'application_type', type: 'string' }),
        field({ path: 'beneficiary.name', type: 'string' }),
        field({ path: 'flag', type: 'boolean' }),
      ],
      variables,
    );

    expect(mappings).toEqual({
      amount: 'v_amount',
      application_type: 'v_type',
      'beneficiary.name': 'v_name',
      flag: 'v_flag',
    });
  });

  it('never suggests unsupported fields', () => {
    const mappings = suggestMappings(
      [field({ path: 'references', type: 'array', unsupported: 'no' })],
      variables,
    );
    expect(mappings).toEqual({});
  });
});

describe('buildOpenApiPayload', () => {
  const fields = [
    field({ path: 'amount', type: 'number', required: true }),
    field({ path: 'expiry_date', type: 'string' }),
    field({
      path: 'application_type',
      type: 'string',
      required: true,
      enumValues: ['guarantee', 'standby_dc'],
    }),
    field({ path: 'beneficiary.name', type: 'string', required: true }),
    field({ path: 'flag', type: 'boolean' }),
  ];

  it('assembles nested typed JSON when every required field is satisfied', () => {
    const result = buildOpenApiPayload(
      fields,
      {
        amount: 'v_amount',
        application_type: 'v_type',
        'beneficiary.name': 'v_name',
        flag: 'v_flag',
      },
      variables,
    );

    expect(result.ready).toBe(true);
    expect(result.payload).toEqual({
      amount: 500000,
      application_type: 'guarantee',
      beneficiary: { name: 'ACME' },
      flag: true,
    });
    expect(result.missing).toEqual([]);
    expect(result.invalid).toEqual([]);
  });

  it('names required fields with no mapping or empty values', () => {
    const result = buildOpenApiPayload(
      fields,
      { application_type: 'v_type' },
      [
        variables[0],
        variables[1],
        { variableId: 'v_empty', label: 'Name', displayValue: null },
      ],
    );

    expect(result.ready).toBe(false);
    expect(result.missing).toEqual(['amount', 'beneficiary.name']);
    expect(result.issues[0]?.message).toContain('Required field');
  });

  it('rejects enum, number and boolean mismatches instead of coercing', () => {
    const result = buildOpenApiPayload(
      [
        field({ path: 'amount', type: 'number', required: true }),
        field({
          path: 'application_type',
          type: 'string',
          required: true,
          enumValues: ['guarantee', 'standby_dc'],
        }),
        field({ path: 'beneficiary.name', type: 'string', required: true }),
        field({ path: 'flag', type: 'boolean' }),
      ],
      {
        amount: 'v_amount',
        application_type: 'v_type',
        'beneficiary.name': 'v_name',
        flag: 'v_flag',
      },
      [
        { variableId: 'v_amount', label: 'Amount', displayValue: 'not-a-number' },
        { variableId: 'v_type', label: 'Type', displayValue: 'invented' },
        { variableId: 'v_name', label: 'Name', displayValue: 'ACME' },
        { variableId: 'v_flag', label: 'Flag', displayValue: 'maybe' },
      ],
    );

    expect(result.ready).toBe(false);
    expect(result.invalid).toEqual(['amount', 'application_type', 'flag']);
    expect(result.payload).toEqual({ beneficiary: { name: 'ACME' } });
  });

  it('blocks a required unsupported field but ignores an optional one', () => {
    const required = buildOpenApiPayload(
      [field({ path: 'references', type: 'array', required: true, unsupported: 'arrays' })],
      {},
      variables,
    );
    expect(required.ready).toBe(false);
    expect(required.issues[0]).toMatchObject({ path: 'references', reason: 'unsupported' });

    const optional = buildOpenApiPayload(
      [field({ path: 'references', type: 'array', unsupported: 'arrays' })],
      {},
      variables,
    );
    expect(optional.ready).toBe(true);
    expect(optional.payload).toEqual({});
  });

  it('omits optional empty fields', () => {
    const result = buildOpenApiPayload(
      [field({ path: 'note', type: 'string' })],
      { note: 'v_empty' },
      [{ variableId: 'v_empty', label: 'Note', displayValue: '' }],
    );
    expect(result.ready).toBe(true);
    expect(result.payload).toEqual({});
  });
});