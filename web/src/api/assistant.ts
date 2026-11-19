/**
 * Knowledge-assistant HTTP client (task 5.1).
 *
 * One place talks to `/assistant/*`; everything injects `fetchImpl` in tests so URL, method, headers
 * and the `{error: {...}}` contract are asserted without a live server.
 */

import { API_BASE } from './client';
import { ApiError, NETWORK_CODE, TIMEOUT_CODE } from './errors';
import type {
  AssistantErrorBody,
  AssistantSelection,
  AssistantSnapshot,
  Capabilities,
  EvidenceDetail,
  Feedback,
  FeedbackInput,
  Message,
  Page,
  Run,
  RunAccepted,
  Session,
} from './assistantTypes';

export const ASSISTANT_BASE = `${API_BASE}/assistant`;
export const ASSISTANT_TIMEOUT_MS = 30_000;

export interface AssistantOptions {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  /** POC-only fake identity header; the server still decides the principal. */
  user?: string;
}

interface RequestConfig extends AssistantOptions {
  method: 'GET' | 'POST' | 'PUT';
  body?: unknown;
  idempotencyKey?: string;
}

const isAbortError = (error: unknown): boolean =>
  typeof error === 'object' && error !== null && (error as { name?: string }).name === 'AbortError';

async function requestJson<T>(path: string, config: RequestConfig): Promise<T> {
  const doFetch = config.fetchImpl ?? globalThis.fetch;
  const controller = new AbortController();
  const timeoutMs = config.timeoutMs ?? ASSISTANT_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers: Record<string, string> = {};
  if (config.body !== undefined) headers['Content-Type'] = 'application/json';
  if (config.idempotencyKey) headers['Idempotency-Key'] = config.idempotencyKey;
  if (config.user) headers['X-Demo-User'] = config.user;
  try {
    const response = await doFetch(`${ASSISTANT_BASE}${path}`, {
      method: config.method,
      headers,
      body: config.body === undefined ? undefined : JSON.stringify(config.body),
      signal: controller.signal,
    });
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const body = (payload ?? {}) as { error?: AssistantErrorBody };
      const error = body.error;
      throw new ApiError(
        response.status,
        error?.code ?? `HTTP_${response.status}`,
        error?.message ?? `assistant request failed with status ${response.status}`,
        error,
      );
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (isAbortError(error)) {
      throw new ApiError(0, TIMEOUT_CODE, `assistant request aborted after ${timeoutMs} ms`);
    }
    throw new ApiError(0, NETWORK_CODE, (error as Error)?.message ?? 'network error');
  } finally {
    clearTimeout(timer);
  }
}

let keySequence = 0;

