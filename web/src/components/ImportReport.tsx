import { explainError } from '../api/errors';
import type { ImportedDocument } from '../api/types';

/** What one import round is doing, and what it produced (`document-import` D10). */
export interface ImportState {
  phase: 'idle' | 'reading' | 'ready' | 'failed';
  documents: ImportedDocument[];
  failure: { code: string; message: string } | null;
}

export const initialImportState: ImportState = {
  phase: 'idle',
  documents: [],
  failure: null,
};

/** How a document's text was obtained — never a guess, always named (spec: 文本来源必须可识别). */
export const FORM_LABELS: Record<string, string> = {
  pdf_text: 'PDF · text layer',
  docx_text: 'Word · DOCX',
  image_ocr: 'Image · recognised text, please check',
  plain_text: 'Plain text',
  email: 'Email',
};

/** Client-side text for the server's error codes; the raw code stays visible underneath. */
export const IMPORT_ERROR_TEXT: Record<string, string> = {
  unsupported_mime: 'This file type is not supported (PDF, DOCX, PNG and JPEG are).',
  ocr_engine_missing:
    'The local OCR engine is not installed on the server, so images cannot be read right now.',
  no_text_recognized: 'No text could be recognised in this file.',
  no_text_found: 'This file contains no text.',
  image_open_failed: 'This image could not be opened.',
  pdf_open_failed: 'This PDF could not be opened.',
  docx_unreadable: 'This DOCX could not be read.',
  file_too_large: 'This file is larger than the import limit.',
  too_many_pages: 'This file has more pages than the OCR limit allows.',
  file_not_found: 'The uploaded file was not found on the server.',
  read_failed: 'The file could not be read as text.',
};

export const errorCode = (error: string): string => error.split(':')[0].trim();

export const errorText = (error: string): string =>
  IMPORT_ERROR_TEXT[errorCode(error)] ?? 'The file could not be read.';

export interface ImportReportProps {
  state: ImportState;
  onUse: (document: ImportedDocument) => void;
  onRetry: () => void;
  onStartBlank: () => void;
}

/**
 * The import report (task 4.3). It never turns a failure into a success line: a file with errors is
 * listed with its reason and no "use this text" action.
 */
export function ImportReport({ state, onUse, onRetry, onStartBlank }: ImportReportProps) {
  if (state.phase === 'idle') return null;

  if (state.phase === 'reading') {
    return (
      <div className="notice" role="status">
        <h3>Reading the uploaded file…</h3>
        <p className="tiny muted">
          Text extraction and OCR run on the server; the editor keeps its current content until you
          choose a document.
        </p>
      </div>
    );
  }

  if (state.phase === 'failed') {
    return (
      <div className="notice notice--bad" role="alert">
        <h3>The upload did not produce a document</h3>
        <p>{state.failure ? explainError(state.failure.code) : 'The request failed.'}</p>
        <p className="tiny muted">
          {state.failure?.message} · code <code>{state.failure?.code}</code>
        </p>
        <div className="version-actions">
          <button type="button" className="primary" onClick={onRetry}>
            Re-upload
          </button>
          <button type="button" onClick={onStartBlank}>
            Start from blank
          </button>
        </div>
      </div>
    );
  }

  const usable = state.documents.filter((document) => document.errors.length === 0);
  const failed = state.documents.filter((document) => document.errors.length > 0);

  return (
    <div className="notice" role="status">
      <h3>
        {usable.length > 0
          ? `${usable.length} document${usable.length === 1 ? '' : 's'} ready`
          : 'No document could be read'}
      </h3>
      <ul className="tiny">
        {state.documents.map((document) => (
          <li key={document.file_id} data-testid={`import-result-${document.file_id}`}>
            <strong>{document.filename}</strong>{' '}
            <span className="muted">{FORM_LABELS[document.form] ?? document.form}</span>
            {document.rich?.provenance ? (
              <div className="tiny muted" data-testid={`import-provenance-${document.file_id}`}>
                structure: {document.rich.provenance}
                {document.rich.provenanceNote ? ` · ${document.rich.provenanceNote}` : ''}
              </div>
            ) : null}
            {document.errors.length > 0 ? (
              <ul>
                {document.errors.map((error) => (
                  <li key={error} className="muted">
                    {errorText(error)} <code className="tiny">{errorCode(error)}</code>
                  </li>
                ))}
              </ul>
            ) : (
              <>
                {' '}
                <button type="button" onClick={() => onUse(document)}>
                  Use this text
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
      {failed.length > 0 ? (
        <p className="tiny muted">
          {failed.length} file{failed.length === 1 ? '' : 's'} could not be read. Re-upload them, or
          start from blank and type the text.
        </p>
      ) : null}
      <div className="version-actions">
        <button type="button" onClick={onRetry}>
          Re-upload
        </button>
        <button type="button" onClick={onStartBlank}>
          Start from blank
        </button>
      </div>
    </div>
  );
}