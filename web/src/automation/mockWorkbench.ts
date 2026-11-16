/**
 * Deterministic, local-only workbench data (no fetch, no model).
 *
 * Everything the Automation workbench shows is derived from
 * `fixtures/automation/workbench_demo.json` plus the current document. Replacing this module with an
 * API adapter is the only change the later backend P1/P2 phases should need.
 */

import fixture from '../../../fixtures/automation/workbench_demo.json';

import type { RichDocument } from '../rich/richDocument';
import { richToPlainText } from '../rich/plainText';
import type { VariableDefinition } from '../rich/variableOperations';

export type VariableValueType = VariableDefinition['valueType'];

export interface ApiTemplateField {
  fieldId: string;
  label: string;
  type: 'string' | 'enum' | 'date';
  required: boolean;
  options?: string[];
}

export interface ApiTemplateSummary {
  id: string;
  name: string;
  version: string;
  fields: ApiTemplateField[];
}

export interface MappingCandidate {
  fieldId: string;
  status: 'matched' | 'ambiguous' | 'missing';
  value: string | null;
  evidence: string | null;
  reason: string;
  options?: string[];
}

export interface PayloadPreview {
  /** Required fields are all confirmed; optional gaps are allowed. */
  ready: boolean;
  state: 'ready' | 'mapping_not_ready';
  payload: Record<string, unknown>;
  missing: string[];
  templateVersion: string;
  documentDigest: string;
  /** The workbench never delivers anything; this stays false by construction. */
  sent: false;
}

export const defaultTemplateName: string = fixture.defaultTemplateName;

export const downstreamTemplates: ApiTemplateSummary[] =
  fixture.downstreamTemplates as ApiTemplateSummary[];

const suggestedVariables = fixture.variables as Array<{
  label: string;
  valueType: VariableValueType;
  required: boolean;
}>;

/**
 * Suggested definition for a selection: the fixture knows a few common labels, everything else is a
 * plain optional string. This is mock behaviour, not extraction.
 */
export function suggestDefinition(selectedText: string): VariableDefinition {
  const normalised = selectedText.trim().toLowerCase();
  const known = suggestedVariables.find(
    (variable) => variable.label === normalised || normalised.includes(variable.label),
  );
  return {
    label: selectedText.trim().slice(0, 40) || known?.label || 'variable',
    valueType: known?.valueType ?? 'string',
    required: known?.required ?? false,
  };
}

const sentenceWith = (text: string, pattern: RegExp): string | null => {
  const match = pattern.exec(text);
  if (!match) return null;
  const start = Math.max(0, text.lastIndexOf('.', match.index) + 1);
  const end = text.indexOf('.', match.index);
  return text
    .slice(start, end === -1 ? undefined : end + 1)
    .trim();
};

/** A `{{label}}` placeholder is not evidence of a value: never invent one from it. */
const realValue = (value: string | undefined): string | null => {
  const trimmed = (value ?? '').trim();
  if (!trimmed || /^\{\{.*\}\}$/.test(trimmed)) return null;
  return trimmed;
};

function matchApplicationType(text: string, field: ApiTemplateField): MappingCandidate {
  const guarantee = /guarantee|保函/i.test(text);
  const standby = /standby|备用信用证/i.test(text);
  if (guarantee && standby) {
    return {
      fieldId: field.fieldId,
      status: 'ambiguous',
      value: null,
      evidence: sentenceWith(text, /guarantee|standby|保函|备用信用证/i),
      reason: 'Both guarantee and standby wording appear.',
      options: field.options,
    };
  }
  if (guarantee) {
    return {
      fieldId: field.fieldId,
      status: 'matched',
      value: 'guarantee',
      evidence: sentenceWith(text, /guarantee|保函/i),
      reason: 'Document wording indicates a guarantee.',
      options: field.options,
    };
  }
  if (standby) {
    return {
      fieldId: field.fieldId,
      status: 'matched',
      value: 'standby_dc',
      evidence: sentenceWith(text, /standby|备用信用证/i),
      reason: 'Document wording indicates a standby.',
      options: field.options,
    };
  }
  return {
    fieldId: field.fieldId,
    status: 'missing',
    value: null,
    evidence: null,
    reason: 'No guarantee/standby wording found.',
    options: field.options,
  };
}

const MONTH_NAMES: Record<string, number> = {
  jan: 1,
  january: 1,
  feb: 2,
  february: 2,
  mar: 3,
  march: 3,
  apr: 4,
  april: 4,
  may: 5,
  jun: 6,
  june: 6,
  jul: 7,
  july: 7,
  aug: 8,
  august: 8,
  sep: 9,
  sept: 9,
  september: 9,
  oct: 10,
  october: 10,
  nov: 11,
  november: 11,
  dec: 12,
  december: 12,
};

const pad2 = (value: number): string => String(value).padStart(2, '0');

const normalizeYear = (raw: string): number => {
  const value = Number(raw);
  if (raw.length === 2) return value < 70 ? 2000 + value : 1900 + value;
  return value;
};

const isValidDate = (year: number, month: number, day: number): boolean => {
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return false;
  if (year < 1900 || year > 2200 || month < 1 || month > 12 || day < 1) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= days[month - 1];
};

const toIso = (yearRaw: string, monthRaw: string, dayRaw: string): string | null => {
  const year = normalizeYear(yearRaw);
  const month = Number(monthRaw);
  const day = Number(dayRaw);
  return isValidDate(year, month, day) ? `${year}-${pad2(month)}-${pad2(day)}` : null;
};

