/** Tasks 4.1 / 4.3 — the transport client and the envelope guard. */

import { describe, expect, it } from 'vitest';

import {
  API_BASE,
  askGate,
  createRun,
  createRunWithFiles,
  disposeFinding,
  getRun,
  triggerStage,
} from './client';
import { INVALID_RESPONSE_CODE, TIMEOUT_CODE } from './errors';
import type { DispositionResponse, GateResponse } from './types';
import { doneEnvelope, gateDecision } from '../test/fixtures';

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

describe('createRunWithFiles', () => {
  it('posts the files as multipart and lets the browser set the boundary', async () => {
    const calls: Call[] = [];
    const file = new File(['%PDF-1.4 fake'], 'guarantee.pdf', { type: 'application/pdf' });

    await createRunWithFiles([file], { fetchImpl: record(calls, doneEnvelope()) });

    expect(calls[0].url).toBe(`${API_BASE}/runs`);
    expect(calls[0].init.method).toBe('POST');
    expect(calls[0].init.body).toBeInstanceOf(FormData);
    expect((calls[0].init.body as FormData).get('files')).toBeTruthy();
    // A Content-Type here would replace the browser's boundary and the server would see zero files.
    expect(calls[0].init.headers).toBeUndefined();
  });

  it('sends every chosen file under the same field name', async () => {
    const calls: Call[] = [];
    const files = [
      new File(['a'], 'one.pdf', { type: 'application/pdf' }),
      new File(['b'], 'two.docx'),
    ];

    await createRunWithFiles(files, { fetchImpl: record(calls, doneEnvelope()) });

    expect((calls[0].init.body as FormData).getAll('files')).toHaveLength(2);
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

describe('askGate / disposeFinding', () => {
  it('asks one operation with the candidate digest the caller supplies', async () => {
    const calls: Call[] = [];
    const response: GateResponse = {
      thread_id: 'R-1',
      operation: 'start_approval',
      gate: gateDecision({ decision: 'allowed', reason_codes: [] }),
      verification: null,
    };

    const result = await askGate('R-1', 'start_approval', 'digest-1', {
      fetchImpl: record(calls, response),
    });

    expect(result.gate.decision).toBe('allowed');
    expect(calls[0].url).toBe(`${API_BASE}/runs/R-1/gate`);
    expect(calls[0].init.method).toBe('POST');
    expect(JSON.parse(calls[0].init.body as string)).toEqual({
      operation: 'start_approval',
      candidate_digest: 'digest-1',
    });
  });

  it('appends a disposition with actor and reason', async () => {
    const calls: Call[] = [];
    const response: DispositionResponse = {
      thread_id: 'R-1',
      finding_id: 'B-001',
      events: [],
      latest: 'rejected',
    };

    await disposeFinding('R-1', 'B-001', 'rejected', 'vendor will resend', 'ops', {
      fetchImpl: record(calls, response),
    });

    expect(calls[0].url).toBe(`${API_BASE}/runs/R-1/findings/B-001/disposition`);
    expect(JSON.parse(calls[0].init.body as string)).toEqual({
      disposition: 'rejected',
      reason: 'vendor will resend',
      actor: 'ops',
    });
  });

  it('keeps the server error code for a refused disposition', async () => {
    const body = { code: 'REASON_REQUIRED', message: 'rejecting a critical finding requires a reason' };

    await expect(
      disposeFinding('R-1', 'B-001', 'rejected', undefined, 'ops', {
        fetchImpl: respond(body, 400),
      }),
    ).rejects.toMatchObject({ status: 400, code: 'REASON_REQUIRED' });
  });
});