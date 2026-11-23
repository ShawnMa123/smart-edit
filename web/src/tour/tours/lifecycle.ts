/**
 * Lifecycle tours (3 parts, one per role). A browser session cannot switch identity, so each part
 * verifies the state left by the previous one and hands off with a deep link:
 *
 *   1/3 applicant: New document → edit → audit → submit        (?tour=lifecycle-applicant)
 *   2/3 bankops:   Approval → First approval → Approve         (?tour=lifecycle-first)
 *   3/3 compliance: Approval → Second approval → Approved      (?tour=lifecycle-second)
 *
 * Approval clicks stay manual unless the operator chose "Let the tour submit".
 */

import type { Tour, WaitPredicate } from '../types';
import { SAMPLE_GUARANTEE } from './core';

const T = (name: string): string => `[data-tour="${name}"]`;

const APPROVAL_PENDING: WaitPredicate = {
  kind: 'text',
  selector: T('approval-status'),
  includes: 'Pending',
};
const APPROVAL_APPROVED: WaitPredicate = {
  kind: 'text',
  selector: T('approval-status'),
  includes: 'Approved',
};
const NO_LOCK: WaitPredicate = {
  kind: 'text',
  selector: T('editor-status'),
  includes: 'lock: unknown',
};

export const LIFECYCLE_APPLICANT: Tour = {
  id: 'lifecycle-applicant',
  version: 1,
  title: 'Lifecycle 1/3 · New document → submit (applicant)',
  description:
    'Start from New document, paste the sample, audit it and submit. Ends at Pending first approval; part 2 runs as Bank Ops.',
  steps: [
    {
      id: 'role',
      title: 'Sign in as the applicant',
      target: T('session-user'),
      placement: 'bottom',
      until: { kind: 'text', selector: T('session-user'), includes: 'Applicant' },
      timeoutMs: 15_000,
      timeoutHint:
        'Part 1/3 must run in the Applicant window (applicant@atlas-trade.test). Sign in there, then retry.',
      body:
        'Part 1/3 creates and submits as the Applicant. The top bar shows the signed-in name; check it before starting.',
    },
    {
      id: 'start',
      title: 'Start a fresh document',
      target: T('editor-surface'),
      placement: 'left',
      body:
        'This part begins with New document, not with an existing draft. It ends by handing the submission to Bank Operations.',
    },
    {
      id: 'new-document',
      title: 'Create the draft',
      target: T('new-document'),
      placement: 'bottom',
      action: { kind: 'click', selector: T('new-document') },
      until: { kind: 'text', selector: T('document-title'), includes: 'Untitled document' },
      timeoutMs: 20_000,
      body:
        'New document keeps the previous document and opens a fresh draft. In guide mode, click it yourself; autopilot clicks it for you.',
    },
    {
      id: 'paste',
      title: 'Fill the draft',
      target: T('editor-surface'),
      placement: 'left',
      action: { kind: 'paste', text: SAMPLE_GUARANTEE },
      until: { kind: 'text', selector: '[data-testid="editor-rich"]', includes: 'DEMAND GUARANTEE' },
      timeoutMs: 30_000,
      body: 'Paste the standard guarantee sample (DEMO.md appendix A.1), or let autopilot insert it.',
    },
    {
      id: 'saved',
      title: 'Wait for the save',
      target: T('save-state'),
      placement: 'bottom',
      until: { kind: 'saveState' },
      timeoutMs: 30_000,
      body: 'The submission freezes the saved revision; wait for “Saved to server”.',
    },
    {
      id: 'audit-tab',
      title: 'Audit before submitting',
      target: T('assistant-tabs'),
      placement: 'left',
      action: { kind: 'click', selector: T('tab-audit') },
      until: { kind: 'selector', selector: T('conformance-run') },
      timeoutMs: 15_000,
      body: 'Run the template audit on the saved draft so the submission is not blind.',
    },
    {
      id: 'config',
      title: 'Use the standard checklist',
      target: T('conformance-config'),
      placement: 'left',
      action: { kind: 'select', selector: T('conformance-config'), value: 'guarantee-standard' },
      until: { kind: 'selector', selector: T('conformance-run') },
      body: 'The calibration config is versioned; the report records which version judged the draft.',
    },
    {
      id: 'run',
      title: 'Run the audit',
      target: T('conformance-run'),
      placement: 'left',
      action: { kind: 'click', selector: T('conformance-run') },
      until: { kind: 'conformanceReport' },
      timeoutMs: 150_000,
      body: 'Findings need a locatable quote; missing required fields come from the deterministic extractor.',
    },
    {
      id: 'outcome',
      title: 'Check the outcome',
      target: T('conformance-outcome'),
      placement: 'left',
      until: { kind: 'conformanceReport' },
      body: 'Assessed / planned and coverage. Not assessed is not a pass.',
    },
    {
      id: 'submit',
      title: 'Open the submission',
      target: T('submit-version'),
      placement: 'top',
      action: { kind: 'click', selector: T('submit-version') },
      until: { kind: 'selector', selector: T('submit-confirm') },
      timeoutMs: 20_000,
      requiresApprovalAuto: true,
      skipIf: [APPROVAL_PENDING, APPROVAL_APPROVED, NO_LOCK],
      skipNote:
        'Skipping submission: this draft is already pending/approved, or this window does not hold the edit lock.',
      body:
        'Submit new version freezes a snapshot. Autopilot opens it only when you allowed the submission step.',
    },
    {
      id: 'confirm',
      title: 'Confirm the approval chain',
      target: T('submit-confirm'),
      placement: 'top',
      action: { kind: 'click', selector: T('submit-confirm') },
      until: { kind: 'text', selector: T('approval-status'), includes: 'Pending first' },
      timeoutMs: 25_000,
      requiresApprovalAuto: true,
      optional: true,
      skipIf: [APPROVAL_PENDING, APPROVAL_APPROVED, NO_LOCK],
      body:
        'Bank Operations approves first, then Compliance. The submitter cannot approve their own document.',
    },
    {
      id: 'handoff',
      title: 'Part 1/3 complete — hand off',
      placement: 'center',
      until: { kind: 'text', selector: T('approval-status'), includes: 'Pending first' },
      body:
        'In a second window sign in as bankops@atlas-trade.test, then open Take the tour → Lifecycle 2/3 (or add ?tour=lifecycle-first). Compliance does part 3.',
      nextLabel: 'Finish',
    },
  ],
};

