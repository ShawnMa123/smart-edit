import { describe, expect, it, vi } from 'vitest';

import { approvalStages, loadApprovalCounts } from './approvalCounts';

const response = (status: number, body: unknown) =>
  ({
    ok: status < 400,
    status,
    json: async () => body,
  }) as unknown as Response;

describe('approvalStages', () => {
  it('only asks for the stages the principal can decide', () => {
    expect(approvalStages([])).toEqual([]);
    expect(approvalStages(['approval.submit'])).toEqual([]);
    expect(approvalStages(['approval.first'])).toEqual(['first']);
    expect(approvalStages(['approval.second'])).toEqual(['second']);
    expect(approvalStages(['approval.first', 'approval.second'])).toEqual(['first', 'second']);
  });
});

describe('loadApprovalCounts', () => {
  it('aggregates both approval stages without double counting and reads server unread', async () => {
    const calls: string[] = [];
    const fetchImpl = vi.fn(async (url: string) => {
      const path = String(url);
      calls.push(path);
      if (path.includes('/approvals?stage=first')) {
        return response(200, [{ submission_id: 'a' }, { submission_id: 'b' }]);
      }
      if (path.includes('/approvals?stage=second')) {
        return response(200, [{ submission_id: 'b' }, { submission_id: 'c' }]);
      }
      if (path.includes('/activity/unread-count')) return response(200, { unread_count: 3 });
      return response(404, { code: 'NOT_FOUND' });
    }) as unknown as typeof fetch;

    const counts = await loadApprovalCounts('org_1', ['approval.first', 'approval.second'], {
      fetchImpl,
    });

    expect(counts).toEqual({ approval: 3, activityUnread: 3 });
    expect(calls.some((url) => url.includes('stage=first'))).toBe(true);
    expect(calls.some((url) => url.includes('stage=second'))).toBe(true);
    expect(calls.some((url) => url.includes('/activity/unread-count?org_id=org_1&scope=all'))).toBe(
      true,
    );
  });

  it('falls back to zero when the server refuses the counts', async () => {
    const fetchImpl = vi.fn(async () => response(403, { code: 'FORBIDDEN' })) as unknown as typeof fetch;

    await expect(
      loadApprovalCounts('org_1', ['approval.first'], { fetchImpl }),
    ).resolves.toEqual({ approval: 0, activityUnread: 0 });
  });

  it('does not call the approval API without a pending-permission role', async () => {
    const calls: string[] = [];
    const fetchImpl = vi.fn(async (url: string) => {
      calls.push(String(url));
      return response(200, { unread_count: 1 });
    }) as unknown as typeof fetch;

    await expect(loadApprovalCounts('org_1', ['approval.submit'], { fetchImpl })).resolves.toEqual({
      approval: 0,
      activityUnread: 1,
    });
    expect(calls.some((url) => url.includes('/approvals'))).toBe(false);
  });
});