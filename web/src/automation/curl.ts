/**
 * Receipts → replayable artefacts: a `curl` command and the exact JSON body.
 *
 * Everything comes from the receipt itself (`request.target`, `request.sent_body`) plus the connector
 * for the auth header *name*; secrets are never included — the command references an env var instead.
 */

import type { Connector, DispatchReceipt } from '../api/automationRegistry';

const quote = (value: string): string => `'${value.replace(/'/g, `'\\''`)}'`;

export function receiptTarget(receipt: DispatchReceipt): { url: string; method: string } | null {
  const target = receipt.request?.target;
  if (!target || typeof target !== 'object') return null;
  const record = target as Record<string, unknown>;
  if (typeof record.url !== 'string' || !record.url) return null;
  return { url: record.url, method: typeof record.method === 'string' ? record.method : 'POST' };
}

/** The body that was actually sent (falls back to `request.body` for older receipts). */
export function receiptBody(receipt: DispatchReceipt): Record<string, unknown> {
  const sent = receipt.request?.sent_body ?? receipt.request?.body;
  if (sent && typeof sent === 'object' && !Array.isArray(sent)) return sent as Record<string, unknown>;
  return {};
}

export function buildCurl(receipt: DispatchReceipt, connector?: Connector | null): string {
  const target = receiptTarget(receipt);
  if (!target) return '# this receipt predates target recording; resend to get a replayable receipt';
  const lines = [`curl -X ${target.method} ${quote(target.url)}`];
  lines.push(`  -H ${quote('Content-Type: application/json')}`);
  if (connector && connector.auth_kind === 'bearer') {
    lines.push(`  -H ${quote('Authorization: Bearer $SMART_EDIT_DOWNSTREAM_TOKEN')}`);
  } else if (connector && connector.auth_kind === 'header') {
    const name = connector.auth_header || 'X-Api-Key';
    lines.push(`  -H ${quote(`${name}: $SMART_EDIT_DOWNSTREAM_TOKEN`)}`);
  }
  lines.push(`  --data-raw ${quote(JSON.stringify(receiptBody(receipt)))}`);
  return lines.join(' \\\n');
}

/** Filename + content for the "download payload" action. */
export function payloadFile(receipt: DispatchReceipt): { filename: string; content: string } {
  const target = receiptTarget(receipt);
  const path = target ? target.url.replace(/^https?:\/\/[^/]+/, '') : '';
  const base = (path.split('/').filter(Boolean).pop() || 'payload').replace(/[^a-zA-Z0-9._-]+/g, '-');
  return {
    filename: `${base}-${receipt.dispatch_id}.json`,
    content: JSON.stringify(receiptBody(receipt), null, 2),
  };
}