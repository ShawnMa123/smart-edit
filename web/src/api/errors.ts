/**
 * Error contract (design D7): copy comes from the machine-readable `code`; the server `message` is
 * only ever shown as detail.
 */

export const TIMEOUT_CODE = 'TIMEOUT';
export const INVALID_RESPONSE_CODE = 'INVALID_RESPONSE';
export const NETWORK_CODE = 'NETWORK';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail?: unknown;

  constructor(status: number, code: string, message: string, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

const MESSAGES: Record<string, string> = {
  EMPTY_SUBMISSION: 'There is nothing to audit yet — the document text is empty.',
  unknown_stage: 'That stage is not a triggerable target in this build. Check the supported stages.',
  REFUSED: 'The server refused this request because a prerequisite is missing.',
  NOT_STANDALONE: 'This agent cannot be triggered on its own.',
  unknown_run:
    'This run is no longer held by the server. Run state does not survive a restart — start a new run.',
  INCOMPLETE_RESULT:
    'The server could not assemble the run result, so no conclusion is available for this run.',
  [TIMEOUT_CODE]:
    'The audit exceeded the 120 second limit. It may still be finishing on the server; nothing was concluded here.',
  [INVALID_RESPONSE_CODE]:
    'The server response was missing required fields (stages), so no conclusion is shown.',
  [NETWORK_CODE]: 'The server could not be reached, so no conclusion is shown.',
  // A 5xx with no `code` means the response never came from `console-api`: the dev proxy answered
  // because nothing was listening behind it (or the process died). Say that instead of implying the
  // document was rejected.
  HTTP_500:
    'The API returned an internal error with no error code. In development this usually means the backend is not running — check the uvicorn terminal, then run the audit again.',
  HTTP_502:
    'The API gateway could not reach the backend, so no conclusion is shown. Check that the backend is running.',
  HTTP_503:
    'The API is temporarily unavailable, so no conclusion is shown. Try again once the backend is up.',
  HTTP_504:
    'The API gateway timed out before the backend answered, so no conclusion is shown.',
};

export function explainError(code: string): string {
  return (
    MESSAGES[code] ??
    `The server refused the request (${code}). No conclusion was produced for this run.`
  );
}

/** Every code the client can produce or receive — asserted by the error-copy test. */
export const KNOWN_ERROR_CODES = Object.keys(MESSAGES);