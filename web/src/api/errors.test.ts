/** Task 4.2 — error copy comes from the machine-readable code. */

import { describe, expect, it } from 'vitest';

import { KNOWN_ERROR_CODES, explainError } from './errors';

describe('explainError', () => {
  it('has a distinct, non-empty message for every known code', () => {
    const messages = KNOWN_ERROR_CODES.map((code) => explainError(code));

    expect(messages).toHaveLength(KNOWN_ERROR_CODES.length);
    expect(new Set(messages).size).toBe(messages.length);
    expect(messages.every((message) => message.trim().length > 10)).toBe(true);
  });

  it('covers the codes the transport can produce', () => {
    for (const code of [
      'unknown_stage',
      'REFUSED',
      'NOT_STANDALONE',
      'unknown_run',
      'EMPTY_SUBMISSION',
      'INCOMPLETE_RESULT',
    ]) {
      expect(KNOWN_ERROR_CODES).toContain(code);
    }
  });

  it('names the code for an unknown value without inventing a cause', () => {
    const message = explainError('SOMETHING_NEW');

    expect(message).toContain('SOMETHING_NEW');
    expect(message).toContain('No conclusion');
  });

  it('explains a codeless 5xx as a missing backend, not a rejected document', () => {
    // Regression: a stopped backend behind the dev proxy answers 500 with an empty body, so the
    // client only has `HTTP_500`. Saying "the server refused the request" sent a reader looking for a
    // document problem that did not exist.
    const message = explainError('HTTP_500');

    expect(message).toContain('backend is not running');
    expect(message).toContain('uvicorn');
    expect(message).not.toMatch(/refused the request/i);
  });

  it('distinguishes gateway failures from refusals', () => {
    for (const code of ['HTTP_502', 'HTTP_503', 'HTTP_504']) {
      expect(explainError(code)).not.toBe(explainError('REFUSED'));
      expect(explainError(code)).toContain('conclusion');
    }
  });
});