import { useEffect, useRef, useState } from 'react';

/**
 * Elapsed milliseconds while `active`; resets to 0 when it turns off.
 *
 * The AI platforms do not report progress, so this only feeds an honest "how long have we been
 * waiting" label. 100 ms keeps the counter alive without re-rendering the whole panel too often.
 */
export function useElapsedMs(active: boolean, intervalMs = 100): number {
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef<number | null>(null);

  useEffect(() => {
    if (!active) {
      startedAt.current = null;
      setElapsed(0);
      return;
    }
    startedAt.current = Date.now();
    setElapsed(0);
    const timer = window.setInterval(() => {
      if (startedAt.current !== null) setElapsed(Date.now() - startedAt.current);
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [active, intervalMs]);

  return elapsed;
}