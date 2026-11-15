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

function matchExpiryDate(text: string, field: ApiTemplateField): MappingCandidate {
  const date = /\b\d{4}-\d{2}-\d{2}\b/.exec(text)?.[0] ?? null;
  return {
    fieldId: field.fieldId,
    status: date ? 'matched' : 'missing',
    value: date,
    evidence: date ? sentenceWith(text, /\b\d{4}-\d{2}-\d{2}\b/) : null,
    reason: date ? 'Date found in the document.' : 'No unambiguous date found.',
  };
}

function matchBeneficiary(text: string, field: ApiTemplateField): MappingCandidate {
  const raw = /beneficiary\s*[::]\s*([^\n.]+)/i.exec(text)?.[1];
  const value = realValue(raw);
  return {
    fieldId: field.fieldId,
    status: value ? 'matched' : 'missing',
    value,
    evidence: value ? sentenceWith(text, /beneficiary\s*[::]/i) : null,
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