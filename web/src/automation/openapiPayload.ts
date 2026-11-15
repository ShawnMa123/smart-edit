/**
 * Variable -> OpenAPI field mapping and request JSON assembly (design D19).
 *
 * Pure functions only: the component owns state, this module owns the rules. Conversion failures
 * block readiness; nothing is coerced silently.
 */

import type { ContractField } from './openapi';

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

const normalize = (value: string): string => value.toLowerCase().replace(/[^a-z0-9]+/g, '');

/** Auto-suggest by variable label vs. the last path segment (and the full path). */
export function suggestMappings(
  fields: ContractField[],
  variables: MappingVariable[],
): Record<string, string> {
  const byLabel = new Map(variables.map((variable) => [normalize(variable.label), variable.variableId]));
  const mappings: Record<string, string> = {};
  for (const field of fields) {
    if (field.unsupported) continue;
    const last = field.path.split('.').at(-1) ?? field.path;
    const match = byLabel.get(normalize(last)) ?? byLabel.get(normalize(field.path));
    if (match) mappings[field.path] = match;
  }
  return mappings;
}

const setPath = (target: Record<string, unknown>, path: string, value: unknown): void => {
  const parts = path.split('.');
  let current = target;
  for (const part of parts.slice(0, -1)) {
    const next = current[part];
    if (!next || typeof next !== 'object' || Array.isArray(next)) {
      current[part] = {};
    }
    current = current[part] as Record<string, unknown>;
  }
  current[parts[parts.length - 1]] = value;
};

function convert(
  value: string,
  field: ContractField,
): { ok: true; value: unknown } | { ok: false } {
  switch (field.type) {
    case 'string':
      return { ok: true, value };
    case 'number': {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? { ok: true, value: parsed } : { ok: false };
    }
    case 'integer': {
      const parsed = Number(value);
      return Number.isFinite(parsed) && Number.isInteger(parsed)
        ? { ok: true, value: parsed }
        : { ok: false };
    }
    case 'boolean': {
      const lowered = value.trim().toLowerCase();
      if (lowered === 'true') return { ok: true, value: true };
      if (lowered === 'false') return { ok: true, value: false };
      return { ok: false };
    }
    default:
      return { ok: false };
  }
}

export function buildOpenApiPayload(
  fields: ContractField[],
  mappings: Record<string, string>,
  variables: MappingVariable[],
): OpenApiPayload {
  const byId = new Map(variables.map((variable) => [variable.variableId, variable]));
  const payload: Record<string, unknown> = {};
  const issues: PayloadIssue[] = [];
  const missing: string[] = [];
  const invalid: string[] = [];

  for (const field of fields) {
    if (field.unsupported) {
      if (field.required) {
        issues.push({
          path: field.path,
          reason: 'unsupported',
          message: 'A required field uses an unsupported schema.',
        });
        missing.push(field.path);
      }
      continue;
    }

    const variableId = mappings[field.path];
    const variable = variableId ? byId.get(variableId) : undefined;
    if (!variable) {
      if (field.required) {
        issues.push({
          path: field.path,
          reason: 'missing',
          message: 'Required field has no mapped variable.',
        });
        missing.push(field.path);
      }
      continue;
    }

    const value = variable.displayValue ?? '';
    if (!value.trim()) {
      if (field.required) {
        issues.push({
          path: field.path,
          reason: 'missing',
          message: 'Required field has an empty value.',
        });
        missing.push(field.path);
      }
      continue;
    }

    if (field.enumValues && !field.enumValues.includes(value)) {
      issues.push({
        path: field.path,
        reason: 'invalid',
        message: `Value must be one of: ${field.enumValues.join(', ')}.`,
      });
      invalid.push(field.path);
      continue;
    }

    const converted = convert(value, field);
    if (!converted.ok) {
      issues.push({
        path: field.path,
        reason: 'invalid',
        message: `Value cannot be converted to ${field.type}.`,
      });
      invalid.push(field.path);
      continue;
    }

    setPath(payload, field.path, converted.value);
  }

  return {
    ready: issues.length === 0,
    payload,
    missing,
    invalid,
    issues,
  };
}