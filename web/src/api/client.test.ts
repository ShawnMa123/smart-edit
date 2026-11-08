/** Tasks 4.1 / 4.3 — the transport client and the envelope guard. */

import { describe, expect, it } from 'vitest';

import { API_BASE, createRun, getRun, triggerStage } from './client';
import { INVALID_RESPONSE_CODE, TIMEOUT_CODE } from './errors';
import { doneEnvelope } from '../test/fixtures';

interface Call {
  url: string;
  init: RequestInit;
}

const respond = (payload: unknown, status = 200) =>
  ((url: string, init: RequestInit) => {
    void url;
    void init;
    return Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => payload } as unknown as Response);
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

const reject = (error: unknown) =>
  (() => Promise.reject(error)) as unknown as typeof fetch;

describe('createRun', () => {
  it('posts the document text and returns the envelope', async () => {
    const calls: Call[] = [];
    const envelope = doneEnvelope();

    const result = await createRun('Demand Guarantee', { fetchImpl: record(calls, envelope) });

    expect(result.thread_id).toBe(envelope.thread_id);
    expect(calls[0].url).toBe(`${API_BASE}/runs`);
    expect(calls[0].init.method).toBe('POST');
    expect(calls[0].init.body).toBe(JSON.stringify({ text: 'Demand Guarantee' }));
  });

  it('maps a refusal body onto a typed ApiError', async () => {
    const body = { code: 'REFUSED', message: 'missing prerequisite keys [\'files\']', detail: { missing: ['files'] } };

    await expect(
      createRun('text', { fetchImpl: respond(body, 409) }),
    ).rejects.toMatchObject({ status: 409, code: 'REFUSED', detail: { missing: ['files'] } });
  });

  it('rejects a 200 that lacks stages', async () => {
    await expect(
      createRun('text', { fetchImpl: respond({ thread_id: 'R-1', fields: {} }) }),
    ).rejects.toMatchObject({ code: INVALID_RESPONSE_CODE });
  });

  it('reports a timeout when the request is aborted', async () => {
    const abort = Object.assign(new Error('aborted'), { name: 'AbortError' });

    await expect(createRun('text', { fetchImpl: reject(abort) })).rejects.toMatchObject({
      code: TIMEOUT_CODE,
    });
  });

  it('reports a transport failure distinctly from a timeout', async () => {
    await expect(
      createRun('text', { fetchImpl: reject(new Error('connection refused')) }),
    ).rejects.toMatchObject({ code: 'NETWORK' });
  });
});

describe('triggerStage / getRun', () => {
  it('addresses the stage path with encoded ids', async () => {
    const calls: Call[] = [];
    await triggerStage('R-1', 'normalize', { fetchImpl: record(calls, doneEnvelope()) });

    expect(calls[0].url).toBe(`${API_BASE}/runs/R-1/stages/normalize`);
    expect(calls[0].init.method).toBe('POST');
  });

  it('reads a run', async () => {
    const calls: Call[] = [];
    await getRun('R-1', { fetchImpl: record(calls, doneEnvelope()) });

    expect(calls[0].url).toBe(`${API_BASE}/runs/R-1`);
    expect(calls[0].init.method).toBe('GET');
  });

  it('names a template when template-driven audit is asked for', async () => {
    const calls: Call[] = [];
    await triggerStage('R-1', 'audit', {
      fetchImpl: record(calls, doneEnvelope()),
      template: 'adidas-guarantee',
    });

    expect(calls[0].url).toBe(`${API_BASE}/runs/R-1/stages/audit?template=adidas-guarantee`);
    expect(calls[0].init.method).toBe('POST');
  });

  it('sends no template parameter when none was named', async () => {
    const calls: Call[] = [];
    await triggerStage('R-1', 'audit', { fetchImpl: record(calls, doneEnvelope()), template: '   ' });

    expect(calls[0].url).toBe(`${API_BASE}/runs/R-1/stages/audit`);
  });
});