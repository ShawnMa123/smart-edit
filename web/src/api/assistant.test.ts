/** Task 5.1 — assistant client URL/method/header/error mapping. */

import { describe, expect, it } from 'vitest';

import {
  ASSISTANT_BASE,
  createRun,
  createSession,
  createSnapshot,
  getCitation,
  getRun,
  putFeedback,
} from './assistant';
import { NETWORK_CODE } from './errors';

interface Call {
  url: string;
  init: RequestInit;
}

const respond =
  (payload: unknown, status = 200) =>
  ((url: string, init: RequestInit) => {
    void url;
    void init;
    return Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      json: async () => payload,
    } as unknown as Response);
  }) as unknown as typeof fetch;

const record = (calls: Call[], payload: unknown, status = 200) =>
  ((url: string, init: RequestInit) => {
    calls.push({ url, init });
    return Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      json: async () => payload,
    } as unknown as Response);
  }) as unknown as typeof fetch;

describe('assistant client', () => {
  it('creates a snapshot without an idempotency key', async () => {
    const calls: Call[] = [];
    const snapshot = { id: 'snap_1' };

    const result = await createSnapshot(
      { document_id: 'doc-1', text: 'hello', content_sha256: 'a'.repeat(64) },
      { fetchImpl: record(calls, snapshot) },
    );

    expect(result.id).toBe('snap_1');
    expect(calls[0].url).toBe(`${ASSISTANT_BASE}/snapshots`);
    expect(calls[0].init.method).toBe('POST');
    expect((calls[0].init.headers as Record<string, string>)['Content-Type']).toBe(
      'application/json',
    );
    expect(
      (calls[0].init.headers as Record<string, string>)['Idempotency-Key'],
    ).toBeUndefined();
  });

  it('creates a session with the idempotency key and fake identity header', async () => {
    const calls: Call[] = [];
    await createSession(
      { workspace_id: 'ws_demo_01', locale: 'zh-CN' },
      'key-1',
      { fetchImpl: record(calls, { id: 'sess_1' }), user: 'user_a' },
    );

    expect(calls[0].url).toBe(`${ASSISTANT_BASE}/sessions`);
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toBe('key-1');
    expect(headers['X-Demo-User']).toBe('user_a');
    expect(JSON.parse(String(calls[0].init.body))).toEqual({
      workspace_id: 'ws_demo_01',
      locale: 'zh-CN',
    });
  });

  it('maps a camelCase selection onto the server field names', async () => {
    const calls: Call[] = [];
    await createRun(
      'sess_1',
      {
        question: 'What does this say?',
        selection: {
          nodeId: 'block_0',
          startOffset: 3,
          endOffset: 11,
          selectedText: 'URDG 758',
        },
      },
      'run-key',
      { fetchImpl: record(calls, { id: 'run_1', status: 'queued' }, 202) },
    );

    expect(calls[0].url).toBe(`${ASSISTANT_BASE}/sessions/sess_1/runs`);
    expect(JSON.parse(String(calls[0].init.body))).toEqual({
      question: 'What does this say?',
      selection: {
        node_id: 'block_0',
        start_offset: 3,
        end_offset: 11,
        selected_text: 'URDG 758',
      },
    });
  });

  it('reads a run and encodes citation ids', async () => {
    const calls: Call[] = [];
    await getRun('run 1', { fetchImpl: record(calls, { id: 'run 1' }) });
    await getCitation('msg/1', 'cite 2', { fetchImpl: record(calls, { citation_id: 'cite 2' }) });

    expect(calls[0].url).toBe(`${ASSISTANT_BASE}/runs/run%201`);
    expect(calls[1].url).toBe(
      `${ASSISTANT_BASE}/messages/msg%2F1/citations/cite%202`,
    );
  });

  it('puts feedback as JSON', async () => {
    const calls: Call[] = [];
    await putFeedback('msg_1', { rating: 'helpful' }, { fetchImpl: record(calls, { id: 'fb_1' }) });

    expect(calls[0].url).toBe(`${ASSISTANT_BASE}/messages/msg_1/feedback`);
    expect(calls[0].init.method).toBe('PUT');
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ rating: 'helpful' });
  });

  it('maps the error envelope onto a typed ApiError', async () => {
    const body = {
      error: {
        code: 'RESOURCE_NOT_FOUND',
        message: 'session not found',
        request_id: 'req_1',
        retryable: false,
      },
    };
    await expect(
      createSession(
        { workspace_id: 'ws_demo_01', locale: 'zh-CN' },
        'key-1',
        { fetchImpl: respond(body, 404) },
      ),
    ).rejects.toMatchObject({ status: 404, code: 'RESOURCE_NOT_FOUND' });
  });

  it('maps a transport rejection onto NETWORK', async () => {
    await expect(
      getRun('run_1', { fetchImpl: (() => Promise.reject(new Error('down'))) as unknown as typeof fetch }),
    ).rejects.toMatchObject({ status: 0, code: NETWORK_CODE });
  });

  it('sends web_search only when the caller opts in', async () => {
    const calls: Call[] = [];

    await createRun('sess_1', { question: 'q' }, 'key-1', {
      fetchImpl: record(calls, { id: 'run_1', status: 'queued' }, 202),
    });
    await createRun('sess_1', { question: 'q', web_search: true }, 'key-2', {
      fetchImpl: record(calls, { id: 'run_2', status: 'queued' }, 202),
    });

    expect(JSON.parse(String(calls[0].init.body))).not.toHaveProperty('web_search');
    expect(JSON.parse(String(calls[1].init.body)).web_search).toBe(true);
  });
});