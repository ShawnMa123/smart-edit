/**
 * Audit deep dive: the same template audit, focused on the strict config, evidence and export.
 * Assumes a guarantee draft is open (the core tour leaves one behind).
 */

import type { Tour } from '../types';

const T = (name: string): string => `[data-tour="${name}"]`;

export const AUDIT_TOUR: Tour = {
  id: 'audit',
  version: 1,
  title: 'Audit deep dive',
  description:
    'Strict config, evidence, redaction and export — about 2 minutes. Use the core tour first if you have not audited a document yet.',
  steps: [
    {
      id: 'audit-tab',
      title: 'Open the Audit tab',
      target: T('assistant-tabs'),
      placement: 'left',
      action: { kind: 'click', selector: T('tab-audit') },
      until: { kind: 'selector', selector: T('conformance-run') },
      timeoutMs: 15_000,
      body:
        'The audit reads the saved draft, checks required fields without a model, then asks the approved model to judge each calibration requirement.',
    },
    {
      id: 'strict-config',
      title: 'Switch to the strict config',
      target: T('conformance-config'),
      placement: 'left',
      action: { kind: 'select', selector: T('conformance-config'), value: 'guarantee-strict' },
      until: { kind: 'selector', selector: T('conformance-run') },
      body:
        'Same document, stricter checklist: governing law and a sanctions/lawful-source declaration become required. The verdict changes without any code change.',
    },
    {
      id: 'run',
      title: 'Run the audit',
      target: T('conformance-run'),
      placement: 'left',
      action: { kind: 'click', selector: T('conformance-run') },
      until: { kind: 'conformanceReport' },
      timeoutMs: 150_000,
      body:
        'One model call per chunk. A finding must quote a block that can be located, and severity is capped at Warning/human review.',
    },
    {
      id: 'outcome',
      title: 'Read the outcome and coverage',
      target: T('conformance-outcome'),
      placement: 'left',
      until: { kind: 'conformanceReport' },
      body:
        '"Assessed" counts only items the model actually judged; everything else is reported as not assessed, never as a pass.',
    },
    {
      id: 'findings',
      title: 'Findings carry their evidence',
      target: T('conformance-findings'),
      placement: 'left',
      optional: true,
      until: { kind: 'conformanceReport' },
      body:
        'Each card shows the checklist wording, the verbatim quote and a jump-to-block action. A finding without a locatable quote is downgraded to unable to assess.',
    },
    {
      id: 'details',
      title: 'Inspect the checklist that was used',
      target: T('conformance-details'),
      placement: 'left',
      optional: true,
      action: { kind: 'click', selector: `${T('conformance-details')} > summary` },
      body:
        'Read-only: requirement wording, required fields and generation limits. The report records the config version and sha.',
    },
    {
      id: 'redaction',
      title: 'What left the service',
      target: T('conformance-redaction'),
      placement: 'left',
      optional: true,
      action: { kind: 'click', selector: `${T('conformance-redaction')} > summary` },
      body:
        'Masked identifiers are listed as kind + count + a masked sample; the original value never appears in the report.',
    },
    {
      id: 'export',
      title: 'Take the evidence with you',
      target: T('conformance-export'),
      placement: 'left',
      optional: true,
      body:
        'Copy, download Markdown, or print the report. The export keeps the same outcome, coverage, limitations and provenance.',
    },
    {
      id: 'done',
      title: 'That is the audit deep dive',
      placement: 'center',
      body:
        'Next: run the same steps after editing a value (the report is pinned to the revision) or open `?tour=legal` to see the regulatory scan.',
      nextLabel: 'Finish',
    },
  ],
};