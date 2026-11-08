/**
 * Audit view model (design D6) — the single place that decides **what may be claimed**.
 *
 * The rule this module exists for: `extract` failing makes every required field a `missing`
 * placeholder, and rendering that as a defect list would accuse the customer's document of a failure
 * that is ours. So field checks are reported only when the stages that produce them completed, and
 * an incomplete run carries a `blockedReason` instead of a result.
 */

import type {
  AuditFinding,
  FieldValue,
  Finding,
  GateDecision,
  RunEnvelope,
  StageReport,
} from './api/types';
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

/** `verification.audit.outcome` / gate vocabulary the panel renders. */
export const LABEL_AUDIT_NOT_RUN = 'Rule audit did not run';
export const NOTE_GATE_NOT_ASKED =
  'No operation was asked about, so nothing is allowed: the gate answers one named operation at a time.';

export interface AuditFindingRow {
  key: string;
  id: string | null;
  rule: string | null;
  severity: string;
  gateType: string | null;
  targetOperations: string[];
  message: string;
  fieldId: string | null;
  evidence: string | null;
}

export interface GateSummary {
  /** `false` means "nobody asked", which is not the same as "allowed". */
  asked: boolean;
  operation: string | null;
  /** `allowed` / `blocked` / `indeterminate` / `not-asked`. */
  decision: string;
  reasonCodes: string[];
  openGaps: number | null;
  authorizedFindingIds: string[];
  unsupportedCapability: string | null;
}

/** What `verification.audit` says, in the units the panel prints. */
export interface AuditSummary {
  /** True only when the envelope carries a server-produced report. */
  ran: boolean;
  planned: number | null;
  assessed: number | null;
  ratio: number | null;
  outcome: string;
  completion: string | null;
  verdict: string | null;
  counts: Record<string, number>;
  findings: AuditFindingRow[];
  hardBlockFindings: number;
  engineVersion: string | null;
  schemaVersion: string | null;
  bundleVersions: Record<string, string>;
  /** Server-side digest — a *different* algorithm from the browser digest, so never compared. */
  serverDigest: string | null;
  gate: GateSummary;
}

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
  audit: AuditSummary;
}

const lastReport = (stages: StageReport[], stage: string): StageReport | undefined =>
  [...stages].reverse().find((report) => report.stage === stage);

/** Latest status of one stage (`'absent'` when the run never reached it). */
export function stageStatus(envelope: RunEnvelope, stage: string): string {
  return lastReport(envelope.stages, stage)?.status ?? 'absent';
}

/**
 * Did the stages that actually produce field values finish?
 *
 * The one predicate the panel and the "should I even audit?" decision share: with no model provider
 * `extract` fails but `normalize` still reports `done` with placeholder fields, so checking
 * `normalize` alone would send placeholders into the audit and report the *document* as incomplete.
 */
export function fieldChecksRan(envelope: RunEnvelope): boolean {
  return stageStatus(envelope, 'extract') === 'done' && stageStatus(envelope, 'normalize') === 'done';
}

const toAuditFindingRow = (finding: AuditFinding, index: number): AuditFindingRow => ({
  key: finding.id ?? `${finding.check_id}#${index}`,
  id: finding.id,
  rule: finding.rule_id
    ? `${finding.rule_id}${finding.rule_version === null ? '' : `@${finding.rule_version}`}`
    : null,
  severity: finding.severity,
  gateType: finding.gate_type,
  targetOperations: finding.target_operations ?? [],
  message: finding.message,
  fieldId: finding.field_id,
  evidence: finding.evidence,
});

const gateSummary = (envelope: RunEnvelope): GateSummary => {
  const gate: GateDecision | null = envelope.gate ?? null;
  if (!gate) {
    return {
      asked: false,
      operation: null,
      decision: 'not-asked',
      reasonCodes: [],
      openGaps: null,
      authorizedFindingIds: [],
      unsupportedCapability: null,
    };
  }
  return {
    asked: true,
    operation: gate.operation,
    decision: gate.decision,
    reasonCodes: gate.reason_codes ?? [],
    openGaps: gate.open_gaps ?? null,
    authorizedFindingIds: gate.authorized_finding_ids ?? [],
    unsupportedCapability: gate.unsupported_capability ?? null,
  };
};

/**
 * The rule audit as reported by the server — or "did not run", which is a claim of its own.
 *
 * The server digest is shown for reference and **never** compared with the browser digest: they hash
 * different payloads, so treating them as interchangeable would fake a staleness check.
 */
export function auditSummary(envelope: RunEnvelope): AuditSummary {
  const verification = envelope.verification ?? null;
  const report = verification?.audit ?? null;
  const findings = (report?.findings ?? []).map(toAuditFindingRow);

  return {
    ran: Boolean(report),
    planned: report?.planned ?? null,
    assessed: report?.coverage.assessed ?? null,
    ratio: report?.coverage.ratio ?? null,
    outcome: report?.outcome ?? 'unknown',
    completion: report?.completion ?? null,
    verdict: verification?.verdict ?? null,
    counts: report?.counts ?? {},
    findings,
    hardBlockFindings: findings.filter((finding) => finding.gateType === 'hard_block').length,
    engineVersion: report?.engine_version ?? null,
    schemaVersion: report?.schema_version ?? null,
    bundleVersions: report?.bundle_versions ?? {},
    serverDigest: report?.snapshot_digest ?? null,
    gate: gateSummary(envelope),
  };
}

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
  const checksRan = fieldChecksRan(envelope);

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
    audit: auditSummary(envelope),
  };
}