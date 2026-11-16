/** Mock downstream delivery: deterministic receipt, no network (task 11.4). */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { mockSend } from './mockDownstreamSend';
import type { DownstreamSystem } from './downstreamSystemStore';

const system: DownstreamSystem = {
  id: 'sys_demo',
  name: 'Trade sandbox',
  baseUrl: 'https://sandbox.example.com/api/',
  environment: 'sandbox',
  enabled: true,
  auth: { type: 'bearer', hint: 'mock token' },
  specText: '{}',
  specUpdatedAt: '2026-11-15T10:00:00.000Z',
  createdAt: '2026-11-15T10:00:00.000Z',
  updatedAt: '2026-11-15T10:00:00.000Z',
};

const operation = {
  method: 'post',
  path: '/trade/preview',
  operationId: 'previewTradeApplication',
};
const at = new Date('2026-11-15T10:00:00Z');
const payload = { amount: 500000 };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('mockSend', () => {
  it('returns a 200 mock receipt without making a network request', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const receipt = mockSend({ system, operation, payload, simulateFailure: false, now: at });

    expect(receipt).toMatchObject({
      simulated: true,
      status: 200,
      outcome: 'mock_success',
      method: 'POST',
      endpoint: 'https://sandbox.example.com/api/trade/preview',
      requestId: `mock_previewTradeApplication_${at.getTime()}`,
      sentAt: at.toISOString(),
      payload,
    });
    expect(receipt.message).toContain('No network request');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('returns a 500 mock error when failure is simulated', () => {
    const receipt = mockSend({ system, operation, payload, simulateFailure: true, now: at });

    expect(receipt).toMatchObject({
      status: 500,
      outcome: 'MOCK_DOWNSTREAM_ERROR',
      simulated: true,
    });
    expect(receipt.message).toContain('Simulated downstream failure');
  });

  it('joins base URL and path without duplicate slashes', () => {
    expect(
      mockSend({
        system: { ...system, baseUrl: 'https://example.com/api' },
        operation: { method: 'get', path: 'health' },
        payload: {},
        simulateFailure: false,
        now: at,
      }).endpoint,
    ).toBe('https://example.com/api/health');
  });

  it('copies the payload so later mutations do not alter the receipt', () => {
    const original = { amount: 1 };
    const receipt = mockSend({
      system,
      operation,
      payload: original,
      simulateFailure: false,
      now: at,
    });

    original.amount = 2;
    expect(receipt.payload).toEqual({ amount: 1 });
  });
});