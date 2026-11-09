import { useEffect, useState } from 'react';

/** The prototype's breakpoint: three panes at ≥ 1366 px, one pane plus tabs below it (design D8). */
export const NARROW_QUERY = '(max-width: 1365px)';

const matchesNarrow = (): boolean =>
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(NARROW_QUERY).matches
    : false;

export function useNarrowViewport(): boolean {
  const [narrow, setNarrow] = useState<boolean>(matchesNarrow);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia(NARROW_QUERY);
    const onChange = (event: MediaQueryListEvent) => setNarrow(event.matches);
    setNarrow(query.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  return narrow;
}