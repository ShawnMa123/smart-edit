/** Receipts → curl / payload file (F5). */

import { describe, expect, it } from 'vitest';

import { buildCurl, payloadFile, receiptBody, receiptTarget } from './curl';
import type { Connector, DispatchReceipt } from '../api/automationRegistry';

const receipt: DispatchReceipt = {
  dispatch_id: 'dsp_1',
  connector_id: 'con_1',
  status: 'succeeded',
  status_code: 200,
  latency_ms: 15,
  request: {
    target: { url: 'http://127.0.0.1:18080/trade/applications', method: 'POST', schema_kind: 'openapi' },
    sent_body: { amount: 250000, beneficiary: { name: 'Meridian Exports Pte Ltd' } },
    body: { amount: 250000 },
  },
  response_excerpt: '{"accepted":true}',
  created_at: '2026-11-21T00:00:00Z',
};

const connector = (over: Partial<Connector> = {}): Connector => ({
  connector_id: 'con_1',
  name: 'Trade intake',
  base_url: 'http://127.0.0.1:18080',
  path: '/trade/applications',
  method: 'POST',
  auth_kind: 'header',
  auth_header: 'X-Api-Key',
  secret_env: 'TRADE_TOKEN',
  secret_configured: true,
  timeout_seconds: 10,
  extra_headers: {},
  created_at: '2026-11-20T00:00:00Z',
  request_fields: [],
  body_map: {},
  spec_warnings: [],
  ...over,
});

describe('receipt artefacts', () => {
  it('prefers the exact body that was sent', () => {
    expect(receiptBody(receipt)).toEqual({
      amount: 250000,
      beneficiary: { name: 'Meridian Exports Pte Ltd' },
    });
  });

  it('builds a curl with the env var placeholder, never the secret', () => {
    const command = buildCurl(receipt, connector());

    expect(command).toContain("curl -X POST 'http://127.0.0.1:18080/trade/applications'");
    expect(command).toContain("'Content-Type: application/json'");
    expect(command).toContain("'X-Api-Key: $SMART_EDIT_DOWNSTREAM_TOKEN'");
    expect(command).toContain('--data-raw');
    expect(command).not.toContain('s3cret');
  });

  it('explains a receipt that predates target recording', () => {
    const oldReceipt = { ...receipt, request: { values: { amount: '1' } } };
    expect(receiptTarget(oldReceipt)).toBeNull();
    expect(buildCurl(oldReceipt, null)).toContain('predates target recording');
    expect(payloadFile(oldReceipt).content).toBe('{}');
  });

  it('names the payload file after the path and dispatch', () => {
    expect(payloadFile(receipt)).toEqual({
      filename: 'applications-dsp_1.json',
      content: JSON.stringify(receiptBody(receipt), null, 2),
    });
  });
});