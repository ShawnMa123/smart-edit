/**
 * Approval walkthrough: how a snapshot becomes approved.
 *
 * Approvals by other roles cannot be performed from one session, so the tour explains the handoff
 * instead of pretending to switch accounts. The Approve click is gated by the launcher choice.
 */

import type { Tour } from '../types';

const T = (name: string): string => `[data-tour="${name}"]`;

export const APPROVAL_TOUR: Tour = {
  id: 'approval',
  version: 1,
  title: 'Two-person approval',
  description:
    'Snapshot, separation of duties and the handoff between reviewers — about 90 seconds. No email is sent in this build.',
  steps: [
    {
      id: 'open-approval',
      title: 'Open the Approval module',
      target: T('topbar-approval'),
      placement: 'bottom',
      action: { kind: 'click', selector: T('topbar-approval') },
      until: { kind: 'selector', selector: T('approval-document') },
      timeoutMs: 15_000,
      body:
        'Approval works on the submitted snapshot (revision + sha), never on the live draft. The top card shows the current document and its status.',
    },
    {
      id: 'tabs',
      title: 'The tabs depend on your role',
      target: T('approval-tabs'),
      placement: 'bottom',
      until: { kind: 'selector', selector: T('approval-tabs') },
      body:
        'First approval, Second approval, My submissions and Documents only appear when your role includes them. That is the separation of duties made visible.',
    },
    {
      id: 'first-tab',
      title: 'First approver queue',
      target: T('approval-tab-first'),
      placement: 'bottom',
      optional: true,
      action: { kind: 'click', selector: T('approval-tab-first') },
      body:
        'Bank Operations reviews the submission here. Select a record to see its timeline and decisions. Returning or rejecting requires a comment.',
    },
    {
      id: 'approve',
      title: 'Approve or return',
      target: T('approval-approve'),
      placement: 'top',
      optional: true,
      action: { kind: 'click', selector: T('approval-approve') },
      requiresApprovalAuto: true,
      body:
        'The submitter cannot approve their own document. If you kept the submission step manual, click Approve yourself; autopilot only clicks when you allowed it.',
    },
    {
      id: 'handoff',
      title: 'Hand off to the second approver',
      placement: 'center',
      body:
        'Compliance approves second, in their own window (compliance@atlas-trade.test). The document stays read-only while any approval is pending.',
    },
    {
      id: 'done',
      title: 'That is the approval loop',
      placement: 'center',
      body:
        'Every decision is written to Activity. Return to the editor with Approval → Documents → Open; `?tour=core` replays the whole path.',
      nextLabel: 'Finish',
    },
  ],
};