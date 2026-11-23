/**
 * Legal deep dive: open the sanctions sample, scan the draft, read the gate and jump to a clause.
 *
 * Note: the scan is independent of the template audit; it uses the statute corpus and the
 * deterministic compliance rules. Web search is left OFF on purpose (it is slow and unverified).
 */

import type { Tour } from '../types';

const T = (name: string): string => `[data-tour="${name}"]`;

export const LEGAL_TOUR: Tour = {
  id: 'legal',
  version: 1,
  title: 'Legal risk scan',
  description:
    'A sanctions sample → gate, findings and draft anchors — about 2 minutes. Web search stays off by default.',
  steps: [
    {
      id: 'open-sample',
      title: 'Open the sanctions sample',
      target: T('open-document'),
      placement: 'bottom',
      action: { kind: 'select', selector: T('open-document'), value: 'sanctions-zh' },
      until: {
        kind: 'text',
        selector: '[data-testid="editor-rich"]',
        includes: '出口合同',
      },
      timeoutMs: 20_000,
      body:
        'In guide mode, pick “sanctions-zh” in Open document…; autopilot selects it for you. If the option is missing (it was renamed), skip this step and open any draft with the sanctions text.',
    },
    {
      id: 'legal-tab',
      title: 'Open the Legal tab',
      target: T('assistant-tabs'),
      placement: 'left',
      action: { kind: 'click', selector: T('tab-legal') },
      until: { kind: 'selector', selector: T('legal-document-tab') },
      timeoutMs: 15_000,
      body:
        'Legal is a separate capability: it looks for regulatory red flags, not for your desk checklist.',
    },
    {
      id: 'document-mode',
      title: 'Switch to Document check',
      target: T('legal-document-tab'),
      placement: 'left',
      action: { kind: 'click', selector: T('legal-document-tab') },
      until: { kind: 'selector', selector: T('legal-scan') },
      body:
        'Statute advice answers a question; Document check scans the draft: required elements, date consistency, risky wording, then statute evidence per clause.',
    },
    {
      id: 'scan',
      title: 'Scan the draft',
      target: T('legal-scan'),
      placement: 'left',
      action: { kind: 'click', selector: T('legal-scan') },
      until: { kind: 'selector', selector: T('legal-report') },
      timeoutMs: 120_000,
      body:
        'The scan runs deterministic checks first, then retrieval and the model. Leave “Use web search” off: it only sends uncovered clause headings and results are unverified.',
    },
    {
      id: 'gate',
      title: 'Read the gate before the findings',
      target: T('legal-report'),
      placement: 'left',
      until: { kind: 'selector', selector: T('legal-report') },
      body:
        'Blocked / Needs human review comes from findings plus coverage. “Unchecked units” means part of the document was not assessed — not that it was clean.',
    },
    {
      id: 'findings',
      title: 'Findings are grouped by severity',
      target: T('legal-findings'),
      placement: 'left',
      optional: true,
      until: { kind: 'selector', selector: T('legal-report') },
      body:
        'Critical hard blocks come only from deterministic rules. Model and statute findings stay at Warning/human review and must cite evidence.',
    },
    {
      id: 'jump',
      title: 'Jump back to the draft',
      target: T('legal-jump'),
      placement: 'left',
      optional: true,
      until: { kind: 'selector', selector: T('legal-report') },
      body:
        'Every anchor quotes the draft verbatim; “Jump to clause” moves the editor to that block so a reviewer can check it in context.',
    },
    {
      id: 'done',
      title: 'That is the legal scan',
      placement: 'center',
      body:
        'Next: try `?tour=approval` for the two-person approval walkthrough, or `?tour=audit` for the desk checklist deep dive.',
      nextLabel: 'Finish',
    },
  ],
};