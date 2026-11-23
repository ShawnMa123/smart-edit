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
  AuditReport,
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
export const LABEL_TEMPLATE_NOT_REQUESTED = 'No customer template was requested';
export const LABEL_TEMPLATE_UNRESOLVED = 'Template could not be resolved';
export const NOTE_GATE_NOT_ASKED =
  'No operation was asked about, so nothing is allowed: the gate answers one named operation at a time.';

export interface AuditFindingRow {
  key: string;
  id: string | null;
  /** The server's finding title / message — the human sentence the row leads with. */
  headline: string;
  rule: string | null;
  ruleId: string | null;
  ruleVersion: string | number | null;
  severity: string;
  severityLabel: string;
  severityClass: string;
  gateType: string | null;
  /** "Blocks" / "Needs human review" / "Advisory" — never the raw machine value. */
  gateLabel: string;
  targetOperations: string[];
  /** `start_approval` -> "Start approval", so the row explains the action in words. */
  operationLabels: string[];
  method: string;
  fieldId: string | null;
  /** The field's business label from the envelope (`保函金额` / "Amount"), when known. */
  fieldLabel: string | null;
  message: string;
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
  template: TemplateSummary;
  /** Where the field values came from (change D8); never inferred from the stage reason alone. */
  extraction: ExtractionSummary;
  /** The audit date recorded in the report (change D5); null in older reports. */
  asOf: string | null;
}

/** `verification.extraction`, in the units the panel prints. */
export interface ExtractionSummary {
  /** `deterministic` / `fixture` / `llm` / `unknown`. */
  source: string;
  profileId: string | null;
  version: string | null;
  contentSha256: string | null;
  fieldsFound: number | null;
  fieldsMissing: number | null;
  llmFallback: boolean;
  /** Fields the extractor refused to settle (`notes` contains `extraction_conflict`). */
  conflictFields: string[];
  label: string;
}

/** The customer template that judged this document, or why none did (design D20). */
export interface TemplateSummary {
  requested: boolean;
  templateId: string | null;
  version: string | null;
  /** A demo pack must be labelled as such wherever it is shown. */
  synthetic: boolean;
  counterparty: string | null;
  reason: string | null;
  reasonCodes: string[];
  conflicts: string[];
  candidates: Array<{ templateId: string; version: string }>;
  /** How many planned units came from the template (0 when none applied). */
  units: number;
  policyPacks: string[];
  label: string;
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

/** `gate_type` in words. The raw value stays on the row for tests/debugging, never for display. */
const GATE_LABELS: Record<string, string> = {
  hard_block: 'Blocks',
  human_review: 'Needs human review',
  advisory: 'Advisory',
};

/** Protected operations in words; an unknown value falls back to Title Case, never to a raw snake_case. */
const OPERATION_LABELS: Record<string, string> = {
  save_draft: 'Save draft',
  submit_version: 'Submit version',
  start_approval: 'Start approval',
  formal_export: 'Formal export',
  handoff: 'Handoff',
  formal_mapping: 'Formal mapping',
};

const titleCase = (value: string): string =>
  value
    .replace(/[_-]+/g, ' ')
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());

const operationLabel = (operation: string): string =>
  OPERATION_LABELS[operation] ?? titleCase(operation);

const fieldLabelFor = (envelope: RunEnvelope, fieldId: string | null): string | null => {
  if (!fieldId) return null;
  const entry = envelope.fields?.[fieldId] ?? envelope.extra_fields?.[fieldId];
  const label = entry?.label?.trim();
  return label ? label : null;
};

/**
 * The rule reference to print. Schema checks carry the schema *hash* as their version, which reads
 * like a commit id and says nothing to a reviewer — keep the version only for business rules, where
 * it is a real rule version (`GR-AMOUNT-POSITIVE@1`).
 */
const ruleReference = (
  ruleId: string | null,
  ruleVersion: string | number | null,
): string | null => {
  if (!ruleId) return null;
  if (ruleId.startsWith('SCHEMA:')) return ruleId;
  return ruleVersion === null || ruleVersion === undefined ? ruleId : `${ruleId}@${ruleVersion}`;
};

const toAuditFindingRow = (
  finding: AuditFinding,
  envelope: RunEnvelope,
  index: number,
): AuditFindingRow => {
  const token = severityToken(finding.severity);
  const fieldLabel = fieldLabelFor(envelope, finding.field_id);
  return {
    key: finding.id ?? `${finding.check_id}#${index}`,
    id: finding.id,
    headline: finding.message,
    rule: ruleReference(finding.rule_id, finding.rule_version),
    ruleId: finding.rule_id,
    ruleVersion: finding.rule_version,
    severity: finding.severity,
    severityLabel: token.label,
    severityClass: token.className,
    gateType: finding.gate_type,
    gateLabel: finding.gate_type ? (GATE_LABELS[finding.gate_type] ?? titleCase(finding.gate_type)) : 'No gate',
    targetOperations: finding.target_operations ?? [],
    operationLabels: (finding.target_operations ?? []).map(operationLabel),
    method: finding.method,
    fieldId: finding.field_id,
    fieldLabel,
    message: finding.message,
    evidence: finding.evidence,
  };
};