export const LIFECYCLE_FIRST: Tour = {
  id: 'lifecycle-first',
  version: 1,
  title: 'Lifecycle 2/3 · First approval (Bank Ops)',
  description:
    'Bank Operations reads the frozen snapshot and approves. Run part 1 first; part 3 runs as Compliance.',
  steps: [
    {
      id: 'role',
      title: 'Sign in as Bank Operations',
      target: T('session-user'),
      placement: 'bottom',
      until: { kind: 'text', selector: T('session-user'), includes: 'Bank Operations' },
      timeoutMs: 15_000,
      timeoutHint:
        'Part 2/3 must run in the Bank Ops window (bankops@atlas-trade.test). The Applicant also has a “First approval” tab, but it is the counterparty queue and will be empty for this submission.',
      body:
        'Check the signed-in name in the top bar. The applicant’s First approval tab is the counterparty queue, not the Bank Ops queue.',
    },
    {
      id: 'open-approval',
      title: 'Open the Approval module',
      target: T('topbar-approval'),
      placement: 'bottom',
      action: { kind: 'click', selector: T('topbar-approval') },
      until: { kind: 'selector', selector: T('approval-document') },
      timeoutMs: 15_000,
      body:
        'If nothing is waiting, part 1 has not submitted yet: switch to the applicant window and finish Lifecycle 1/3.',
    },
    {
      id: 'first-tab',
      title: 'First approval queue',
      target: T('approval-tab-first'),
      placement: 'bottom',
      optional: true,
      action: { kind: 'click', selector: T('approval-tab-first') },
      until: { kind: 'selector', selector: T('approval-queue') },
      timeoutMs: 15_000,
      timeoutHint:
        'The approval queue did not load. Check the signed-in role: the Applicant’s First approval tab is the counterparty queue and is empty for this submission.',
      body:
        'Only roles with approval.first or approval.counterparty see this tab. Bank Ops reviews the submitted snapshot here.',
    },
    {
      id: 'select',
      title: 'Select the submission',
      target: T('approval-select'),
      placement: 'right',
      optional: true,
      action: { kind: 'click', selector: T('approval-select') },
      until: { kind: 'selector', selector: T('approval-approve') },
      timeoutMs: 15_000,
      targetTimeoutMs: 8000,
      skipNote:
        'No pending request appeared in this queue. If this is the Applicant window, switch to Bank Ops: the lifecycle submission waits for Bank Ops.',
      body: 'Selecting a request shows the frozen text, the timeline and the decision buttons.',
    },
    {
      id: 'approve',
      title: 'Approve (or return)',
      target: T('approval-approve'),
      placement: 'top',
      optional: true,
      action: { kind: 'click', selector: T('approval-approve') },
      until: { kind: 'text', selector: T('approval-detail'), includes: 'Pending second' },
      timeoutMs: 25_000,
      requiresApprovalAuto: true,
      timeoutHint:
        'Approving did not move the request. Confirm you selected the pending request and that the decision succeeded (a comment is only required for Return/Reject).',
      body:
        'The submitter cannot approve their own document. Approve moves it to Compliance; Return sends it back with a required comment. Autopilot clicks only when you allowed it.',
    },
    {
      id: 'handoff',
      title: 'Part 2/3 complete — hand off',
      placement: 'center',
      until: { kind: 'selector', selector: T('approval-tabs') },
      body:
        'In the compliance window sign in as compliance@atlas-trade.test, then open Take the tour → Lifecycle 3/3 (or ?tour=lifecycle-second).',
      nextLabel: 'Finish',
    },
  ],
};

