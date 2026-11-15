/**
 * OpenAPI 3.x JSON -> JSON request contract (design D19).
 *
 * Deliberately a small, local subset: JSON only, local `$ref`, object schemas flattened into dotted
 * scalar paths. Unsupported constructs are reported, never guessed. No network access.
 */

export type ScalarType = 'string' | 'number' | 'integer' | 'boolean';

export interface ContractField {
  path: string;
  type: ScalarType | 'array' | 'object' | 'unknown';
  required: boolean;
  enumValues?: string[];
  description?: string;
  /** Present when this field cannot be mapped; the UI must not offer a mapping. */
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

const METHODS = ['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'] as const;
const SCALAR_TYPES = new Set(['string', 'number', 'integer', 'boolean']);

interface WalkState {
  root: Record<string, unknown>;
  fields: ContractField[];
  warnings: Set<string>;
  /** Object identity on the current recursion path; catches `$ref` cycles. */
  visiting: Set<Record<string, unknown>>;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const asString = (value: unknown): string | undefined =>
  typeof value === 'string' ? value : undefined;

function resolvePointer(root: Record<string, unknown>, ref: string): unknown {
  if (!ref.startsWith('#/')) return undefined;
  return ref
    .slice(2)
    .split('/')
    .map((token) => token.replace(/~1/g, '/').replace(/~0/g, '~'))
    .reduce<unknown>((current, token) => (isRecord(current) ? current[token] : undefined), root);
}

function deref(value: unknown, state: WalkState, label: string): Record<string, unknown> | null {
  let current = value;
  const seen = new Set<string>();
  while (isRecord(current) && typeof current.$ref === 'string') {
    const ref = current.$ref;
    if (!ref.startsWith('#/')) {
      state.warnings.add(`${label}: external $ref ${ref} is not supported`);
      return null;
    }
    if (seen.has(ref)) {
      state.warnings.add(`${label}: circular $ref ${ref}`);
      return null;
    }
    seen.add(ref);
    const resolved = resolvePointer(state.root, ref);
    if (!isRecord(resolved)) {
      state.warnings.add(`${label}: unresolved $ref ${ref}`);
      return null;
    }
    current = resolved;
  }
  return isRecord(current) ? current : null;
}

function collectSchema(schema: unknown, prefix: string, state: WalkState): void {
  const resolved = deref(schema, state, prefix || 'request schema');
  if (!resolved) return;

  if (state.visiting.has(resolved)) {
    state.warnings.add(`${prefix || 'request schema'}: circular schema reference`);
    return;
  }

  if (resolved.oneOf !== undefined || resolved.anyOf !== undefined) {
    state.warnings.add(`${prefix || 'request schema'}: oneOf/anyOf is not supported`);
    if (prefix) {
      state.fields.push({
        path: prefix,
        type: 'unknown',
        required: false,
        unsupported: 'oneOf/anyOf is not supported.',
      });
    }
    return;
  }
  if (resolved.allOf !== undefined) {
    state.warnings.add(`${prefix || 'request schema'}: allOf is not supported`);
    if (prefix) {
      state.fields.push({
        path: prefix,
        type: 'unknown',
        required: false,
        unsupported: 'allOf is not supported.',
      });
    }
    return;
  }

  const properties = resolved.properties;
  if (!isRecord(properties)) {
    state.warnings.add(`${prefix || 'request schema'}: no object properties found`);
    return;
  }

  const required = new Set(
    Array.isArray(resolved.required)
      ? resolved.required.filter((value): value is string => typeof value === 'string')
      : [],
  );

  state.visiting.add(resolved);
  for (const [key, rawProperty] of Object.entries(properties)) {
    const path = prefix ? `${prefix}.${key}` : key;
    const property = deref(rawProperty, state, path);
    if (!property) continue;

    if (isRecord(property.properties) || property.type === 'object') {
      collectSchema(property, path, state);
      continue;
    }

    const isRequired = required.has(key);
    const description = asString(property.description);
    const enumValues = Array.isArray(property.enum)
      ? property.enum.map((value) => String(value))
      : undefined;
    const type = asString(property.type) ?? '';

    if (property.oneOf !== undefined || property.anyOf !== undefined) {
      state.warnings.add(`${path}: oneOf/anyOf is not supported`);
      state.fields.push({
        path,
        type: 'unknown',
        required: isRequired,
        unsupported: 'oneOf/anyOf is not supported.',
      });
      continue;
    }
    if (type === 'array') {
      state.fields.push({
        path,
        type: 'array',
        required: isRequired,
        ...(description ? { description } : {}),
        unsupported: 'Array fields are not supported for variable mapping.',
      });
      state.warnings.add(`${path}: array fields are not supported`);
      continue;
    }
    if (!SCALAR_TYPES.has(type)) {
      state.fields.push({
        path,
        type: 'unknown',
        required: isRequired,
        ...(description ? { description } : {}),
        unsupported: 'Missing or unsupported type.',
      });
      state.warnings.add(`${path}: missing or unsupported type`);
      continue;
    }

    state.fields.push({
      path,
      type: type as ScalarType,
      required: isRequired,
      ...(description ? { description } : {}),
      ...(enumValues ? { enumValues } : {}),
    });
  }
  state.visiting.delete(resolved);
}
export function parseOpenApi(text: string): OpenApiParseResult {
  if (!text.trim()) return { ok: false, error: 'Paste an OpenAPI JSON document first.' };

  let root: unknown;
  try {
    root = JSON.parse(text);
  } catch {
    return {
      ok: false,
      error: /^\s*openapi\s*:/m.test(text)
        ? 'YAML is not supported. Provide OpenAPI 3.x JSON.'
        : 'Invalid JSON. Provide an OpenAPI 3.x JSON document.',
    };
  }
  if (!isRecord(root)) return { ok: false, error: 'The document must be a JSON object.' };

  if (root.swagger !== undefined) {
    return {
      ok: false,
      error: 'Swagger 2.0 is not supported. Provide an OpenAPI 3.x JSON document.',
    };
  }
  const openapi = asString(root.openapi);
  if (!openapi || !openapi.startsWith('3.')) {
    return { ok: false, error: 'Only OpenAPI 3.x JSON is supported.' };
  }
  const paths = root.paths;
  if (!isRecord(paths)) {
    return { ok: false, error: 'The OpenAPI document has no paths object.' };
  }

  const info = isRecord(root.info) ? root.info : {};
  const title = asString(info.title) ?? 'Untitled API';
  const version = asString(info.version) ?? 'unknown';
  const operations: ContractOperation[] = [];

  for (const [path, rawPathItem] of Object.entries(paths)) {
    if (!isRecord(rawPathItem)) continue;
    for (const method of METHODS) {
      const rawOperation = rawPathItem[method];
      if (!isRecord(rawOperation)) continue;

      const warnings = new Set<string>();
      const state: WalkState = {
        root,
        fields: [],
        warnings,
        visiting: new Set(),
      };

      const requestBody = deref(rawOperation.requestBody, state, `${method.toUpperCase()} ${path}`);
      let schema: unknown;
      if (!requestBody) {
        warnings.add('No request body.');
      } else {
        const content = requestBody.content;
        if (isRecord(content)) {
          const jsonKey = Object.keys(content).find(
            (key) => key.split(';')[0].trim().toLowerCase() === 'application/json',
          );
          const media = jsonKey ? content[jsonKey] : undefined;
          schema = isRecord(media) ? media.schema : undefined;
        }
        if (!schema) warnings.add('No application/json request body.');
      }

      if (schema) collectSchema(schema, '', state);

      const fields = state.fields;
      const available =
        Boolean(schema) &&
        fields.some((field) => !field.unsupported && SCALAR_TYPES.has(field.type));

      operations.push({
        id: `${method.toUpperCase()} ${path}`,
        method: method.toUpperCase(),
        path,
        ...(asString(rawOperation.operationId)
          ? { operationId: asString(rawOperation.operationId) }
          : {}),
        ...(asString(rawOperation.summary) ? { summary: asString(rawOperation.summary) } : {}),
        fields,
        warnings: [...warnings],
        available,
      });
    }
  }

  return { ok: true, contract: { title, version, operations } };
}
