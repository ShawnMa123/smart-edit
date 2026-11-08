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

const lookup = (table: Record<string, StatusToken>, value: string): StatusToken =>
  table[value] ?? table.unknown;

export const fieldStatusToken = (status: string): StatusToken => lookup(FIELD_STATUS, status);
export const stageStatusToken = (status: string): StatusToken => lookup(STAGE_STATUS, status);
export const severityToken = (severity: string): StatusToken => lookup(SEVERITY, severity);

/** Every distinct status label the app can render — asserted by the token test. */
export const ALL_STATUS_LABELS: string[] = [
  ...Object.values(FIELD_STATUS),
  ...Object.values(STAGE_STATUS),
  ...Object.values(SEVERITY),
  ...Object.values(RESULT_TONE),
].map((entry) => entry.label);