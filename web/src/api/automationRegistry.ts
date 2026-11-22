/**
 * Server-side automation registry client (`/automation/templates*`, `/connectors`, `/dispatches`).
 *
 * Mirrors `app/api/automation.py` + `app/automation/registry_schemas.py`. The browser-local
 * workbench keeps working; this client is the shared, durable path (templates → variables →
 * downstream dispatch).
 */

import { API_BASE } from './client';
import { ApiError, NETWORK_CODE, TIMEOUT_CODE } from './errors';

export const REGISTRY_BASE = `${API_BASE}/automation`;
export const REGISTRY_TIMEOUT_MS = 90_000;

export type VariableValueType = 'string' | 'amount' | 'date' | 'currency' | 'integer' | 'boolean';
export type VariableSource = 'deterministic' | 'llm' | 'manual';

export interface TemplateVariable {
  key: string;
  label: string;
  value_type: VariableValueType;
  required: boolean;
  quote?: string | null;
  start?: number | null;
  end?: number | null;
  sample_value?: string | null;
  source: VariableSource;
}

export interface ServerTemplate {
  template_id: string;
  name: string;
  version: string;
  source_kind: string;
  source_note?: string | null;
  document_id?: string | null;
  text_chars: number;
  variables: TemplateVariable[];
  variables_source?: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface TemplateSuggestion {
  template_id: string;
  variables: TemplateVariable[];
  suggested_by: 'deterministic' | 'llm' | 'merged';
  model?: string | null;
  warnings: string[];
}

export interface BoundValue {
  value: string | null;
  quote?: string | null;
  source: 'document' | 'missing';
}

export interface BodyIssue {
  path: string;
  reason: 'missing' | 'invalid' | 'unsupported';
  message: string;
}

export interface PreparedPayload {
  template_id: string;
  template_name: string;
  template_version: string;
  document_id?: string | null;
  values: Record<string, BoundValue>;
  payload: Record<string, unknown>;
  missing_required: string[];
  /** Present when the selected connector carries an OpenAPI spec. */
  connector_id?: string | null;
  content_type?: string | null;
  request_body?: Record<string, unknown> | null;
  body_mapping: Record<string, string>;
  body_issues: BodyIssue[];
  unmapped_required: string[];
}

export interface SpecField {
  path: string;
  type: string;
  required: boolean;
  enum: string[];
  unsupported?: string | null;
}

export interface Connector {
  connector_id: string;
  name: string;
  base_url: string;
  path: string;
  method: string;
  auth_kind: 'none' | 'bearer' | 'header';
  auth_header?: string | null;
  secret_env?: string | null;
  secret_configured: boolean;
  timeout_seconds: number;
  extra_headers: Record<string, string>;
  created_at: string;
  /** OpenAPI contract, when the downstream system's spec was attached. */
  spec_title?: string | null;
  spec_version?: string | null;
  operation?: string | null;
  operation_method?: string | null;
  operation_path?: string | null;
  content_type?: string | null;
  request_fields: SpecField[];
  body_map: Record<string, string>;
  spec_warnings: string[];
  spec_error?: string | null;
  schema_kind?: 'openapi' | 'fields' | 'flat';
  fields?: Array<{ path: string; type: string; required: boolean }>;
}

export interface DispatchReceipt {
  dispatch_id: string;
  template_id?: string | null;
  connector_id: string;
  document_id?: string | null;
  status: 'succeeded' | 'failed' | 'refused';
  status_code?: number | null;
  latency_ms?: number | null;
  request: Record<string, unknown>;
  response_excerpt?: string | null;
  error_code?: string | null;
  created_at: string;
}

export interface ConnectorInput {
  name: string;
  base_url: string;
  path?: string;
  method?: 'POST' | 'PUT' | 'PATCH';
  auth_kind?: 'none' | 'bearer' | 'header';
  auth_header?: string;
  secret_env?: string;
  timeout_seconds?: number;
  /** Parsed OpenAPI 3.x JSON document, when the downstream system publishes one. */
  spec?: Record<string, unknown>;
  operation?: string;
  body_map?: Record<string, string>;
  /** Hand-written fields, for downstreams without an OpenAPI document (mutually exclusive). */
  fields?: Array<{ path: string; type: string; required: boolean }>;
}

export interface DispatchPreview {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: Record<string, unknown>;
  content_type?: string | null;
  operation?: string | null;
  schema_kind: 'openapi' | 'fields' | 'flat';
  issues: BodyIssue[];
  refusal?: string | null;
}

export interface RegistryOptions {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

const isAbortError = (error: unknown): boolean =>
  typeof error === 'object' &&
  error !== null &&
  (error as { name?: string }).name === 'AbortError';

export async function request<T>(
  path: string,
  init: RequestInit,
  { fetchImpl, timeoutMs = REGISTRY_TIMEOUT_MS }: RegistryOptions = {},
): Promise<T> {
  const doFetch = fetchImpl ?? globalThis.fetch;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const method = (init.method ?? 'GET').toUpperCase();
  const headers =
    method === 'GET'
      ? init.headers
      : {
          ...((init.headers as Record<string, string> | undefined) ?? {}),
          'X-Requested-With': 'smart-edit',
        };
  try {
    const response = await doFetch(`${REGISTRY_BASE}${path}`, {
      ...init,
      headers,
      credentials: 'include',
      signal: controller.signal,
    });
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const body = (payload ?? {}) as {
        error?: { code?: string; message?: string; detail?: unknown };
        code?: string;
        message?: string;
        detail?: unknown;
      };
      throw new ApiError(
        response.status,
        body.error?.code ?? body.code ?? `HTTP_${response.status}`,
        body.error?.message ?? body.message ?? `request failed with status ${response.status}`,
        body.error?.detail ?? body.detail,
      );
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (isAbortError(error)) {
      throw new ApiError(0, TIMEOUT_CODE, `request aborted after ${timeoutMs} ms`);
    }
    throw new ApiError(0, NETWORK_CODE, (error as Error)?.message ?? 'network error');
  } finally {
    clearTimeout(timer);
  }
}

export function listTemplates(options: RegistryOptions = {}): Promise<{ items: ServerTemplate[] }> {
  return request('/templates', { method: 'GET' }, options);
}

export function createTemplate(
  input: {
    name: string;
    text: string;
    source_kind?: string;
    source_note?: string;
    document_id?: string;
  },
  options: RegistryOptions = {},
): Promise<ServerTemplate> {
  return request(
    '/templates',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    options,
  );
}

export function suggestVariables(
  templateId: string,
  useLlm = true,
  options: RegistryOptions = {},
): Promise<TemplateSuggestion> {
  const query = useLlm ? '' : '?use_llm=false';
  return request(
    `/templates/${encodeURIComponent(templateId)}/variables/suggest${query}`,
    { method: 'POST' },
    options,
  );
}

export interface AppliedTemplate {
  document_id: string;
  draft_id?: string | null;
  title: string;
  text_chars: number;
  filled: Record<string, string>;
  missing: string[];
}

export function renameTemplate(
  templateId: string,
  name: string,
  options: RegistryOptions = {},
): Promise<ServerTemplate> {
  return request(
    `/templates/${encodeURIComponent(templateId)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    },
    options,
  );
}

export function duplicateTemplate(
  templateId: string,
  name?: string,
  options: RegistryOptions = {},
): Promise<ServerTemplate> {
  return request(
    `/templates/${encodeURIComponent(templateId)}/duplicate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(name ? { name } : {}),
    },
    options,
  );
}

export function deleteTemplate(
  templateId: string,
  options: RegistryOptions = {},
): Promise<void> {
  return request(`/templates/${encodeURIComponent(templateId)}`, { method: 'DELETE' }, options);
}

export function applyTemplate(
  templateId: string,
  input: { title?: string; values?: Record<string, string> },
  options: RegistryOptions = {},
): Promise<AppliedTemplate> {
  return request(
    `/templates/${encodeURIComponent(templateId)}/apply`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    options,
  );
}

export interface WriteBackResult {
  document_id: string;
  draft_id: string;
  revision: number;
  applied: Record<string, string>;
  skipped: string[];
}

export function writeBackTemplate(
  templateId: string,
  input: {
    document_id: string;
    draft_id: string;
    lock_id: string;
    fencing_token: number;
    expected_revision: number;
    values: Record<string, string>;
  },
  options: RegistryOptions = {},
): Promise<WriteBackResult> {
  return request(
    `/templates/${encodeURIComponent(templateId)}/write-back`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    options,
  );
}

export function saveVariables(
  templateId: string,
  variables: TemplateVariable[],
  options: RegistryOptions = {},
): Promise<ServerTemplate> {
  return request(
    `/templates/${encodeURIComponent(templateId)}/variables`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ variables }),
    },
    options,
  );
}

