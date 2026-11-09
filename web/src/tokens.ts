/**
 * Status tokens: every status the workspace renders carries a **word** as well as a colour
 * (Requirements §13: never colour alone). Components read from here instead of inventing labels.
 */

export type StatusTone = 'ok' | 'warn' | 'bad' | 'unknown';

export interface StatusToken {
  /** Human-readable label; always shown next to the colour. */
  label: string;
  tone: StatusTone;
  className: string;
}

const token = (label: string, tone: StatusTone): StatusToken => ({
  label,
  tone,
  className: `status status--${tone}`,
});

/** `FieldValue.status` (contract `app/state.py`). */
export const FIELD_STATUS: Record<string, StatusToken> = {
  extracted: token('Extracted', 'ok'),
  inferred: token('Inferred · needs confirmation', 'warn'),
  missing: token('Not found in source', 'bad'),
  unknown: token('Unknown status', 'unknown'),
};

/** `StageReport.status`. */
export const STAGE_STATUS: Record<string, StatusToken> = {
  done: token('Done', 'ok'),
  skipped: token('Skipped', 'warn'),
  partial: token('Partial', 'warn'),
  failed: token('Failed', 'bad'),
  unknown: token('Unknown status', 'unknown'),
};

/** `Finding.severity`. */
export const SEVERITY: Record<string, StatusToken> = {
  critical: token('Critical', 'bad'),
  warn: token('Warning', 'warn'),
  info: token('Info', 'ok'),
  unknown: token('Unknown severity', 'unknown'),
};

/** How the panel describes a whole result. */
export const RESULT_TONE: Record<string, StatusToken> = {
  ran: token('Checks ran', 'ok'),
  'did-not-run': token('Checks did not run', 'bad'),
  stale: token('Stale report', 'warn'),
};

/**
 * `verification.audit.outcome` (agent-audit report). Deliberately worded differently from
 * `LABEL_NO_FINDINGS` so a screen can never claim "compliant" by picking the greener token.
 */
export const AUDIT_OUTCOME: Record<string, StatusToken> = {
  no_findings: token('No findings reported', 'ok'),
  findings_present: token('Findings reported', 'warn'),
  needs_input: token('Needs input', 'warn'),
  unable_to_assess: token('Unable to assess', 'unknown'),
  unknown: token('Unknown outcome', 'unknown'),
};

/** `gate.decision`. `not-asked` is a first-class value: nobody asked the gate, so nothing is allowed. */
export const GATE_DECISION: Record<string, StatusToken> = {
  allowed: token('Allowed', 'ok'),
  blocked: token('Blocked', 'bad'),
  indeterminate: token('Indeterminate', 'warn'),
  'not-asked': token('Not asked', 'unknown'),
  unknown: token('Unknown decision', 'unknown'),
};

const lookup = (table: Record<string, StatusToken>, value: string): StatusToken =>
  table[value] ?? table.unknown;

export const fieldStatusToken = (status: string): StatusToken => lookup(FIELD_STATUS, status);
export const stageStatusToken = (status: string): StatusToken => lookup(STAGE_STATUS, status);
export const severityToken = (severity: string): StatusToken => lookup(SEVERITY, severity);
export const auditOutcomeToken = (outcome: string): StatusToken => lookup(AUDIT_OUTCOME, outcome);
export const gateDecisionToken = (decision: string): StatusToken => lookup(GATE_DECISION, decision);

/** Every distinct status label the app can render — asserted by the token test. */
export const ALL_STATUS_LABELS: string[] = [
  ...Object.values(FIELD_STATUS),
  ...Object.values(STAGE_STATUS),
  ...Object.values(SEVERITY),
  ...Object.values(RESULT_TONE),
  ...Object.values(AUDIT_OUTCOME),
  ...Object.values(GATE_DECISION),
].map((entry) => entry.label);