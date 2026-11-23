/**
 * The Automation tour: one walkthrough that **performs** the workbench, then explains the rest.
 *
 * It opens the prepared demo document and really clicks through Automate (template → AI fields →
 * confirm → downstream → mapping → preview), then switches to Rules (dry-run), Runs (job timeline)
 * and Sandbox. Send is the one control it never presses: that is a real allow-listed HTTP call.
 *
 * Bank Operations only: the tab is hidden without `automation.view`, so every step is guarded and
 * falls back to a skip with a note instead of failing on a control the session cannot see.
 */

import type { Tour, TourStep, WaitPredicate } from '../types';

const T = (name: string): string => `[data-tour="${name}"]`;

const NO_AUTOMATION_ACCESS: WaitPredicate = { kind: 'absent', selector: T('tab-automation') };

const guarded = (step: TourStep): TourStep => ({
  ...step,
  optional: true,
  skipIf: [...(step.skipIf ?? []), NO_AUTOMATION_ACCESS],
});

const DEMO_TITLE = 'Automation demo';
const HOME_TITLE = 'Demand Guarantee';

export const AUTOMATION_TOUR: Tour = {
  id: 'automation',
  version: 2,
  title: 'Automation workbench',
  description:
    'The tour runs Automate on a prepared document — template → AI fields → mapping → preview — then walks Rules, Runs and Sandbox. About 6 minutes; Send is explained, never clicked.',
  requiresRole: 'Bank Operations',
  steps: [
    guarded({
      id: 'open-demo-document',
      title: 'Open the prepared demo document',
      target: T('open-document'),
      placement: 'bottom',
      action: { kind: 'selectByText', selector: T('open-document'), includes: DEMO_TITLE },
      until: { kind: 'text', selector: T('document-title'), includes: DEMO_TITLE },
      timeoutMs: 20_000,
      skipIf: [{ kind: 'text', selector: T('document-title'), includes: DEMO_TITLE }],
      skipNote: 'The prepared demo document is already open.',
      timeoutHint:
        'The seeded document is missing: run scripts/seed_automation_demo.py on the server, then Retry (or Skip to work on the current document).',
      body:
        '“Automation demo · trade application” was created by the seed script with a real submission and two approvals, and it is bound to the trade-application template. The tour switched to it so every click below has matching data — autopilot just picked it in the document switcher.',
    }),
    guarded({
      id: 'open-automate',
      title: 'Open the Automation tab',
      target: T('assistant-tabs'),
      placement: 'left',
      action: { kind: 'click', selector: T('tab-automation') },
      until: { kind: 'selector', selector: T('automation-workbench') },
      timeoutMs: 15_000,
      skipNote:
        'This session cannot see the Automation tab. Sign in as bankops@atlas-trade.test (or an organisation administrator) and run `?tour=automation` again.',
      body:
        'Automation is a Bank Operations back office. It has four areas — Automate, Rules, Runs and Sandbox — and the tour walks all of them, starting with the server registry.',
    }),
    guarded({
      id: 'boundary',
      title: 'One area is real, one is practice',
      target: T('automation-boundary'),
      placement: 'left',
      body:
        '**Automate** is the real path: templates and confirmed fields persist on the server, the body follows the downstream contract, and dispatch makes one allow-listed HTTP call with a replayable receipt. **Sandbox** is browser-local — localStorage, no network, no send. Neither approves or submits anything.',
    }),
    guarded({
      id: 'select-template',
      title: '1 · Select the template (tour clicks it)',
      target: T('automation-template-list'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      action: {
        kind: 'clickByText',
        selector: `${T('automation-template-list')} button`,
        includes: 'Trade application',
      },
      until: { kind: 'selector', selector: T('automation-variables') },
      timeoutMs: 15_000,
      body:
        'Each row is a template version with its confirmed-variable count; the tour picked the trade-application one. Saving the same name later adds a version instead of overwriting, and Document type must be bound — this document is, or the worker would record `skipped / no_binding`.',
    }),
    guarded({
      id: 'find-variables',
      title: '2 · The tour asks the model for fields',
      target: T('automation-find-variables'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      action: { kind: 'click', selector: T('automation-find-variables') },
      until: { kind: 'selector', selector: T('automation-suggestions') },
      timeoutMs: 120_000,
      timeoutHint:
        'The model did not answer in time. Skip this step — the template already has confirmed fields — and continue.',
      body:
        '“Find variables with AI” just ran. Every proposal carries a verbatim quote and a source tag, and the checkboxes arrive pre-ticked; nothing is persisted yet. This is a real model call, hence the longer wait.',
    }),
    guarded({
      id: 'confirm-variables',
      title: '2 · Confirm writes them',
      target: T('automation-confirm-variables'),
      placement: 'left',
      targetTimeoutMs: 5_000,
      action: { kind: 'click', selector: T('automation-confirm-variables') },
      until: { kind: 'text', selector: T('automation-variable-summary'), includes: 'confirmed:' },
      timeoutMs: 30_000,
      body:
        'The tour pressed Confirm: the ticked fields are merged into the template on the server. The heading above now counts only confirmed variables — the only ones the mapping is allowed to use.',
    }),
    guarded({
      id: 'select-connector',
      title: '3 · Switch to the contract downstream',
      target: T('automation-connector-select'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      action: {
        kind: 'selectByText',
        selector: T('automation-connector-select'),
        includes: 'Trade intake',
      },
      until: { kind: 'selector', selector: T('automation-payload-preview') },
      timeoutMs: 30_000,
      timeoutHint:
        'The “Trade intake …” connector is missing. Pick a connector that has an OpenAPI operation, or Skip this step.',
      body:
        'A connector is an allow-listed host + path + method + auth, plus an OpenAPI operation. The tour switched to the spec-driven connector; Review rebuilt itself from the document’s values.',
    }),
    guarded({
      id: 'open-mapping',
      title: '3 · Open the field mapping',
      target: T('automation-mapping-details'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      action: { kind: 'open', selector: T('automation-mapping-details') },
      body:
        'Mapping is setup, not review. The tour opened the disclosure idempotently — running it again will not close it. Each request field points at one confirmed variable.',
    }),
    guarded({
      id: 'reset-mapping',
      title: '3 · The tour maps fields by label',
      target: T('automation-reset-mapping'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      action: { kind: 'click', selector: T('automation-reset-mapping') },
      until: { kind: 'selector', selector: T('automation-payload-preview') },
      timeoutMs: 30_000,
      body:
        '“Reset to suggestions” maps each request field to the confirmed variable whose label matches, saves the pair mapping on the server and rebuilds the review. A required field with no match stays unmapped and keeps Send disabled.',
    }),
    guarded({
      id: 'review-body',
      title: '4 · Every field has a source',
      target: T('automation-review-body'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      body:
        'Each line is `field ← variable`, or “not sent” when nothing matched; issues carry the server’s reason code. This is the contract check: the body is built from the approved snapshot, not from the live editor.',
    }),
    guarded({
      id: 'preview',
      title: '4 · The tour previews the request',
      target: T('automation-preview-request'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      action: { kind: 'click', selector: T('automation-preview-request') },
      until: { kind: 'selector', selector: T('automation-request-preview') },
      timeoutMs: 30_000,
      body:
        'Preview just built method, URL, headers and body exactly as they would go out — with no HTTP call and no receipt. This is the last safe click; everything below it leaves the service.',
    }),
    guarded({
      id: 'send',
      title: 'Send stays human',
      target: T('automation-send'),
      placement: 'left',
      targetTimeoutMs: 3_000,
      body:
        'Send performs one allow-listed HTTP call and records status, latency and a dispatch id. The tour never presses it: whether a real document leaves the service is a human decision, and that boundary is the product.',
    }),
    guarded({
      id: 'rules',
      title: 'Rules: which template reaches which downstream',
      target: T('automation-areas'),
      placement: 'left',
      action: { kind: 'click', selector: T('automation-area-rules') },
      until: { kind: 'selector', selector: T('automation-rules') },
      timeoutMs: 15_000,
      body:
        'A rule pairs one template kind with one connector. New rules start in **shadow**: they compute the request and call nobody. Raising a tier is an explicit, audited change — shadow → needs_review (a person releases the job) → auto_send (the worker sends). This workspace ships one shadow rule (`Demo · …`).',
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
        'The tour pressed Dry-run: it builds exactly what this rule would send for the open (approved) document — URL, method, body and mapping issues — and stops before any call. No receipt is written and the downstream never sees it.',
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
        'After the final approval the worker turns each matching rule into one job per downstream. The Delivery banner is per open document; this document has a real job from the seed, so nothing is mocked here. The fallbacks are manual: release a needs_review job, retry a failed one, or cancel a queued one.',
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
        'The tour opened Details: queued → shadowed (or sent / needs_review). A shadowed job still stores the request it would have sent, so “we only simulated it” is evidence the reviewer can inspect — not a missing step.',
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
        'The sandbox keeps templates in localStorage and builds the payload preview in the browser. Nothing here is shared, dispatched or recorded — use Automate for the real path. The tour now walks its three sub-tabs.',
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
        'Mark a selection as a variable (right-click, toolbar or Alt+Shift+V). Occurrences sharing the variable id update together; same-named ordinary text is untouched, and a deleted required variable is reported as missing rather than dropped.',
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
    guarded({
      id: 'restore-document',
      title: 'Back to the core demo document',
      target: T('open-document'),
      placement: 'bottom',
      action: { kind: 'selectByText', selector: T('open-document'), includes: HOME_TITLE },
      until: { kind: 'text', selector: T('document-title'), includes: HOME_TITLE },
      timeoutMs: 20_000,
      skipIf: [{ kind: 'text', selector: T('document-title'), includes: HOME_TITLE }],
      skipNote: 'The core demo document is already open.',
      body:
        'The tour switched back so the rest of the demo starts where it did. The automation demo document stays in the switcher with its own delivery state, rules and runs.',
    }),
    {
      id: 'done',
      title: 'That is Automation — performed, then explained',
      placement: 'center',
      body:
        'The tour selected a template, asked the model for fields, confirmed them, switched to the contract downstream, remapped by label, built the preview — then dry-ran the rule, opened the real job timeline and walked the sandbox. It never pressed Send: that stays a human decision. Reset the demo data before a repeated full run.',
      nextLabel: 'Finish',
    },
  ],
};