/** Unique per action; the server hashes the body so a retried different request is a 409. */
export function newIdempotencyKey(prefix = 'web'): string {
  keySequence += 1;
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${keySequence}`;
  return `${prefix}-${random}`;
}

export function createSnapshot(
  input: {
    document_id: string;
    text: string;
    content_sha256: string;
    version_label?: string | null;
  },
  options: AssistantOptions = {},
): Promise<AssistantSnapshot> {
  return requestJson('/snapshots', { ...options, method: 'POST', body: input });
}

export function createSession(
  input: {
    workspace_id: string;
    locale: 'zh-CN' | 'en';
    document_id?: string | null;
    snapshot_id?: string | null;
    attachment_ids?: string[];
  },
  idempotencyKey: string,
  options: AssistantOptions = {},
): Promise<Session> {
  return requestJson('/sessions', {
    ...options,
    method: 'POST',
    body: input,
    idempotencyKey,
  });
}

export function listSessions(
  workspaceId: string,
  options: AssistantOptions = {},
): Promise<Page<Session>> {
  return requestJson(`/sessions?workspace_id=${encodeURIComponent(workspaceId)}`, {
    ...options,
    method: 'GET',
  });
}

export function getSession(sessionId: string, options: AssistantOptions = {}): Promise<Session> {
  return requestJson(`/sessions/${encodeURIComponent(sessionId)}`, { ...options, method: 'GET' });
}

export interface RunInput {
  question: string;
  selection?: AssistantSelection | null;
  applicable_on?: string | null;
  jurisdiction_codes?: string[];
  rule_version?: string | null;
  /** Per-run opt-in for the web retrieval layer; omitted means off. */
  web_search?: boolean;
  /** Who chose `web_search` (`knowledge-simple-ask`): the toggle or the deployment default. */
  web_search_source?: 'user' | 'default';
}

const toServerSelection = (selection: AssistantSelection): Record<string, unknown> => ({
  node_id: selection.nodeId,
  start_offset: selection.startOffset,
  end_offset: selection.endOffset,
  selected_text: selection.selectedText,
});

export function createRun(
  sessionId: string,
  input: RunInput,
  idempotencyKey: string,
  options: AssistantOptions = {},
): Promise<RunAccepted> {
  const body = {
    question: input.question,
    ...(input.selection ? { selection: toServerSelection(input.selection) } : {}),
    ...(input.applicable_on ? { applicable_on: input.applicable_on } : {}),
    ...(input.jurisdiction_codes?.length ? { jurisdiction_codes: input.jurisdiction_codes } : {}),
    ...(input.rule_version ? { rule_version: input.rule_version } : {}),
    ...(input.web_search ? { web_search: true } : {}),
    ...(input.web_search_source ? { web_search_source: input.web_search_source } : {}),
  };
  return requestJson(`/sessions/${encodeURIComponent(sessionId)}/runs`, {
    ...options,
    method: 'POST',
    body,
    idempotencyKey,
  });
}

export function getRun(runId: string, options: AssistantOptions = {}): Promise<Run> {
  return requestJson(`/runs/${encodeURIComponent(runId)}`, { ...options, method: 'GET' });
}

export function cancelRun(
  runId: string,
  idempotencyKey: string,
  options: AssistantOptions = {},
): Promise<{ run_id: string; status: 'cancelled'; cancelled_at: string }> {
  return requestJson(`/runs/${encodeURIComponent(runId)}/cancel`, {
    ...options,
    method: 'POST',
    idempotencyKey,
  });
}

export function listMessages(
  sessionId: string,
  options: AssistantOptions = {},
): Promise<Page<Message>> {
  return requestJson(`/sessions/${encodeURIComponent(sessionId)}/messages`, {
    ...options,
    method: 'GET',
  });
}

export function getCitation(
  messageId: string,
  citationId: string,
  options: AssistantOptions = {},
): Promise<EvidenceDetail> {
  return requestJson(
    `/messages/${encodeURIComponent(messageId)}/citations/${encodeURIComponent(citationId)}`,
    { ...options, method: 'GET' },
  );
}

export function putFeedback(
  messageId: string,
  input: FeedbackInput,
  options: AssistantOptions = {},
): Promise<Feedback> {
  return requestJson(`/messages/${encodeURIComponent(messageId)}/feedback`, {
    ...options,
    method: 'PUT',
    body: input,
  });
}

export function getCapabilities(options: AssistantOptions = {}): Promise<Capabilities> {
  return requestJson('/capabilities', { ...options, method: 'GET' });
}

export interface AssistantClient {
  createSnapshot: typeof createSnapshot;
  createSession: typeof createSession;
  listSessions: typeof listSessions;
  getSession: typeof getSession;
  createRun: typeof createRun;
  getRun: typeof getRun;
  cancelRun: typeof cancelRun;
  listMessages: typeof listMessages;
  getCitation: typeof getCitation;
  putFeedback: typeof putFeedback;
  getCapabilities: typeof getCapabilities;
}

export const assistantClient: AssistantClient = {
  createSnapshot,
  createSession,
  listSessions,
  getSession,
  createRun,
  getRun,
  cancelRun,
  listMessages,
  getCitation,
  putFeedback,
  getCapabilities,
};