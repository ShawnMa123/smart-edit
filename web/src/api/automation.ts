/** Automation client: fixture proposal, accept, apply and undo. */

import { API_BASE, DEFAULT_TIMEOUT_MS } from './client';
import { ApiError, INVALID_RESPONSE_CODE, NETWORK_CODE, TIMEOUT_CODE } from './errors';

export const AUTOMATION_BASE = `${API_BASE}/automation`;

export type Applicability = 'current' | 'stale' | 'expired' | 'unavailable';
export type ApplicationStatus = 'not_applied' | 'applied' | 'undone';

export interface ProposalContext {
  document_id: string;
  draft_id: string;
  revision: number;
  content_sha256: string;
  variables_version: number;
  authorization_version: string;
}

export interface ProposalPreview {
  before_text: string;
  after_text: string;
  summary: string;
}

export interface AutomationProposal {
  proposal_id: string;
  context: ProposalContext;
  operations: Array<{
    op: 'replace_text';
    anchor: {
      snapshot_id: string;
      node_id: string;
      start_cp: number;
      end_cp: number;
      quote_sha256: string;
    };
    replacement_text: string;
  }>;
  preview: ProposalPreview;
  risk_flags: string[];
  review_receipt: { receipt_id: string; verdict: string; validator_version: string };
  expires_at: string;
  disposition: 'open' | 'accepted' | 'rejected';
  application_status: ApplicationStatus;
  applicability: Applicability;
  revision: number;
}

export interface ApplyReceipt {
  receipt_id: string;
  proposal_id: string;
  previous_revision: number;
  new_revision: number;
  new_checkpoint_id: string;
  content_sha256: string;
  variables_version: number;
  actor_user_id: string;
  applied_at: string;
  reversal_of_receipt_id: string | null;
}

export interface FixtureProposalInput {
  document_id: string;
  draft_id: string;
  search_text?: string;
  replacement_text?: string;
  expires_in_seconds?: number;
}

export interface ApplyInput {
  proposal_id: string;
  expected_snapshot_id: string;
  expected_draft_revision: number;
  lock_id: string;
  fencing_token: number;
  acknowledged_risk_codes: string[];
}

export interface UndoInput {
  expected_draft_revision: number;
  lock_id: string;
  fencing_token: number;
}

export interface AutomationOptions {
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
  idempotencyKey?: string;
  ifMatch?: string;
}

const isAbortError = (error: unknown): boolean =>
  typeof error === 'object' &&
  error !== null &&
  (error as { name?: string }).name === 'AbortError';

const errorDetail = (payload: unknown): unknown => {
  if (typeof payload !== 'object' || payload === null) return payload;
  const body = payload as { error?: Record<string, unknown> };
  return body.error ?? payload;
};

export const newIdempotencyKey = (prefix = 'web'): string =>
  `${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;

async function request<T>(
  path: string,
  init: RequestInit,
  { timeoutMs = DEFAULT_TIMEOUT_MS, fetchImpl }: AutomationOptions = {},
): Promise<T> {
  const doFetch = fetchImpl ?? globalThis.fetch;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await doFetch(`${AUTOMATION_BASE}${path}`, { ...init, signal: controller.signal });
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const body = (payload ?? {}) as {
        code?: string;
        message?: string;
        error?: { code?: string; message?: string };
      };
      const code = body.error?.code ?? body.code ?? `HTTP_${response.status}`;
      const message =
        body.error?.message ?? body.message ?? `request failed with status ${response.status}`;
      throw new ApiError(response.status, code, message, errorDetail(payload));
    }
    if (payload === null) throw new ApiError(200, INVALID_RESPONSE_CODE, 'empty response');
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

export function createFixtureProposal(
  input: FixtureProposalInput,
  options: AutomationOptions = {},
): Promise<AutomationProposal> {
  return request(
    '/proposals',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': options.idempotencyKey ?? newIdempotencyKey('proposal'),
      },
      body: JSON.stringify(input),
    },
    options,
  );
}

export function getProposal(
  proposalId: string,
  options: AutomationOptions = {},
): Promise<AutomationProposal> {
  return request(`/proposals/${encodeURIComponent(proposalId)}`, { method: 'GET' }, options);
}

export function decideProposal(
  proposalId: string,
  decision: 'accepted' | 'rejected',
  options: AutomationOptions = {},
): Promise<AutomationProposal> {
  return request(
    `/proposals/${encodeURIComponent(proposalId)}/decisions`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': options.idempotencyKey ?? newIdempotencyKey('decision'),
        ...(options.ifMatch ? { 'If-Match': options.ifMatch } : {}),
      },
      body: JSON.stringify({ decision }),
    },
    options,
  );
}

export function applyProposal(
  proposalId: string,
  input: ApplyInput,
  options: AutomationOptions = {},
): Promise<ApplyReceipt> {
  return request(
    `/proposals/${encodeURIComponent(proposalId)}/apply`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': options.idempotencyKey ?? newIdempotencyKey('apply'),
        ...(options.ifMatch ? { 'If-Match': options.ifMatch } : {}),
      },
      body: JSON.stringify(input),
    },
    options,
  );
}

export function undoApplication(
  receiptId: string,
  input: UndoInput,
  options: AutomationOptions = {},
): Promise<ApplyReceipt> {
  return request(
    `/applications/${encodeURIComponent(receiptId)}/undo`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': options.idempotencyKey ?? newIdempotencyKey('undo'),
        ...(options.ifMatch ? { 'If-Match': options.ifMatch } : {}),
      },
      body: JSON.stringify(input),
    },
    options,
  );
}