/** Submission/approval HTTP client. Cookies + the CSRF signal are mandatory on writes. */

import { API_BASE } from './client';
import { ApiError } from './errors';
import type {
  ApprovalDecisionInput,
  ApprovalDetail,
  ApprovalSummary,
  SubmissionCreateInput,
  SubmissionSummary,
} from './approvalTypes';

export interface ApprovalOptions {
  fetchImpl?: typeof fetch;
}

async function request<T>(
  path: string,
  method: 'GET' | 'POST',
  body: unknown,
  options: ApprovalOptions = {},
): Promise<T> {
  const doFetch = options.fetchImpl ?? globalThis.fetch;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') headers['X-Requested-With'] = 'smart-edit';
  const response = await doFetch(`${API_BASE}${path}`, {
    method,
    headers,
    credentials: 'include',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (payload ?? {}) as {
      code?: string;
      message?: string;
      detail?: unknown;
      error?: { code?: string; message?: string };
    };
    throw new ApiError(
      response.status,
      error.error?.code ?? error.code ?? `HTTP_${response.status}`,
      error.error?.message ?? error.message ?? `request failed with status ${response.status}`,
      error.detail,
    );
  }
  return payload as T;
}

export const submitDocument = (
  documentId: string,
  input: SubmissionCreateInput,
  options?: ApprovalOptions,
) =>
  request<{ submission: SubmissionSummary; request: { request_id: string; status: string } }>(
    `/documents/${encodeURIComponent(documentId)}/submissions`,
    'POST',
    {
      lock_id: input.lockId,
      fencing_token: input.fencingToken,
      expected_revision: input.expectedRevision,
      content_sha256: input.contentSha256,
    },
    options,
  );

export const listSubmissions = (documentId: string, options?: ApprovalOptions) =>
  request<SubmissionSummary[]>(
    `/documents/${encodeURIComponent(documentId)}/submissions`,
    'GET',
    undefined,
    options,
  );

export const listApprovals = (stage: 'first' | 'second' | null, options?: ApprovalOptions) => {
  const query = stage ? `?stage=${stage}` : '';
  return request<ApprovalSummary[]>(`/approvals${query}`, 'GET', undefined, options);
};

export const getApproval = (requestId: string, options?: ApprovalOptions) =>
  request<ApprovalDetail>(`/approvals/${encodeURIComponent(requestId)}`, 'GET', undefined, options);

export const decideApproval = (
  requestId: string,
  input: ApprovalDecisionInput,
  options?: ApprovalOptions,
) =>
  request<ApprovalDetail>(
    `/approvals/${encodeURIComponent(requestId)}/decisions`,
    'POST',
    {
      decision: input.decision,
      comment: input.comment,
      expected_revision: input.expectedRevision,
    },
    options,
  );