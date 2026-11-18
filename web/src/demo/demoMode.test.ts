import { describe, expect, it, vi } from 'vitest';

import { DEMO_MODE_KEY, readDemoMode, writeDemoMode } from './demoMode';

describe('demo mode preference', () => {
  it('defaults off and persists on/off through localStorage', () => {
    globalThis.localStorage.clear();
    expect(readDemoMode()).toBe(false);

    expect(writeDemoMode(true)).toBe(true);
    expect(globalThis.localStorage.getItem(DEMO_MODE_KEY)).toBe('1');
    expect(readDemoMode()).toBe(true);

    expect(writeDemoMode(false)).toBe(true);
    expect(globalThis.localStorage.getItem(DEMO_MODE_KEY)).toBeNull();
    expect(readDemoMode()).toBe(false);
  });

  it('reports a storage failure without throwing', () => {
    const broken = {
      getItem: () => {
        throw new Error('no storage');
      },
      setItem: () => {
        throw new Error('no storage');
      },
      removeItem: () => {
        throw new Error('no storage');
      },
    };
    vi.stubGlobal('localStorage', broken);

    expect(readDemoMode()).toBe(false);
    expect(writeDemoMode(true)).toBe(false);
  });
});