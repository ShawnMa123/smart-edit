/**
 * Sandbox contract helpers.
 *
 * Both parsing and body assembly live on the server (`/automation/spec/parse` and `/spec/build`), which
 * share the registry's own implementation — one set of rules for the sandbox preview and the real
 * dispatch. This module only holds the view types plus the label↔field suggestion heuristic.
 */

import { parseSpec, buildSpecBody } from '../api/automationRegistry';

export type SpecScalarType = 'string' | 'number' | 'integer' | 'boolean';

export interface ContractField {
  path: string;
  type: SpecScalarType | 'array' | 'object' | 'unknown';
  required: boolean;
  enumValues?: string[];
  description?: string;
  unsupported?: string;
}

export interface ContractOperation {
  id: string;
  method: string;
  path: string;
  operationId?: string;
  summary?: string;
  fields: ContractField[];
  warnings: string[];
  available: boolean;
}

export interface OpenApiContract {
  title: string;
  version: string;
  operations: ContractOperation[];
}

export type OpenApiParseResult =
  | { ok: true; contract: OpenApiContract }
  | { ok: false; error: string };

export interface MappingVariable {
  variableId: string;
  label: string;
  displayValue: string | null;
}

export interface PayloadIssue {
  path: string;
  reason: 'missing' | 'invalid' | 'unsupported';
  message: string;
}

export interface OpenApiPayload {
  ready: boolean;
  payload: Record<string, unknown>;
  missing: string[];
  invalid: string[];
  issues: PayloadIssue[];
}

/** Parse a JSON document on the server; YAML/Swagger errors come back as the server's message. */
export async function parseContract(text: string): Promise<OpenApiParseResult> {
  if (!text.trim()) return { ok: false, error: 'Paste an OpenAPI JSON document first.' };
  let document: Record<string, unknown>;
  try {
    document = JSON.parse(text) as Record<string, unknown>;
  } catch {
    return {
      ok: false,
      error: /^\s*openapi\s*:/m.test(text)
        ? 'YAML is not supported. Provide OpenAPI 3.x JSON.'
        : 'Invalid JSON. Provide an OpenAPI 3.x JSON document.',
    };
  }
  try {
    const parsed = await parseSpec(document);
    return {
      ok: true,
      contract: {
        title: parsed.title,
        version: parsed.version,
        operations: parsed.operations.map((operation) => ({
          id: operation.id,
          method: operation.method,
          path: operation.path,
          operationId: operation.operation_id ?? undefined,
          summary: operation.summary ?? undefined,
          warnings: operation.warnings,
          available: operation.available,
          fields: operation.fields.map((field) => ({
            path: field.path,
            type: field.type as ContractField['type'],
            required: field.required,
            enumValues: field.enum.length ? field.enum : undefined,
            unsupported: field.unsupported ?? undefined,
          })),
        })),
      },
    };
  } catch (error) {
    const code = (error as { code?: string }).code;
    const message = (error as Error).message;
    if (code === 'invalid_spec' || code === 'spec_too_large') return { ok: false, error: message };
    return { ok: false, error: message || 'The OpenAPI document could not be parsed.' };
  }
}

const normalize = (value: string): string => value.toLowerCase().replace(/[^a-z0-9]+/g, '');

/** A leaf called `name`/`date`/… says little; its parent segment carries the meaning. */
const GENERIC_LEAVES = new Set([
  'name',
  'no',
  'number',
  'ref',
  'reference',
  'code',
  'id',
  'value',
  'text',
  'amount',
  'date',
]);

export function suggestMappings(
  fields: ContractField[],
  variables: MappingVariable[],
): Record<string, string> {
  const byLabel = new Map(variables.map((variable) => [normalize(variable.label), variable.variableId]));
  const mappings: Record<string, string> = {};
  for (const field of fields) {
    if (field.unsupported) continue;
    const segments = field.path.split('.');
    const leaf = segments.at(-1) ?? field.path;
    let match = byLabel.get(normalize(leaf)) ?? byLabel.get(normalize(field.path));
    if (!match && GENERIC_LEAVES.has(leaf.toLowerCase())) {
      for (const parent of [...segments.slice(0, -1)].reverse()) {
        match = byLabel.get(normalize(parent));
        if (match) break;
      }
    }
    if (match) mappings[field.path] = match;
  }
  return mappings;
}

/** Body assembly is a server call: the sandbox must not keep its own copy of the contract rules. */
export async function buildPayload(
  document: Record<string, unknown>,
  operation: ContractOperation,
  mapping: Record<string, string>,
  variables: MappingVariable[],
): Promise<OpenApiPayload> {
  const result = await buildSpecBody({
    spec: document,
    operation: operation.id,
    mapping,
    values: Object.fromEntries(
      variables.map((variable) => [variable.variableId, variable.displayValue ?? '']),
    ),
  });
  return {
    ready: result.ready,
    payload: result.body,
    missing: result.missing,
    invalid: result.invalid,
    issues: result.issues,
  };
}