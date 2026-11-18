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
import { activityStore } from '../workspace/activityStore';

beforeAll(() => {
  if (!globalThis.crypto?.subtle) {
    Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
  }
  // Only DOM environments have a `window`; the node environment (e2e) has no localStorage to shim.
  if (typeof globalThis.window === 'undefined') return;
  // jsdom does not implement scrollIntoView; ProseMirror calls it when a toolbar control focuses.
  if (typeof HTMLElement !== 'undefined' && !HTMLElement.prototype.scrollIntoView) {
    HTMLElement.prototype.scrollIntoView = () => undefined;
  }
  if (typeof Range !== 'undefined' && !Range.prototype.getClientRects) {
    // ProseMirror asks the current range for geometry when focusing a toolbar command.
    Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  }
  if (typeof Range !== 'undefined' && !Range.prototype.getBoundingClientRect) {
    Range.prototype.getBoundingClientRect = () =>
      ({
        x: 0,
        y: 0,
        width: 0,
        height: 0,
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        toJSON: () => ({}),
      }) as DOMRect;
  }
  const storage = memoryStorage();
  for (const target of [globalThis, globalThis.window]) {
    Object.defineProperty(target, 'localStorage', { value: storage, configurable: true });
  }
});

beforeEach(() => {
  globalThis.localStorage?.clear();
  // `activityStore` may fall back to its own memory when Node exposes no localStorage; clear the
  // demo document so component tests never inherit another test's activity entries.
  activityStore.clear('demo-document');
});