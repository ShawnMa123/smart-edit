/**
 * Test setup.
 *
 * - jsdom has no `crypto.subtle`: shim Node's Web Crypto (browser code is untouched).
 * - Node ≥ 22 exposes a `localStorage` getter that is unavailable without `--localstorage-file`, so
 *   install an in-memory one for component tests. `versionStore` also injects storage explicitly.
 */
import { webcrypto } from 'node:crypto';

import { beforeAll, beforeEach } from 'vitest';

import { memoryStorage } from '../versionStore';

beforeAll(() => {
  if (!globalThis.crypto?.subtle) {
    Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
  }
  // Only DOM environments have a `window`; the node environment (e2e) has no localStorage to shim.
  if (typeof globalThis.window === 'undefined') return;
  const storage = memoryStorage();
  for (const target of [globalThis, globalThis.window]) {
    Object.defineProperty(target, 'localStorage', { value: storage, configurable: true });
  }
});

beforeEach(() => {
  globalThis.localStorage?.clear();
});