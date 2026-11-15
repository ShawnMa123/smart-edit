/** Download helper: deterministic names, Blob URL and no network (task 10.4). */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { buildJsonFile, downloadJson, jsonFilename } from './payloadExport';

const operation = {
  operationId: 'createTradeApplication',
  method: 'POST',
  path: '/trade/applications',
};

const at = new Date(2026, 10, 15, 9, 5, 7);
const originalCreate = URL.createObjectURL;
const originalRevoke = URL.revokeObjectURL;

beforeEach(() => {
  Object.defineProperty(URL, 'createObjectURL', {
    value: vi.fn(() => 'blob:mock'),
    configurable: true,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    value: vi.fn(),
    configurable: true,
  });
});

afterEach(() => {
  Object.defineProperty(URL, 'createObjectURL', {
    value: originalCreate,
    configurable: true,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    value: originalRevoke,
    configurable: true,
  });
  vi.restoreAllMocks();
});

describe('jsonFilename', () => {
  it('uses the operationId and a deterministic timestamp', () => {
    expect(jsonFilename(operation, at)).toBe('createTradeApplication-20261115-090507.json');
  });

  it('falls back to method/path and sanitises unsafe characters', () => {
    expect(jsonFilename({ method: 'POST', path: '/trade/{id}/x' }, at)).toBe(
      'POST-trade-id-x-20261115-090507.json',
    );
  });
});

describe('buildJsonFile', () => {
  it('pretty-prints the payload and pairs it with the filename', () => {
    const file = buildJsonFile(operation, { amount: 500000, guarantee: true }, at);
    expect(file.filename).toBe('createTradeApplication-20261115-090507.json');
    expect(file.content).toBe('{\n  "amount": 500000,\n  "guarantee": true\n}');
  });
});

describe('downloadJson', () => {
  it('creates a Blob URL, clicks a download anchor and revokes the URL', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);

    const filename = downloadJson(operation, { amount: 1 });

    expect(filename).toMatch(/^createTradeApplication-\d{8}-\d{6}\.json$/);
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock');
    expect(document.body.querySelector('a')).toBeNull();
  });
});