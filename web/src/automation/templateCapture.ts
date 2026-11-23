/**
 * The pre-save description of the current document (design D12).
 *
 * Kept separate from the component so the source rules, character count and duplicate-name warning
 * are unit-testable and cannot drift from the store's validation.
 */

import type { RichDocument } from '../rich/richDocument';
import { richToPlainText } from '../rich/plainText';
import { collectVariables } from '../rich/variableOperations';
import {
  MAX_TEMPLATE_NAME,
  type TemplateRecord,
  type TemplateSource,
  type TemplateVariableSummary,
} from './templateStore';

export interface CapturePreview {
  /** Trimmed and bounded, exactly what a capture would store. */
  name: string;
  nameError: string | null;
  source: TemplateSource;
  sourceLabel: string;
  provenanceNote: string | null;
  boundRevision: number | null;
  revisionLabel: string;
  charCount: number;
  variables: TemplateVariableSummary[];
  nextVersion: string;
  /** A snapshot with the same name; saving adds a version instead of overwriting it. */
  duplicate: TemplateRecord | null;
  empty: boolean;
  canCapture: boolean;
}

export interface DescribeCaptureInput {
  document: RichDocument;
  draftRevision: number | null;
  name: string;
  templates: TemplateRecord[];
  nextVersion: string;
}

/** Never claim more than the stored provenance. */
export const sourceLabel = (source: TemplateSource): string =>
  source.kind === 'imported' ? `Imported · ${source.provenance}` : 'Edited in this browser';

const sourceOf = (document: RichDocument): TemplateSource =>
  document.provenance
    ? {
        kind: 'imported',
        provenance: document.provenance,
        ...(document.provenanceNote ? { note: document.provenanceNote } : {}),
      }
    : { kind: 'edited' };

export function describeCapture({
  document,
  draftRevision,
  name,
  templates,
  nextVersion,
}: DescribeCaptureInput): CapturePreview {
  const trimmed = name.trim().slice(0, MAX_TEMPLATE_NAME);
  const source = sourceOf(document);
  const text = richToPlainText(document);
  const empty = text.trim().length === 0;
  const variables = collectVariables(document).map((variable) => ({
    label: variable.label,
    valueType: variable.valueType,
    required: variable.required,
  }));
  const duplicate =
    trimmed.length > 0
      ? (templates.find(
          (template) => template.name.trim().toLowerCase() === trimmed.toLowerCase(),
        ) ?? null)
      : null;

  return {
    name: trimmed,
    nameError: trimmed ? null : 'Enter a template name before saving.',
    source,
    sourceLabel: sourceLabel(source),
    provenanceNote: document.provenance ? document.provenanceNote ?? null : null,
    boundRevision: draftRevision,
    revisionLabel: draftRevision === null ? 'No server draft' : `Revision ${draftRevision}`,
    charCount: text.length,
    variables,
    nextVersion,
    duplicate,
    empty,
    canCapture: !empty && trimmed.length > 0,
  };
}