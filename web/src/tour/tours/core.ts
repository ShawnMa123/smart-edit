/**
 * The core tour: the same path as `DEMO.md` (8 minutes), expressed as steps.
 *
 * Copy is English because the console UI is English. Targets use `data-tour` attributes owned by
 * this module (tests may rename `data-testid` freely without breaking the tour).
 */

import type { Tour, WaitPredicate } from '../types';

export const SAMPLE_GUARANTEE = `DEMAND GUARANTEE
Guarantee No: BG-2026-00417
Applicant: Alpha Tech Pte Ltd
Beneficiary: Beta Construction Ltd
Amount: USD 500,000.00
Currency: USD
Issue Date: 12/03/26
Expiry Date: 12/03/27
Governing Rules: URDG 758

This guarantee is payable on first written demand.`;

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

export const CORE_TOUR: Tour = {
  id: 'core',
  version: 1,
  title: 'Product tour · the core loop',
  description:
    'Document → template audit → evidence → export → submission. About 4 minutes; you can stop at any time.',
  steps: [
    {
      id: 'welcome',
      title: 'Your document lives here',
      target: T('editor-surface'),
      placement: 'left',
      body:
        'The middle pane is the draft. Every check in this product reads this document — never a cached copy.',
    },
    {
      id: 'status',
      title: 'Revision, save state and lock',
      target: T('editor-status'),
      placement: 'bottom',
      body:
        'Each save bumps the draft revision. Audits pin that revision, so a report can never quietly describe an older version. "lock: this session" means you hold the edit lock.',
    },
    {
      id: 'lock',
      title: 'Wait for the edit lock',
      target: T('editor-status'),
      placement: 'bottom',
      until: { kind: 'text', selector: T('editor-status'), includes: 'lock: this session' },
      timeoutMs: 20_000,
      skipIf: [APPROVAL_PENDING, APPROVAL_APPROVED],
      skipNote:
        'This document is read-only (submitted), so the edit-lock step is skipped. Open a draft if you want to edit it.',
      body:
        'The editor is editable only while this window holds the lock. If another window holds it, release it there (or open another draft), then continue. Without the lock, edits stay in this browser and autosave cannot run.',
    },
    {
      id: 'paste',
      title: 'Put the sample guarantee in',
      target: T('editor-surface'),
      placement: 'left',
      action: { kind: 'paste', text: SAMPLE_GUARANTEE },
      until: { kind: 'text', selector: '[data-testid="editor-rich"]', includes: 'DEMAND GUARANTEE' },
      timeoutMs: 30_000,
      skipIf: [APPROVAL_PENDING, APPROVAL_APPROVED],
      skipNote:
        'The draft is read-only, so the sample is not pasted; the tour audits the text that is already there.',
      body:
        'In guide mode, select everything (Cmd/Ctrl+A) and paste the standard guarantee sample. In autopilot the tour inserts it for you.',
    },
    {
      id: 'saved',
      title: 'Wait for "Saved to server"',
      target: T('save-state'),
      placement: 'bottom',
      until: { kind: 'saveState' },
      timeoutMs: 30_000,
      body:
        'Autosave runs 2 seconds after you stop typing. The audit reads the saved revision; if you edit afterwards, the report is marked stale instead of pretending to be current.',
    },
    {
      id: 'audit-tab',
      title: 'Open the Audit tab',
      target: T('assistant-tabs'),
      placement: 'left',
      action: { kind: 'click', selector: T('tab-audit') },
      until: { kind: 'selector', selector: T('conformance-run') },
      timeoutMs: 15_000,
      body:
        'The Audit tab is a template audit: it reads the saved draft, checks required fields without a model, then asks the approved model to judge each calibration requirement.',
    },
    {
      id: 'config',
      title: 'Pick a calibration config',
      target: T('conformance-config'),
      placement: 'left',
      action: { kind: 'select', selector: T('conformance-config'), value: 'guarantee-standard' },
      until: { kind: 'selector', selector: T('conformance-run') },
      body:
        'A config is versioned data under app/configs/conformance: requirements, required fields and generation limits. Switching the config changes the verdict without changing code.',
    },
    {
      id: 'run',
      title: 'Run the template audit',
      target: T('conformance-run'),
      placement: 'left',
      action: { kind: 'click', selector: T('conformance-run') },
      until: { kind: 'conformanceReport' },
      timeoutMs: 150_000,
      body:
        'One model call per chunk, then the server validates every answer: unknown requirements are dropped, findings need a quote that can be located, and severity is capped. Nothing here can hard-block.',
    },
    {
      id: 'outcome',
      title: 'Read the outcome first',
      target: T('conformance-outcome'),
      placement: 'left',
      until: { kind: 'conformanceReport' },
      body:
        'Outcome, assessed/planned requirements and coverage. "Coverage" is the honest denominator: an item nobody could judge is counted as not assessed, not as a pass.',
    },
    {
      id: 'missing',
      title: 'Missing required fields',
      target: T('conformance-missing'),
      placement: 'left',
      optional: true,
      until: { kind: 'conformanceReport' },
      body:
        'Missing fields come from deterministic extraction, not from the model. If extraction cannot run, this block stays empty and the report says why.',
    },
    {
      id: 'findings',
      title: 'What does not match',
      target: T('conformance-findings'),
      placement: 'left',
      optional: true,
      until: { kind: 'conformanceReport' },
      body:
        'Each finding quotes the document verbatim and can jump to that block. A finding without a locatable quote is downgraded to "unable to assess" — the model cannot invent a defect.',
    },
    {
      id: 'details',
      title: 'Inspect the config that was used',
      target: T('conformance-details'),
      placement: 'left',
      optional: true,
      action: { kind: 'click', selector: `${T('conformance-details')} > summary` },
      body:
        'Config details are read-only: requirement wording, required fields and limits. The report records the config version and sha, so you can reconstruct the exact checklist later.',
    },
    {
      id: 'redaction',
      title: 'See what leaves the service',
      target: T('conformance-redaction'),
      placement: 'left',
      optional: true,
      action: { kind: 'click', selector: `${T('conformance-redaction')} > summary` },
      body:
        'Before the model call, account/card numbers, IBAN/BIC, e-mail, phone and ID numbers are masked and replaced with [redacted]. The report shows the kind, count and a masked sample — never the original value.',
    },
    {
      id: 'export',
      title: 'Take the report with you',
      target: T('conformance-export'),
      placement: 'left',
      optional: true,
      body:
        'Copy the report, download it as Markdown, or print/PDF. The export carries the same outcome, coverage, limitations, redaction steps and provenance as the screen.',
    },
    {
      id: 'tabs',
      title: 'Four assistant capabilities',
      target: T('assistant-tabs'),
      placement: 'left',
      body:
        'Audit is the template check you just ran. Knowledge answers from the approved corpus; Automation maps a template to a downstream system; Legal scans the draft for regulatory red flags. The two audit products stay separate on purpose.',
    },
    {
      id: 'submit',
      title: 'Submit a frozen snapshot',
      target: T('submit-version'),
      placement: 'top',
      action: { kind: 'click', selector: T('submit-version') },
      until: { kind: 'selector', selector: T('submit-confirm') },
      timeoutMs: 20_000,
      requiresApprovalAuto: true,
      skipIf: [APPROVAL_PENDING, APPROVAL_APPROVED, NO_LOCK],
      skipNote:
        'Skipping the submission step: this draft is already pending/approved, or this window does not hold the edit lock. Open another draft or reset the demo document to run this part.',
      body:
        'Approval works on a snapshot (revision + sha), not on a live draft. In guide mode you open the dialog yourself; autopilot only opens it when you allowed the submit step.',
    },
    {
      id: 'confirm-submit',
      title: 'Confirm the chain',
      target: T('submit-confirm'),
      placement: 'top',
      action: { kind: 'click', selector: T('submit-confirm') },
      until: { kind: 'text', selector: T('approval-status'), includes: 'Pending first' },
      timeoutMs: 25_000,
      requiresApprovalAuto: true,
      optional: true,
      skipIf: [APPROVAL_PENDING, APPROVAL_APPROVED, NO_LOCK],
      body:
        'Bank Operations approves first, then Compliance. The submitter cannot approve their own document. If you kept the approval step manual, click the button yourself and press Next once the status changes.',
    },
    {
      id: 'handoff',
      title: 'Hand off to the approvers',
      target: T('approval-status'),
      placement: 'top',
      until: { kind: 'text', selector: T('approval-status'), includes: 'Pending first' },
      skipIf: [APPROVAL_APPROVED, NO_LOCK],
      body:
        'The draft is now read-only until an approver acts. Open a second (private) window, sign in as bankops@atlas-trade.test, then Approve under Approval → First approval; Compliance approves second.',
    },
    {
      id: 'done',
      title: "That's the core loop",
      placement: 'center',
      body:
        'Draft → templated audit with evidence → export → frozen submission → two-person approval. Reset the demo document before the next run: scripts/seed_identity_users.py (then restart).',
      nextLabel: 'Finish',
    },
  ],
};