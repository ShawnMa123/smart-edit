/**
 * Automation deep dive: the Bank Operations back office behind the Automation tab.
 *
 * Automation is the only surface that hands a document to another system, so this tour explains the
 * registry, the downstream contract and the delivery tiers *before* anything is sent. It never
 * dispatches: Send is described, not clicked, and there is no submission step to approve.
 *
 * The tab is hidden (not merely disabled) for roles without `automation.view`, so every step is
 * guarded by an `absent` predicate: an applicant session skips the walkthrough with one note
 * instead of failing on a control it cannot see.
 */

import type { Tour, TourStep, WaitPredicate } from '../types';

const T = (name: string): string => `[data-tour="${name}"]`;

/** `AssistantPanel` drops the tab entirely without `automation.view` (Bank Ops / admins only). */
const NO_AUTOMATION_ACCESS: WaitPredicate = { kind: 'absent', selector: T('tab-automation') };

/** Skip politely — never fail — when this session cannot see the tab or the area is data-empty. */
const guarded = (step: TourStep): TourStep => ({
  ...step,
  optional: true,
  skipIf: [...(step.skipIf ?? []), NO_AUTOMATION_ACCESS],
});

export const AUTOMATION_TOUR: Tour = {
  id: 'automation',
  version: 1,
  title: 'Automation workbench',
  description:
    'Template → confirmed fields → downstream contract → rules and runs — about 4 minutes. Bank Operations only; nothing is sent during the tour.',
  steps: [
    guarded({
      id: 'open-tab',
      title: 'Open the Automation tab',
      target: T('assistant-tabs'),
      placement: 'left',
      action: { kind: 'click', selector: T('tab-automation') },
      until: { kind: 'selector', selector: T('automation-workbench') },
      timeoutMs: 15_000,
      skipNote:
        'This session cannot see the Automation tab. It needs the Bank Operations role (or an organisation administrator); sign in as bankops@atlas-trade.test and run `?tour=automation` again.',
      body:
        'Automation sits in the right pane beside Audit, Knowledge and Legal. It is a Bank Operations back office: without `automation.view` the tab is hidden rather than shown and refused. If you are signed in as applicant, this step skips — switch role first.',
    }),
    guarded({
      id: 'boundary',
      title: 'Two halves, one boundary',
      target: T('automation-boundary'),
      placement: 'left',
      body:
        '**Automate** is the real path: templates and confirmed fields persist on the server, the request body follows the downstream contract, and dispatch makes one allow-listed HTTP call with a replayable receipt. **Sandbox** is a browser-local playground — localStorage, no network, no send. Neither one approves or submits anything.',
    }),
    guarded({
      id: 'areas',
      title: 'Four areas',
      target: T('automation-areas'),
      placement: 'left',
      body:
        'Automate is the server registry; Rules decide which template reaches which downstream and at what tier; Runs is what the worker did after the final approval; Sandbox is the local practice area. Machine suggestions never send on their own.',
    }),
    guarded({
      id: 'template',
      title: '1 · Template (server)',
      target: T('automation-areas'),
      placement: 'left',
      action: { kind: 'click', selector: T('automation-area-server') },
      until: { kind: 'selector', selector: T('automation-template') },
      timeoutMs: 15_000,
      body:
        'Saving the open draft creates a versioned server template (name + version), not a browser snapshot. Binding the document to a template is what “same kind of document” means for automatic rules, so the binding is a deliberate click, not a guess.',
    }),
    guarded({
      id: 'fields',
      title: '2 · Fields are confirmed, never assumed',
      target: T('automation-variables'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      body:
        '“Find variables with AI” proposes fields with a verbatim quote; nothing is stored until you confirm. The mapping downstream can only use confirmed variables, so an AI guess never becomes a sent value on its own.',
    }),
    guarded({
      id: 'downstream',
      title: '3 · Downstream contract',
      target: T('automation-downstream'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      body:
        'A connector names an allow-listed host and an OpenAPI operation. Field mapping says which confirmed variable fills each request field; a missing required mapping blocks Send instead of silently dropping the field.',
    }),
    guarded({
      id: 'mapping-details',
      title: 'Open the field mapping',
      target: T('automation-mapping-details'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      action: { kind: 'open', selector: T('automation-mapping-details') },
      body:
        'The disclosure is idempotent: autopilot opens it only when it is closed, so a repeat run never flips it shut. Mapping is setup, not review — unmapped required fields and unsupported schema types are flagged here and block Send.',
    }),
    guarded({
      id: 'review',
      title: '4 · Review, then a human sends',
      target: T('automation-review'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      body:
        'Preview request builds the exact body without calling out. Send performs one allow-listed HTTP call and records status, latency and a receipt. This tour stops here on purpose: whether to send is a human decision, and the receipt is the evidence.',
    }),
    guarded({
      id: 'history',
      title: 'Receipts keep the history',
      target: T('automation-history-details'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      action: { kind: 'open', selector: T('automation-history-details') },
      body:
        'Recent dispatches keep the evidence: outcome, status code, latency and timestamp, filterable by succeeded / failed / refused. A refusal is recorded too — nothing is silently retried, and the history only appears once this session has dispatches.',
    }),
    guarded({
      id: 'rules',
      title: 'Rules and delivery tiers',
      target: T('automation-areas'),
      placement: 'left',
      action: { kind: 'click', selector: T('automation-area-rules') },
      until: { kind: 'selector', selector: T('automation-rules') },
      timeoutMs: 15_000,
      body:
        'A rule pairs one template kind with one connector. New rules start in **shadow**: they compute the request and call nobody. Raising a tier is an explicit, audited change — shadow → needs_review (a person releases the job) → auto_send (the worker sends). This demo workspace ships one shadow rule (`Demo · …`); **Save rule** adds another from the first template + connector.',
    }),
    guarded({
      id: 'rule-list',
      title: 'Dry-run before you raise a tier',
      target: T('automation-rule-list'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      body:
        '“Dry-run on this document” shows the body the rule would build, without sending. Warnings such as a duplicate connector are surfaced here; pausing or disabling a rule keeps its history instead of deleting it.',
    }),
    guarded({
      id: 'rule-dry-run',
      title: 'Dry-run against the open document',
      target: T('automation-rule-dry-run'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      action: { kind: 'click', selector: T('automation-rule-dry-run') },
      until: { kind: 'selector', selector: T('automation-dry-run-result') },
      timeoutMs: 30_000,
      body:
        'Dry-run builds the exact request this rule would send for the document in the editor — URL, method, body and every mapping issue — and stops before any call. It is the cheapest review: no receipt is written and the downstream never sees it.',
    }),
    guarded({
      id: 'runs',
      title: 'Runs: what actually happened',
      target: T('automation-areas'),
      placement: 'left',
      action: { kind: 'click', selector: T('automation-area-runs') },
      until: { kind: 'selector', selector: T('automation-runs') },
      timeoutMs: 15_000,
      body:
        'After the final approval the worker turns each matching rule into one job per downstream. The Delivery banner is per open document; when the document has no jobs the list falls back to the newest runs in the workspace, so a real shadow job is visible here. Each job keeps its timeline, and the fallbacks are manual: release a needs_review job, retry a failed one, or cancel one that is still queued.',
    }),
    guarded({
      id: 'run-detail',
      title: 'A run keeps its timeline',
      target: T('automation-run-item'),
      placement: 'left',
      targetTimeoutMs: 5_000,
      action: { kind: 'click', selector: `${T('automation-run-item')} button` },
      until: { kind: 'selector', selector: T('automation-run-timeline') },
      timeoutMs: 20_000,
      body:
        'Details opens the job timeline (queued → shadowed, or sent / needs_review). A shadowed job still stores the request it would have sent, so “we only simulated it” is evidence the reviewer can inspect — not a missing step.',
    }),
    guarded({
      id: 'kill-switch',
      title: 'The kill switch wins over every rule',
      target: T('automation-auto-send'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      body:
        'Automatic sending is gated globally (`SMART_EDIT_AUTOMATION_AUTO_SEND`). When it is off, an auto_send rule behaves like shadow: the job still computes and records what it would send, but no call leaves the service.',
    }),
    guarded({
      id: 'sandbox',
      title: 'Sandbox is not the registry',
      target: T('automation-areas'),
      placement: 'left',
      action: { kind: 'click', selector: T('automation-area-sandbox') },
      until: { kind: 'selector', selector: T('automation-sandbox') },
      timeoutMs: 15_000,
      body:
        'The sandbox keeps templates in localStorage and builds the payload preview in the browser. It is useful for practice and for showing the contract, but nothing here is shared, dispatched or recorded — use Automate for the real path. Autopilot now walks its three sub-tabs so you can see each one without typing.',
    }),
    guarded({
      id: 'sandbox-templates',
      title: 'Sandbox · Templates',
      target: T('automation-sandbox-tab-template'),
      placement: 'left',
      action: { kind: 'click', selector: T('automation-sandbox-tab-template') },
      until: { kind: 'selector', selector: T('automation-sandbox-panel-template') },
      timeoutMs: 15_000,
      body:
        'Captured snapshots live in this browser only (localStorage, newest kept, oldest dropped). “Apply to editor” replaces the local draft through the normal autosave path; the template itself never changes.',
    }),
    guarded({
      id: 'sandbox-variables',
      title: 'Sandbox · Variables & fill',
      target: T('automation-sandbox-tab-variables'),
      placement: 'left',
      action: { kind: 'click', selector: T('automation-sandbox-tab-variables') },
      until: { kind: 'selector', selector: T('automation-sandbox-panel-variables') },
      timeoutMs: 15_000,
      body:
        'Mark a selection as a variable (right-click, toolbar or Alt+Shift+V). Every occurrence sharing the variable id updates together; same-named ordinary text is untouched, and a deleted required variable is reported as missing rather than dropped.',
    }),
    guarded({
      id: 'sandbox-mapping',
      title: 'Sandbox · Payload preview',
      target: T('automation-sandbox-tab-mapping'),
      placement: 'left',
      action: { kind: 'click', selector: T('automation-sandbox-tab-mapping') },
      until: { kind: 'selector', selector: T('automation-sandbox-panel-mapping') },
      timeoutMs: 15_000,
      body:
        'The OpenAPI spec is parsed in the browser and the payload is built locally: required/enum/type issues make it not_ready, and “Download JSON” writes a local file. The UI says Not sent — there is no network call in the sandbox.',
    }),
    {
      id: 'done',
      title: 'That is the automation back office',
      placement: 'center',
      body:
        'Template → confirmed fields → downstream contract → one allow-listed call, with rules and runs for the automatic path. If the workbench never appeared, this session lacks `automation.view`: sign in as bankops@atlas-trade.test (or an organisation administrator), then run `?tour=automation` again. `?tour=approval` shows what has to happen before the worker can queue a job.',
      nextLabel: 'Finish',
    },
  ],
};