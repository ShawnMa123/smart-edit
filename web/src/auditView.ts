/**
 * Audit view model (design D6) — the single place that decides **what may be claimed**.
 *
 * The rule this module exists for: `extract` failing makes every required field a `missing`
 * placeholder, and rendering that as a defect list would accuse the customer's document of a failure
 * that is ours. So field checks are reported only when the stages that produce them completed, and
 * an incomplete run carries a `blockedReason` instead of a result.
 */

import type { FieldValue, Finding, RunEnvelope, StageReport } from './api/types';
import type { Snapshot } from './snapshot';
import { fieldStatusToken, severityToken, stageStatusToken } from './tokens';

export const SCOPE_RAN: string[] = [
  'Required-field presence, from the field dictionary',
  'Value format: amount, currency, date order',
  'Field length limits and truncation',
];

export const SCOPE_NOT_RUN: string[] = [
  'Semantic consistency checks (RULE-02)',
  'Customer / bank template clauses (RULE-03)',
  'Regulatory coverage and jurisdiction applicability (Requirements §9.2)',
];

export const LABEL_NOT_RUN = 'Field checks did not run';
export const LABEL_FINDINGS = 'Findings need review';
export const LABEL_NO_FINDINGS = 'No findings in the checks that ran';
export const NOTE_NO_FINDINGS = 'No findings does not mean the document is compliant.';

export type FieldChecks = 'ran' | 'did-not-run';

export interface SourceLocation {
  fileId: string;
  page: number | null;
  span: string;
}

export interface CheckRow {
  key: string;
  label: string | null;
  value: string | null;
  normalizedFrom: string | null;
  status: string;
  statusLabel: string;
  statusClass: string;
  notes: string[];
  source: SourceLocation | null;
}

export interface FindingRow {
  id: string;
  severity: string;
  severityLabel: string;
  severityClass: string;
  blocking: boolean;
  message: string;
  evidence: string | null;
  fieldKeys: string[];
  source: string;
}

export interface StageRow {
  stage: string;
  status: string;
  statusLabel: string;
  statusClass: string;
  reason: string | null;
  produced: number;
}

export interface AuditViewModel {
  fieldChecks: FieldChecks;
  blockedReason: string | null;
  resultLabel: string;
  stepsRan: string[];
  stepsNotRun: string[];
  checks: CheckRow[];
  findings: FindingRow[];
  severityCounts: { critical: number; warn: number; info: number };
  statusCounts: { extracted: number; inferred: number; missing: number; unknown: number };
  stages: StageRow[];
  stale: boolean;
  usedFixture: boolean;
  digest: string;
  capturedAt: string;
}

const lastReport = (stages: StageReport[], stage: string): StageReport | undefined =>
  [...stages].reverse().find((report) => report.stage === stage);

const STATUS_ORDER: Record<string, number> = { missing: 0, inferred: 1, unknown: 2, extracted: 3 };

const toCheckRow = (field: FieldValue): CheckRow => {
  const token = fieldStatusToken(field.status);
  return {
    key: field.key,
    label: field.label,
    value: field.value,
    normalizedFrom: field.normalized_from,
    status: field.status,
    statusLabel: token.label,
    statusClass: token.className,
    notes: field.notes ?? [],
    source: field.source
      ? { fileId: field.source.file_id, page: field.source.page, span: field.source.span }
      : null,
  };
};

const toFindingRow = (finding: Finding): FindingRow => {
  const token = severityToken(finding.severity);
  return {
    id: finding.id,
    severity: finding.severity,
    severityLabel: token.label,
    severityClass: token.className,
    blocking: finding.blocking,
    message: finding.message,
    evidence: finding.evidence,
    fieldKeys: finding.field_keys ?? [],
    source: finding.source,
  };
};

const countBy = (rows: CheckRow[]) => {
  const counts = { extracted: 0, inferred: 0, missing: 0, unknown: 0 };
  for (const row of rows) {
    const bucket = (row.status in counts ? row.status : 'unknown') as keyof typeof counts;
    counts[bucket] += 1;
  }
  return counts;
};

export function buildAuditView(
  envelope: RunEnvelope,
  snapshot: Snapshot,
  currentDigest: string,
): AuditViewModel {
  const stages: StageRow[] = envelope.stages.map((report) => {
    const token = stageStatusToken(report.status);
    return {
      stage: report.stage,
      status: report.status,
      statusLabel: token.label,
      statusClass: token.className,
      reason: report.reason,
      produced: report.produced,
    };
  });

  const extract = lastReport(envelope.stages, 'extract');
  const normalize = lastReport(envelope.stages, 'normalize');
  const checksRan = extract?.status === 'done' && normalize?.status === 'done';

  const checks = checksRan
    ? Object.values(envelope.fields)
        .map(toCheckRow)
        .sort(
          (a, b) =>
            (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) || a.key.localeCompare(b.key),
        )
    : [];

  const findings = envelope.findings.map(toFindingRow);
  const severityCounts = { critical: 0, warn: 0, info: 0 };
  for (const finding of findings) {
    const bucket = (finding.severity in severityCounts ? finding.severity : 'info') as
      | 'critical'
      | 'warn'
      | 'info';
    severityCounts[bucket] += 1;
  }

  const usedFixture = Boolean(extract?.reason?.includes('fixture:'));

  return {
    fieldChecks: checksRan ? 'ran' : 'did-not-run',
    blockedReason: checksRan
      ? null
      : (extract?.reason ?? normalize?.reason ?? 'the extraction stage did not complete'),
    resultLabel: !checksRan ? LABEL_NOT_RUN : findings.length > 0 ? LABEL_FINDINGS : LABEL_NO_FINDINGS,
    stepsRan: SCOPE_RAN,
    stepsNotRun: SCOPE_NOT_RUN,
    checks,
    findings,
    severityCounts,
    statusCounts: checksRan ? countBy(checks) : { extracted: 0, inferred: 0, missing: 0, unknown: 0 },
    stages,
    stale: snapshot.digest !== currentDigest,
    usedFixture,
    digest: snapshot.digest,
    capturedAt: snapshot.capturedAt,
  };
}