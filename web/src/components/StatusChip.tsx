import type { ReactNode } from 'react';

import type { StatusToken } from '../tokens';

/** Renders a status as a word plus colour — never colour alone (Requirements §13). */
export function StatusChip({ token, title }: { token: StatusToken; title?: ReactNode }) {
  return (
    <span className={token.className} title={typeof title === 'string' ? title : undefined}>
      {token.label}
    </span>
  );
}