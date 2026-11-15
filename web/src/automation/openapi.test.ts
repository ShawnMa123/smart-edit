/** OpenAPI 3.x JSON subset: operations, local refs, flattening and honest failures (task 10.1). */

import { describe, expect, it } from 'vitest';

import fixture from '../../../fixtures/automation/openapi_sample.json';
import { parseOpenApi, type ContractOperation } from './openapi';

const parsed = () => {
  const result = parseOpenApi(JSON.stringify(fixture));
  if (!result.ok) throw new Error(result.error);
  return result.contract;
};

const operation = (contract: ReturnType<typeof parsed>, operationId: string): ContractOperation => {
  const found = contract.operations.find((item) => item.operationId === operationId);
  if (!found) throw new Error(`missing ${operationId}`);
  return found;
};

describe('parseOpenApi', () => {
  it('reads the title/version and lists operations with availability', () => {
    const contract = parsed();

    expect(contract.title).toBe('Trade Intake API');
    expect(contract.version).toBe('1.4.0');
    expect(contract.operations).toHaveLength(4);
    expect(operation(contract, 'createTradeApplication')).toMatchObject({
      method: 'POST',
      path: '/trade/applications',
      available: true,
    });
    expect(operation(contract, 'getTradeApplication').available).toBe(false);
    expect(operation(contract, 'createWithoutJsonBody').available).toBe(false);
    expect(operation(contract, 'createWithoutJsonBody').warnings).toContain(
      'No application/json request body.',
    );
  });

  it('resolves local refs and flattens object properties into dotted paths', () => {
    const create = operation(parsed(), 'createTradeApplication');
    const byPath = new Map(create.fields.map((field) => [field.path, field]));

    expect(byPath.get('application_type')).toMatchObject({
      type: 'string',
      required: true,
      enumValues: ['guarantee', 'standby_dc'],
    });
    expect(byPath.get('amount')).toMatchObject({ type: 'number', required: true });
    expect(byPath.get('expiry_date')).toMatchObject({ type: 'string', required: false });
    expect(byPath.get('beneficiary.name')).toMatchObject({ type: 'string', required: true });
    expect(byPath.get('beneficiary.country')).toMatchObject({
      enumValues: ['CN', 'SG'],
      required: false,
    });
  });

  it('reports unsupported constructs instead of inventing fields', () => {
    const create = operation(parsed(), 'createTradeApplication');

    expect(create.fields.find((field) => field.path === 'references')).toMatchObject({
      type: 'array',
      unsupported: 'Array fields are not supported for variable mapping.',
    });
    expect(create.warnings.some((warning) => warning.includes('circular schema reference'))).toBe(
      true,
    );
    expect(create.fields.some((field) => field.path === 'structured')).toBe(false);
  });

  it('rejects Swagger 2.0, YAML and malformed JSON with readable errors', () => {
    expect(parseOpenApi('{"swagger":"2.0","paths":{}}')).toEqual({
      ok: false,
      error: 'Swagger 2.0 is not supported. Provide an OpenAPI 3.x JSON document.',
    });
    expect(parseOpenApi('openapi: 3.0.0\npaths: {}').ok).toBe(false);
    const yaml = parseOpenApi('openapi: 3.0.0\npaths: {}');
    expect(yaml.ok ? '' : yaml.error).toContain('YAML is not supported');
    expect(parseOpenApi('{oops').ok).toBe(false);
    expect(parseOpenApi('').ok).toBe(false);
  });

  it('reports external refs and oneOf/allOf as unsupported', () => {
    const external = parseOpenApi(
      JSON.stringify({
        openapi: '3.0.0',
        info: { title: 'X', version: '1' },
        paths: {
          '/x': {
            post: {
              requestBody: {
                content: {
                  'application/json': {
                    schema: { $ref: 'https://example.com/schema.json' },
                  },
                },
              },
            },
          },
        },
      }),
    );
    expect(external.ok).toBe(true);
    if (!external.ok) return;
    expect(external.contract.operations[0].warnings.join(' ')).toContain('external $ref');

    const composed = parseOpenApi(
      JSON.stringify({
        openapi: '3.0.0',
        paths: {
          '/x': {
            post: {
              requestBody: {
                content: {
                  'application/json': {
                    schema: {
                      type: 'object',
                      properties: { choice: { oneOf: [{ type: 'string' }] } },
                    },
                  },
                },
              },
            },
          },
        },
      }),
    );
    expect(composed.ok).toBe(true);
    if (!composed.ok) return;
    expect(composed.contract.operations[0].fields[0]).toMatchObject({
      path: 'choice',
      unsupported: 'oneOf/anyOf is not supported.',
    });
  });

  it('marks a spec without paths or with an untitled info as an error/fallback', () => {
    expect(parseOpenApi('{"openapi":"3.0.0"}').ok).toBe(false);
    const contract = parseOpenApi('{"openapi":"3.0.0","paths":{}}');
    expect(contract.ok).toBe(true);
    if (!contract.ok) return;
    expect(contract.contract.title).toBe('Untitled API');
    expect(contract.contract.operations).toEqual([]);
  });
});