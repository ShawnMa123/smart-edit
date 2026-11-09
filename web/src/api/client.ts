/**
 * The only place that talks HTTP (design D10). Everything else depends on this module, so a demo can
 * swap a mock server in and no component can bypass the error contract.
 */

import { assertEnvelope } from './envelope';
import { ApiError, NETWORK_CODE, TIMEOUT_CODE } from './errors';
import type { RunEnvelope } from './types';

export const API_BASE: string = import.meta.env?.VITE_API_BASE ?? '/api';
export const DEFAULT_TIMEOUT_MS = 120_000;

export interface RequestOptions {
  timeoutMs?: number;
  /** Injected in tests; defaults to the global fetch. */
  fetchImpl?: typeof fetch;
  /** Template-driven audit: narrows which published template applies (`?template=`). */
  template?: string;
}

const isAbortError = (error: unknown): boolean =>
  typeof error === 'object' &&
  error !== null &&
  (error as { name?: string }).name === 'AbortError';

async function request(
  path: string,
  init: RequestInit,
  { timeoutMs = DEFAULT_TIMEOUT_MS, fetchImpl }: RequestOptions = {},
): Promise<RunEnvelope> {
  const doFetch = fetchImpl ?? globalThis.fetch;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await doFetch(`${API_BASE}${path}`, { ...init, signal: controller.signal });
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
    return assertEnvelope(payload);
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

/** Create one run from pasted document text. */
export function createRun(text: string, options: RequestOptions = {}): Promise<RunEnvelope> {
  return request(
    '/runs',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    },
    options,
  );
}

/**
 * Create one run from uploaded files (`document-import`).
 *
 * No `Content-Type` header on purpose: the browser must set the multipart boundary itself, otherwise
 * FastAPI parses zero files and answers `EMPTY_SUBMISSION`.
 */
export function createRunWithFiles(
  files: File[],
  options: RequestOptions = {},
): Promise<RunEnvelope> {
  const form = new FormData();
  for (const file of files) {
    form.append('files', file, file.name);
  }
  return request('/runs', { method: 'POST', body: form }, options);
}

/** Trigger a stage chain (`parse` / `extract` / `normalize` / `audit`).
 *
 * `options.template` asks for template-driven audit; it can only narrow which published template
 * applies, never select a version (design D18).
 */
export function triggerStage(
  threadId: string,
  stage: string,
  options: RequestOptions = {},
): Promise<RunEnvelope> {
  const template = options.template?.trim();
  const query = template ? `?template=${encodeURIComponent(template)}` : '';
  return request(
    `/runs/${encodeURIComponent(threadId)}/stages/${encodeURIComponent(stage)}${query}`,
    { method: 'POST' },
    options,
  );
}

export function getRun(threadId: string, options: RequestOptions = {}): Promise<RunEnvelope> {
  return request(`/runs/${encodeURIComponent(threadId)}`, { method: 'GET' }, options);
}