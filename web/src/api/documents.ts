/** Document-host client: drafts, ETags, conditional saves and locks. */

import type { RichDocument } from '../rich/richDocument';
import type { SubmissionSummary } from './approvalTypes';
import { API_BASE, DEFAULT_TIMEOUT_MS } from './client';
import { ApiError, INVALID_RESPONSE_CODE, NETWORK_CODE, TIMEOUT_CODE } from './errors';

export const DOCUMENTS_BASE = `${API_BASE}/documents`;

export interface DraftView {
  document_id: string;
  draft_id: string;
  title: string | null;
  revision: number;
  etag: string;
  content: RichDocument;
  text: string;
  content_sha256: string;
  variables: Record<string, unknown>;
  variables_version: number;
  updated_at: string | null;
  /** `draft` when no submission exists; otherwise the latest submission status. */
  submission_status?: SubmissionSummary['status'] | 'draft';
  submission?: (SubmissionSummary & { created_at: string }) | null;
}

export interface DocumentCreateInput {
  document_id?: string;
  title?: string;
  content?: RichDocument;
  text?: string;
  variables?: Record<string, unknown>;
}

export interface DraftSaveInput {
  content?: RichDocument;
  text?: string;
  lockId: string;
  fencingToken: number;
}

export interface VariablesUpdateInput {
  variables: Record<string, unknown>;
  lockId: string;
  fencingToken: number;
}

export interface LockView {
  lock_id: string;
  draft_id: string;
  owner_user_id: string;
  lease_until: string;
  fencing_token: number;
  released_at: string | null;
}

export interface HostOptions {
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
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

async function request<T>(
  path: string,
  init: RequestInit,
  { timeoutMs = DEFAULT_TIMEOUT_MS, fetchImpl }: HostOptions = {},
): Promise<{ data: T; etag: string | null }> {
  const doFetch = fetchImpl ?? globalThis.fetch;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const method = (init.method ?? 'GET').toUpperCase();
  const headers =
    method === 'GET'
      ? init.headers
      : { ...((init.headers as Record<string, string> | undefined) ?? {}), 'X-Requested-With': 'smart-edit' };
  try {
    const response = await doFetch(`${DOCUMENTS_BASE}${path}`, {
      ...init,
      headers,
      credentials: 'include',
      signal: controller.signal,
    });
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
    return { data: payload as T, etag: response.headers?.get?.('ETag') ?? null };
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

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'smart-edit' },
  body: JSON.stringify(body),
});

export async function createDocument(
  input: DocumentCreateInput,
  options: HostOptions = {},
): Promise<DraftView> {
  return (await request<DraftView>('', json(input), options)).data;
}

export interface DocumentSummary {
  document_id: string;
  title: string;
  revision: number;
  draft_id: string | null;
  submission_status: SubmissionSummary['status'] | 'draft';
  updated_at: string | null;
  owner_user_id: string;
  department_id: string | null;
}

export async function listDocuments(options: HostOptions = {}): Promise<DocumentSummary[]> {
  return (await request<DocumentSummary[]>('', { method: 'GET' }, options)).data;
}

export async function getDocument(documentId: string, options: HostOptions = {}): Promise<DraftView> {
  return (await request<DraftView>(`/${encodeURIComponent(documentId)}`, { method: 'GET' }, options))
    .data;
}

export async function getDraft(
  documentId: string,
  draftId: string,
  options: HostOptions = {},
): Promise<DraftView> {
  return (
    await request<DraftView>(
      `/${encodeURIComponent(documentId)}/drafts/${encodeURIComponent(draftId)}`,
      { method: 'GET' },
      options,
    )
  ).data;
}

export async function saveDraft(
  documentId: string,
  draftId: string,
  revision: number,
  input: DraftSaveInput,
  options: HostOptions = {},
): Promise<DraftView> {
  return (
    await request<DraftView>(
      `/${encodeURIComponent(documentId)}/drafts/${encodeURIComponent(draftId)}`,
      {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'If-Match': `"draft-${revision}"`,
        },
        body: JSON.stringify({
          content: input.content,
          text: input.text,
          lock_id: input.lockId,
          fencing_token: input.fencingToken,
        }),
      },
      options,
    )
  ).data;
}

export async function updateVariables(
  documentId: string,
  draftId: string,
  variablesVersion: number,
  input: VariablesUpdateInput,
  options: HostOptions = {},
): Promise<DraftView> {
  return (
    await request<DraftView>(
      `/${encodeURIComponent(documentId)}/drafts/${encodeURIComponent(draftId)}/variables`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'If-Match': `"variables-${variablesVersion}"`,
        },
        body: JSON.stringify({
          variables: input.variables,
          lock_id: input.lockId,
          fencing_token: input.fencingToken,
        }),
      },
      options,
    )
  ).data;
}

export async function acquireLock(
  documentId: string,
  draftId: string,
  options: HostOptions = {},
): Promise<LockView> {
  return (
    await request<LockView>(
      `/${encodeURIComponent(documentId)}/drafts/${encodeURIComponent(draftId)}/lock`,
      json({ lease_seconds: 30 }),
      options,
    )
  ).data;
}

export async function releaseLock(
  documentId: string,
  lockId: string,
  options: HostOptions = {},
): Promise<LockView> {
  return (
    await request<LockView>(
      `/${encodeURIComponent(documentId)}/locks/${encodeURIComponent(lockId)}/release`,
      { method: 'POST' },
      options,
    )
  ).data;
}