export const LIFECYCLE_SECOND: Tour = {
  id: 'lifecycle-second',
  version: 1,
  title: 'Lifecycle 3/3 · Second approval (Compliance) → Approved',
  description:
    'Compliance approves second; the tour then opens the document to show the terminal Approved state.',
  steps: [
    {
      id: 'role',
      title: 'Sign in as Compliance',
      target: T('session-user'),
      placement: 'bottom',
      until: { kind: 'text', selector: T('session-user'), includes: 'Compliance' },
      timeoutMs: 15_000,
      timeoutHint:
        'Part 3/3 must run in the Compliance window (compliance@atlas-trade.test). Sign in there, then retry.',
      body:
        'Check the signed-in name in the top bar. Compliance is the second approver for this route.',
    },
    {
      id: 'open-approval',
      title: 'Open the Approval module',
      target: T('topbar-approval'),
      placement: 'bottom',
      action: { kind: 'click', selector: T('topbar-approval') },
      until: { kind: 'selector', selector: T('approval-document') },
      timeoutMs: 15_000,
      body:
        'If nothing is waiting, part 2 has not approved yet: finish Lifecycle 2/3 in the Bank Ops window.',
    },
    {
      id: 'second-tab',
      title: 'Second approval queue',
      target: T('approval-tab-second'),
      placement: 'bottom',
      optional: true,
      action: { kind: 'click', selector: T('approval-tab-second') },
      until: { kind: 'selector', selector: T('approval-queue') },
      timeoutMs: 15_000,
      timeoutHint:
        'The approval queue did not load. Confirm you are in the Compliance window and that part 2/3 approved.',
      body: 'Compliance is the second approver; the route is shown on each pending request.',
    },
    {
      id: 'select',
      title: 'Select the submission',
      target: T('approval-select'),
      placement: 'right',
      optional: true,
      action: { kind: 'click', selector: T('approval-select') },
      until: { kind: 'selector', selector: T('approval-approve') },
      timeoutMs: 15_000,
      targetTimeoutMs: 8000,
      skipNote:
        'No pending request appeared for second approval. Run part 2/3 (Bank Ops approve) first, then retry here.',
      body: 'The frozen text and both decisions are visible before you approve.',
    },
    {
      id: 'approve',
      title: 'Approve → final state',
      target: T('approval-approve'),
      placement: 'top',
      optional: true,
      action: { kind: 'click', selector: T('approval-approve') },
      until: { kind: 'text', selector: T('approval-detail'), includes: 'Approved' },
      timeoutMs: 25_000,
      requiresApprovalAuto: true,
      timeoutHint:
        'The request did not reach Approved. Confirm you selected the second-approval request and that the decision succeeded.',
      body:
        'Approving here is terminal: the document becomes Approved and read-only. Autopilot clicks only when you allowed it.',
    },
    {
      id: 'open-documents',
      title: 'Open the approved document',
      target: T('approval-tab-documents'),
      placement: 'bottom',
      optional: true,
      action: { kind: 'click', selector: T('approval-tab-documents') },
      until: { kind: 'selector', selector: T('approval-open-document') },
      timeoutMs: 15_000,
      body: 'Documents lists every draft and submission; open the one you just approved.',
    },
    {
      id: 'open-document',
      title: 'Verify the terminal state',
      target: T('approval-open-document'),
      placement: 'right',
      optional: true,
      action: { kind: 'click', selector: T('approval-open-document') },
      until: { kind: 'text', selector: T('approval-status'), includes: 'Approved' },
      timeoutMs: 25_000,
      body:
        'Back in the editor the status chip reads Approved and the text is read-only. Activity keeps the full decision trail.',
    },
    {
      id: 'done',
      title: 'Lifecycle complete: Draft → Pending first → Pending second → Approved',
      placement: 'center',
      body:
        'That is the full document lifecycle across three roles. Reset the demo document (DEMO.md §1.2) before replaying, then start again at Lifecycle 1/3.',
      nextLabel: 'Finish',
    },
  ],
};