/**
 * Template-conformance audit client (`/conformance/*`).
 *
 * The review is asynchronous: `submitReview` answers a run, the panel polls `getRun`, then reads
 * `getReport`. Every response is typed; the error shape is the shared `ApiError` contract.
 */

import { API_BASE, DEFAULT_TIMEOUT_MS } from './client';
import { ApiError, NETWORK_CODE, TIMEOUT_CODE } from './errors';

export const CONFORMANCE_BASE = `${API_BASE}/conformance`;

export type ConformanceOutcome =
  | 'findings_present'
  | 'no_findings'
  | 'needs_input'
  | 'unable_to_assess';
export type RequirementStatus = 'pass' | 'finding' | 'unable_to_assess';
export type RequirementLevel = 'must' | 'should' | 'info';
export type Confidence = 'high' | 'medium' | 'low';

export interface ConformanceConfigSummary {
  config_id: string;
  version: string;
  name: string;
  document_types: string[];
  language: string;
  description: string;
  requirement_count: number;
  required_fields: string[];
  content_sha256: string;
}

export interface ConformanceRequirement {
  id: string;
  title: string;
  level: RequirementLevel;
  check: string | null;
  evidence_hint: string | null;
  suggestion: string | null;
}

export interface ConformanceConfigDetail extends ConformanceConfigSummary {
  extraction_profile: string | null;
  generation: Record<string, number>;
  requirements: ConformanceRequirement[];
}

export interface ConformanceRun {
  run_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  stage: string;
  created_at: string;
  finished_at: string | null;
  report_id: string | null;
  error: string | null;
  progress: Record<string, unknown>;
}

export interface RequirementResult {
  id: string;
  title: string;
  level: RequirementLevel;
  status: RequirementStatus;
  severity: 'Warning' | 'Info';
  gate_type: 'advisory' | 'human_review';
  explanation: string;
  suggestion: string | null;
  quote: string | null;
  block_index: number | null;
  confidence: Confidence;
  reason_codes: string[];
}

export interface MissingField {
  key: string;
  label: string;
  note: string | null;
}

export interface RedactionStep {
  kind: string;
  count: number;
  sample: string;
}

export interface RedactionInfo {
  applied: boolean;
  total: number;
  note: string;
  steps: RedactionStep[];
}

export interface ConformanceSnapshot {
  document_id: string;
  draft_id: string | null;
  title: string | null;
  revision: number | null;
  content_sha256: string | null;
  analyzed_chars: number;
  truncated: boolean;
}

export interface ConformanceCounts {
  requirements: number;
  passed: number;
  findings: number;
  unable_to_assess: number;
  missing_fields: number;
  coverage_ratio: number;
}

export interface ConformanceProvenance {
  model: string | null;
  prompt_version: string;
  config_sha256: string;
  extraction_status: 'deterministic' | 'not_run' | 'failed';
  extraction_profile: string | null;
  model_calls: number;
  duration_ms: number;
  redaction: RedactionInfo;
}

export interface ConformanceReport {
  report_id: string;
  run_id: string;
  outcome: ConformanceOutcome;
  completion: 'complete' | 'partial';
  config: ConformanceConfigSummary;
  snapshot: ConformanceSnapshot;
  summary: string;
  summary_note: string;
  results: RequirementResult[];
  missing_fields: MissingField[];
  counts: ConformanceCounts;
  limitations: Array<{ code: string; message: string }>;
  provenance: ConformanceProvenance;
}

export interface ReviewInput {
  workspace_id: string;
  document_id: string;
  config_id: string;
  draft_id?: string | null;
  expected_revision?: number | null;
  expected_content_sha256?: string | null;
  language?: string | null;
}

export interface ConformanceOptions {
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

const isAbortError = (error: unknown): boolean =>
  typeof error === 'object' &&
  error !== null &&
  (error as { name?: string }).name === 'AbortError';

async function request<T>(
  path: string,
  init: RequestInit,
  { timeoutMs = DEFAULT_TIMEOUT_MS, fetchImpl }: ConformanceOptions = {},
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
    const response = await doFetch(`${CONFORMANCE_BASE}${path}`, {
      ...init,
      headers,
      credentials: 'include',
      signal: controller.signal,
    });
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const body = (payload ?? {}) as { code?: string; message?: string; detail?: unknown };
      throw new ApiError(
        response.status,
        body.code ?? `HTTP_${response.status}`,
        body.message ?? `request failed with status ${response.status}`,
        body.detail,
      );
    }
    if (payload === null) {
      throw new ApiError(response.status, 'EMPTY_RESPONSE', 'the server returned no body');
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

export function listConfigs(options: ConformanceOptions = {}): Promise<ConformanceConfigSummary[]> {
  return request('/configs', { method: 'GET' }, options);
}

export function getConfig(
  configId: string,
  options: ConformanceOptions = {},
): Promise<ConformanceConfigDetail> {
  return request(`/configs/${encodeURIComponent(configId)}`, { method: 'GET' }, options);
}

export function submitReview(
  input: ReviewInput,
  options: ConformanceOptions = {},
): Promise<ConformanceRun> {
  return request(
    '/reviews',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
    options,
  );
}

export function getRun(runId: string, options: ConformanceOptions = {}): Promise<ConformanceRun> {
  return request(`/runs/${encodeURIComponent(runId)}`, { method: 'GET' }, options);
}

export function getReport(
  reportId: string,
  options: ConformanceOptions = {},
): Promise<ConformanceReport> {
  return request(`/reports/${encodeURIComponent(reportId)}`, { method: 'GET' }, options);
}

export interface ConformanceClient {
  listConfigs: typeof listConfigs;
  getConfig: typeof getConfig;
  submitReview: typeof submitReview;
  getRun: typeof getRun;
  getReport: typeof getReport;
}

export const conformanceClient: ConformanceClient = {
  listConfigs,
  getConfig,
  submitReview,
  getRun,
  getReport,
};