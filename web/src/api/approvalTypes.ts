/** Types for the submission/approval API (document-submission-approval). */

export type SubmissionStatus =
  | 'draft'
  | 'pending_first'
  | 'pending_second'
  | 'approved'
  | 'returned'
  | 'rejected';

export interface ApprovalStep {
  step_id: string;
  request_id: string;
  stage: 'first' | 'second';
  decision: 'approve' | 'return' | 'reject';
  actor_user_id: string;
  comment: string | null;
  expected_revision: number;
  created_at: string;
  decided_at: string;
}

export type ApprovalRoute = 'bank_first' | 'counterparty_first';

export interface SubmissionSummary {
  submission_id: string;
  document_id: string;
  revision: number;
  content_sha256: string;
  status: SubmissionStatus;
  submitted_by: string;
  created_at: string;
  request_id: string;
  current_stage: 'first' | 'second' | null;
  /** Who reviews the first stage: Bank Operations, or the counterparty (bank-originated drafts). */
  route?: ApprovalRoute;
  approval_revision: number;
  latest_comment: string | null;
  latest_decision: string | null;
  latest_actor: string | null;
  latest_decided_at: string | null;
  /** Document title (the workspace-wide "My submissions" list). */
  title?: string | null;
}

export interface ApprovalSummary extends SubmissionSummary {
  title?: string;
  snapshot_revision?: number;
  snapshot_sha256?: string;
  department_id?: string | null;
}

export interface ApprovalDetail extends ApprovalSummary {
  workspace_id: string;
  content: Record<string, unknown>;
  text: string;
  variables: Record<string, unknown>;
  variables_version: number;
  steps: ApprovalStep[];
  can_decide: boolean;
}

export interface SubmissionCreateInput {
  lockId: string;
  fencingToken: number;
  expectedRevision: number;
  contentSha256: string;
}

export interface ApprovalDecisionInput {
  decision: 'approve' | 'return' | 'reject';
  comment?: string;
  expectedRevision: number;
}