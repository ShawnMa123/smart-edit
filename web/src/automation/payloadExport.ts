/**
 * Downloading a request JSON file (design D19 / task 10.4). Never sends anything.
 */

import type { ContractOperation } from './specContract';

type OperationRef = Pick<ContractOperation, 'operationId' | 'method' | 'path'>;

const pad = (value: number): string => String(value).padStart(2, '0');

export function jsonFilename(operation: OperationRef, now: Date = new Date()): string {
  const raw = operation.operationId?.trim() || `${operation.method}-${operation.path}`;
  const base =
    raw
      .replace(/[^a-zA-Z0-9._-]+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^[-.]+|[-.]+$/g, '') || 'request';
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(
    now.getHours(),
  )}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `${base}-${stamp}.json`;
}

export function buildJsonFile(
  operation: OperationRef,
  payload: Record<string, unknown>,
  now: Date = new Date(),
): { filename: string; content: string } {
  return {
    filename: jsonFilename(operation, now),
    content: JSON.stringify(payload, null, 2),
  };
}

/** Browser-only side effect: trigger a download and return the file name. */
export function downloadJson(
  operation: OperationRef,
  payload: Record<string, unknown>,
): string {
  const file = buildJsonFile(operation, payload);
  const blob = new Blob([file.content], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = file.filename;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  return file.filename;
}