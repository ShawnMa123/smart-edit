/**
 * The audit's only view of a rich document (design D3).
 *
 * The actual rules live in `projection.ts` so the editor selection and the audit can never drift
 * apart. This module keeps the historical name used across the workspace.
 */

import type { RichDocument } from './richDocument';
import { projectDocument } from './projection';

export function richToPlainText(document: RichDocument | null | undefined): string {
  return projectDocument(document).text;
}