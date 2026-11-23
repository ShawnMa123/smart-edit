/** Honest elapsed-time counter used by the AI wait boxes. */

import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useElapsedMs } from './useElapsedMs';

describe('useElapsedMs', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('counts while active and resets when it stops', () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ active }) => useElapsedMs(active), {
      initialProps: { active: true },
    });

    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(result.current).toBeGreaterThanOrEqual(600);

    rerender({ active: false });
    expect(result.current).toBe(0);
  });
});