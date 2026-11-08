/**
 * Envelope guard (task 4.3): a 200 without `stages` is an error state, never a usable envelope.
 * `console-api` requires clients to treat a missing `stages` key as an implementation defect.
 */

import { ApiError, INVALID_RESPONSE_CODE } from './errors';
import type { RunEnvelope } from './types';

export function isEnvelope(value: unknown): value is RunEnvelope {
  if (!value || typeof value !== 'object') return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.thread_id === 'string' &&
    Array.isArray(record.stages) &&
    Array.isArray(record.findings) &&
    Array.isArray(record.trail) &&
    Array.isArray(record.supported_stages) &&
    typeof record.fields === 'object' &&
    record.fields !== null
  );
}

export function assertEnvelope(value: unknown): RunEnvelope {
  if (!isEnvelope(value)) {
    throw new ApiError(
      200,
      INVALID_RESPONSE_CODE,
      'response is missing thread_id / stages / fields / findings / trail / supported_stages',
    );
  }
  return value;
}