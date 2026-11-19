/**
 * Aggregate the top-bar counts from existing APIs (`approval-ui-polish` D5).
 *
 * Approval counts come from the stage lists the principal is allowed to see; the unread count
 * comes from `/activity/unread-count`. A refused or failed request falls back to zero instead of
 * surfacing browser-local numbers as if they were server work.
 */

import { listApprovals } from '../api/approval';
import { getActivityUnreadCount } from '../api/identity';

export interface ApprovalCounts {
  approval: number;
  activityUnread: number;
}

export interface ApprovalCountOptions {
  fetchImpl?: typeof fetch;
}

/** Stages the principal may act on; no permission means no approval badge. */
export function approvalStages(permissions: string[]): Array<'first' | 'second'> {
  const stages: Array<'first' | 'second'> = [];
  if (permissions.includes('approval.first')) stages.push('first');
  if (permissions.includes('approval.second')) stages.push('second');
  return stages;
}

export async function loadApprovalCounts(
  orgId: string,
  permissions: string[],
  options: ApprovalCountOptions = {},
): Promise<ApprovalCounts> {
  const stages = approvalStages(permissions);

  const approval = await (stages.length === 0
    ? Promise.resolve(0)
    : Promise.all(
        stages.map((stage) => listApprovals(stage, options).catch(() => [])),
      ).then((lists) => {
        const seen = new Set<string>();
        for (const list of lists) {
          for (const item of list) seen.add(item.submission_id);
        }
        return seen.size;
      }));

  const activityUnread = await getActivityUnreadCount(orgId, 'all', options).catch(() => 0);

  return { approval, activityUnread };
}