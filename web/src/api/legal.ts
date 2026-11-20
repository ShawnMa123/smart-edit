/**
 * Legal-review HTTP client (`/legal/*`).
 *
 * Mirrors `app/api/legal.py`:
 * - POST `/legal/reviews` -> 202 + `ReviewRun` (question scope answers synchronously, a document
 *   scan comes back `queued`);
 * - GET `/legal/runs/{id}` -> the polled run (progress line);
 * - GET `/legal/reports/{id}` -> the report (`app/legal_review/contracts.py`).
 */

import { API_BASE } from './client';
import { ApiError, NETWORK_CODE, TIMEOUT_CODE } from './errors';

export const LEGAL_BASE = `${API_BASE}/legal`;
export const LEGAL_TIMEOUT_MS = 90_000;
/** A scan is 8-20 s; the client polls until this budget is exhausted. */
export const LEGAL_SCAN_TIMEOUT_MS = 120_000;
export const LEGAL_POLL_INTERVAL_MS = 900;

export interface LegalOptions {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

export type LegalMethod = 'deterministic' | 'semantic' | 'legal';
export type LegalScope = 'question' | 'document';
export type CheckStatus =
  | 'pass'
  | 'finding'
  | 'not_applicable'
  | 'needs_input'
  | 'unable_to_assess'
  | 'failed';
export type Severity = 'Critical' | 'Warning' | 'Info';
export type GateType = 'advisory' | 'human_review' | 'hard_block';
export type SupportLevel = 'strong' | 'qualified' | 'insufficient' | 'not_applicable';
export type FindingBasis = 'rule' | 'statute' | 'web';
export type LegalGateStatus = 'clear' | 'advisory' | 'needs_human_review' | 'blocked';

export interface RuleRef {
  rule_id: string;
  version: string;
}

export interface CheckResult {
  check_id: string;
  method: LegalMethod;
  scope_key: string;
  status: CheckStatus;
  rule_refs: RuleRef[];
  reason_codes: string[];
  finding_ids: string[];
  missing_facts: string[];
  clause_id?: string | null;
  evidence_count?: number;
  search_queries?: string[];
}

/** Where in the draft a finding applies. `quote` is a real substring of the draft text. */
export interface DocumentAnchor {
  clause_id: string;
  block_index: number;
  start_cp: number;
  end_cp: number;
  quote: string;
}

/** A statute or web citation. */
export interface EvidenceAnchor {
  chunk_id?: string | null;
  doc_id?: string | null;
  article_label?: string | null;
  jurisdiction?: string | null;
  effective_from?: string | null;
  title?: string | null;
  source_version?: string | null;
  excerpt?: string | null;
  url?: string | null;
  unverified?: boolean;
}

export interface Finding {
  finding_id: string;
  check_id: string;
  method: LegalMethod;
  category: string;
  severity: Severity;
  gate_type: GateType;
  target_operations: string[];
  title: string;
  explanation: string;
  anchors: EvidenceAnchor[];
  document_anchors?: DocumentAnchor[];
  suggestion?: string | null;
  basis?: FindingBasis;
  rule_refs: RuleRef[];
  evidence_ids: string[];
  applicability: Record<string, unknown>;
  support_level: SupportLevel;
  disposition: string;
  version: number;
}

export interface ReviewRun {
  run_id: string;
  status: string;
  stage: string;
  created_at: string;
  deadline_at: string;
  report_id: string | null;
  error: string | null;
  finished_at: string | null;
  progress?: {
    stage?: string;
    planned?: number;
    done?: number;
    current?: string | null;
    findings?: number;
  };
}

export interface CoverageSummary {
  planned: number;
  settled: number;
  assessed: number;
  assessed_ratio: number;
  by_status: Record<string, number>;
  clauses: number;
  truncated: boolean;
  coverage_ratio_policy?: number;
}

export interface LegalGate {
  status: LegalGateStatus;
  reasons: string[];
  coverage_ratio: number;
  policy: string;
}

export interface ReviewReport {
  report_id: string;
  run_id: string;
  completion: 'complete' | 'partial';
  outcome: 'findings_present' | 'no_findings' | 'needs_input' | 'unable_to_assess';
  findings: Finding[];
  coverage: CheckResult[];
  limitations: Record<string, unknown>[];
  snapshot?: {
    document_id?: string;
    revision?: number | null;
    content_sha256?: string | null;
  };
  coverage_summary?: CoverageSummary;
  retrieval?: {
    queries?: number;
    hits?: number;
    web_requested?: boolean;
    web_used?: boolean;
    web_calls?: number;
    layers?: Record<string, unknown>[];
  };
  gate?: LegalGate;
}

export interface ReviewInput {
  workspace_id: string;
  document_id: string;
  /** `question` scope only; defaults keep the old call sites working. */
  snapshot_id?: string;
  facts_version_id?: string;
  modes: LegalMethod[];
  question?: string;
  facts?: Record<string, unknown>;
  scope?: LegalScope;
  draft_id?: string;
  expected_revision?: number;
  expected_content_sha256?: string;
  business_type?: string;
  applicable_on?: string;
  jurisdiction_codes?: string[];
  /** The user's choice for the outbound web leg; `undefined` = deployment default. */
  web_search?: boolean;
}

interface LegalRequestConfig extends LegalOptions {
  method: 'GET' | 'POST';
  body?: unknown;
}

const isAbortError = (error: unknown): boolean =>
  typeof error === 'object' && error !== null && (error as { name?: string }).name === 'AbortError';

async function requestJson<T>(path: string, config: LegalRequestConfig): Promise<T> {
  const doFetch = config.fetchImpl ?? globalThis.fetch;
  const controller = new AbortController();
  const timeoutMs = config.timeoutMs ?? LEGAL_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers: Record<string, string> = {};
  if (config.body !== undefined) headers['Content-Type'] = 'application/json';
  try {
    const response = await doFetch(`${LEGAL_BASE}${path}`, {
      method: config.method,
      headers:
        config.method === 'GET'
          ? headers
          : { ...headers, 'X-Requested-With': 'smart-edit' },
      body: config.body === undefined ? undefined : JSON.stringify(config.body),
      credentials: 'include',
      signal: controller.signal,
    });
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const body = (payload ?? {}) as {
        error?: { code?: string; message?: string };
        code?: string;
        message?: string;
        detail?: unknown;
      };
      throw new ApiError(
        response.status,
        body.error?.code ?? body.code ?? `HTTP_${response.status}`,
        body.error?.message ?? body.message ?? `legal request failed with status ${response.status}`,
        body.error ?? body.detail,
      );
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (isAbortError(error)) {
      throw new ApiError(0, TIMEOUT_CODE, `legal request aborted after ${timeoutMs} ms`);
    }
    throw new ApiError(0, NETWORK_CODE, (error as Error)?.message ?? 'network error');
  } finally {
    clearTimeout(timer);
  }
}

export function submitReview(input: ReviewInput, options: LegalOptions = {}): Promise<ReviewRun> {
  return requestJson('/reviews', { ...options, method: 'POST', body: input });
}

export function getRun(runId: string, options: LegalOptions = {}): Promise<ReviewRun> {
  return requestJson(`/runs/${encodeURIComponent(runId)}`, { ...options, method: 'GET' });
}

export function getReport(reportId: string, options: LegalOptions = {}): Promise<ReviewReport> {
  return requestJson(`/reports/${encodeURIComponent(reportId)}`, { ...options, method: 'GET' });
}

/** Kept for older imports: evidence anchors used to be called finding anchors. */
export type FindingAnchor = EvidenceAnchor;

export interface LegalClient {
  submitReview: typeof submitReview;
  getReport: typeof getReport;
  getRun?: typeof getRun;
}

export const legalClient: LegalClient = {
  submitReview,
  getReport,
  getRun,
};
