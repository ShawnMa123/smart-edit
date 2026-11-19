import { describe, expect, it, vi } from 'vitest';

import {
  decideApproval,
  getApproval,
  listApprovals,
  listSubmissions,
  submitDocument,
} from './approval';
import { ApiError } from './errors';

const response = (status: number, body: unknown) =>
  ({
    ok: status < 400,
    status,
    json: async () => body,
  }) as unknown as Response;

const summary = {
  submission_id: 'sub_1',
  document_id: 'doc_1',
  revision: 3,
  content_sha256: 'a'.repeat(64),
  status: 'pending_first',
  submitted_by: 'u1',
  created_at: '2026-11-19T00:00:00Z',
  request_id: 'apr_1',
  current_stage: 'first',
  approval_revision: 1,
  latest_comment: null,
  latest_decision: null,
  latest_actor: null,
  latest_decided_at: null,
};

describe('approval client', () => {
  it('submits with credentials and the CSRF signal', async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const fetchImpl = vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url: String(url), init });
      return response(201, { submission: summary, request: { request_id: 'apr_1', status: 'pending_first' } });
    }) as unknown as typeof fetch;

    await submitDocument(
      'doc_1',
      { lockId: 'lock_1', fencingToken: 2, expectedRevision: 3, contentSha256: 'a'.repeat(64) },
      { fetchImpl },
    );
    expect(calls[0].url).toBe('/api/documents/doc_1/submissions');
    expect(calls[0].init.method).toBe('POST');
    expect(calls[0].init.credentials).toBe('include');
    expect((calls[0].init.headers as Record<string, string>)['X-Requested-With']).toBe('smart-edit');
    expect(JSON.parse(String(calls[0].init.body))).toEqual({
      lock_id: 'lock_1',
      fencing_token: 2,
      expected_revision: 3,
      content_sha256: 'a'.repeat(64),
    });
  });

  it('lists submissions, inboxes and detail, and posts decisions', async () => {
    const urls: string[] = [];
    const fetchImpl = vi.fn(async (url: string, init: RequestInit) => {
      urls.push(`${init.method} ${String(url)}`);
      if (String(url).includes('/decisions')) {
        return response(201, { ...summary, text: 'body', can_decide: false, steps: [] });
      }
      if (String(url).includes('/approvals/')) {
        return response(200, { ...summary, text: 'body', can_decide: true, steps: [] });
      }
      return response(200, [summary]);
    }) as unknown as typeof fetch;
    const options = { fetchImpl };
    await listSubmissions('doc_1', options);
    await listApprovals('first', options);
    await getApproval('apr_1', options);
    await decideApproval(
      'apr_1',
      { decision: 'return', comment: 'add expiry', expectedRevision: 1 },
      options,
    );
    expect(urls).toEqual([
      'GET /api/documents/doc_1/submissions',
      'GET /api/approvals?stage=first',
      'GET /api/approvals/apr_1',
      'POST /api/approvals/apr_1/decisions',
    ]);
  });

  it('maps the wrapped host error body', async () => {
    const fetchImpl = vi.fn(async () =>
      response(422, { error: { code: 'comment_required', message: 'comment required' } }),
    ) as unknown as typeof fetch;
    await expect(
      decideApproval('apr_1', { decision: 'return', expectedRevision: 1 }, { fetchImpl }),
    ).rejects.toMatchObject({ status: 422, code: 'comment_required' });
    await expect(
      decideApproval('apr_1', { decision: 'return', expectedRevision: 1 }, { fetchImpl }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});