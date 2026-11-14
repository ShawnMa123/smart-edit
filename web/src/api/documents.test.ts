/** Document-host client: URL, ETag/If-Match and 412 mapping. */

import { describe, expect, it } from 'vitest';

import {
  DOCUMENTS_BASE,
  createDocument,
  getDocument,
  saveDraft,
} from './documents';

interface Call {
  url: string;
  init: RequestInit;
}

const response = (payload: unknown, status = 200, etag: string | null = null) =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
    headers: { get: (name: string) => (name.toLowerCase() === 'etag' ? etag : null) },
  }) as unknown as Response;

const record = (calls: Call[], payload: unknown, status = 200, etag: string | null = null) =>
  ((url: string, init: RequestInit) => {
    calls.push({ url, init });
    return Promise.resolve(response(payload, status, etag));
  }) as unknown as typeof fetch;

const view = {
  document_id: 'doc-1',
  draft_id: 'draft-1',
  title: 'G',
  revision: 1,
  etag: 'draft-1',
  content: { type: 'doc', content: [] },
  text: '',
  content_sha256: 'a'.repeat(64),
  variables: {},
  variables_version: 1,
  updated_at: null,
};

describe('documents client', () => {
  it('creates and reads through /documents', async () => {
    const calls: Call[] = [];
    const created = await createDocument(
      { document_id: 'doc-1', text: 'hello' },
      { fetchImpl: record(calls, view, 201, '"draft-1"') },
    );
    expect(created.draft_id).toBe('draft-1');
    expect(calls[0].url).toBe(DOCUMENTS_BASE);
    expect(calls[0].init.method).toBe('POST');

    await getDocument('doc-1', { fetchImpl: record(calls, view, 200, '"draft-1"') });
    expect(calls[1].url).toBe(`${DOCUMENTS_BASE}/doc-1`);
  });

  it('sends If-Match and the lock on save', async () => {
    const calls: Call[] = [];
    await saveDraft(
      'doc-1',
      'draft-1',
      3,
      { text: 'next', lockId: 'lock-1', fencingToken: 7 },
      { fetchImpl: record(calls, view, 200, '"draft-4"') },
    );
    const headers = calls[0].init.headers as Record<string, string>;
    expect(calls[0].url).toBe(`${DOCUMENTS_BASE}/doc-1/drafts/draft-1`);
    expect(calls[0].init.method).toBe('PUT');
    expect(headers['If-Match']).toBe('"draft-3"');
    const body = JSON.parse(String(calls[0].init.body));
    expect(body.lock_id).toBe('lock-1');
    expect(body.fencing_token).toBe(7);
  });

  it('keeps the 412 detail instead of treating it as a network error', async () => {
    const fetchImpl = record(
      [],
      {
        error: {
          code: 'stale_draft',
          message: 'moved',
          current_revision: 4,
          content_sha256: 'b'.repeat(64),
        },
      },
      412,
    );
    await expect(
      saveDraft('doc-1', 'draft-1', 3, { text: 'x', lockId: 'l', fencingToken: 1 }, { fetchImpl }),
    ).rejects.toMatchObject({
      status: 412,
      code: 'stale_draft',
      detail: { current_revision: 4 },
    });
  });
});