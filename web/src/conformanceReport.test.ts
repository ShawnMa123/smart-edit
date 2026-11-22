/** The exported Markdown must carry the same honest facts the panel shows. */

import { describe, expect, it } from 'vitest';

import type { ConformanceReport } from './api/conformance';
import { reportFileName, reportToMarkdown } from './conformanceReport';

const REPORT: ConformanceReport = {
  report_id: 'crp_1',
  run_id: 'cfr_1',
  outcome: 'findings_present',
  completion: 'partial',
  config: {
    config_id: 'guarantee-standard',
    version: '1.0.0',
    name: 'Standard desk check',
    document_types: ['guarantee'],
    language: 'auto',
    description: '',
    requirement_count: 1,
    required_fields: ['guarantee_amount'],
    content_sha256: 'c'.repeat(64),
  },
  snapshot: {
    document_id: 'doc-1',
    draft_id: 'draft-1',
    title: 'DG',
    revision: 4,
    content_sha256: 'a'.repeat(64),
    analyzed_chars: 1200,
    truncated: true,
  },
  summary: 'One clause does not match.',
  summary_note: "'Pass' is not a compliance statement.",
  results: [
    {
      id: 'rules.urdg_758',
      title: 'Governing rules are URDG 758',
      level: 'must',
      status: 'finding',
      severity: 'Warning',
      gate_type: 'human_review',
      explanation: 'Another rule set is named.',
      suggestion: 'Use URDG 758.',
      quote: 'Governing Rules: UCP 600',
      block_index: 7,
      confidence: 'high',
      reason_codes: [],
    },
    {
      id: 'parties.legal_names',
      title: 'Complete legal names',
      level: 'must',
      status: 'unable_to_assess',
      severity: 'Warning',
      gate_type: 'human_review',
      explanation: 'Not visible.',
      suggestion: null,
      quote: null,
      block_index: null,
      confidence: 'low',
      reason_codes: ['evidence_not_locatable'],
    },
  ],
  missing_fields: [{ key: 'guarantee_amount', label: 'Guarantee amount', note: null }],
  counts: {
    requirements: 2,
    passed: 0,
    findings: 1,
    unable_to_assess: 1,
    missing_fields: 1,
    coverage_ratio: 0.5,
  },
  limitations: [
    { code: 'document_truncated', message: 'Only part of the document was sent.' },
  ],
  provenance: {
    model: 'doubao:test',
    prompt_version: 'conformance/1',
    config_sha256: 'c'.repeat(64),
    extraction_status: 'deterministic',
    extraction_profile: 'guarantee-default',
    model_calls: 2,
    duration_ms: 1200,
    redaction: {
      applied: true,
      total: 1,
      note: 'Best-effort pattern redaction.',
      steps: [{ kind: 'email', count: 1, sample: 'o•••@example.com' }],
    },
  },
};

describe('reportToMarkdown', () => {
  it('keeps outcome, findings, evidence, limitations, redaction and provenance', () => {
    const markdown = reportToMarkdown(REPORT);

    expect(markdown).toContain('# Template audit — Standard desk check');
    expect(markdown).toContain('Outcome: **findings_present** (partial)');
    expect(markdown).toContain('Coverage: 0/2 assessed · 50%');
    expect(markdown).toContain('### Governing rules are URDG 758');
    expect(markdown).toContain('Quote: “Governing Rules: UCP 600”');
    expect(markdown).toContain('`document_truncated` Only part of the document was sent.');
    expect(markdown).toContain('email × 1 — masked sample `o•••@example.com`');
    expect(markdown).toContain('Not assessed');
    expect(markdown).toContain('evidence_not_locatable');
    expect(markdown).toContain("'Pass' is not a compliance statement.");
    expect(markdown).toContain('Model: doubao:test · prompt conformance/1 · 2 call(s)');
  });

  it('names the file after the config and revision', () => {
    expect(reportFileName(REPORT)).toBe('template-audit-guarantee-standard-rev4.md');
  });
});