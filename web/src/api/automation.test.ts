/** Automation client: headers, If-Match and error codes. */

import { describe, expect, it } from 'vitest';

import {
  AUTOMATION_BASE,
  applyProposal,
  createRun,
  decideProposal,
  getRun,
  undoApplication,
} from './automation';

interface Call {
  url: string;
  init: RequestInit;
}

const response = (payload: unknown, status = 200) =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
    headers: { get: () => null },
  }) as unknown as Response;

const record = (calls: Call[], payload: unknown, status = 200) =>
  ((url: string, init: RequestInit) => {
    calls.push({ url, init });
    return Promise.resolve(response(payload, status));
  }) as unknown as typeof fetch;

const proposal = {
  proposal_id: 'prop-1',
  context: {
    document_id: 'doc-1',
    draft_id: 'draft-1',
    revision: 1,
    content_sha256: 'a'.repeat(64),
    variables_version: 1,
    authorization_version: 'auth-demo-1',
  },
  operations: [],
  preview: { before_text: 'a', after_text: 'b', summary: 's' },
  risk_flags: [],
  review_receipt: { receipt_id: 'r', verdict: 'pass', validator_version: 'v1' },
  expires_at: '2030-01-01T00:00:00+00:00',
  disposition: 'open',
  application_status: 'not_applied',
  applicability: 'current',
  revision: 1,
};

describe('automation client', () => {
  it('creates a rewrite run with an idempotency key', async () => {
    const calls: Call[] = [];
    const run = {
      run_id: 'run-1',
      task_type: 'rewrite',
      document_id: 'doc-1',
      draft_id: 'draft-1',
      status: 'queued',
      stage: 'queued',
      revision: 1,
      created_at: '2026-01-01T00:00:00+00:00',
      deadline_at: '2026-01-01T00:02:00+00:00',
      started_at: null,
      finished_at: null,
      result_id: null,
      error: null,
    };
    await createRun(
      {
        task_type: 'rewrite',
        document_id: 'doc-1',
        draft_id: 'draft-1',
        input: { intent: 'replace_text', search_text: 'Amount:', replacement_text: 'Reviewed amount:' },
      },
      { fetchImpl: record(calls, run, 202), idempotencyKey: 'run-key' },
    );
    expect(calls[0].url).toBe(`${AUTOMATION_BASE}/runs`);
    expect((calls[0].init.headers as Record<string, string>)['Idempotency-Key']).toBe('run-key');

    await getRun('run-1', { fetchImpl: record(calls, run, 200) });
    expect(calls[1].url).toBe(`${AUTOMATION_BASE}/runs/run-1`);
  });

  it('sends proposal If-Match on decisions and draft If-Match on apply/undo', async () => {
    const calls: Call[] = [];
    await decideProposal('prop-1', 'accepted', {
      fetchImpl: record(calls, proposal, 201),
      ifMatch: 'proposal-1',
      idempotencyKey: 'd-key',
    });
    expect((calls[0].init.headers as Record<string, string>)['If-Match']).toBe('proposal-1');

    await applyProposal(
      'prop-1',
      {
        proposal_id: 'prop-1',
        expected_snapshot_id: 'a'.repeat(64),
        expected_draft_revision: 1,
        lock_id: 'lock-1',
        fencing_token: 2,
        acknowledged_risk_codes: [],
      },
      { fetchImpl: record(calls, { receipt_id: 'receipt-1' }, 201), ifMatch: 'draft-1' },
    );
    expect((calls[1].init.headers as Record<string, string>)['If-Match']).toBe('draft-1');

    await undoApplication(
      'receipt-1',
      { expected_draft_revision: 2, lock_id: 'lock-1', fencing_token: 2 },
      { fetchImpl: record(calls, { receipt_id: 'receipt-2' }, 201), ifMatch: 'draft-2' },
    );
    expect((calls[2].init.headers as Record<string, string>)['If-Match']).toBe('draft-2');
  });

  it('maps a 409 already_applied to the ApiError code', async () => {
    await expect(
      applyProposal(
        'prop-1',
        {
          proposal_id: 'prop-1',
          expected_snapshot_id: 'a'.repeat(64),
          expected_draft_revision: 1,
          lock_id: 'lock-1',
          fencing_token: 2,
          acknowledged_risk_codes: [],
        },
        {
          fetchImpl: record(
            [],
            { error: { code: 'already_applied', message: 'applied', existing_receipt_id: 'r1' } },
            409,
          ),
        },
      ),
    ).rejects.toMatchObject({ status: 409, code: 'already_applied' });
  });
});