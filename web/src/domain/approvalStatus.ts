/**
 * One shared approval-status model (`approval-status-ui` D1).
 *
 * Every surface (document header, banner, submission cards, top bar) reads its wording, tone,
 * icon, read-only rule and next actor from here. Colour is never the only signal: each entry
 * carries a label, an icon and an accessible description.
 */

import type { SubmissionStatus } from '../api/approvalTypes';

export type ApprovalStatusTone = 'neutral' | 'processing' | 'success' | 'warning' | 'error';

export interface ApprovalStatusMeta {
  /** Canonical status key; `unknown` is a first-class value, never silently treated as Draft. */
  key: SubmissionStatus | 'unknown';
  /** Full label shown in the header and badge, e.g. "Pending first approval". */
  label: string;
  /** Short label used where space is tight, e.g. "Pending first". */
  shortLabel: string;
  /** Role the submission is waiting for, e.g. "Bank Operations". */
  waitingFor: string | null;
  /** Who must act next; `null` when nobody is waiting. */
  nextActor: string | null;
  tone: ApprovalStatusTone;
  icon: string;
  readOnly: boolean;
  /** Position in the four-step approval path (0 = not submitted, 1..4 = Submitted..Approved). */
  step: 0 | 1 | 2 | 3 | 4;
  /** Sentence used as the badge title and in supporting copy. */
  description: string;
}

export const APPROVAL_STATUS: Record<SubmissionStatus, ApprovalStatusMeta> = {
  draft: {
    key: 'draft',
    label: 'Draft',
    shortLabel: 'Draft',
    waitingFor: null,
    nextActor: null,
    tone: 'neutral',
    icon: '●',
    readOnly: false,
    step: 0,
    description: 'Not submitted for approval.',
  },
  pending_first: {
    key: 'pending_first',
    label: 'Pending first approval',
    shortLabel: 'Pending first',
    waitingFor: 'Bank Operations',
    nextActor: 'Bank Operations (First Approver)',
    tone: 'processing',
    icon: '⏳',
    readOnly: true,
    step: 2,
    description: 'Waiting for Bank Operations to approve.',
  },
  pending_second: {
    key: 'pending_second',
    label: 'Pending second approval',
    shortLabel: 'Pending second',
    waitingFor: 'Compliance',
    nextActor: 'Compliance (Second Approver)',
    tone: 'processing',
    icon: '⏳',
    readOnly: true,
    step: 3,
    description: 'Waiting for Compliance to approve.',
  },
  approved: {
    key: 'approved',
    label: 'Approved',
    shortLabel: 'Approved',
    waitingFor: null,
    nextActor: null,
    tone: 'success',
    icon: '✓',
    readOnly: true,
    step: 4,
    description: 'Approved by both approvers; the submitted version is read-only.',
  },
  returned: {
    key: 'returned',
    label: 'Returned',
    shortLabel: 'Returned',
    waitingFor: null,
    nextActor: 'Applicant (revise and resubmit)',
    tone: 'warning',
    icon: '↩',
    readOnly: false,
    step: 1,
    description: 'Returned for edits; a new submission restarts approval.',
  },
  rejected: {
    key: 'rejected',
    label: 'Rejected',
    shortLabel: 'Rejected',
    waitingFor: null,
    nextActor: 'Applicant (start a new submission)',
    tone: 'error',
    icon: '✕',
    readOnly: false,
    step: 1,
    description: 'Rejected; a new submission is required.',
  },
};

const UNKNOWN_STATUS: ApprovalStatusMeta = {
  key: 'unknown',
  label: 'Unknown',
  shortLabel: 'Unknown',
  waitingFor: null,
  nextActor: null,
  tone: 'neutral',
  icon: '?',
  readOnly: true,
  step: 0,
  description: 'Unknown approval status; the editor stays read-only until it is recognised.',
};

const hasStatus = (value: string): value is SubmissionStatus =>
  Object.prototype.hasOwnProperty.call(APPROVAL_STATUS, value);

/** Resolve any status string; unknown values stay visibly unknown instead of becoming Draft. */
export function approvalStatusMeta(status?: string | null): ApprovalStatusMeta {
  if (status && hasStatus(status)) return APPROVAL_STATUS[status];
  return {
    ...UNKNOWN_STATUS,
    description: `Unknown approval status: ${status ?? 'none'}.`,
  };
}

export interface ApprovalStepDefinition {
  key: 'submitted' | 'first' | 'second' | 'approved';
  label: string;
}

/** The four-step path rendered by the pending banner. */
export const APPROVAL_STEPS: ApprovalStepDefinition[] = [
  { key: 'submitted', label: 'Submitted' },
  { key: 'first', label: 'Bank Operations' },
  { key: 'second', label: 'Compliance' },
  { key: 'approved', label: 'Approved' },
];

export type ApprovalStepState = 'done' | 'current' | 'upcoming';

/** Map the shared status onto the four step markers. */
export function approvalStepStates(meta: ApprovalStatusMeta): ApprovalStepState[] {
  if (meta.key === 'approved') return ['done', 'done', 'done', 'done'];
  if (meta.key === 'pending_first') return ['done', 'current', 'upcoming', 'upcoming'];
  if (meta.key === 'pending_second') return ['done', 'done', 'current', 'upcoming'];
  if (meta.key === 'returned' || meta.key === 'rejected') {
    return ['done', 'upcoming', 'upcoming', 'upcoming'];
  }
  return ['upcoming', 'upcoming', 'upcoming', 'upcoming'];
}