export function preparePayload(
  templateId: string,
  input: { document_id?: string; text?: string; connector_id?: string },
  options: RegistryOptions = {},
): Promise<PreparedPayload> {
  return request(
    `/templates/${encodeURIComponent(templateId)}/prepare`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    options,
  );
}

export function listConnectors(options: RegistryOptions = {}): Promise<{ items: Connector[] }> {
  return request('/connectors', { method: 'GET' }, options);
}

export function createConnector(
  input: ConnectorInput,
  options: RegistryOptions = {},
): Promise<Connector> {
  return request(
    '/connectors',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    options,
  );
}

export function updateConnector(
  connectorId: string,
  patch: Partial<ConnectorInput>,
  options: RegistryOptions = {},
): Promise<Connector> {
  return request(
    `/connectors/${encodeURIComponent(connectorId)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    },
    options,
  );
}

export function disableConnector(
  connectorId: string,
  options: RegistryOptions = {},
): Promise<Connector> {
  return request(`/connectors/${encodeURIComponent(connectorId)}`, { method: 'DELETE' }, options);
}

export function readConnectorSpec(
  connectorId: string,
  options: RegistryOptions = {},
): Promise<{ connector_id: string; operation: string | null; spec: Record<string, unknown> }> {
  return request(`/connectors/${encodeURIComponent(connectorId)}/spec`, { method: 'GET' }, options);
}

export function readMapping(
  templateId: string,
  connectorId: string,
  options: RegistryOptions = {},
): Promise<{ template_id: string; connector_id: string; body_map: Record<string, string>; configured: boolean }> {
  const query = `?template_id=${encodeURIComponent(templateId)}&connector_id=${encodeURIComponent(connectorId)}`;
  return request(`/mappings${query}`, { method: 'GET' }, options);
}

export interface SpecFieldResponse {
  path: string;
  type: string;
  required: boolean;
  enum: string[];
  unsupported?: string | null;
}

export interface SpecOperationResponse {
  id: string;
  method: string;
  path: string;
  operation_id?: string | null;
  summary?: string | null;
  content_type?: string | null;
  available: boolean;
  fields: SpecFieldResponse[];
  warnings: string[];
}

export function parseSpec(
  spec: Record<string, unknown>,
  options: RegistryOptions = {},
): Promise<{ title: string; version: string; operations: SpecOperationResponse[] }> {
  return request(
    '/spec/parse',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ spec }),
    },
    options,
  );
}

export interface SpecBuildResponse {
  operation: string;
  body: Record<string, unknown>;
  mapping: Record<string, string>;
  issues: BodyIssue[];
  missing: string[];
  invalid: string[];
  ready: boolean;
}

export function buildSpecBody(
  input: {
    spec: Record<string, unknown>;
    operation: string;
    mapping?: Record<string, string>;
    values?: Record<string, string>;
  },
  options: RegistryOptions = {},
): Promise<SpecBuildResponse> {
  return request(
    '/spec/build',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    options,
  );
}

export function saveMapping(
  connectorId: string,
  bodyMap: Record<string, string>,
  templateId?: string,
  options: RegistryOptions = {},
): Promise<Connector> {
  return request(
    `/connectors/${encodeURIComponent(connectorId)}/mapping`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(templateId ? { body_map: bodyMap, template_id: templateId } : { body_map: bodyMap }),
    },
    options,
  );
}

export interface DocumentTemplateBinding {
  document_id: string;
  template_id: string | null;
  template_name: string | null;
}

export function getDocumentTemplate(
  documentId: string,
  options: RegistryOptions = {},
): Promise<DocumentTemplateBinding> {
  return request(`/documents/${encodeURIComponent(documentId)}/template`, { method: 'GET' }, options);
}

export function bindDocumentTemplate(
  documentId: string,
  templateId: string,
  options: RegistryOptions = {},
): Promise<DocumentTemplateBinding> {
  return request(
    `/documents/${encodeURIComponent(documentId)}/template`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_id: templateId }),
    },
    options,
  );
}

export function listDispatches(
  limit = 20,
  options: RegistryOptions = {},
): Promise<{ items: DispatchReceipt[] }> {
  return request(`/dispatches?limit=${limit}`, { method: 'GET' }, options);
}

export function previewDispatch(
  input: {
    template_id: string;
    connector_id: string;
    document_id?: string;
    values?: Record<string, string>;
  },
  options: RegistryOptions = {},
): Promise<DispatchPreview> {
  return request(
    '/dispatches/preview',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    options,
  );
}

export function dispatch(
  input: {
    template_id: string;
    connector_id: string;
    document_id?: string;
    values?: Record<string, string>;
    idempotency_key?: string;
  },
  options: RegistryOptions = {},
): Promise<DispatchReceipt> {
  return request(
    '/dispatches',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    options,
  );
}

export interface RegistryClient {
  listTemplates: typeof listTemplates;
  createTemplate: typeof createTemplate;
  renameTemplate: typeof renameTemplate;
  duplicateTemplate: typeof duplicateTemplate;
  deleteTemplate: typeof deleteTemplate;
  applyTemplate: typeof applyTemplate;
  writeBackTemplate: typeof writeBackTemplate;
  suggestVariables: typeof suggestVariables;
  saveVariables: typeof saveVariables;
  preparePayload: typeof preparePayload;
  listConnectors: typeof listConnectors;
  createConnector: typeof createConnector;
  updateConnector: typeof updateConnector;
  disableConnector: typeof disableConnector;
  readConnectorSpec: typeof readConnectorSpec;
  parseSpec: typeof parseSpec;
  buildSpecBody: typeof buildSpecBody;
  readMapping: typeof readMapping;
  saveMapping: typeof saveMapping;
  getDocumentTemplate: typeof getDocumentTemplate;
  bindDocumentTemplate: typeof bindDocumentTemplate;
  previewDispatch: typeof previewDispatch;
  listDispatches: typeof listDispatches;
  dispatch: typeof dispatch;
}

export const registryClient: RegistryClient = {
  listTemplates,
  createTemplate,
  renameTemplate,
  duplicateTemplate,
  deleteTemplate,
  applyTemplate,
  writeBackTemplate,
  suggestVariables,
  saveVariables,
  preparePayload,
  listConnectors,
  createConnector,
  updateConnector,
  disableConnector,
  readConnectorSpec,
  parseSpec,
  buildSpecBody,
  readMapping,
  saveMapping,
  getDocumentTemplate,
  bindDocumentTemplate,
  previewDispatch,
  listDispatches,
  dispatch,
};