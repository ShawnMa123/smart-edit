/**
 * Deterministic mock delivery (design D21).
 *
 * Deliberately has no fetch, no proxy and no credential access: the receipt is simulated material
 * for the UI, never a real downstream response.
 */

import type { DownstreamSystem } from './downstreamSystemStore';

export interface MockOperation {
  method: string;
  path: string;
  operationId?: string;
}

export interface MockSendInput {
  system: DownstreamSystem;
  operation: MockOperation;
  payload: Record<string, unknown>;
  simulateFailure: boolean;
  now?: Date;
}

export interface MockReceipt {
  simulated: true;
  status: 200 | 500;
  requestId: string;
  method: string;
  endpoint: string;
  sentAt: string;
  payload: Record<string, unknown>;
  outcome: 'mock_success' | 'MOCK_DOWNSTREAM_ERROR';
  message: string;
}

const requestKey = (operation: MockOperation): string =>
  (operation.operationId?.trim() || operation.method).replace(/[^a-zA-Z0-9_-]+/g, '-');

export function mockSend({
  system,
  operation,
  payload,
  simulateFailure,
  now = new Date(),
}: MockSendInput): MockReceipt {
  const base = system.baseUrl.replace(/\/+$/, '');
  const path = operation.path.startsWith('/') ? operation.path : `/${operation.path}`;
  const requestId = `mock_${requestKey(operation)}_${now.getTime()}`;
  const shared = {
    simulated: true as const,
    requestId,
    method: operation.method.toUpperCase(),
    endpoint: `${base}${path}`,
    sentAt: now.toISOString(),
    payload: JSON.parse(JSON.stringify(payload)) as Record<string, unknown>,
  };

  if (simulateFailure) {
    return {
      ...shared,
      status: 500,
      outcome: 'MOCK_DOWNSTREAM_ERROR',
      message: 'Simulated downstream failure. No network request was made.',
    };
  }

  return {
    ...shared,
    status: 200,
    outcome: 'mock_success',
    message: 'Simulated downstream accepted the request. No network request was made.',
  };
}