/** Parse one date token and normalise it to `YYYY-MM-DD`; unknown/ambiguous shapes return null. */
function normaliseDateToken(raw: string): string | null {
  const trimmed = raw.trim();

  const yearFirst =
    /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/.exec(trimmed) ??
    /^(\d{4})年(\d{1,2})月(\d{1,2})日$/.exec(trimmed);
  if (yearFirst) return toIso(yearFirst[1], yearFirst[2], yearFirst[3]);

  const dayFirst = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$/.exec(trimmed);
  if (dayFirst) {
    const first = Number(dayFirst[1]);
    const second = Number(dayFirst[2]);
    // DD/MM is the default for contract dates; MM/DD is only used when it is unambiguous.
    const monthFirst = second > 12 && first <= 12;
    return monthFirst
      ? toIso(dayFirst[3], dayFirst[1], dayFirst[2])
      : toIso(dayFirst[3], dayFirst[2], dayFirst[1]);
  }

  const dayMonthName = /^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})[,\s]+(\d{2,4})$/i.exec(
    trimmed,
  );
  if (dayMonthName) {
    const month = MONTH_NAMES[dayMonthName[2].toLowerCase()];
    return month ? toIso(dayMonthName[3], String(month), dayMonthName[1]) : null;
  }

  const monthNameDay = /^([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?[,\s]+(\d{2,4})$/i.exec(
    trimmed,
  );
  if (monthNameDay) {
    const month = MONTH_NAMES[monthNameDay[1].toLowerCase()];
    return month ? toIso(monthNameDay[3], String(month), monthNameDay[2]) : null;
  }

  return null;
}

const DATE_PATTERNS = [
  /\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b/g,
  /\d{4}年\d{1,2}月\d{1,2}日/g,
  /\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b/g,
  /\b\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}[,\s]+\d{2,4}\b/gi,
  /\b[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?[,\s]+\d{2,4}\b/gi,
];

function findDate(text: string): { iso: string; index: number } | null {
  const candidates: Array<{ raw: string; index: number }> = [];
  for (const pattern of DATE_PATTERNS) {
    for (const match of text.matchAll(pattern)) {
      if (match.index !== undefined) candidates.push({ raw: match[0], index: match.index });
    }
  }
  candidates.sort((left, right) => left.index - right.index);
  for (const candidate of candidates) {
    const iso = normaliseDateToken(candidate.raw);
    if (iso) return { iso, index: candidate.index };
  }
  return null;
}

const lineWith = (text: string, index: number): string => {
  const start = text.lastIndexOf('\n', Math.max(0, index - 1)) + 1;
  const end = text.indexOf('\n', index);
  return text.slice(start, end === -1 ? undefined : end).trim();
};

function matchExpiryDate(text: string, field: ApiTemplateField): MappingCandidate {
  const found = findDate(text);
  return {
    fieldId: field.fieldId,
    status: found ? 'matched' : 'missing',
    value: found?.iso ?? null,
    evidence: found ? lineWith(text, found.index) : null,
    reason: found ? 'Date found and normalised to YYYY-MM-DD.' : 'No unambiguous date found.',
  };
}

const BENEFICIARY_LINE = /beneficiary(?:\s+name)?\s*[：:]\s*([^\n.]+)/i;
const BENEFICIARY_EVIDENCE = /beneficiary(?:\s+name)?\s*[：:]/i;

function matchBeneficiary(text: string, field: ApiTemplateField): MappingCandidate {
  const raw = BENEFICIARY_LINE.exec(text)?.[1];
  const value = realValue(raw);
  return {
    fieldId: field.fieldId,
    status: value ? 'matched' : 'missing',
    value,
    evidence: value ? sentenceWith(text, BENEFICIARY_EVIDENCE) : null,
    reason: value
      ? 'Beneficiary line found in the document.'
      : 'No beneficiary value found (placeholders are not values).',
  };
}

/** Deterministic keyword matching against the synthetic template. No model, no network. */
export function matchDocument(
  document: RichDocument,
  template: ApiTemplateSummary,
): MappingCandidate[] {
  const text = richToPlainText(document);
  return template.fields.map((field) => {
    switch (field.fieldId) {
      case 'application_type':
        return matchApplicationType(text, field);
      case 'expiry_date':
        return matchExpiryDate(text, field);
      case 'beneficiary_name':
        return matchBeneficiary(text, field);
      default:
        return {
          fieldId: field.fieldId,
          status: 'missing',
          value: null,
          evidence: null,
          reason: 'No deterministic matcher for this field.',
        };
    }
  });
}

export interface PayloadBinding {
  templateVersion: string;
  documentDigest: string;
}

/**
 * Build the preview from explicit per-field decisions only: an unconfirmed candidate never enters the
 * payload, and an invalid enum value is reported as missing rather than sent.
 */
export function buildPayload(
  template: ApiTemplateSummary,
  decisions: Record<string, string>,
  binding: PayloadBinding,
): PayloadPreview {
  const payload: Record<string, unknown> = {};
  const missing: string[] = [];
  for (const field of template.fields) {
    const value = decisions[field.fieldId]?.trim();
    if (!value) {
      if (field.required) missing.push(field.fieldId);
      continue;
    }
    if (field.type === 'enum' && field.options && !field.options.includes(value)) {
      missing.push(field.fieldId);
      continue;
    }
    payload[field.fieldId] = value;
  }
  const ready = missing.length === 0;
  return {
    ready,
    state: ready ? 'ready' : 'mapping_not_ready',
    payload,
    missing,
    templateVersion: binding.templateVersion,
    documentDigest: binding.documentDigest,
    sent: false,
  };
}

/** Fixture data exposed for mock/UI tests so both read the same source file. */
export const __fixture = { suggestedVariables, defaultTemplateName, downstreamTemplates };