import { useEffect, useState } from 'react';

/** The reference prototype switches from rail + three panes at 960px. */
export const NARROW_QUERY = '(max-width: 960px)';

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