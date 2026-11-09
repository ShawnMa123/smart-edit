/** Isolated file so React's per-module warning dedupe cannot hide the first render. */
import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';

const stubViewport = () => {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }));
};

afterEach(() => vi.unstubAllGlobals());

describe('spec regression found by the audit test design', () => {
  it.fails('BUG-F3 the wide layout renders panes without React key warnings', () => {
    stubViewport();
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      render(<App />);
      const keyWarnings = error.mock.calls.filter((call) =>
        String(call[0]).includes('unique "key" prop'),
      );
      expect(keyWarnings).toEqual([]);
    } finally {
      error.mockRestore();
    }
  });
});
