/**
 * Parse the "custom fields" textarea into request fields.
 *
 * Downstreams that publish no OpenAPI document still need a contract; one line per field keeps it
 * typable in a demo: `amount: number *`, `beneficiary.name: string *`, `note: string`.
 * A trailing `*` marks the field required; the type defaults to `string`.
 */

export type FieldType = 'string' | 'number' | 'integer' | 'boolean';

export interface ParsedField {
  path: string;
  type: FieldType;
  required: boolean;
}

export interface ParsedFields {
  fields: ParsedField[];
  errors: string[];
}

const TYPES = new Set<FieldType>(['string', 'number', 'integer', 'boolean']);
const PATH = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/;

export function parseFieldLines(text: string): ParsedFields {
  const fields: ParsedField[] = [];
  const errors: string[] = [];
  const seen = new Set<string>();

  text
    .split('\n')
    .map((line) => line.trim())
    .forEach((line, index) => {
      if (!line || line.startsWith('#')) return;
      const [rawPath, ...rest] = line.split(':');
      const path = rawPath.trim();
      const tail = rest.join(':').trim();
      const required = tail.endsWith('*');
      const rawType = (required ? tail.slice(0, -1) : tail).trim().toLowerCase() || 'string';
      if (!PATH.test(path)) {
        errors.push(`line ${index + 1}: “${path}” is not a dotted field name`);
        return;
      }
      if (seen.has(path)) {
        errors.push(`line ${index + 1}: “${path}” is declared twice`);
        return;
      }
      if (!TYPES.has(rawType as FieldType)) {
        errors.push(`line ${index + 1}: “${rawType}” is not one of ${[...TYPES].join(' / ')}`);
        return;
      }
      seen.add(path);
      fields.push({ path, type: rawType as FieldType, required });
    });

  if (!fields.length && !errors.length) errors.push('add at least one field');
  return { fields, errors };
}