const GATE_ORDER: Record<string, number> = { hard_block: 0, human_review: 1, advisory: 2 };
const SEVERITY_ORDER: Record<string, number> = { critical: 0, warn: 1, info: 2 };

/** Blocking findings first, then severity; the plan order is not the reviewer's order. */
const byUrgency = (a: AuditFindingRow, b: AuditFindingRow): number =>
  (GATE_ORDER[a.gateType ?? ''] ?? 3) - (GATE_ORDER[b.gateType ?? ''] ?? 3) ||
  (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3) ||
  a.headline.localeCompare(b.headline);

const auditFindingRows = (envelope: RunEnvelope, report: AuditReport | null): AuditFindingRow[] =>
  (report?.findings ?? [])
    .map((finding, index) => toAuditFindingRow(finding, envelope, index))
    .sort(byUrgency);

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
 * The extraction provenance block (change D8).
 *
 * `source` is copied from the server and never guessed: a run whose extract stage failed has no
 * provenance, and that is rendered as `unknown` — not as `deterministic` and not as clean.
 */
export function extractionSummary(envelope: RunEnvelope): ExtractionSummary {
  const raw = envelope.verification?.extraction ?? null;
  const source = raw?.source ?? 'unknown';
  const conflictFields = Object.values(envelope.fields)
    .filter((field) => (field.notes ?? []).includes('extraction_conflict'))
    .map((field) => field.key)
    .sort();
  const label =
    source === 'deterministic'
      ? raw?.profile_id
        ? `Deterministic profile · ${raw.profile_id} v${raw.version ?? '?'}`
        : 'Deterministic profile'
      : source === 'fixture'
        ? 'Fixture replay (demo, not this document)'
        : source === 'llm'
          ? 'Model extraction'
          : 'Extraction source not recorded';

  return {
    source,
    profileId: raw?.profile_id ?? null,
    version: raw?.version ?? null,
    contentSha256: raw?.content_sha256 ?? null,
    fieldsFound: raw?.fields_found ?? null,
    fieldsMissing: raw?.fields_missing ?? null,
    llmFallback: Boolean(raw?.llm_fallback),
    conflictFields,
    label,
  };
}

/**
 * The rule audit as reported by the server — or "did not run", which is a claim of its own.
 *
 * The server digest is shown for reference and **never** compared with the browser digest: they hash
 * different payloads, so treating them as interchangeable would fake a staleness check.
 */
export function auditSummary(envelope: RunEnvelope): AuditSummary {
  const verification = envelope.verification ?? null;
  const report = verification?.audit ?? null;
  const findings = auditFindingRows(envelope, report);

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
    template: templateSummary(envelope),
    extraction: extractionSummary(envelope),
    asOf: report?.as_of ?? verification?.policy?.as_of ?? null,
  };
}

/**
 * The template block. Three states are kept apart on purpose: requested and applied, requested and
 * refused (with the reason), and never requested at all — the last one is not a clean audit, it is simply
 * a rule-bundle audit, and the screen must say which.
 */
export function templateSummary(envelope: RunEnvelope): TemplateSummary {
  const baseline = envelope.verification?.audit?.template ?? null;
  const checks = envelope.verification?.checks ?? [];
  const units = checks.filter((issue) => (issue.check_id ?? issue.checker).startsWith('TEMPLATE:')).length;
  const requested = baseline?.requested ?? false;
  const label = baseline?.template_id
    ? `${baseline.synthetic ? 'Synthetic template' : 'Template'} · ${baseline.template_id} v${
        baseline.version ?? '?'
      }`
    : requested
      ? LABEL_TEMPLATE_UNRESOLVED
      : LABEL_TEMPLATE_NOT_REQUESTED;

  return {
    requested,
    templateId: baseline?.template_id ?? null,
    version: baseline?.version ?? null,
    synthetic: baseline?.synthetic ?? false,
    counterparty: baseline?.counterparty ?? null,
    reason: baseline?.reason ?? null,
    reasonCodes: baseline?.reason_codes ?? [],
    conflicts: baseline?.conflicts ?? [],
    candidates: (baseline?.candidate_templates ?? []).map((candidate) => ({
      templateId: candidate.template_id,
      version: candidate.version,
    })),
    units,
    policyPacks: (baseline?.policy_packs ?? []).map((pack) => `${pack.pack_id} v${pack.version}`),
    label,
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

  const usedFixture =
    Boolean(extract?.reason?.includes('fixture:')) ||
    envelope.verification?.extraction?.source === 'fixture';

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