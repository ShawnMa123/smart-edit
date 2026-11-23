/**
 * Turning a stored template into an editable working document (design D17).
 *
 * The stored record is a snapshot. Apply must never hand that snapshot to the editor by reference:
 * later typing would otherwise mutate the template that is supposed to be immutable.
 */

import type { RichDocument } from '../rich/richDocument';
import { collectVariables } from '../rich/variableOperations';
import type { TemplateRecord } from './templateStore';

export interface AppliedTemplateVariable {
  variableId: string;
  label: string;
  required: boolean;
}

export interface AppliedTemplate {
  document: RichDocument;
  /** Top-level variables the workbench should keep tracking for the required-missing report. */
  variables: AppliedTemplateVariable[];
}

const clone = (document: RichDocument): RichDocument =>
  JSON.parse(JSON.stringify(document)) as RichDocument;

export function applyTemplate(record: TemplateRecord): AppliedTemplate {
  const document = clone(record.rich);
  return {
    document,
    variables: collectVariables(document).map((variable) => ({
      variableId: variable.variableId,
      label: variable.label,
      required: variable.required,
    })),
  };
}